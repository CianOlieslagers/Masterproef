# cnf_lut.py
from __future__ import annotations
from typing import List
from tony_sat.core.cnf_builder import CNFBuilder


def lut2(cnf: CNFBuilder, c: int, d: int, v: List[int], y: int) -> None:
    """
    2-input LUT encoding with bit-order:
      idx = 2*c + d
      (c,d)=00 -> v0
      (c,d)=01 -> v1
      (c,d)=10 -> v2
      (c,d)=11 -> v3
    Enforces: for each input combo, y <-> v[idx].

    v must be length 4.
    """
    if len(v) != 4:
        raise ValueError("lut2 expects v = [v0,v1,v2,v3]")

    v0, v1, v2, v3 = v

    # If c=0,d=0 then y <-> v0
    cnf.add_clause([ c,  d, -y,  v0])
    cnf.add_clause([ c,  d,  y, -v0])

    # If c=0,d=1 then y <-> v1
    cnf.add_clause([ c, -d, -y,  v1])
    cnf.add_clause([ c, -d,  y, -v1])

    # If c=1,d=0 then y <-> v2
    cnf.add_clause([-c,  d, -y,  v2])
    cnf.add_clause([-c,  d,  y, -v2])

    # If c=1,d=1 then y <-> v3
    cnf.add_clause([-c, -d, -y,  v3])
    cnf.add_clause([-c, -d,  y, -v3])


def lut4(cnf: CNFBuilder, xs: List[int], v: List[int], y: int, prefix: str= "") -> None:
    """
    4-input LUT encoding.

    Inputs:
      xs = [x0,x1,x2,x3]  (x0 MSB, x3 LSB)
    Truth table bits:
      v[0..15] where idx = 8*x0 + 4*x1 + 2*x2 + 1*x3

    Enforces: for each row r, if xs == bits(r) then y <-> v[r].
    """
    if len(xs) != 4:
        raise ValueError("lut4 expects xs = [x0,x1,x2,x3]")
    if len(v) != 16:
        raise ValueError("lut4 expects v of length 16")

    x0, x1, x2, x3 = xs

    for r in range(16):
        # nieuw (canon, LSB-first):
        b0 = (r >> 0) & 1
        b1 = (r >> 1) & 1
        b2 = (r >> 2) & 1
        b3 = (r >> 3) & 1

        l0 = x0 if b0 == 1 else -x0
        l1 = x1 if b1 == 1 else -x1
        l2 = x2 if b2 == 1 else -x2
        l3 = x3 if b3 == 1 else -x3

        sel = cnf.new_var(f"{prefix}lut4_sel_{r}")
        # sel -> li
        cnf.add_clause([-sel, l0])
        cnf.add_clause([-sel, l1])
        cnf.add_clause([-sel, l2])
        cnf.add_clause([-sel, l3])

        # (l0 & l1 & l2 & l3) -> sel
        cnf.add_clause([-l0, -l1, -l2, -l3, sel])

        # sel -> (y <-> v[r])
        cnf.add_clause([-sel, -y, v[r]])
        cnf.add_clause([-sel, y, -v[r]])
