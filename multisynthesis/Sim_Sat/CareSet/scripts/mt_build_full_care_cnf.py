import json
import sys
from pathlib import Path

def load_json(path):
    with open(path, "r") as f:
        return json.load(f)

class VarMgr:
    def __init__(self):
        self.next_var = 1
        self.map = {}

    def get(self, key):
        if key not in self.map:
            self.map[key] = self.next_var
            self.next_var += 1
        return self.map[key]

def add_and_clauses(clauses, a, b, c):
    # c <-> (a & b)
    clauses.append([-c, a])
    clauses.append([-c, b])
    clauses.append([c, -a, -b])

def add_or_clauses(clauses, a, b, c):
    # c <-> (a | b)
    clauses.append([-a, c])
    clauses.append([-b, c])
    clauses.append([-c, a, b])

def add_xor_clauses(clauses, a, b, c):
    # c <-> (a xor b)
    clauses.append([-a, -b, -c])
    clauses.append([ a,  b, -c])
    clauses.append([ a, -b,  c])
    clauses.append([-a,  b,  c])

def normalize_fanin(src_aig, child_lit, is_complemented):
    return -child_lit if is_complemented else child_lit

def parse_aag(aag_path):
    with open(aag_path, "r") as f:
        lines = [line.strip() for line in f if line.strip()]

    if not lines[0].startswith("aag "):
        raise RuntimeError("Expected ASCII AAG input")

    parts = lines[0].split()
    _, M, I, L, O, A = parts[:6]
    M, I, L, O, A = map(int, (M, I, L, O, A))

    idx = 1
    pis = []
    for _ in range(I):
        lit = int(lines[idx])
        pis.append(lit // 2)
        idx += 1

    # skip latches if any
    idx += L

    pos = []
    for _ in range(O):
        lit = int(lines[idx])
        pos.append(lit)
        idx += 1

    ands = {}
    for _ in range(A):
        lhs, rhs0, rhs1 = map(int, lines[idx].split())
        ands[lhs // 2] = (rhs0, rhs1)
        idx += 1

    return {
        "pis": set(pis),
        "ands": ands,
        "pos": pos,
    }

def build_node_cnf(node_id, side, pivot, pivot_value, outer_collected_set, aig_data,
                   X_set, vm, clauses, memo):
    key = (side, node_id)
    if key in memo:
        return memo[key]

    # pivot forced
    if node_id == pivot:
        v = vm.get(key)
        clauses.append([ -v ] if not pivot_value else [ v ])
        memo[key] = v
        return v

    # global PI
    if node_id in aig_data["pis"]:
        if node_id not in X_set:
            raise RuntimeError(f"PI node {node_id} not present in X")
        v = vm.get(("x", node_id))
        memo[key] = v
        return v

    # outside outer collected => interface node => must be in X
    if node_id not in outer_collected_set:
        if node_id not in X_set:
            raise RuntimeError(f"External node {node_id} not present in X")
        v = vm.get(("x", node_id))
        memo[key] = v
        return v

    # internal AND node
    if node_id not in aig_data["ands"]:
        raise RuntimeError(f"Node {node_id} is neither PI nor AND in parsed AAG")

    rhs0, rhs1 = aig_data["ands"][node_id]

    child0_id = rhs0 // 2
    child1_id = rhs1 // 2
    child0_compl = (rhs0 % 2 == 1)
    child1_compl = (rhs1 % 2 == 1)

    a = build_node_cnf(child0_id, side, pivot, pivot_value, outer_collected_set,
                       aig_data, X_set, vm, clauses, memo)
    b = build_node_cnf(child1_id, side, pivot, pivot_value, outer_collected_set,
                       aig_data, X_set, vm, clauses, memo)

    a_lit = normalize_fanin(aig_data, a, child0_compl)
    b_lit = normalize_fanin(aig_data, b, child1_compl)

    c = vm.get(key)
    add_and_clauses(clauses, a_lit, b_lit, c)
    memo[key] = c
    return c

def main():
    if len(sys.argv) != 7:
        print("Usage: python3 mt_build_full_care_cnf.py <input.aag> <outer.json> <care_vars.json> <F1_random.json> <out.cnf> <out.meta.json>")
        sys.exit(1)

    aag_path      = Path(sys.argv[1])
    outer_path    = Path(sys.argv[2])
    care_vars_path= Path(sys.argv[3])
    f1_path       = Path(sys.argv[4])
    out_cnf_path  = Path(sys.argv[5])
    out_meta_path = Path(sys.argv[6])

    aig_data = parse_aag(aag_path)
    outer = load_json(outer_path)
    care  = load_json(care_vars_path)
    f1    = load_json(f1_path)

    pivot = care["pivot"]
    X = care["X"]
    S = care["S"]
    Z = care["Z"]
    F1 = f1["care_minterms"]
    outer_collected = outer["collected_nodes"]

    outer_collected_set = set(outer_collected)
    X_set = set(X)

    vm = VarMgr()
    clauses = []

    # shared X vars
    for x in X:
        vm.get(("x", x))

    memo = {}

    # Build left/right copies for all Z
    z_left = {}
    z_right = {}
    xor_vars = []

    for z in Z:
        zl = build_node_cnf(z, "L", pivot, False, outer_collected_set, aig_data, X_set, vm, clauses, memo)
        zr = build_node_cnf(z, "R", pivot, True,  outer_collected_set, aig_data, X_set, vm, clauses, memo)
        z_left[z] = zl
        z_right[z] = zr

        xv = vm.get(("xor", z))
        add_xor_clauses(clauses, zl, zr, xv)
        xor_vars.append(xv)

    # Build OR tree to O
    if len(xor_vars) == 0:
        raise RuntimeError("Z is empty")

    if len(xor_vars) == 1:
        O = xor_vars[0]
    else:
        cur = xor_vars[0]
        for i, nxt in enumerate(xor_vars[1:], start=1):
            o = vm.get(("or", i))
            add_or_clauses(clauses, cur, nxt, o)
            cur = o
        O = cur

    # assert O = 1
    clauses.append([O])

    # Map S to SAT vars
    # If s is a PI or external node in X, reuse x-var.
    # Otherwise build left copy variable for s (s-space values come from the context).
    s_var_map = {}
    for s in S:
        if s in X_set:
            s_var_map[s] = vm.get(("x", s))
        else:
            s_var_map[s] = build_node_cnf(s, "L", pivot, False, outer_collected_set, aig_data, X_set, vm, clauses, memo)

    # Add blocking clauses for F1
    for bits in F1:
        if len(bits) != len(S):
            raise RuntimeError(f"Invalid F1 minterm length {len(bits)} for |S|={len(S)}")

        block = []
        for i, bit in enumerate(bits):
            v = s_var_map[S[i]]
            if bit == "1":
                block.append(-v)
            elif bit == "0":
                block.append(v)
            else:
                raise RuntimeError(f"Invalid bit '{bit}' in minterm {bits}")
        clauses.append(block)

    num_vars = vm.next_var - 1
    num_clauses = len(clauses)

    with open(out_cnf_path, "w") as f:
        f.write(f"p cnf {num_vars} {num_clauses}\n")
        for cl in clauses:
            f.write(" ".join(str(l) for l in cl) + " 0\n")

    meta = {
        "pivot": pivot,
        "x_count": len(X),
        "s_count": len(S),
        "z_count": len(Z),
        "f1_count": len(F1),
        "num_vars": num_vars,
        "num_clauses": num_clauses,
        "O_var": O,
        "X_var_map": {str(x): vm.get(("x", x)) for x in X},
        "S_var_map": {str(s): s_var_map[s] for s in S},
        "Z_left_var_map": {str(z): z_left[z] for z in Z},
        "Z_right_var_map": {str(z): z_right[z] for z in Z},
    }

    with open(out_meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    print("Full care CNF built.")
    print(f"  pivot = {pivot}")
    print(f"  |X| = {len(X)}")
    print(f"  |S| = {len(S)}")
    print(f"  |Z| = {len(Z)}")
    print(f"  |F1| = {len(F1)}")
    print(f"  vars = {num_vars}")
    print(f"  clauses = {num_clauses}")
    print(f"  wrote CNF:  {out_cnf_path}")
    print(f"  wrote meta: {out_meta_path}")

if __name__ == "__main__":
    main()
