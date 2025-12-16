# toy_circuit.py
from __future__ import annotations
from typing import List, Tuple
from cnf_builder import CNFBuilder
from cnf_gates import gate_and, gate_xor, gate_mux
from cnf_lut import lut2


def build_spec(cnf: CNFBuilder, a: int, b: int, c: int, d: int, prefix: str = "") -> Tuple[int, int]:
    """
    SPEC:
      g = a & b
      S = MUX(g, (c xor d), c)
    Returns: (S, g)
    """
    g = cnf.new_var(f"{prefix}g")
    gate_and(cnf, a, b, g)

    cxord = cnf.new_var(f"{prefix}c_xor_d")
    gate_xor(cnf, c, d, cxord)

    S = cnf.new_var(f"{prefix}S")
    gate_mux(cnf, g, cxord, c, S)
    return S, g


def build_target(cnf: CNFBuilder, g: int, c: int, d: int, v_bits: List[int], prefix: str = "") -> int:
    """
    TARGET:
      L = LUT(v, c, d)
      T = MUX(g, L, c)
    Returns: T
    """
    L = cnf.new_var(f"{prefix}LUT_out")
    lut2(cnf, c, d, v_bits, L)

    T = cnf.new_var(f"{prefix}T")
    gate_mux(cnf, g, L, c, T)
    return T
