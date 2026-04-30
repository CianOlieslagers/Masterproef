from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional, Set

from tony_sat.core.cnf_builder import CNFBuilder
from tony_sat.core.cnf_gates import gate_xor, gate_or
from tony_sat.core.cnf_lut import lut4
from tony_sat.core.lut_truth import cubes_to_tt16
from tony_sat.core.blif_parser import BlifDesign


def _reverse4(r: int) -> int:
    return ((r & 0x1) << 3) | ((r & 0x2) << 1) | ((r & 0x4) >> 1) | ((r & 0x8) >> 3)


@dataclass
class PatchMiter:
    cnf: CNFBuilder
    diff_var: int
    patch_bits: Dict[int, int]  # row -> var (rows are 0..(2^k-1))
    pit_fanins: List[str]


def build_patch_miter(
    design: BlifDesign,
    pit_lut: str,
    care_rows: Set[int],
    free_rows: Set[int],
) -> PatchMiter:
    """
    Build miter between:
      - orig: BLIF truth tables fixed
      - mut : same, except pit LUT is driven by patch bits p[row]
    Patch bits:
      rows range is 0..(2^k-1) where k = number of pit fanins in BLIF
    Constraints:
      for r in care_rows: p[r] == orig_tt[r]
      free_rows: unconstrained
    """
    cnf = CNFBuilder()

    def build_circuit(prefix: str, patchable: bool) -> Tuple[Dict[str, int], List[int], Dict[int, int], List[str]]:
        net2var: Dict[str, int] = {}

        def vnet(net: str) -> int:
            key = f"{prefix}{net}"
            if key not in net2var:
                net2var[key] = cnf.new_var(key)
            return net2var[key]

        # PIs
        for pi in design.inputs:
            vnet(pi)

        patch_bits_local: Dict[int, int] = {}
        pit_fanins_local: List[str] = []

        for nb in design.names:
            out = vnet(nb.output)
            nfi = len(nb.fanins)
            if nfi > 4:
                raise ValueError(f"Unsupported .names with {nfi} fanins: {nb.output}")

            if nfi == 0:
                tt16 = cubes_to_tt16(nb.cubes, 0)
                cnf.add_unit(out, tt16 == 0xFFFF)
                continue

            in_vars = [vnet(n) for n in nb.fanins]
            tt16 = cubes_to_tt16(nb.cubes, nfi)

            # Pad to 4 inputs with dummy=0
            while len(in_vars) < 4:
                d = cnf.new_var(f"{prefix}__dummy_{nb.output}_{len(in_vars)}")
                cnf.add_unit(d, False)
                in_vars.append(d)

            # xs passed to lut4: [MSB..LSB] = [in3,in2,in1,in0]
            xs = [in_vars[0], in_vars[1], in_vars[2], in_vars[3]]
            cfg_vars: List[int] = []

            if patchable and nb.output == pit_lut:
                # Patch bits only for meaningful rows 0..(2^k-1)
                k = len(nb.fanins)
                pit_fanins_local = list(nb.fanins)

                for r in range(16):
                    # Determine which tt16 bit corresponds to this lut4 row r
                    # With our lut4 input ordering, lut4 row r aligns with tt16 bit r.
                    # But for nfi<4, only rows consistent with dummy=0 are reachable.
                    if r < (1 << k):
                        pr = cnf.new_var(f"{prefix}{pit_lut}__patch_{r}")
                        patch_bits_local[r] = pr
                        cfg_vars.append(pr)
                    else:
                        # rows beyond 2^k are unreachable by construction (dummy=0),
                        # but still need a cfg var to satisfy lut4 API; fix to orig bit.
                        bit = (tt16 >> r) & 1
                        vr = cnf.new_var(f"{prefix}{nb.output}__cfg_{r}")
                        cnf.add_unit(vr, bool(bit))
                        cfg_vars.append(vr)

            else:
                for r in range(16):
                    bit = (tt16 >> r) & 1
                    vr = cnf.new_var(f"{prefix}{nb.output}__cfg_{r}")
                    cnf.add_unit(vr, bool(bit))
                    cfg_vars.append(vr)

            lut4(cnf, xs, cfg_vars, out, prefix=f"{prefix}{nb.output}__")

        outs = [vnet(o) for o in design.outputs]
        return net2var, outs, patch_bits_local, pit_fanins_local

    # Build orig and mutant
    net_o, outs_o, _, _ = build_circuit("o__", patchable=False)
    net_m, outs_m, patch_bits, pit_fanins = build_circuit("m__", patchable=True)

    # Enforce same primary inputs for orig and mutant (miter requirement)
    for pi in design.inputs:
        a = cnf.var(f"o__{pi}")
        b = cnf.var(f"m__{pi}")
        cnf.add_clause([-a, b])
        cnf.add_clause([a, -b])

    # CARE constraints: p[r] == orig_tt[r]
    # We need orig_tt for pit_lut:
    pit_tt16 = None
    pit_nfi = None
    for nb in design.names:
        if nb.output == pit_lut:
            pit_nfi = len(nb.fanins)
            pit_tt16 = cubes_to_tt16(nb.cubes, pit_nfi)
            break
    if pit_tt16 is None or pit_nfi is None:
        raise KeyError(f"pit LUT {pit_lut} not found in BLIF")

    for r in sorted(care_rows):
        if r not in patch_bits:
            raise KeyError(f"CARE row {r} not in patch_bits (k={pit_nfi})")
        bit = (pit_tt16 >> r) & 1
        cnf.add_unit(patch_bits[r], bool(bit))
    # diff = OR_i (outs_o[i] XOR outs_m[i])
    if len(outs_o) != len(outs_m):
        raise RuntimeError("Output mismatch between orig and mutant build")

    xors: List[int] = []
    for i, (a, b) in enumerate(zip(outs_o, outs_m)):
        xv = cnf.new_var(f"diff_xor_{i}")
        gate_xor(cnf, a, b, xv)
        xors.append(xv)

    if not xors:
        raise RuntimeError("No outputs in design")

    diff = xors[0]
    for i in range(1, len(xors)):
        dv = cnf.new_var(f"diff_or_{i}")
        gate_or(cnf, diff, xors[i], dv)
        diff = dv

    return PatchMiter(cnf=cnf, diff_var=diff, patch_bits=patch_bits, pit_fanins=pit_fanins)
