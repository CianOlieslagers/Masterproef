# tony_sat/core/dc_io.py
from __future__ import annotations
import json
from typing import Set, Tuple

def load_dc_rows(path: str) -> Tuple[Set[int], Set[int]]:
    """
    Returns (care_rows, free_rows)
    free_rows = DONT_CARE ∪ UNREACHABLE
    """
    obj = json.load(open(path, "r", encoding="utf-8"))
    rows = obj.get("rows")
    if rows is None:
        raise KeyError(f"No 'rows' key in {path}. Keys={list(obj.keys())}")

    care, free = set(), set()
    for r in rows:
        row = int(r["row"])
        st = r["status"]
        if st == "CARE":
            care.add(row)
        elif st in ("DONT_CARE", "UNREACHABLE"):
            free.add(row)
        else:
            raise ValueError(f"Unknown status {st} in {path}")
    return care, free
