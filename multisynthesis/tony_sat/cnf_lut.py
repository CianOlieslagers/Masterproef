# cnf_lut.py
from __future__ import annotations
from typing import List
from cnf_builder import CNFBuilder


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
