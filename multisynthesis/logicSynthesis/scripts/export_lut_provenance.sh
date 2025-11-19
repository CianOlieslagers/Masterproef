#!/usr/bin/env bash
set -euo pipefail

MPROOT="${MPROOT:-$HOME/Masterproef/multisynthesis}"
OUT_DIR="${OUT_DIR:-$MPROOT/logicSynthesis/results}"
PROV_DIR="$OUT_DIR/Provenance"
LOG_DIR="${LOG_DIR:-$MPROOT/logicSynthesis/logs}"

BLIF=""
AAG_IN=""
DESIGN=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --blif)   BLIF="$(realpath -m "$2")"; shift 2;;
    --aag)    AAG_IN="$(realpath -m "$2")"; shift 2;;
    --design) DESIGN="$2"; shift 2;;
    -h|--help) echo "Gebruik: $0 --blif mapped.blif --aag pre_or_post.{aag|aig} --design NAME"; exit 0;;
    *) echo "Onbekend arg: $1" >&2; exit 1;;
  esac
done

[[ -z "$BLIF" || -z "$AAG_IN" || -z "$DESIGN" ]] && { echo "Vereist: --blif --aag --design"; exit 1; }
[[ ! -f "$BLIF"   ]] && { echo "BLIF niet gevonden: $BLIF"; exit 1; }
[[ ! -f "$AAG_IN" ]] && { echo "AAG/AIG niet gevonden: $AAG_IN"; exit 1; }

mkdir -p "$PROV_DIR" "$LOG_DIR"

YOSYS_BIN="${YOSYS_BIN:-$(command -v yosys || true)}"
[[ -x "${YOSYS_BIN:-}" ]] || { echo "Yosys niet gevonden (zet YOSYS_BIN of PATH)"; exit 1; }

# 0) Zorg dat we ASCII AAG hebben (gebruik Yosys voor .aig → .aag)
AAG_ASCII="$AAG_IN"
hdr="$(head -c 4 "$AAG_IN" || true)"
if [[ "$hdr" != "aag " ]]; then
  if [[ "$hdr" == "aig " || "${AAG_IN##*.}" == "aig" ]]; then
    AAG_TMP="$(mktemp --suffix=.aag)"
    "$YOSYS_BIN" -q -p "read_aiger \"$AAG_IN\"; write_aiger -ascii -symbols \"$AAG_TMP\""
    AAG_ASCII="$AAG_TMP"
    echo "Geconverteerd met Yosys: $AAG_IN → $AAG_ASCII"
  else
    echo "Onbekend AIG/AAG formaat (header='$hdr'); verwacht 'aag ' of 'aig '." >&2
    exit 1
  fi
fi

# 1) BLIF → Yosys JSON
JSON_TMP="$(mktemp --suffix=.json)"
"$YOSYS_BIN" -q -p "read_blif \"$BLIF\"; write_json \"$JSON_TMP\""

# 2) Parse en schrijf provenance JSON
OUT_JSON="$PROV_DIR/${DESIGN}.lut_to_aig_leaves.json"
PY="${PYTHON:-python3}"
"$PY" - << 'PYCODE' "$JSON_TMP" "$AAG_ASCII" "$OUT_JSON" "$DESIGN"


import json, sys, os, csv

json_in, aag_in, out_json, design = sys.argv[1:]

# ---- AAG ASCII parser: PI name -> literal ----

pi_name_to_lit = {}
with open(aag_in, 'r', encoding='utf-8') as f:
    lines = f.readlines()

M=I=L=O=A=None
it = iter(lines)
for ln in it:
    if ln.startswith('aag '):
        parts = ln.strip().split()
        M,I,L,O,A = map(int, parts[1:6])
        break
if I is None:
    raise SystemExit("AAG header niet gevonden")

# I PI-literals na header
pi_lits_list = []
idx = 0
for ln in it:
    s = ln.strip()
    if not s: continue
    pi_lits_list.append(int(s.split()[0]))
    idx += 1
    if idx >= I: break

# symbolen 'i<k> <name>'
symbols = {}
for ln in lines:
    if ln and ln[0] in ('i','o','l'):
        parts = ln.rstrip('\n').split(' ', 1)
        if len(parts) == 2:
            symbols[parts[0]] = parts[1]

for k, lit in enumerate(pi_lits_list):
    tag = f"i{k}"
    if tag in symbols:
        pi_name_to_lit[symbols[tag]] = lit

lit_to_pi_name = {lit: name for name, lit in pi_name_to_lit.items()}

# ---- Yosys JSON parsing ----
with open(json_in, 'r', encoding='utf-8') as f:
    y = json.load(f)

def norm_bit(b):
    if isinstance(b, str) and b.startswith("\\"): return b[1:]
    return b

def norm_vec(v):
    if isinstance(v, list): return [norm_bit(x) for x in v]
    return [norm_bit(v)]

def clean_name(s):
    return s[1:] if isinstance(s, str) and s.startswith("\\") else s

def build_bit_to_name(mod):
    bit_to_name = {}
    netnames = mod.get("netnames", {}) or {}
    for nname, rec in netnames.items():
        nn = clean_name(nname)
        for b in rec.get("bits", []):
            bb = norm_bit(b)
            bit_to_name[bb] = nn
    return bit_to_name

def build_producer_map(mod, bit_to_name):
    prod = {}
    for _, c in (mod.get("cells") or {}).items():
        conns = c.get("connections", {})
        Yv = norm_vec(conns.get("Y", []))
        if not Yv: continue
        yb = Yv[0]
        yname = bit_to_name.get(yb, yb)
        prod[yname] = yname
    return prod

modules = (y.get("modules") or {})
if not modules:
    raise SystemExit("Geen modules in Yosys JSON?")

lut_nodes = []
K = 0

for _, mod in modules.items():
    bit_to_name = build_bit_to_name(mod)
    producer = build_producer_map(mod, bit_to_name)
    cells = mod.get("cells") or {}

    for _, c in cells.items():
        conns = c.get("connections", {})
        if "Y" not in conns or "A" not in conns:
            continue
        A = norm_vec(conns.get("A", []))
        Yv = norm_vec(conns.get("Y", []))
        if not Yv: continue

        ybit = Yv[0]
        yname = bit_to_name.get(ybit, ybit)

        resolved_A_names = [bit_to_name.get(ain, ain) for ain in A]

        pi_lits = []
        leaf_luts = []
        for nm in resolved_A_names:
            if isinstance(nm, str) and nm in pi_name_to_lit:
                pi_lits.append(pi_name_to_lit[nm])
            else:
                leaf_luts.append(producer.get(nm, nm))

        cut_size = len(A)
        if cut_size > K: K = cut_size

        lut_nodes.append({
            "lut_out": yname,
            "aig_leaves": sorted(set(pi_lits)),
            "aig_leaf_names": [lit_to_pi_name.get(l) for l in sorted(set(pi_lits))],
            "leaf_lut_outs": leaf_luts,
            "cut_size": cut_size
        })

out = {
  "format": "lut_to_aig_leaves:v1",
  "circuit": design,
  "K": K,
  "lut_nodes": lut_nodes
}
with open(out_json, 'w', encoding='utf-8') as f:
    json.dump(out, f, indent=2)
print(f"JSON → {out_json}")

# ---- Extra: CSV’s ----
base = os.path.splitext(out_json)[0]
csv_luts = base + ".lut_nodes.csv"
csv_pi  = base + ".pi_counts.csv"

# 1) per-LUT CSV
with open(csv_luts, 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(["lut_out","cut_size","num_pi_leaves","pi_literals","pi_names","num_internal_leaves","internal_leaves"])
    for n in lut_nodes:
        w.writerow([
            n["lut_out"],
            n["cut_size"],
            len(n["aig_leaves"]),
            " ".join(map(str, n["aig_leaves"])),
            " ".join(x for x in n["aig_leaf_names"] if x),
            len(n["leaf_lut_outs"]),
            " ".join(map(str, n["leaf_lut_outs"]))
        ])
print(f"CSV → {csv_luts}")

# 2) PI-frequenties (hoe vaak een PI in LUT-cuts zit)
from collections import Counter
cnt = Counter()
for n in lut_nodes:
    for name in (n["aig_leaf_names"] or []):
        if name: cnt[name] += 1

with open(csv_pi, 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(["pi_name","count"])
    for name, k in sorted(cnt.items(), key=lambda x: (-x[1], x[0])):
        w.writerow([name, k])
print(f"CSV → {csv_pi}")

PYCODE
echo "Klaar: $OUT_JSON"
