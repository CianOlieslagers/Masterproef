#!/usr/bin/env bash
set -euo pipefail

# VtoAigBlif.sh — Verilog (.v) → BLIF (.pre.blif) en optioneel AIG (.pre.aag) via Yosys
#
# Gebruik (oude stijl, backwards-compatible):
#   ./VtoAigBlif.sh <src.v> [--write-aig] [--out-yosys-blif DIR] [--out-yosys-aig DIR]
#
# Gebruik (nieuwe stijl):
#   ./VtoAigBlif.sh <src.v> [--top NAME] [--lib FILE.v] [--lib-blackbox]
#                     [--define NAME[=VAL]]... [--incdir DIR]...
#                     [--no-flatten] [--allow-latches] [--no-aig]
#                     [--yosys-bin PATH] [--out-dir DIR] [--log-dir DIR]
#
# Default projectlayout:
#   MPROOT = ~/Masterproef/multisynthesis
#   OUT_DIR = $MPROOT/elaboration/results
#   LOG_DIR = $MPROOT/elaboration/logs
#   BLIF gaat naar: $OUT_DIR/Blif
#   AIG  gaat naar: $OUT_DIR/Aig

########## Defaults ##########
MPROOT="${MPROOT:-$HOME/Masterproef/multisynthesis}"
OUT_DIR="${OUT_DIR:-$MPROOT/elaboration/results}"
LOG_DIR="${LOG_DIR:-$MPROOT/elaboration/logs}"

# Submappen (kunnen overschreven worden met --out-yosys-blif / --out-yosys-aig)
OUT_YOSYS_BLIF="${OUT_YOSYS_BLIF:-$OUT_DIR/Blif}"
OUT_YOSYS_AIG="${OUT_YOSYS_AIG:-$OUT_DIR/Aig}"

WRITE_AIG="${WRITE_AIG:-1}"         # standaard: schrijf AIG
ALLOW_LATCHES="${ALLOW_LATCHES:-0}"  # standaard: geen latches toegestaan
DO_FLATTEN="${DO_FLATTEN:-1}"        # standaard: flatten aan
YOSYS_BIN="${YOSYS_BIN:-}"           # autodetect indien leeg

SRC=""
TOP=""
LIB=""
LIB_BLACKBOX=0

# verzamelbare opties
DEF_OPTS=()   # --define NAME[=VAL] → -DNAME[=VAL]
INC_OPTS=()   # --incdir DIR → -I DIR

########## Parse args ##########
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      sed -n '1,60p' "$0"; exit 0;;
    --top) TOP="$2"; shift 2;;
    --lib) LIB="$(realpath -m "$2")"; shift 2;;
    --lib-blackbox) LIB_BLACKBOX=1; shift;;
    --define) DEF_OPTS+=("-D$2"); shift 2;;
    --incdir) INC_OPTS+=("-I" "$2"); shift 2;;
    --no-flatten) DO_FLATTEN=0; shift;;
    --allow-latches) ALLOW_LATCHES=1; shift;;
    --no-aig) WRITE_AIG=0; shift;;
    --write-aig) WRITE_AIG=1; shift;;                             # oude vlag
    --yosys-bin) YOSYS_BIN="$(realpath -m "$2")"; shift 2;;
    --out-dir) OUT_DIR="$(realpath -m "$2")"; shift 2;;
    --out-yosys-blif) OUT_YOSYS_BLIF="$(realpath -m "$2")"; shift 2;;  # oude vlag
    --out-yosys-aig)  OUT_YOSYS_AIG="$(realpath -m "$2")"; shift 2;;   # oude vlag
    *)
      if [[ -z "$SRC" ]]; then
        SRC="$(realpath -m "$1")"; shift
      else
        echo "Onbekend argument: $1" >&2; exit 1
      fi;;
  esac
done

[[ -z "${SRC:-}" ]] && { echo "Fout: geen input .v"; exit 1; }
[[ ! -f "$SRC" ]] && { echo "Bestand niet gevonden: $SRC"; exit 1; }
[[ -n "$LIB" && ! -f "$LIB" ]] && { echo "Library niet gevonden: $LIB"; exit 1; }

# Als --out-dir is ingesteld, herleid submappen (tenzij expliciet al overschreven)
if [[ -n "${OUT_DIR:-}" ]]; then
  [[ "${OUT_YOSYS_BLIF:-}" == "$HOME/Masterproef/multisynthesis/elaboration/results/Blif" ]] && OUT_YOSYS_BLIF="$OUT_DIR/Blif"
  [[ "${OUT_YOSYS_AIG:-}"  == "$HOME/Masterproef/multisynthesis/elaboration/results/Aig"  ]] && OUT_YOSYS_AIG="$OUT_DIR/Aig"
fi

mkdir -p "$OUT_YOSYS_BLIF" "$OUT_YOSYS_AIG" "$LOG_DIR"

########## Vind Yosys ##########
if [[ -z "$YOSYS_BIN" ]]; then
  # 1) OSS-CAD-Suite
  if [[ -x "$HOME/oss-cad-suite/bin/yosys" ]]; then
    YOSYS_BIN="$HOME/oss-cad-suite/bin/yosys"
  # 2) VTR-binary (soms meegebouwd)
  elif [[ -x "$HOME/Masterproef/vtr-verilog-to-routing/build/yosys/yosys" ]]; then
    YOSYS_BIN="$HOME/Masterproef/vtr-verilog-to-routing/build/yosys/yosys"
  # 3) Systeem
  elif command -v yosys >/dev/null 2>&1; then
    YOSYS_BIN="$(command -v yosys)"
  else
    echo "Fout: Yosys niet gevonden. Zet --yosys-bin of zet PATH." >&2
    exit 1
  fi
fi

echo "Yosys: $YOSYS_BIN"

########## Bestandsnamen ##########
base="$(basename "$SRC" .v)"
PRE_BLIF="$OUT_YOSYS_BLIF/${base}.pre.blif"

PRE_AAG="$OUT_YOSYS_AIG/${base}.pre.aag"   # ASCII AIGER
PRE_AIG="$OUT_YOSYS_AIG/${base}.pre.aig" 

LOGFILE="$LOG_DIR/${base}.yosys.log"

########## Bouw Yosys-script ##########
tmpys="$(mktemp)"
{
  # Library (optioneel)
  if [[ -n "$LIB" ]]; then
    if [[ $LIB_BLACKBOX -eq 1 ]]; then
      echo "read_verilog -sv -lib \"$LIB\""
    else
      echo "read_verilog -sv \"$LIB\""
    fi
  fi

  # Bron met defines en incdirs
  echo -n "read_verilog -sv"
  for x in "${INC_OPTS[@]}"; do echo -n " $x"; done
  for d in "${DEF_OPTS[@]}"; do echo -n " $d"; done
  echo " \"$SRC\""

  if [[ -n "$TOP" ]]; then
    echo "hierarchy -check -top \"$TOP\""
  else
    echo "hierarchy -check -auto-top"
  fi

  echo "proc; opt; fsm; opt; memory; opt"
  echo "techmap; opt_clean"

  if [[ $DO_FLATTEN -eq 1 ]]; then
    echo "flatten -wb; opt -purge"
  fi

  echo "check -assert"

  if [[ $ALLOW_LATCHES -eq 0 ]]; then
    # assert: geen latches
    echo "select -assert-none t:\\\$dlatch*"
  fi

  echo "write_blif \"$PRE_BLIF\""

  if [[ $WRITE_AIG -eq 1 ]]; then
    echo "aigmap"
    echo "write_aiger \"$PRE_AIG\""
    echo "write_aiger -ascii \"$PRE_AAG\""

  fi
} > "$tmpys"

########## Run ##########
set +e
"$YOSYS_BIN" -s "$tmpys" | tee "$LOGFILE"
rc=$?
set -e
rm -f "$tmpys"

[[ $rc -ne 0 ]] && { echo "Yosys faalde, zie log: $LOGFILE"; exit $rc; }

[[ ! -s "$PRE_BLIF" ]] && { echo "Mislukt: $PRE_BLIF ontbreekt of leeg"; exit 1; }
echo "OK → BLIF: $PRE_BLIF"

if [[ $WRITE_AIG -eq 1 ]]; then
  [[ ! -s "$PRE_AAG" ]] && { echo "Mislukt: $PRE_AAG ontbreekt of leeg"; exit 1; }
  [[ ! -s "$PRE_AIG" ]] && { echo "Mislukt: $PRE_AIG ontbreekt of leeg"; exit 1; }
  echo "OK → AIG (ascii): $PRE_AAG"
  echo "OK → AIG (bin) : $PRE_AIG"
fi
# Extra sanity prints
echo "---- Samenvatting ----"
grep -n '^\.\(model\|inputs\|outputs\)' "$PRE_BLIF" || true
if [[ $ALLOW_LATCHES -eq 0 ]]; then
  if grep -q '^\.latch' "$PRE_BLIF"; then
    echo "WAARSCHUWING: latches gevonden in BLIF!"
  else
    echo "Check: geen latches gevonden."
  fi
fi
