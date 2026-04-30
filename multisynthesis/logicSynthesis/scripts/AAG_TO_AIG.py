#!/usr/bin/env python3
"""
aag_to_aig.py — Convert ASCII AIGER (.aag) to binary AIGER (.aig) using Yosys.

Dependency:
  - yosys (must be in PATH)

Usage:
  python3 aag_to_aig.py input.aag output.aig
"""

import shutil
import subprocess
import sys
from pathlib import Path


def die(msg: str, code: int = 1):
    print(f"[ERROR] {msg}", file=sys.stderr)
    sys.exit(code)


def main():
    if len(sys.argv) != 3:
        die("Usage: python3 aag_to_aig.py input.aag output.aig")

    in_path = Path(sys.argv[1]).resolve()
    out_path = Path(sys.argv[2]).resolve()

    if not in_path.exists():
        die(f"Input file does not exist: {in_path}")

    if in_path.suffix.lower() != ".aag":
        print(f"[WARN] Input extension is {in_path.suffix}, expected .aag")

    yosys = shutil.which("yosys")
    if yosys is None:
        die("Yosys not found in PATH")

    yosys_script = f"""
read_aiger "{in_path}"
write_aiger "{out_path}"
"""

    result = subprocess.run(
        [yosys, "-q", "-p", yosys_script],
        text=True,
        capture_output=True
    )

    if result.returncode != 0:
        die(
            "Yosys failed\n"
            f"STDERR:\n{result.stderr}\n"
            f"STDOUT:\n{result.stdout}"
        )

    if not out_path.exists() or out_path.stat().st_size == 0:
        die("Output file not created or empty")

    print(f"[OK] Converted:\n  AAG → {in_path}\n  AIG → {out_path}")


if __name__ == "__main__":
    main()
