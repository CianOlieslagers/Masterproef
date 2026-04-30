# tony_sat/core/lut_truth.py
from __future__ import annotations
from typing import List, Tuple


class LutTruthError(Exception):
    pass


def _parse_cube_line(line: str) -> Tuple[str, str]:
    """
    Parse cube lines like:
      "-0-0 1"
      "1111 1"
      "0"      (constant 0 block)
      "1"      (constant 1 block)

    Returns: (pattern, value_char)
    """
    parts = line.split()
    if len(parts) == 1:
        # e.g. "0" or "1" in constant blocks
        pat = parts[0]
        if pat not in ("0", "1"):
            raise LutTruthError(f"Invalid cube line (single token): {line}")
        return ("", pat)  # pattern empty => constant
    if len(parts) == 2:
        pat, val = parts
        if val not in ("0", "1"):
            raise LutTruthError(f"Invalid cube value: {line}")
        return (pat, val)
    raise LutTruthError(f"Invalid cube line format: {line}")


def _match_pattern(pattern: str, bits: List[int]) -> bool:
    """
    pattern length must equal len(bits).
    '-' matches both.
    """
    if len(pattern) != len(bits):
        raise LutTruthError(f"Pattern length {len(pattern)} != bits length {len(bits)}")
    for ch, b in zip(pattern, bits):
        if ch == '-':
            continue
        if ch == '0' and b != 0:
            return False
        if ch == '1' and b != 1:
            return False
        if ch not in ('0', '1', '-'):
            raise LutTruthError(f"Invalid pattern char '{ch}' in {pattern}")
    return True


def cubes_to_tt16(cubes: List[str], n_fanins: int) -> int:
    """
    Compute 16-bit truth table for a LUT with n_fanins (0..4) from BLIF cubes.
    Output is an int where bit i corresponds to input combination i.

    IMPORTANT (bit order):
      We define combination index i by bits [b0,b1,b2,b3] where:
        b0 = LSB, b3 = MSB
      For n_fanins < 4, we use the first n_fanins bits [b0..b(n-1)].
    """
    if n_fanins < 0 or n_fanins > 4:
        raise LutTruthError(f"Unsupported n_fanins={n_fanins} (expected 0..4)")

    parsed = [_parse_cube_line(c) for c in cubes]

    # Handle constant block: .names out ; "0" or "1"
    if n_fanins == 0:
        # If any cube drives 1, output is 1; else 0 (BLIF semantics)
        out_val = 0
        for pat, val in parsed:
            if pat != "":
                raise LutTruthError("0-fanin .names should not have a pattern.")
            if val == "1":
                out_val = 1
        return 0xFFFF if out_val == 1 else 0x0000

    tt = 0
    for i in range(16):
        bits4 = [(i >> k) & 1 for k in range(4)]  # b0..b3
        bits = bits4[:n_fanins]

        y = 0
        # BLIF .names is sum-of-products: output is 1 if any cube (with output 1) matches.
        # We ignore cubes with output 0 (usually absent in mapped BLIF).
        for pat, val in parsed:
            if val != "1":
                continue
            if pat == "":
                # constant 1 cube (rare in n_fanins>0 but allowed)
                y = 1
                break
            if len(pat) != n_fanins:
                raise LutTruthError(f"Pattern length {len(pat)} != n_fanins {n_fanins} in cube '{pat} 1'")
            if _match_pattern(pat, bits):
                y = 1
                break

        if y == 1:
            tt |= (1 << i)

    return tt & 0xFFFF


def tt16_to_hex(tt16: int) -> str:
    """
    Return 4-hex-digit lowercase string, e.g. 0c0c
    """
    return f"{tt16 & 0xFFFF:04x}"
