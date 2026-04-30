#!/usr/bin/env python3
import argparse
import json
import re
import sys
from collections import Counter, defaultdict


class ValidationError(Exception):
    pass


class Report:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.infos = []

    def error(self, msg):
        self.errors.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)

    def info(self, msg):
        self.infos.append(msg)

    def ok(self):
        return len(self.errors) == 0

    def print(self):
        print("\n=== VALIDATION REPORT ===\n")

        if self.infos:
            print("[INFO]")
            for m in self.infos:
                print(f"  - {m}")
            print()

        if self.warnings:
            print("[WARNINGS]")
            for m in self.warnings:
                print(f"  - {m}")
            print()

        if self.errors:
            print("[ERRORS]")
            for m in self.errors:
                print(f"  - {m}")
            print()

        if self.ok():
            print("RESULT: PASS")
        else:
            print("RESULT: FAIL")


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


# ------------------------------------------------------------
# AAG PARSER + VALIDATOR
# ------------------------------------------------------------

class AAG:
    def __init__(self):
        self.M = None
        self.I = None
        self.L = None
        self.O = None
        self.A = None

        self.input_literals = []
        self.latch_lines = []
        self.output_literals = []
        self.and_gates = {}   # lhs_var -> (rhs0_lit, rhs1_lit)

        self.defined_vars = set()
        self.input_vars = set()
        self.latch_vars = set()
        self.and_vars = set()

    @staticmethod
    def lit_to_var(lit):
        return lit // 2

    @staticmethod
    def lit_is_complemented(lit):
        return lit % 2 == 1


def parse_aag(path, report):
    aag = AAG()

    with open(path, "r", encoding="utf-8") as f:
        raw_lines = [line.strip() for line in f if line.strip() != ""]

    if not raw_lines:
        raise ValidationError(f"AAG file is leeg: {path}")

    header = raw_lines[0].split()
    if len(header) != 6 or header[0] != "aag":
        raise ValidationError(
            "Eerste lijn is geen geldige AAG header. Verwacht: "
            "'aag M I L O A'"
        )

    try:
        aag.M, aag.I, aag.L, aag.O, aag.A = map(int, header[1:])
    except ValueError:
        raise ValidationError("Header bevat niet-integer waarden.")

    if min(aag.M, aag.I, aag.L, aag.O, aag.A) < 0:
        raise ValidationError("Header bevat negatieve waarden.")

    expected_min_lines = 1 + aag.I + aag.L + aag.O + aag.A
    if len(raw_lines) < expected_min_lines:
        raise ValidationError(
            f"Te weinig regels in AAG. Verwacht minstens {expected_min_lines}, "
            f"maar vond {len(raw_lines)}."
        )

    idx = 1

    # Inputs
    for _ in range(aag.I):
        try:
            lit = int(raw_lines[idx])
        except ValueError:
            raise ValidationError(f"Ongeldige input literal op regel {idx+1}.")
        aag.input_literals.append(lit)
        idx += 1

    # Latches
    for _ in range(aag.L):
        parts = raw_lines[idx].split()
        if len(parts) < 2:
            raise ValidationError(f"Ongeldige latch-regel op regel {idx+1}.")
        try:
            lhs = int(parts[0])
            rhs = int(parts[1])
        except ValueError:
            raise ValidationError(f"Ongeldige latch-regel op regel {idx+1}.")
        aag.latch_lines.append((lhs, rhs))
        idx += 1

    # Outputs
    for _ in range(aag.O):
        try:
            lit = int(raw_lines[idx])
        except ValueError:
            raise ValidationError(f"Ongeldige output literal op regel {idx+1}.")
        aag.output_literals.append(lit)
        idx += 1

    # AND gates
    for _ in range(aag.A):
        parts = raw_lines[idx].split()
        if len(parts) != 3:
            raise ValidationError(
                f"Ongeldige AND-regel op regel {idx+1}. Verwacht 3 integers."
            )
        try:
            lhs, rhs0, rhs1 = map(int, parts)
        except ValueError:
            raise ValidationError(f"Ongeldige AND-regel op regel {idx+1}.")
        lhs_var = lhs // 2
        if lhs_var in aag.and_gates:
            raise ValidationError(
                f"Dubbele definitie van AND node var={lhs_var} (regel {idx+1})."
            )
        aag.and_gates[lhs_var] = (rhs0, rhs1)
        idx += 1

    # Basic semantic checks
    validate_aag_semantics(aag, report)

    return aag


def validate_aag_semantics(aag, report):
    max_lit = 2 * aag.M + 1

    # Inputs
    seen_input_vars = set()
    for lit in aag.input_literals:
        if lit < 0 or lit > max_lit:
            raise ValidationError(f"Input literal {lit} valt buiten bereik 0..{max_lit}.")
        if lit == 0:
            raise ValidationError("Input literal mag niet 0 zijn.")
        if lit % 2 != 0:
            raise ValidationError(f"Input literal {lit} moet even zijn.")
        var = lit // 2
        if var == 0:
            raise ValidationError("Input var 0 is ongeldig.")
        if var in seen_input_vars:
            raise ValidationError(f"Dubbele input var {var}.")
        seen_input_vars.add(var)

    aag.input_vars = seen_input_vars

    # Latches
    seen_latch_vars = set()
    for lhs, rhs in aag.latch_lines:
        if lhs < 0 or lhs > max_lit or rhs < 0 or rhs > max_lit:
            raise ValidationError(f"Latch literal buiten bereik: lhs={lhs}, rhs={rhs}.")
        if lhs == 0 or lhs % 2 != 0:
            raise ValidationError(f"Latch lhs moet een niet-nul even literal zijn: {lhs}.")
        lhs_var = lhs // 2
        if lhs_var == 0:
            raise ValidationError("Latch lhs var 0 is ongeldig.")
        if lhs_var in seen_latch_vars:
            raise ValidationError(f"Dubbele latch var {lhs_var}.")
        seen_latch_vars.add(lhs_var)

    aag.latch_vars = seen_latch_vars

    # Outputs
    for lit in aag.output_literals:
        if lit < 0 or lit > max_lit:
            raise ValidationError(f"Output literal {lit} valt buiten bereik 0..{max_lit}.")

    # AND gates
    seen_and_vars = set()
    for lhs_var, (rhs0, rhs1) in aag.and_gates.items():
        lhs = lhs_var * 2
        if lhs < 2 or lhs > 2 * aag.M:
            raise ValidationError(f"AND lhs {lhs} buiten bereik.")
        if lhs % 2 != 0:
            raise ValidationError(f"AND lhs {lhs} moet even zijn.")
        if rhs0 < 0 or rhs0 > max_lit or rhs1 < 0 or rhs1 > max_lit:
            raise ValidationError(
                f"AND var {lhs_var} heeft fanins buiten bereik: {rhs0}, {rhs1}."
            )
        if lhs_var in seen_and_vars:
            raise ValidationError(f"Dubbele AND-definitie voor var {lhs_var}.")
        seen_and_vars.add(lhs_var)

    aag.and_vars = seen_and_vars

    # Disjointness van definitions
    overlap = (aag.input_vars & aag.latch_vars) | (aag.input_vars & aag.and_vars) | (aag.latch_vars & aag.and_vars)
    if overlap:
        raise ValidationError(f"Variabelen dubbel gedefinieerd over input/latch/and: {sorted(overlap)}")

    aag.defined_vars = aag.input_vars | aag.latch_vars | aag.and_vars

    # Referenties moeten naar bestaande variabelen wijzen (behalve constant 0 / 1 => var 0)
    def check_ref_lit(lit, context):
        var = lit // 2
        if var == 0:
            return
        if var not in aag.defined_vars:
            raise ValidationError(f"{context}: referentie naar ongedefinieerde var {var} (lit {lit}).")

    for lhs, rhs in aag.latch_lines:
        check_ref_lit(rhs, f"Latch {lhs//2}")

    for lit in aag.output_literals:
        check_ref_lit(lit, "Output")

    for lhs_var, (rhs0, rhs1) in aag.and_gates.items():
        check_ref_lit(rhs0, f"AND {lhs_var}")
        check_ref_lit(rhs1, f"AND {lhs_var}")

    # Loopdetectie op combinatorische AIG-grafiek
    # We bekijken alleen AND -> AND afhankelijkheden.
    dep_graph = defaultdict(list)
    for lhs_var, (rhs0, rhs1) in aag.and_gates.items():
        for lit in (rhs0, rhs1):
            var = lit // 2
            if var in aag.and_vars:
                dep_graph[lhs_var].append(var)

    # DFS cycle detection
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {v: WHITE for v in aag.and_vars}

    def dfs(v, stack):
        color[v] = GRAY
        stack.append(v)
        for u in dep_graph[v]:
            if color[u] == GRAY:
                cycle = stack[stack.index(u):] + [u]
                raise ValidationError(f"Combinatorische loop gedetecteerd: {' -> '.join(map(str, cycle))}")
            if color[u] == WHITE:
                dfs(u, stack)
        stack.pop()
        color[v] = BLACK

    for v in aag.and_vars:
        if color[v] == WHITE:
            dfs(v, [])

    report.info(
        f"AAG parsed: M={aag.M}, I={aag.I}, L={aag.L}, O={aag.O}, A={aag.A}"
    )
    report.info(f"AAG AND-nodes: {len(aag.and_vars)}")
    if aag.L != 0:
        report.warn(
            f"Deze validator ondersteunt latches syntactisch, maar jouw flow lijkt combinatorisch. "
            f"Gevonden L={aag.L}."
        )


# ------------------------------------------------------------
# LUT_CONES VALIDATOR
# ------------------------------------------------------------

HEX_RE = re.compile(r"^[0-9a-fA-F]+$")


def validate_lut_cones(data, aag, report):
    if not isinstance(data, dict):
        raise ValidationError("lut_cones.json root moet een object/dict zijn.")

    required_top = ["format", "circuit", "K", "lut_cones"]
    for k in required_top:
        if k not in data:
            raise ValidationError(f"lut_cones.json mist top-level key '{k}'.")

    if not isinstance(data["lut_cones"], list):
        raise ValidationError("'lut_cones' moet een lijst zijn.")

    cones = data["lut_cones"]
    if len(cones) == 0:
        raise ValidationError("'lut_cones' is leeg.")

    all_root_nodes = []
    all_internal_nodes = []
    covered_and_nodes = []
    all_leaf_nodes = []

    node_to_cones = defaultdict(list)

    for i, cone in enumerate(cones):
        ctx = f"lut_cones[{i}]"

        for k in ["lut_root", "lut_name", "func_hex", "leaves", "internal_nodes", "node_functions"]:
            if k not in cone:
                raise ValidationError(f"{ctx} mist key '{k}'.")

        lut_root = cone["lut_root"]
        lut_name = cone["lut_name"]
        func_hex = cone["func_hex"]
        leaves = cone["leaves"]
        internal_nodes = cone["internal_nodes"]
        node_functions = cone["node_functions"]

        if not is_int(lut_root):
            raise ValidationError(f"{ctx}.lut_root moet integer zijn.")
        if not isinstance(lut_name, str):
            raise ValidationError(f"{ctx}.lut_name moet string zijn.")
        if lut_name != f"LUT_{lut_root}":
            report.warn(
                f"{ctx}.lut_name='{lut_name}' komt niet overeen met verwachte naam 'LUT_{lut_root}'."
            )
        if not isinstance(func_hex, str) or not HEX_RE.fullmatch(func_hex):
            raise ValidationError(f"{ctx}.func_hex moet een hex string zijn.")
        if not isinstance(leaves, list) or not all(is_int(x) for x in leaves):
            raise ValidationError(f"{ctx}.leaves moet een lijst van integers zijn.")
        if not isinstance(internal_nodes, list) or not all(is_int(x) for x in internal_nodes):
            raise ValidationError(f"{ctx}.internal_nodes moet een lijst van integers zijn.")
        if not isinstance(node_functions, list):
            raise ValidationError(f"{ctx}.node_functions moet een lijst zijn.")

        # duplicaten binnen cone
        if len(leaves) != len(set(leaves)):
            raise ValidationError(f"{ctx}.leaves bevat duplicaten.")
        if len(internal_nodes) != len(set(internal_nodes)):
            raise ValidationError(f"{ctx}.internal_nodes bevat duplicaten.")

        # Root mag niet ook internal zijn
        if lut_root in internal_nodes:
            raise ValidationError(f"{ctx}: lut_root {lut_root} zit ook in internal_nodes.")

        # node_functions checks
        nf_nodes = []
        root_seen_in_nf = False
        for j, nf in enumerate(node_functions):
            nctx = f"{ctx}.node_functions[{j}]"
            if not isinstance(nf, dict):
                raise ValidationError(f"{nctx} moet een object/dict zijn.")
            if "node" not in nf or "func_hex" not in nf:
                raise ValidationError(f"{nctx} mist 'node' of 'func_hex'.")
            if not is_int(nf["node"]):
                raise ValidationError(f"{nctx}.node moet integer zijn.")
            if not isinstance(nf["func_hex"], str) or not HEX_RE.fullmatch(nf["func_hex"]):
                raise ValidationError(f"{nctx}.func_hex moet een hex string zijn.")
            nf_nodes.append(nf["node"])
            if nf["node"] == lut_root:
                root_seen_in_nf = True

        if len(nf_nodes) != len(set(nf_nodes)):
            raise ValidationError(f"{ctx}.node_functions bevat dubbele node ids.")

        allowed_nf_nodes = set(internal_nodes) | {lut_root}
        extra_nf = set(nf_nodes) - allowed_nf_nodes
        missing_nf = allowed_nf_nodes - set(nf_nodes)

        if extra_nf:
            raise ValidationError(
                f"{ctx}.node_functions bevat nodes buiten internal_nodes/root: {sorted(extra_nf)}"
            )
        if missing_nf:
            raise ValidationError(
                f"{ctx}.node_functions mist nodes uit internal_nodes/root: {sorted(missing_nf)}"
            )
        if not root_seen_in_nf:
            raise ValidationError(f"{ctx}.node_functions bevat de lut_root {lut_root} niet.")

        all_root_nodes.append(lut_root)
        all_internal_nodes.extend(internal_nodes)
        covered_and_nodes.append(lut_root)
        covered_and_nodes.extend(internal_nodes)
        all_leaf_nodes.extend(leaves)

        node_to_cones[lut_root].append(i)
        for n in internal_nodes:
            node_to_cones[n].append(i)

    # Duplicaten over cones
    duplicate_coverage = {n: idxs for n, idxs in node_to_cones.items() if len(idxs) > 1}
    if duplicate_coverage:
        pretty = ", ".join(f"{n}->cones{idxs}" for n, idxs in sorted(duplicate_coverage.items()))
        raise ValidationError(
            f"Een AAG-node mag niet als root/internal in meerdere cones zitten. Dubbele coverage: {pretty}"
        )

    root_set = set(all_root_nodes)
    internal_set = set(all_internal_nodes)
    covered_set = set(covered_and_nodes)

    if len(all_root_nodes) != len(root_set):
        counts = Counter(all_root_nodes)
        dup_roots = sorted([n for n, c in counts.items() if c > 1])
        raise ValidationError(f"Dubbele lut_root nodes: {dup_roots}")

    # Roots/internal moeten AND-nodes uit AAG zijn
    extra_vs_aag = covered_set - aag.and_vars
    if extra_vs_aag:
        raise ValidationError(
            f"lut_cones bevat root/internal nodes die niet bestaan als AND-node in AAG: {sorted(extra_vs_aag)}"
        )

    missing_vs_aag = aag.and_vars - covered_set
    if missing_vs_aag:
        raise ValidationError(
            f"Niet alle AAG AND-nodes worden gedekt door lut_root/internal_nodes. Ontbrekend: {sorted(missing_vs_aag)}"
        )

    # Leaves mogen inputs of andere gedekte nodes zijn; minstens moeten ze bestaan in AAG
    # of const 0/1 impliciet vermijden we hier omdat je leaves typisch node ids zijn, geen literals
    known_vars = aag.defined_vars
    bad_leaves = sorted(set(n for n in all_leaf_nodes if n not in known_vars))
    if bad_leaves:
        raise ValidationError(
            f"lut_cones bevat leaves die niet bestaan als variabele in AAG: {bad_leaves}"
        )

    report.info(f"lut_cones: {len(cones)} cones")
    report.info(f"lut_cones: {len(root_set)} unieke roots")
    report.info(f"lut_cones: exacte dekking van alle {len(aag.and_vars)} AAG AND-nodes via root+internal")


# ------------------------------------------------------------
# MANHATTAN VALIDATOR
# ------------------------------------------------------------

LUT_NAME_RE = re.compile(r"^LUT_(\d+)$")


def validate_manhattan(data, lut_cones_data, report):
    if not isinstance(data, dict):
        raise ValidationError("manhattan.json root moet een object/dict zijn.")

    required_top = [
        "design", "place_file", "net_file",
        "num_blocks", "num_nets", "num_connections",
        "blocks", "connections"
    ]
    for k in required_top:
        if k not in data:
            raise ValidationError(f"manhattan.json mist top-level key '{k}'.")

    if not isinstance(data["blocks"], dict):
        raise ValidationError("'blocks' moet een object/dict zijn.")
    if not isinstance(data["connections"], list):
        raise ValidationError("'connections' moet een lijst zijn.")

    blocks = data["blocks"]
    connections = data["connections"]

    # Roots uit lut_cones
    lut_roots = set()
    for cone in lut_cones_data["lut_cones"]:
        lut_roots.add(cone["lut_root"])

    block_root_ids = set()

    # blocks checks
    for name, block in blocks.items():
        m = LUT_NAME_RE.fullmatch(name)
        if not m:
            raise ValidationError(
                f"manhattan.blocks bevat niet-LUT blocknaam '{name}'. "
                f"Verwacht alleen namen van de vorm LUT_<id>."
            )

        root_id = int(m.group(1))
        block_root_ids.add(root_id)

        if not isinstance(block, dict):
            raise ValidationError(f"Block '{name}' moet een object/dict zijn.")

        for k in ["x", "y"]:
            if k not in block:
                raise ValidationError(f"Block '{name}' mist key '{k}'.")
            if not is_int(block[k]):
                raise ValidationError(f"Block '{name}'.{k} moet integer zijn.")

        for k in ["subtile", "type"]:
            if k not in block:
                report.warn(f"Block '{name}' mist optionele maar verwachte key '{k}'.")

    # exacte root-overeenkomst
    extra_blocks = block_root_ids - lut_roots
    missing_blocks = lut_roots - block_root_ids

    if extra_blocks:
        raise ValidationError(
            f"manhattan.blocks bevat LUT ids die niet in lut_cones.lut_root zitten: {sorted(extra_blocks)}"
        )
    if missing_blocks:
        raise ValidationError(
            f"manhattan.blocks mist LUT roots die wel in lut_cones zitten: {sorted(missing_blocks)}"
        )

    # counts
    if data["num_blocks"] != len(blocks):
        raise ValidationError(
            f"num_blocks={data['num_blocks']} maar effectief aantal blocks={len(blocks)}"
        )

    if data["num_connections"] != len(connections):
        raise ValidationError(
            f"num_connections={data['num_connections']} maar effectief aantal connections={len(connections)}"
        )

    # connections checks
    unique_net_pairs = set()
    for i, c in enumerate(connections):
        ctx = f"connections[{i}]"
        if not isinstance(c, dict):
            raise ValidationError(f"{ctx} moet een object/dict zijn.")

        for k in ["src", "dst", "dx", "dy", "manhattan"]:
            if k not in c:
                raise ValidationError(f"{ctx} mist key '{k}'.")

        if not isinstance(c["src"], str) or not isinstance(c["dst"], str):
            raise ValidationError(f"{ctx}.src en {ctx}.dst moeten strings zijn.")
        if not all(is_int(c[k]) for k in ["dx", "dy", "manhattan"]):
            raise ValidationError(f"{ctx}.dx/.dy/.manhattan moeten integers zijn.")

        src = c["src"]
        dst = c["dst"]

        if src not in blocks:
            raise ValidationError(f"{ctx}: src '{src}' bestaat niet in blocks.")
        if dst not in blocks:
            raise ValidationError(f"{ctx}: dst '{dst}' bestaat niet in blocks.")

        sx, sy = blocks[src]["x"], blocks[src]["y"]
        dx_expected = blocks[dst]["x"] - sx
        dy_expected = blocks[dst]["y"] - sy
        manh_expected = abs(dx_expected) + abs(dy_expected)

        if c["dx"] != dx_expected:
            raise ValidationError(
                f"{ctx}: dx fout. json={c['dx']} verwacht={dx_expected} voor {src}->{dst}"
            )
        if c["dy"] != dy_expected:
            raise ValidationError(
                f"{ctx}: dy fout. json={c['dy']} verwacht={dy_expected} voor {src}->{dst}"
            )
        if c["manhattan"] != manh_expected:
            raise ValidationError(
                f"{ctx}: manhattan fout. json={c['manhattan']} verwacht={manh_expected} voor {src}->{dst}"
            )

        unique_net_pairs.add((src, dst))

    # num_nets: hangt af van betekenis, maar in jouw beschrijving lijkt dit meestal unieke src->dst paren
    if data["num_nets"] != len(unique_net_pairs):
        report.warn(
            f"num_nets={data['num_nets']} maar unieke (src,dst)-paren={len(unique_net_pairs)}. "
            f"Dat hoeft niet fout te zijn als 'net' in jouw export iets anders betekent."
        )

    report.info(f"manhattan: {len(blocks)} LUT-blocks")
    report.info(f"manhattan: {len(connections)} connections")
    report.info("manhattan: alle LUT-blocks matchen exact met lut_cones roots")


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Strenge validator voor AAG + lut_cones.json + manhattan.json"
    )
    parser.add_argument("--aag", required=True, help="Pad naar .aag bestand")
    parser.add_argument("--lut-cones", required=True, help="Pad naar lut_cones.json")
    parser.add_argument("--manhattan", required=True, help="Pad naar manhattan.json")
    args = parser.parse_args()

    report = Report()

    try:
        aag = parse_aag(args.aag, report)
        lut_cones_data = load_json(args.lut_cones)
        validate_lut_cones(lut_cones_data, aag, report)

        manhattan_data = load_json(args.manhattan)
        validate_manhattan(manhattan_data, lut_cones_data, report)

        # Extra globale waarschuwingen
        if lut_cones_data.get("circuit") and manhattan_data.get("design"):
            if lut_cones_data["circuit"] != manhattan_data["design"]:
                report.warn(
                    f"circuit/design mismatch: lut_cones.circuit='{lut_cones_data['circuit']}' "
                    f"vs manhattan.design='{manhattan_data['design']}'"
                )

    except ValidationError as e:
        report.error(str(e))
    except FileNotFoundError as e:
        report.error(f"Bestand niet gevonden: {e}")
    except json.JSONDecodeError as e:
        report.error(f"JSON parse fout: {e}")
    except Exception as e:
        report.error(f"Onverwachte fout: {type(e).__name__}: {e}")

    report.print()
    sys.exit(0 if report.ok() else 1)


if __name__ == "__main__":
    main()
