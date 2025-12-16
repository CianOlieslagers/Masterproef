#!/usr/bin/env bash
set -euo pipefail

# ---- ABC locatie expliciet instellen ----
ABC_BIN="$HOME/Masterproef/vtr-verilog-to-routing/abc/abc"

if [ ! -x "$ABC_BIN" ]; then
  echo "[ERROR] ABC niet gevonden of niet uitvoerbaar: $ABC_BIN" >&2
  exit 1
fi

# ---- CLI parsing ----
if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
  echo "Gebruik: $0 pad/naar/net.aig [pad/naar/output.dot]" >&2
  exit 1
fi

AIG_PATH="$1"

if [ ! -f "$AIG_PATH" ]; then
  echo "[ERROR] Bestend niet gevonden: $AIG_PATH" >&2
  exit 1
fi

if [ "$#" -eq 2 ]; then
  DOT_PATH="$2"
else
  DOT_PATH="${AIG_PATH%.aig}.dot"
fi

echo "[INFO] AIG-in : $AIG_PATH"
echo "[INFO] DOT-uit: $DOT_PATH"
echo "[INFO] Gebruik ABC: $ABC_BIN"

# ---- Run ABC ----
"$ABC_BIN" -c "
read_aiger $AIG_PATH;
write_dot $DOT_PATH;
"

echo "[OK] DOT geschreven naar: $DOT_PATH"

