#!/usr/bin/env bash
set -euo pipefail

# logic_synth.sh — ABC logic synthesis & K-LUT mapping voor .blif of .aig/.aag
# Default folders (passen in jouw Masterproef-structuur):
#   OUT_DIR = ~/Masterproef/multisynthesis/logicSynthesis/results
#   LOG_DIR = ~/Masterproef/multisynthesis/logicSynthesis/logs
#
# Gebruik:
#   ./logic_synth.sh <input.{blif|aig|aag}> [opties]
#
# Opties:
#   --lut K                 LUT-grootte (default 6)
#   --mode speed|area       Flow focus (default speed)
#   --no-postmap-aig        Schrijf géén post-mapping AIG
#   --abc-bin PATH          Forceer pad naar abc
#   --out-dir DIR           Resultaten-root (heeft subdirs Aig/ en Blif/)
#   --log-dir DIR           Logs-dir
#   --csv FILE              Append pre/post 'ps'-stats als CSV
#   --allow-latches         (alleen BLIF) sta .latch toe (default: blokkeren)

########## Defaults ##########
MPROOT="${MPROOT:-$HOME/Masterproef/multisynthesis}"
OUT_DIR="${OUT_DIR:-$MPROOT/logicSynthesis/results}"
LOG_DIR="${LOG_DIR:-$MPROOT/logicSynthesis/logs}"
K="${K:-4}"
MODE="${MODE:-speed}"

ABC_BIN="${ABC_BIN:-$HOME/Masterproef/vtr-verilog-to-routing/build/abc/abc}"

if [[ ! -x "$ABC_BIN" ]]; then
  echo "Fout: ABC niet gevonden of niet uitvoerbaar op: $ABC_BIN" >&2
  exit 1
fi

WRITE_POSTMAP_AIG=1
ALLOW_LATCHES=0
CSV=""
IN=""

########## Parse args ##########
while [[ $# -gt 0 ]]; do
  case "$1" in
    --lut) K="$2"; shift 2;;
    --mode) MODE="$2"; shift 2;;
    --no-postmap-aig) WRITE_POSTMAP_AIG=0; shift;;
    --abc-bin) ABC_BIN="$2"; shift 2;;
    --out-dir) OUT_DIR="$(realpath -m "$2")"; shift 2;;
    --log-dir) LOG_DIR="$(realpath -m "$2")"; shift 2;;
    --csv) CSV="$(realpath -m "$2")"; shift 2;;
    --allow-latches) ALLOW_LATCHES=1; shift;;
    -h|--help) sed -n '1,80p' "$0"; exit 0;;
    *) if [[ -z "${IN:-}" ]]; then IN="$(realpath -m "$1")"; shift; else echo "Onbekend argument: $1" >&2; exit 1; fi;;
  esac
done

[[ -z "${IN:-}" ]] && { echo "Fout: geen inputbestand"; exit 1; }
[[ ! -f "$IN" ]] && { echo "Bestand niet gevonden: $IN"; exit 1; }



mkdir -p "$OUT_DIR/Aig" "$OUT_DIR/Blif" "$LOG_DIR"


# <<< NIEUW: controleer dat ABC echt bestaat en uitvoerbaar is
if [[ ! -x "$ABC_BIN" ]]; then
  echo "Fout: ABC niet gevonden of niet uitvoerbaar op: $ABC_BIN" >&2
  echo "Pas ABC_BIN aan in logic_synth.sh of exporteer ABC_BIN vóór je de script runt." >&2
  exit 1
fi



########## Vind ABC ##########


pick_abc() {
  try() {
    local cand="$1"
    [[ -n "$cand" && -x "$cand" ]] || return 1
    "$cand" -c "help" >/dev/null 2>&1 || return 1
    echo "$cand"
    return 0
  }

  # 1) Respecteer expliciete env/flag
  if [[ -n "${ABC_BIN:-}" ]]; then
    if try "$ABC_BIN"; then return 0; fi
  fi

  # 2) Bekende VTR-locaties (meerdere varianten)
  local roots=(
    "$HOME/Masterproef/vtr-verilog-to-routing"
    "$HOME/vtr-verilog-to-routing"
  )
  for r in "${roots[@]}"; do
    for cand in \
      "$r/build/abc/abc" \
      "$r/build/abc" \
      "$r/abc/abc" \
      "$r/abc" \
      "$r/build/*/abc/abc" \
      "$r/build/*/abc"
    do
      # shellcheck disable=SC2086
      for c in $cand; do
        if try "$c"; then return 0; fi
      done
    done
  done

  # 3) PATH (soms systeem-abc of yosys-abc)
  if try "$(command -v abc 2>/dev/null)"; then return 0; fi
  if try "$(command -v yosys-abc 2>/dev/null)"; then return 0; fi

  # 4) Fallback: zoek met find in VTR-tree (maxdepth om traagheid te beperken)
  for r in "${roots[@]}"; do
    if [[ -d "$r" ]]; then
      local f
      f="$(find "$r" -maxdepth 6 -type f -name abc -perm -u+x 2>/dev/null | head -n1)"
      if [[ -n "$f" ]] && try "$f"; then return 0; fi
    fi
  done

  return 1
}



########## Input-type & namen ##########
ext="${IN##*.}"
base="$(basename "$IN")"
base="${base%.*}"                     # bv. adder.pre
design="${base%.pre}"                 # bv. adder

# Latch-check voor BLIF
if [[ "$ext" == "blif" && "$ALLOW_LATCHES" -eq 0 ]]; then
  if grep -q '^[[:space:]]*\.latch' "$IN"; then
    echo "Afgebroken: input bevat .latch. Gebruik --allow-latches indien gewenst." >&2
    exit 1
  fi
fi

OUT_POSTOPT_AIG="$OUT_DIR/Aig/${design}.postopt.aig"
OUT_POSTMAP_AIG="$OUT_DIR/Aig/${design}.postmap.aig"
OUT_MAPPED_BLIF="$OUT_DIR/Blif/${design}.mapped.blif"
LOG_FILE="$LOG_DIR/${design}.abc.log"

########## Helpers ##########
run_ps() { "$ABC_BIN" -c "$1" | awk '/i\/o[[:space:]]*=/{print; exit}'; }
parse_ps_csv() {
  awk 'BEGIN{OFS=","}
    {
      line=$0
      gsub(/\x1B\[[0-9;]*[A-Za-z]/,"",line)
      gsub(/^\[[^]]*\][[:space:]]*/,"",line)
      pi=po=lat=nd=edge=aig=lev=""
      if (match(line,/i\/o[[:space:]]*=([0-9]+)\/([0-9]+)/,m)) {pi=m[1];po=m[2]}
      if (match(line,/lat[[:space:]]*=([0-9]+)/,m)) lat=m[1]
      if (match(line,/(^|[[:space:]])nd[[:space:]]*=([0-9]+)/,m)) nd=m[2]
      if (nd=="") if (match(line,/(^|[[:space:]])and[[:space:]]*=([0-9]+)/,m)) nd=m[2]
      if (match(line,/edge[[:space:]]*=([0-9]+)/,m)) edge=m[1]
      if (match(line,/aig[[:space:]]*=([0-9]+)/,m))  aig=m[1]
      if (match(line,/lev[[:space:]]*=([0-9]+)/,m))  lev=m[1]
      printf "%s,%s,%s,%s,%s,%s,%s,%s,%s\n", ENVIRON["CSV_DESIGN"], ENVIRON["CSV_STAGE"], pi, po, lat, nd, edge, aig, lev
    }'
}

########## ABC flow bouwen ##########


READ_CMD=""

case "$ext" in
  blif)
    READ_CMD="read_blif \"$IN\";"
    ;;
  aig)
    # binaire Aiger (wat ABC verwacht)
    READ_CMD="read_aiger \"$IN\";"
    ;;
  aag)
    echo "Fout: .aag (ASCII AIGER) wordt niet rechtstreeks door ABC gelezen." >&2
    echo "      Gebruik .aig of .blif als input voor logic_synth.sh." >&2
    exit 1
    ;;
  *)
    echo "Onbekende extensie: .$ext (verwacht .blif/.aig)" >&2
    exit 1
    ;;
esac


# Mode-afhankelijke opties
if [[ "$MODE" == "area" ]]; then
  RW_OPTS="rewrite -z;"
  IF_OPTS="-a"
else
  RW_OPTS="rewrite -lz;"
  IF_OPTS=""
fi

# Eén ABC-run: pre-ps, optimalisatie, postopt-aig, mapping, post-ps, write_blif, (optioneel) postmap-aig
ABC_CMD="$READ_CMD strash; dch; dc2; $RW_OPTS balance; resub -K $K; ps; write_aiger -s \"$OUT_POSTOPT_AIG\"; if -K $K $IF_OPTS; ps; write_blif \"$OUT_MAPPED_BLIF\";"
if [[ "$WRITE_POSTMAP_AIG" -eq 1 ]]; then
  ABC_CMD="$ABC_CMD read_blif \"$OUT_MAPPED_BLIF\"; strash; write_aiger -s \"$OUT_POSTMAP_AIG\";"
fi

echo "Flow: $MODE | K=$K"
echo "Log : $LOG_FILE"

# Run & capteer logs
set +e
RUN_OUT="$("$ABC_BIN" -c "$ABC_CMD" 2>&1 | tee "$LOG_FILE")"
rc=$?
set -e
[[ $rc -ne 0 ]] && { echo "ABC faalde (rc=$rc). Zie: $LOG_FILE" >&2; exit $rc; }

# Pak pre/post ps-regels uit log
PRE_PS="$(printf '%s\n' "$RUN_OUT" | awk '/i\/o[[:space:]]*=/ {print; exit}')"
POST_PS="$(printf '%s\n' "$RUN_OUT" | awk '/i\/o[[:space:]]*=/ {last=$0} END{print last}')"

echo "[PRE]  $PRE_PS"
echo "[POST] $POST_PS"

[[ -s "$OUT_POSTOPT_AIG" ]] || { echo "Ontbreekt: $OUT_POSTOPT_AIG" >&2; exit 1; }
[[ -s "$OUT_MAPPED_BLIF"  ]] || { echo "Ontbreekt: $OUT_MAPPED_BLIF"  >&2; exit 1; }
if [[ "$WRITE_POSTMAP_AIG" -eq 1 ]]; then
  [[ -s "$OUT_POSTMAP_AIG" ]] || { echo "Ontbreekt: $OUT_POSTMAP_AIG" >&2; exit 1; }
fi

# CSV
if [[ -n "$CSV" ]]; then
  mkdir -p "$(dirname "$CSV")"
  if [[ ! -s "$CSV" ]]; then
    echo "design,stage,pi,po,lat,nd,edge,aig,lev" > "$CSV"
  fi
  export CSV_DESIGN="$design"
  export CSV_STAGE="pre";  printf '%s\n' "$PRE_PS"  | parse_ps_csv >> "$CSV"
  export CSV_STAGE="post"; printf '%s\n' "$POST_PS" | parse_ps_csv >> "$CSV"
  echo "CSV → $CSV"
fi

echo "OK → $OUT_POSTOPT_AIG"
echo "OK → $OUT_MAPPED_BLIF"
[[ "$WRITE_POSTMAP_AIG" -eq 1 ]] && echo "OK → $OUT_POSTMAP_AIG"
