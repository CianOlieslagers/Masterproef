# cnf_gates.py
from __future__ import annotations
from typing import List
from cnf_builder import CNFBuilder


def gate_not(cnf: CNFBuilder, x: int, y: int) -> None:
    # y <-> ~x
    cnf.add_clause([-x, -y])
    cnf.add_clause([x, y])


def gate_and(cnf: CNFBuilder, x1: int, x2: int, y: int) -> None:
    # y <-> (x1 & x2)
    cnf.add_clause([-x1, -x2, y])
    cnf.add_clause([x1, -y])
    cnf.add_clause([x2, -y])


def gate_or(cnf: CNFBuilder, x1: int, x2: int, y: int) -> None:
    # y <-> (x1 | x2)
    cnf.add_clause([x1, x2, -y])
    cnf.add_clause([-x1, y])
    cnf.add_clause([-x2, y])


def gate_xor(cnf: CNFBuilder, x1: int, x2: int, y: int) -> None:
    # y <-> (x1 xor x2)
    cnf.add_clause([-x1, -x2, -y])
    cnf.add_clause([x1, x2, -y])
    cnf.add_clause([-x1, x2, y])
    cnf.add_clause([x1, -x2, y])


def gate_mux(cnf: CNFBuilder, s: int, t: int, f: int, y: int) -> None:
    # y <-> (s ? t : f)
    cnf.add_clause([-s, -t, y])
    cnf.add_clause([-s, t, -y])
    cnf.add_clause([s, -f, y])
    cnf.add_clause([s, f, -y])
