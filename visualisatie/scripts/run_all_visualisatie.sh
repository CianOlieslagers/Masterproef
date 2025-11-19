#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "Gebruik: $0 pad/naar/design.v"
  exit 1
fi

VERILOG_PATH="$1"

if [ ! -f "$VERILOG_PATH" ]; then
  echo "Bestand niet gevonden: $VERILOG_PATH" >&2
  exit 1
fi

# Map van dit script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXAMPLES_DIR="$SCRIPT_DIR/../examples"

# Paden naar de 4 operaties
declare -A OPS
OPS[balancing]="$EXAMPLES_DIR/balancing/run_visualisatie"
OPS[factoring]="$EXAMPLES_DIR/factoring/run_visualisatie"
OPS[rewrite]="$EXAMPLES_DIR/rewrite/run_visualisatie.sh"
OPS[substitution]="$EXAMPLES_DIR/substitution/run_visualisatie.sh"

echo "Verilog : $VERILOG_PATH"
echo "Operaties die zullen draaien:"
for op in balancing factoring rewrite substitution; do
  echo "  - $op : ${OPS[$op]}"
done
echo

# Alles één voor één draaien
for op in balancing factoring rewrite substitution; do
  RUNNER="${OPS[$op]}"

  if [ ! -f "$RUNNER" ]; then
    echo "[ERROR] Script voor $op niet gevonden: $RUNNER" >&2
    continue
  fi

  if [ ! -x "$RUNNER" ]; then
    echo "[WARN] $RUNNER is niet uitvoerbaar (chmod +x nodig?). Ik probeer het toch via 'bash'."
    echo
    echo "=== [$op] (via bash) ==="
    ( cd "$(dirname "$RUNNER")" && bash "$(basename "$RUNNER")" "$VERILOG_PATH" )
  else
    echo
    echo "=== [$op] ==="
    ( cd "$(dirname "$RUNNER")" && ./$(basename "$RUNNER") "$VERILOG_PATH" )
  fi
done
