#!/usr/bin/env python3
"""
aig_to_aag.py — Convert binary AIGER (.aig) to ASCII AIGER (.aag) using Yosys.

Dependency:
  - yosys must be installed and available in PATH

Usage:
  python3 aig_to_aag.py input.aig output.aag
"""

import shutil
import subprocess
import sys
from pathlib import Path


def die(msg: str, code: int = 1) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr)
    raise SystemExit(code)


def main() -> None:
    if len(sys.argv) != 3:
        die("Usage: python3 aig_to_aag.py input.aig output.aag")

    in_path = Path(sys.argv[1]).expanduser().resolve()
    out_path = Path(sys.argv[2]).expanduser().resolve()

    if not in_path.exists():
        die(f"Input file not found: {in_path}")
    if in_path.suffix.lower() != ".aig":
        print(f"[WARN] Input extension is '{in_path.suffix}', expected '.aig' (continuing anyway).")

    yosys = shutil.which("yosys")
    if yosys is None:
        die("Yosys not found in PATH. Install yosys or load your yosys environment/module.")

    # Yosys script: read binary AIGER, then write ASCII AIGER
    yosys_script = f"""
read_aiger "{in_path}"
write_aiger -ascii "{out_path}"
"""

    try:
        res = subprocess.run(
            [yosys, "-q", "-p", yosys_script],
            check=False,
            text=True,
            capture_output=True,
        )
    except Exception as e:
        die(f"Failed to run yosys: {e}")

    if res.returncode != 0:
        die(f"Yosys failed (code {res.returncode}).\nSTDERR:\n{res.stderr.strip()}\nSTDOUT:\n{res.stdout.strip()}")

    if not out_path.exists() or out_path.stat().st_size == 0:
        die(f"Output not created or empty: {out_path}")

    print(f"[OK] Converted:\n  IN : {in_path}\n  OUT: {out_path}")


if __name__ == "__main__":
    main()
