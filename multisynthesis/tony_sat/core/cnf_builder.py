# cnf_builder.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class CNFBuilder:
    var_count: int = 0
    clauses: List[List[int]] = field(default_factory=list)
    name2var: Dict[str, int] = field(default_factory=dict)

    def new_var(self, name: str) -> int:
        if name in self.name2var:
            raise ValueError(f"Variable name already exists: {name}")
        self.var_count += 1
        self.name2var[name] = self.var_count
        return self.var_count

    def var(self, name: str) -> int:
        if name not in self.name2var:
            raise KeyError(f"Unknown variable name: {name}")
        return self.name2var[name]

    def add_clause(self, lits: List[int]) -> None:
        if not lits:
            raise ValueError("Empty clause is not allowed (would make CNF UNSAT).")
        # basic sanity: no 0 literals
        for lit in lits:
            if lit == 0:
                raise ValueError("Literal 0 is not allowed in DIMACS.")
        self.clauses.append(list(lits))

    def add_unit(self, var: int, value: bool) -> None:
        self.add_clause([var if value else -var])

    def extend(self, other: "CNFBuilder") -> None:
        """Merge other into self (requires disjoint var namespaces)."""
        if other.var_count != 0:
            raise NotImplementedError(
                "extend() not supported for non-empty builders (would need var remap)."
            )
