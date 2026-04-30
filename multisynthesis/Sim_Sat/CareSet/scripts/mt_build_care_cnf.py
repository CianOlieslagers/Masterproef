import json
import sys
from pathlib import Path

def load_json(path):
    with open(path, "r") as f:
        return json.load(f)

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

class VarMgr:
    def __init__(self):
        self.next_var = 1
        self.map = {}

    def get(self, key):
        if key not in self.map:
            self.map[key] = self.next_var
            self.next_var += 1
        return self.map[key]

def main():
    if len(sys.argv) != 7:
        print("Usage: python3 mt_build_care_cnf.py <care_mitter.json> <care_vars.json> <F1_random.json> <outer.json> <out.cnf> <out.meta.json>")
        sys.exit(1)

    miter_meta_path = Path(sys.argv[1])
    care_vars_path  = Path(sys.argv[2])
    f1_path         = Path(sys.argv[3])
    outer_path      = Path(sys.argv[4])
    out_cnf_path    = Path(sys.argv[5])
    out_meta_path   = Path(sys.argv[6])

    miter_meta = load_json(miter_meta_path)
    care_vars  = load_json(care_vars_path)
    f1         = load_json(f1_path)
    outer      = load_json(outer_path)

    X = care_vars["X"]
    S = care_vars["S"]
    Z = care_vars["Z"]
    pivot = care_vars["pivot"]
    outer_collected = set(outer["collected_nodes"])
    care_minterms = f1["care_minterms"]

    vm = VarMgr()
    clauses = []

    # Shared X vars
    x_var = {x: vm.get(("x", x)) for x in X}

    # Constant false helper
    const0 = vm.get(("const0", 0))
    clauses.append([-const0])  # const0 = 0

    # Build left/right vars for outer collected nodes.
    # We do not reconstruct full AIG here from source;
    # instead we reserve symbolic vars for S and Z interface,
    # then rely on metadata + later solver backend integration.
    #
    # This exporter is therefore a strict "blocking-clause + interface" CNF scaffold.

    s_var = {s: vm.get(("s", s)) for s in S}
    z_var = {}
    xor_var = {}

    # Link S vars to X vars when they are shared interface nodes
    for s in S:
        if s in x_var:
            clauses.append([-s_var[s], x_var[s]])
            clauses.append([s_var[s], -x_var[s]])

    for z in Z:
        zL = vm.get(("zL", z))
        zR = vm.get(("zR", z))
        z_var[(z, "L")] = zL
        z_var[(z, "R")] = zR

        xz = vm.get(("xor", z))
        xor_var[z] = xz
        add_xor_clauses(clauses, zL, zR, xz)

    # OR all XORs into O
    xor_list = [xor_var[z] for z in Z]
    if not xor_list:
        print("ERROR: empty Z")
        sys.exit(2)

    if len(xor_list) == 1:
        O = xor_list[0]
    else:
        cur = xor_list[0]
        for i, nxt in enumerate(xor_list[1:], start=1):
            o = vm.get(("or", i))
            add_or_clauses(clauses, cur, nxt, o)
            cur = o
        O = cur

    # Assert miter output = 1
    clauses.append([O])

    # Add blocking clauses for all F1 minterms over S
    for bits in care_minterms:
        if len(bits) != len(S):
            print(f"ERROR: minterm length {len(bits)} != |S| {len(S)} for {bits}")
            sys.exit(3)

        block = []
        for i, bit in enumerate(bits):
            v = s_var[S[i]]
            if bit == "1":
                block.append(-v)
            elif bit == "0":
                block.append(v)
            else:
                print(f"ERROR: invalid bit '{bit}' in minterm {bits}")
                sys.exit(4)
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
        "f1_count": len(care_minterms),
        "num_vars": num_vars,
        "num_clauses": num_clauses,
        "O_var": O,
        "X_var_map": {str(k): v for k, v in x_var.items()},
        "S_var_map": {str(k): v for k, v in s_var.items()},
        "Z_left_var_map": {str(z): z_var[(z, "L")] for z in Z},
        "Z_right_var_map": {str(z): z_var[(z, "R")] for z in Z},
    }

    with open(out_meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    print("CNF scaffold built.")
    print(f"  pivot = {pivot}")
    print(f"  |X| = {len(X)}")
    print(f"  |S| = {len(S)}")
    print(f"  |Z| = {len(Z)}")
    print(f"  |F1| = {len(care_minterms)}")
    print(f"  vars = {num_vars}")
    print(f"  clauses = {num_clauses}")
    print(f"  wrote CNF:  {out_cnf_path}")
    print(f"  wrote meta: {out_meta_path}")

if __name__ == "__main__":
    main()
