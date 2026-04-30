#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Gebruik: $0 <RUN_DIR> [VIVADO_BIN]"
  echo "Voorbeeld: $0 ~/Masterproef/project/results/run_eco_batch/2026-04-22_20-18-58 vivado"
  exit 1
fi

RUN_DIR="$(realpath "$1")"
VIVADO_BIN="${2:-vivado}"

if [[ ! -d "$RUN_DIR" ]]; then
  echo "FOUT: RUN_DIR bestaat niet: $RUN_DIR"
  exit 1
fi

OUT_DIR="$RUN_DIR/audit_wrong_nets"
mkdir -p "$OUT_DIR"

MANIFEST_TSV="$OUT_DIR/manifest.tsv"
TCL_SCRIPT="$OUT_DIR/audit_wrong_nets.tcl"
AUDIT_TSV="$OUT_DIR/audit_results.tsv"
SUMMARY_TXT="$OUT_DIR/summary.txt"
VIVADO_LOG="$OUT_DIR/vivado_audit.log"
VIVADO_JOU="$OUT_DIR/vivado_audit.jou"

echo "[1/4] Manifest opbouwen uit iter_* mappen..."

python3 - "$RUN_DIR" "$MANIFEST_TSV" << 'PY'
import os
import re
import sys
import json
from pathlib import Path

run_dir = Path(sys.argv[1])
manifest_tsv = Path(sys.argv[2])

# Zoek iteratiemappen eerst in RUN_DIR/iterations, anders rechtstreeks in RUN_DIR
iterations_root = run_dir / "iterations"
if iterations_root.is_dir():
    iter_dirs = sorted([p for p in iterations_root.iterdir() if p.is_dir() and p.name.startswith("iter_")])
else:
    iter_dirs = sorted([p for p in run_dir.iterdir() if p.is_dir() and p.name.startswith("iter_")])

def read_text(path):
    try:
        return path.read_text(errors="ignore")
    except Exception:
        return ""

def read_json(path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return None

def recursive_find(obj, wanted_keys):
    hits = []
    wanted_keys = {k.lower() for k in wanted_keys}

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                kl = str(k).lower()
                if kl in wanted_keys and isinstance(v, (str, int, float)):
                    hits.append(str(v))
                walk(v)
        elif isinstance(x, list):
            for e in x:
                walk(e)

    walk(obj)
    return hits

def parse_insert_log(insert_log_text):
    out = {}
    patterns = {
        "net_name": r"--net\s+(\S+)",
        "sink_cell": r"--lutB\s+(\S+)",
        "target_slice": r"--target_slice\s+(\S+)",
        "buffer_name": r"--buffer_name\s+(\S+)",
        "split_name": r"--split_name\s+(\S+)",
        "sink_pin_cmd": r"--sink_pin\s+(\S+)",
    }
    for k, pat in patterns.items():
        m = re.search(pat, insert_log_text)
        if m:
            out[k] = m.group(1)
    return out

def parse_compare_log(compare_log_text):
    out = {
        "baseline_ps": "",
        "eco_total_ps": "",
        "delta_total_ps": "",
        "eco_seg1_ps": "",
        "eco_seg2_ps": "",
        "lut_delay_ps": "",
    }

    m = re.search(r'RESULT_JSON:\s*\{(.+?)\}\s*$', compare_log_text, flags=re.M | re.S)
    if m:
        body = "{" + m.group(1) + "}"
        try:
            data = json.loads(body)
            for k in out:
                if k in data:
                    out[k] = str(data[k])
            return out
        except Exception:
            pass

    pats = {
        "baseline_ps": r'baseline_ps["=:\s]+([0-9.+\-Ee]+)',
        "eco_total_ps": r'eco_total_ps["=:\s]+([0-9.+\-Ee]+)',
        "delta_total_ps": r'delta_total_ps["=:\s]+([0-9.+\-Ee]+)',
        "eco_seg1_ps": r'eco_seg1_ps["=:\s]+([0-9.+\-Ee]+)',
        "eco_seg2_ps": r'eco_seg2_ps["=:\s]+([0-9.+\-Ee]+)',
        "lut_delay_ps": r'lut_delay_ps["=:\s]+([0-9.+\-Ee]+)',
    }
    for k, pat in pats.items():
        m = re.search(pat, compare_log_text)
        if m:
            out[k] = m.group(1)
    return out

def parse_resolve_log(resolve_text):
    patterns = [
        r'resolved sink pin\s*=\s*(\S+)',
        r'"sink_pin"\s*:\s*"([^"]+)"',
        r'physical sink pin.*?([A-Za-z0-9_]+)\s*$',
    ]
    for pat in patterns:
        m = re.search(pat, resolve_text, flags=re.I | re.M)
        if m:
            return m.group(1)
    return ""

rows = []

# Referentie-DCP kiezen
reference_dcp = ""
preferred_dcps = [
    run_dir / "current_base.dcp",
    run_dir / "baseline_original.dcp",
]

for dcp in preferred_dcps:
    if dcp.exists():
        reference_dcp = str(dcp)
        break

for it in iter_dirs:
    iter_name = it.name
    base_before = it / "base_before.dcp"
    candidate_json = it / "candidate.json"
    compare_log = it / "compare.log"
    insert_log = it / "insert.log"
    resolve_log = it / "resolve_sink_pin.log"

    if not reference_dcp and base_before.exists():
        reference_dcp = str(base_before)

    cand = read_json(candidate_json) if candidate_json.exists() else None
    cand_hits = {}
    if cand is not None:
        for field, keys in {
            "net_name": {"net", "net_name", "baseline_net", "orig_net"},
            "sink_cell": {"sink_cell", "lutb", "lut_b", "cell_b", "destination_cell", "dest_cell"},
            "target_slice": {"target_slice", "mid_slice", "target_site"},
        }.items():
            hits = recursive_find(cand, keys)
            if hits:
                cand_hits[field] = hits[0]

    insert_text = read_text(insert_log)
    parsed_insert = parse_insert_log(insert_text)

    compare_text = read_text(compare_log)
    cmp = parse_compare_log(compare_text)

    resolve_text = read_text(resolve_log)
    resolved_sink_pin = parse_resolve_log(resolve_text)

    net_name = parsed_insert.get("net_name") or cand_hits.get("net_name", "")
    sink_cell = parsed_insert.get("sink_cell") or cand_hits.get("sink_cell", "")
    target_slice = parsed_insert.get("target_slice") or cand_hits.get("target_slice", "")
    split_name = parsed_insert.get("split_name", "")
    buffer_name = parsed_insert.get("buffer_name", "")
    sink_pin_cmd = parsed_insert.get("sink_pin_cmd", "")

    rows.append({
        "iter": iter_name,
        "base_before_dcp": str(base_before) if base_before.exists() else "",
        "net_name": net_name,
        "sink_cell": sink_cell,
        "target_slice": target_slice,
        "split_name": split_name,
        "buffer_name": buffer_name,
        "sink_pin_cmd": sink_pin_cmd,
        "resolved_sink_pin": resolved_sink_pin,
        "baseline_ps": cmp["baseline_ps"],
        "eco_total_ps": cmp["eco_total_ps"],
        "delta_total_ps": cmp["delta_total_ps"],
        "eco_seg1_ps": cmp["eco_seg1_ps"],
        "eco_seg2_ps": cmp["eco_seg2_ps"],
        "lut_delay_ps": cmp["lut_delay_ps"],
    })

if not reference_dcp:
    print("FOUT: geen referentie-DCP gevonden. Gezocht naar:", file=sys.stderr)
    print(f"  - {run_dir / 'current_base.dcp'}", file=sys.stderr)
    print(f"  - {run_dir / 'baseline_original.dcp'}", file=sys.stderr)
    print("  - eerste base_before.dcp in iter_* mappen", file=sys.stderr)
    sys.exit(2)

with manifest_tsv.open("w", encoding="utf-8") as f:
    header = [
        "reference_dcp",
        "iter",
        "base_before_dcp",
        "net_name",
        "sink_cell",
        "target_slice",
        "split_name",
        "buffer_name",
        "sink_pin_cmd",
        "resolved_sink_pin",
        "baseline_ps",
        "eco_total_ps",
        "delta_total_ps",
        "eco_seg1_ps",
        "eco_seg2_ps",
        "lut_delay_ps",
    ]
    f.write("\t".join(header) + "\n")
    for r in rows:
        vals = [reference_dcp] + [r[h] for h in header[1:]]
        vals = [str(v).replace("\t", " ").replace("\n", " ") for v in vals]
        f.write("\t".join(vals) + "\n")

print(f"Manifest geschreven naar: {manifest_tsv}")
print(f"Reference DCP: {reference_dcp}")
print(f"Aantal iteraties gevonden: {len(rows)}")
PY

echo "[2/4] Vivado Tcl-script genereren..."

cat > "$TCL_SCRIPT" << 'TCL'
if { $argc != 2 } {
    puts "Gebruik: vivado -mode batch -source audit_wrong_nets.tcl -tclargs <manifest.tsv> <audit_results.tsv>"
    exit 1
}

set manifest_tsv [lindex $argv 0]
set audit_tsv    [lindex $argv 1]

proc tsv_escape {s} {
    regsub -all {\t} $s { } s
    regsub -all {\n} $s { } s
    return $s
}

proc is_lut_type {ptype} {
    return [regexp {^CLB\.LUT\.LUT[1-6]$} $ptype]
}

set f [open $manifest_tsv r]
set lines [split [read $f] "\n"]
close $f

if {[llength $lines] < 2} {
    puts "FOUT: leeg manifest"
    exit 2
}

set header [split [lindex $lines 0] "\t"]
array set idx {}
for {set i 0} {$i < [llength $header]} {incr i} {
    set idx([lindex $header $i]) $i
}

set reference_dcp ""
foreach line [lrange $lines 1 end] {
    if {$line eq ""} { continue }
    set cols [split $line "\t"]
    if {[llength $cols] > $idx(reference_dcp)} {
        set reference_dcp [lindex $cols $idx(reference_dcp)]
        break
    }
}

if {$reference_dcp eq ""} {
    puts "FOUT: geen reference_dcp in manifest"
    exit 3
}

puts "Open checkpoint: $reference_dcp"
open_checkpoint $reference_dcp

set out [open $audit_tsv w]
puts $out [join {
    iter
    net_name
    sink_cell
    target_slice
    baseline_ps
    eco_total_ps
    delta_total_ps
    sink_pin_cmd
    resolved_sink_pin
    sink_ref_name
    sink_primitive_group
    sink_primitive_subgroup
    sink_primitive_type
    source_cell
    source_ref_name
    source_primitive_group
    source_primitive_subgroup
    source_primitive_type
    actual_sink_pin_name
    source_is_lut
    sink_is_lut
    sink_pin_looks_lut_input
    strict_lut_to_lut
    likely_io_sink
    net_found_in_reference_dcp
    suspicious_reason
} "\t"]

proc getv {cols idx name} {
    if {[info exists idx($name)] && [llength $cols] > $idx($name)} {
        return [lindex $cols $idx($name)]
    }
    return ""
}

foreach line [lrange $lines 1 end] {
    if {$line eq ""} { continue }
    set cols [split $line "\t"]

    set iter              [getv $cols idx iter]
    set net_name          [getv $cols idx net_name]
    set sink_cell_name    [getv $cols idx sink_cell]
    set target_slice      [getv $cols idx target_slice]
    set baseline_ps       [getv $cols idx baseline_ps]
    set eco_total_ps      [getv $cols idx eco_total_ps]
    set delta_total_ps    [getv $cols idx delta_total_ps]
    set sink_pin_cmd      [getv $cols idx sink_pin_cmd]
    set resolved_sink_pin [getv $cols idx resolved_sink_pin]

    set sink_ref_name ""
    set sink_pg ""
    set sink_psg ""
    set sink_ptype ""
    set source_cell_name ""
    set source_ref_name ""
    set source_pg ""
    set source_psg ""
    set source_ptype ""
    set actual_sink_pin_name ""
    set source_is_lut 0
    set sink_is_lut 0
    set sink_pin_looks_lut_input 0
    set strict_lut_to_lut 0
    set likely_io_sink 0
    set net_found 0
    set suspicious_reasons {}

    set sink_cell [get_cells -quiet $sink_cell_name]
    if {[llength $sink_cell] > 0} {
        set sink_ref_name [get_property REF_NAME $sink_cell]
        set sink_pg        [get_property PRIMITIVE_GROUP $sink_cell]
        set sink_psg       [get_property PRIMITIVE_SUBGROUP $sink_cell]
        set sink_ptype     [get_property PRIMITIVE_TYPE $sink_cell]
        set sink_is_lut    [is_lut_type $sink_ptype]

        if {$sink_pg eq "I/O"} {
            set likely_io_sink 1
            lappend suspicious_reasons "sink_is_io"
        }
        if {!$sink_is_lut} {
            lappend suspicious_reasons "sink_not_lut"
        }
    } else {
        lappend suspicious_reasons "sink_cell_not_found"
    }

    set net [get_nets -quiet $net_name]
    if {[llength $net] > 0} {
        set net_found 1

        set out_pins [get_pins -quiet -of_objects $net -filter {DIRECTION == OUT}]
        if {[llength $out_pins] == 1} {
            set src_pin [lindex $out_pins 0]
            set src_cell [get_cells -quiet -of_objects $src_pin]
            if {[llength $src_cell] > 0} {
                set source_cell_name [get_property NAME $src_cell]
                set source_ref_name  [get_property REF_NAME $src_cell]
                set source_pg        [get_property PRIMITIVE_GROUP $src_cell]
                set source_psg       [get_property PRIMITIVE_SUBGROUP $src_cell]
                set source_ptype     [get_property PRIMITIVE_TYPE $src_cell]
                set source_is_lut    [is_lut_type $source_ptype]
                if {!$source_is_lut} {
                    lappend suspicious_reasons "source_not_lut"
                }
            } else {
                lappend suspicious_reasons "source_cell_not_found"
            }
        } else {
            lappend suspicious_reasons "driver_pin_count_[llength $out_pins]"
        }

        set in_pins [get_pins -quiet -of_objects $net -filter {DIRECTION == IN}]
        set found_sink_pin 0
        foreach p $in_pins {
            set c [get_cells -quiet -of_objects $p]
            if {[llength $c] > 0 && [get_property NAME $c] eq $sink_cell_name} {
                set actual_sink_pin_name [get_property REF_PIN_NAME $p]
                set found_sink_pin 1
                break
            }
        }

        if {!$found_sink_pin} {
            if {[llength $in_pins] == 1} {
                set p [lindex $in_pins 0]
                set actual_sink_pin_name [get_property REF_PIN_NAME $p]
                lappend suspicious_reasons "sink_pin_not_matched_to_sink_cell"
            } else {
                lappend suspicious_reasons "sink_pin_not_found_on_net"
            }
        }

        if {[regexp {^I[0-5]$} $actual_sink_pin_name]} {
            set sink_pin_looks_lut_input 1
        } else {
            if {$actual_sink_pin_name ne ""} {
                lappend suspicious_reasons "sink_pin_$actual_sink_pin_name"
            }
        }

    } else {
        lappend suspicious_reasons "net_not_found_in_reference_dcp"
    }

    if {$source_is_lut && $sink_is_lut && $sink_pin_looks_lut_input} {
        set strict_lut_to_lut 1
    }

    if {$resolved_sink_pin eq "I"} {
        lappend suspicious_reasons "resolved_pin_I"
    }

    puts $out [join [list \
        [tsv_escape $iter] \
        [tsv_escape $net_name] \
        [tsv_escape $sink_cell_name] \
        [tsv_escape $target_slice] \
        [tsv_escape $baseline_ps] \
        [tsv_escape $eco_total_ps] \
        [tsv_escape $delta_total_ps] \
        [tsv_escape $sink_pin_cmd] \
        [tsv_escape $resolved_sink_pin] \
        [tsv_escape $sink_ref_name] \
        [tsv_escape $sink_pg] \
        [tsv_escape $sink_psg] \
        [tsv_escape $sink_ptype] \
        [tsv_escape $source_cell_name] \
        [tsv_escape $source_ref_name] \
        [tsv_escape $source_pg] \
        [tsv_escape $source_psg] \
        [tsv_escape $source_ptype] \
        [tsv_escape $actual_sink_pin_name] \
        $source_is_lut \
        $sink_is_lut \
        $sink_pin_looks_lut_input \
        $strict_lut_to_lut \
        $likely_io_sink \
        $net_found \
        [tsv_escape [join $suspicious_reasons ";"]] \
    ] "\t"]
}

close $out
puts "Audit geschreven naar: $audit_tsv"
exit 0
TCL

echo "[3/4] Vivado audit draaien..."
"$VIVADO_BIN" -mode batch \
  -log "$VIVADO_LOG" \
  -journal "$VIVADO_JOU" \
  -source "$TCL_SCRIPT" \
  -tclargs "$MANIFEST_TSV" "$AUDIT_TSV"


echo "[4/4] Samenvatting opbouwen..."

python3 - "$AUDIT_TSV" "$SUMMARY_TXT" << 'PY'
import sys
from pathlib import Path

audit_tsv = Path(sys.argv[1])
summary_txt = Path(sys.argv[2])

rows = []
with audit_tsv.open() as f:
    header = f.readline().rstrip("\n").split("\t")
    for line in f:
        line = line.rstrip("\n")
        if not line:
            continue
        cols = line.split("\t")
        row = dict(zip(header, cols))
        rows.append(row)

def count(pred):
    return sum(1 for r in rows if pred(r))

total = len(rows)
strict = count(lambda r: r["strict_lut_to_lut"] == "1")
sink_not_lut = count(lambda r: r["sink_is_lut"] == "0")
source_not_lut = count(lambda r: r["source_is_lut"] == "0")
io_sink = count(lambda r: r["likely_io_sink"] == "1")
resolved_I = count(lambda r: r["resolved_sink_pin"] == "I")
actual_I = count(lambda r: r["actual_sink_pin_name"] == "I")
net_missing = count(lambda r: r["net_found_in_reference_dcp"] == "0")

top_sink_types = {}
for r in rows:
    k = r["sink_primitive_type"] or "<EMPTY>"
    top_sink_types[k] = top_sink_types.get(k, 0) + 1

top_sink_types = sorted(top_sink_types.items(), key=lambda kv: (-kv[1], kv[0]))[:20]

bad_examples = [
    r for r in rows
    if r["strict_lut_to_lut"] == "0"
][:20]

with summary_txt.open("w") as f:
    f.write("AUDIT WRONG NETS - SUMMARY\n")
    f.write("==========================\n\n")
    f.write(f"Total iteraties                 : {total}\n")
    f.write(f"Strict LUT->LUT                 : {strict}\n")
    f.write(f"Sink is NOT LUT                 : {sink_not_lut}\n")
    f.write(f"Source is NOT LUT               : {source_not_lut}\n")
    f.write(f"Likely I/O sink                 : {io_sink}\n")
    f.write(f"Resolved sink pin == I          : {resolved_I}\n")
    f.write(f"Actual sink pin on net == I     : {actual_I}\n")
    f.write(f"Net niet gevonden in ref DCP    : {net_missing}\n\n")

    f.write("Top sink primitive types:\n")
    for k, v in top_sink_types:
        f.write(f"  {v:5d}  {k}\n")

    f.write("\nVoorbeelden van verdachte iteraties:\n")
    for r in bad_examples:
        f.write(
            f"  {r['iter']}: net={r['net_name']} sink={r['sink_cell']} "
            f"sink_type={r['sink_primitive_type']} actual_sink_pin={r['actual_sink_pin_name']} "
            f"reason={r['suspicious_reason']}\n"
        )

print(f"Samenvatting geschreven naar: {summary_txt}")
PY

echo
echo "KLAAR"
echo "Audit map: $OUT_DIR"
echo "Belangrijkste bestanden:"
echo "  - $AUDIT_TSV"
echo "  - $SUMMARY_TXT"
echo "  - $VIVADO_LOG"
