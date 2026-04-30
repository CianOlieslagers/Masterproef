# tony_sat/core/blif_to_cnf.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List

from tony_sat.core.blif_parser import BlifDesign
from tony_sat.core.cnf_builder import CNFBuilder
from tony_sat.core.cnf_lut import lut4
from tony_sat.core.lut_truth import cubes_to_tt16


@dataclass
class CnfCircuit:
    cnf: CNFBuilder
    net2var: Dict[str, int]
    inputs: List[str]
    outputs: List[str]
    output_vars: List[int]


def _reverse4(r: int) -> int:
    """Reverse 4-bit index: abcd -> dcba"""
    return ((r & 0x1) << 3) | ((r & 0x2) << 1) | ((r & 0x4) >> 1) | ((r & 0x8) >> 3)


def build_cnf_from_blif(design: BlifDesign) -> CnfCircuit:
    """
    Build CNF for a LUT-mapped combinational BLIF.

    Strategy:
      - one boolean var per net name (PIs + LUT outputs + intermediate nets)
      - each .names with fanins>0 becomes a lut4 constraint with 16 config vars v[0..15]
      - config vars are fixed to match BLIF truth table (BLIF is ground truth)
      - for fanins < 4: we pad with dummy vars fixed to 0 (safe because tt16 is expanded)

    IMPORTANT:
      - cnf_lut.lut4 assumes xs=[x0,x1,x2,x3] with x0=MSB, x3=LSB.
      - Our BLIF truth-table enumeration and previous matching implies fanin order is [LSB..MSB].
        Therefore, we pass xs in reversed fanin order.
      - Similarly, we map tt16 bits into v using reverse4 indexing.
    """
    cnf = CNFBuilder()
    net2var: Dict[str, int] = {}

    def vnet(net: str) -> int:
        if net not in net2var:
            net2var[net] = cnf.new_var(net)
        return net2var[net]

    # Ensure PI vars exist
    for pi in design.inputs:
        vnet(pi)

    # Encode each .names block
    for nb in design.names:
        out_var = vnet(nb.output)
        nfi = len(nb.fanins)

        if nfi > 4:
            raise ValueError(f"Unsupported .names with {nfi} fanins: output={nb.output}")

        # Constant blocks (.names out; '0' or '1')
        if nfi == 0:
            tt16 = cubes_to_tt16(nb.cubes, 0)  # 0x0000 or 0xFFFF
            cnf.add_unit(out_var, tt16 == 0xFFFF)
            continue

        in_vars = [vnet(n) for n in nb.fanins]

        # Expand BLIF cubes to 16-bit truth table in LUT4 view
        tt16 = cubes_to_tt16(nb.cubes, nfi)

        # Pad to 4 inputs with dummy=0 vars
        while len(in_vars) < 4:
            dummy = cnf.new_var(f"__dummy_{nb.output}_{len(in_vars)}")
            cnf.add_unit(dummy, False)  # dummy = 0
            in_vars.append(dummy)

        # cnf_lut.lut4 expects xs=[MSB..LSB], but our in_vars are [LSB..MSB]
        xs = [in_vars[0], in_vars[1], in_vars[2], in_vars[3]]
        # Create 16 config vars and fix them to match tt16, with correct index mapping
        cfg = []
        for r in range(16):
            bit = (tt16 >> r) & 1
            vr = cnf.new_var(f"{nb.output}__cfg_{r}")
            cnf.add_unit(vr, bool(bit))
            cfg.append(vr)

        # Add LUT constraint
        lut4(cnf, xs, cfg, out_var, prefix=f"{nb.output}__")

    out_vars = [vnet(o) for o in design.outputs]

    return CnfCircuit(
        cnf=cnf,
        net2var=net2var,
        inputs=list(design.inputs),
        outputs=list(design.outputs),
        output_vars=out_vars,
    )
