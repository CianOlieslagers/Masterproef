# tony_sat/core/miter_blif.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Tuple

from tony_sat.core.blif_parser import BlifDesign
from tony_sat.core.cnf_builder import CNFBuilder
from tony_sat.core.cnf_gates import gate_xor, gate_or
from tony_sat.core.cnf_lut import lut4
from tony_sat.core.lut_truth import cubes_to_tt16


@dataclass
class BuiltCircuit:
    cnf: CNFBuilder
    net2var: Dict[str, int]
    output_vars: List[int]


def _reverse4(r: int) -> int:
    return ((r & 0x1) << 3) | ((r & 0x2) << 1) | ((r & 0x4) >> 1) | ((r & 0x8) >> 3)


def build_circuit_with_optional_flip(
    design: BlifDesign,
    prefix: str,
    flip_lut: str | None = None,
    flip_row: int | None = None,
) -> BuiltCircuit:
    """
    Build CNF for the design. If flip_lut is set, flip that LUT's row flip_row
    in the BLIF truth table (in tt16 LUT4 view).

    prefix: ensures all CNF var names are unique between orig/mut.
    """
    if (flip_lut is None) != (flip_row is None):
        raise ValueError("flip_lut and flip_row must be both set or both None")
    if flip_row is not None and not (0 <= flip_row <= 15):
        raise ValueError("flip_row must be 0..15")

    cnf = CNFBuilder()
    net2var: Dict[str, int] = {}

    def vnet(net: str) -> int:
        key = f"{prefix}{net}"
        if key not in net2var:
            net2var[key] = cnf.new_var(key)
        return net2var[key]

    # PIs
    for pi in design.inputs:
        vnet(pi)

    # .names blocks
    for nb in design.names:
        out_var = vnet(nb.output)
        nfi = len(nb.fanins)

        if nfi > 4:
            raise ValueError(f"Unsupported .names with {nfi} fanins: output={nb.output}")

        if nfi == 0:
            tt16 = cubes_to_tt16(nb.cubes, 0)
            cnf.add_unit(out_var, tt16 == 0xFFFF)
            continue

        in_vars = [vnet(n) for n in nb.fanins]

        tt16 = cubes_to_tt16(nb.cubes, nfi)

        # Apply flip if this is the pit LUT
        if flip_lut is not None and nb.output == flip_lut:
    # flip_row is in BLIF/tt16 indexing:
    # fanin[0]=b0 (LSB), fanin[1]=b1, ...
    # This matches cubes_to_tt16() and our row constraints.
           tt16 ^= (1 << flip_row)

        # Pad to 4 inputs
        while len(in_vars) < 4:
            dummy = cnf.new_var(f"{prefix}__dummy_{nb.output}_{len(in_vars)}")
            cnf.add_unit(dummy, False)
            in_vars.append(dummy)

        xs = [in_vars[3], in_vars[2], in_vars[1], in_vars[0]]  # MSB..LSB

        cfg = []
        for r in range(16):
            bit = (tt16 >> r) & 1
            vr = cnf.new_var(f"{prefix}{nb.output}__cfg_{r}")
            cnf.add_unit(vr, bool(bit))
            cfg.append(vr)

        lut4(cnf, xs, cfg, out_var, prefix=f"{prefix}{nb.output}__")

    out_vars = [vnet(o) for o in design.outputs]
    return BuiltCircuit(cnf=cnf, net2var=net2var, output_vars=out_vars)


def build_miter(
    design: BlifDesign,
    pit_lut: str,
    row: int,
) -> Tuple[CNFBuilder, int]:
    """
    Returns: (cnf, diff_var)
    CNF contains:
      - orig circuit (prefix o__)
      - mutant circuit (prefix m__)
      - diff = OR(outputs_o XOR outputs_m)
    """
    orig = build_circuit_with_optional_flip(design, prefix="o__")
    mut = build_circuit_with_optional_flip(design, prefix="m__", flip_lut=pit_lut, flip_row=row)

    # Merge CNFs: var namespaces are disjoint because of prefixes
    cnf = CNFBuilder()
    cnf.var_count = orig.cnf.var_count
    cnf.clauses = list(orig.cnf.clauses)
    cnf.name2var = dict(orig.cnf.name2var)

    # Append mut vars with offset remap
    # CNFBuilder doesn't support extend with remap, so we do it manually.
    offset = cnf.var_count

    # Remap mut variables
    mut_var_map: Dict[int, int] = {}
    for name, old_id in mut.cnf.name2var.items():
        new_id = old_id + offset
        mut_var_map[old_id] = new_id
        cnf.name2var[name] = new_id
    cnf.var_count += mut.cnf.var_count

    def remap_lit(lit: int) -> int:
        v = abs(lit)
        sign = 1 if lit > 0 else -1
        return sign * mut_var_map[v]

    for cl in mut.cnf.clauses:
        cnf.add_clause([remap_lit(l) for l in cl])

    # Remap output vars
    mut_out = [mut_var_map[v] for v in mut.output_vars]
    orig_out = orig.output_vars

    # XOR per output + OR into diff
    xor_vars: List[int] = []
    for i, (yo, ym) in enumerate(zip(orig_out, mut_out)):
        x = cnf.new_var(f"diff_xor_{i}")
        gate_xor(cnf, yo, ym, x)
        xor_vars.append(x)

    # OR chain
    if len(xor_vars) == 1:
        diff = xor_vars[0]
    else:
        cur = xor_vars[0]
        for i in range(1, len(xor_vars)):
            nxt = cnf.new_var(f"diff_or_{i}")
            gate_or(cnf, cur, xor_vars[i], nxt)
            cur = nxt
        diff = cur

    return cnf, diff
