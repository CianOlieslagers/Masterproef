# toy_circuit.py
from __future__ import annotations
from typing import List, Tuple

from tony_sat.core.cnf_builder import CNFBuilder
from tony_sat.core.cnf_gates import gate_and, gate_xor, gate_mux
from tony_sat.core.cnf_lut import lut2, lut4


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



def add_conditional_not_equal(cnf: CNFBuilder, g: int, c: int, d: int) -> None:
    """
    Enforce: g -> (d = ~c)
    CNF:
      (~g or c or d)
      (~g or ~c or ~d)
    """
    cnf.add_clause([-g, c, d])
    cnf.add_clause([-g, -c, -d])


def build_target_contextual(
    cnf: CNFBuilder,
    g: int,
    c: int,
    d: int,
    v_bits: List[int],
    prefix: str = "",
) -> Tuple[int, int, int,int]:
    """
    TARGET (Optie 5B):
      u = c
      w = g & d          (contextueel gemaskeerde LUT-input)
      L = LUT(v, u, w)
      T = MUX(g, L, c)

    Returns: (T, u, w)
    """
    u = cnf.new_var(f"{prefix}u")
    # u <-> c  (we kunnen u=c maken met 2 clauses)
    cnf.add_clause([-u, c])
    cnf.add_clause([u, -c])

    w = cnf.new_var(f"{prefix}w")
    gate_and(cnf, g, d, w)

    L = cnf.new_var(f"{prefix}LUT_out")
    lut2(cnf, u, w, v_bits, L)

    T = cnf.new_var(f"{prefix}T")
    gate_mux(cnf, g, L, c, T)
    return T, u, w, L


def enforce_when_row(cnf: CNFBuilder, u: int, w: int, U: int, W: int, L: int, F: int, prefix: str = "") -> None:
    """
    If (u==U and w==W) then enforce L == F.

    Creates selector sel = (u==U) AND (w==W)
    and adds:
      sel -> (L == F)
    """
    sel = cnf.new_var(f"{prefix}sel_u{U}_w{W}")

    # lit is u if U=1 else ~u
    u_lit = u if U == 1 else -u
    w_lit = w if W == 1 else -w

    # sel <-> (u_lit AND w_lit)
    # sel -> u_lit, sel -> w_lit, (u_lit & w_lit) -> sel
    cnf.add_clause([-sel, u_lit])
    cnf.add_clause([-sel, w_lit])
    cnf.add_clause([-u_lit, -w_lit, sel])

    # sel -> (L == F)
    cnf.add_clause([-sel, -L, F])
    cnf.add_clause([-sel, L, -F])

def build_target_contextual_lut4(
    cnf: CNFBuilder,
    g: int,
    c: int,
    d: int,
    v_bits: List[int],
    prefix: str = "",
) -> Tuple[int, List[int], int]:
    """
    TARGET (LUT4 PoC):
      x0 = c
      x1 = d
      x2 = g
      x3 = 0 (const)
      L  = LUT4(v, x0,x1,x2,x3)
      T  = MUX(g, L, c)

    Returns: (T, xs, L)
      xs = [x0,x1,x2,x3] with mapping idx = 8*x0 + 4*x1 + 2*x2 + x3
    """
    # x0 <-> c
    x0 = cnf.new_var(f"{prefix}x0")
    cnf.add_clause([-x0, c])
    cnf.add_clause([x0, -c])

    # x1 <-> d
    x1 = cnf.new_var(f"{prefix}x1")
    cnf.add_clause([-x1, d])
    cnf.add_clause([x1, -d])

    # x2 <-> g
    x2 = cnf.new_var(f"{prefix}x2")
    cnf.add_clause([-x2, g])
    cnf.add_clause([x2, -g])

    # x3 = 0 constant
    x3 = cnf.new_var(f"{prefix}x3_const0")
    cnf.add_unit(x3, False)

    xs = [x0, x1, x2, x3]

    # LUT4 output
    L = cnf.new_var(f"{prefix}LUT4_out")
    lut4(cnf, xs, v_bits, L, prefix=prefix)

    # MUX: if g then L else c
    T = cnf.new_var(f"{prefix}T")
    gate_mux(cnf, g, L, c, T)

    return T, xs, L
