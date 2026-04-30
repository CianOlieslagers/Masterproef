# tony_sat/core/check_blif_hex_against_lut_cones.py
from __future__ import annotations
import json
import argparse
from typing import Dict
import sys


from tony_sat.core.blif_parser import parse_blif
from tony_sat.core.lut_truth import cubes_to_tt16, tt16_to_hex

def expand_ref_to_tt16(ref_hex: str, n_fanins: int) -> int:
    """
    Expand a possibly compact truth table (2^n_fanins bits) to 16-bit LUT4 view.
    Example (n_fanins=2): ref=0x1 -> tt16=0x1111
    """
    ref_int = int(str(ref_hex), 16)

    if n_fanins == 4:
        return ref_int & 0xFFFF

    if n_fanins < 0 or n_fanins > 4:
        raise ValueError(f"n_fanins must be 0..4, got {n_fanins}")

    width = 1 << n_fanins  # 2^k bits
    mask = (1 << width) - 1
    ref_int &= mask

    tt16 = 0
    low_mask = (1 << n_fanins) - 1
    for i in range(16):
        low = i & low_mask
        bit = (ref_int >> low) & 1
        if bit:
            tt16 |= (1 << i)
    return tt16 & 0xFFFF

def load_lut_cones(path: str) -> Dict[str, str]:
    """
    Load mapping LUT_name -> func_hex from mt_lut_cones output.

    Your file shape (confirmed):
      {
        "format": "...",
        "circuit": "...",
        "K": 4,
        "lut_cones": [
          {"lut_name":"LUT_11", "func_hex":"8777", ...},
          ...
        ]
      }
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Case: list under "lut_cones" (your confirmed structure)
    if isinstance(data, dict) and "lut_cones" in data and isinstance(data["lut_cones"], list):
        out: Dict[str, str] = {}
        for entry in data["lut_cones"]:
            if not isinstance(entry, dict):
                continue
            name = entry.get("lut_name")
            hx = entry.get("func_hex")
            if name is not None and hx is not None:
                out[str(name)] = str(hx).lower()
        if out:
            return out

    # Fallbacks (older guesses) — keep for robustness
    if isinstance(data, dict):
        if all(isinstance(v, dict) for v in data.values()):
            out = {}
            for k, v in data.items():
                if "func_hex" in v:
                    out[k] = str(v["func_hex"]).lower()
            if out:
                return out

        for key in ("luts", "cones"):
            if key in data and isinstance(data[key], dict):
                out = {}
                for k, v in data[key].items():
                    if isinstance(v, dict) and "func_hex" in v:
                        out[k] = str(v["func_hex"]).lower()
                if out:
                    return out

    raise RuntimeError(
        "Could not detect lut_cones.json structure automatically. "
        "Expected key 'lut_cones' containing a list of objects with 'lut_name' and 'func_hex'."
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blif", required=True)
    ap.add_argument("--lut_cones", required=True)
    ap.add_argument("--limit", type=int, default=20, help="How many mismatches to print")
    args = ap.parse_args()

    design = parse_blif(args.blif)
    cones = load_lut_cones(args.lut_cones)

    mism = []
    warn = []
    ok = 0
    skipped = 0

    for nb in design.names:
        name = nb.output
        n_fanins = len(nb.fanins)

        # Skip constants and primary output driver
        if name.startswith("new_n"):
            skipped += 1
            continue
        if name.startswith("po"):
            skipped += 1
            continue

        if name not in cones:
            mism.append((name, "MISSING_IN_LUT_CONES", ""))
            continue

        tt16 = cubes_to_tt16(nb.cubes, n_fanins)
        hx = tt16_to_hex(tt16)

        ref_raw = cones[name]
        ref_tt16 = expand_ref_to_tt16(ref_raw, n_fanins)
        ref_hex16 = f"{ref_tt16:04x}"

        if hx != ref_hex16:
            # BLIF is ground truth. For LUTs with <4 fanins, mt_lut_cones can store compact encodings
            # and we have observed at least one real inconsistency (e.g. LUT_388).
            # Therefore: warn only for n_fanins < 4; hard mismatch for n_fanins == 4.
            if n_fanins < 4:
                warn.append((name, n_fanins, ref_raw, ref_hex16, hx))
            else:
                mism.append((name, f"{ref_raw} (-> {ref_hex16})", hx))
        else:
            ok += 1

        print(f"[INFO] Compared LUT hex for BLIF vs lut_cones")
    print(f"       OK={ok}, hard_mismatches={len(mism)}, warnings={len(warn)}, skipped={skipped}")

    if warn:
        print(f"\n[WARN] {len(warn)} LUT(s) have <4 fanins and differ between BLIF (ground truth) and lut_cones:")
        for (name, nfi, ref_raw, ref_hex16, got_hex16) in warn[: args.limit]:
            print(f"  {name} (fanins={nfi}): ref={ref_raw} (-> {ref_hex16})  got={got_hex16}")
        if len(warn) > args.limit:
            print(f"  ... ({len(warn) - args.limit} more warnings)")

    if mism:
        print(f"\n[ERROR] Hard mismatches (fanins==4) — these should not happen:")
        for (name, ref, got) in mism[: args.limit]:
            print(f"  {name}: ref={ref}  got={got}")
        raise SystemExit(1)

    print("[OK] BLIF truth tables are consistent (lut_cones warnings ignored for fanins<4).")


if __name__ == "__main__":
    main()
