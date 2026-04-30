import json
import sys

path = sys.argv[1]

with open(path) as f:
    d = json.load(f)

def s(name):
    return set(d.get(name, []))

pivot = d["pivot"]

tfi_nodes = s("tfi_nodes")
tfo_nodes = s("tfo_nodes")
window_pis = s("window_pis")
window_pos = s("window_pos")
marked_nodes = s("marked_nodes")
reduced_tfo_nodes = s("reduced_tfo_nodes")
reduced_window_pos = s("reduced_window_pos")
collected_nodes = s("collected_nodes")
augmented_window_pis = s("augmented_window_pis")

checks = []

checks.append(("reduced_tfo subset tfo",
               reduced_tfo_nodes.issubset(tfo_nodes)))

checks.append(("reduced_window_pos subset reduced_tfo",
               reduced_window_pos.issubset(reduced_tfo_nodes)))

checks.append(("pivot in collected_nodes",
               pivot in collected_nodes))

checks.append(("window_pis covered by collected or augmented",
               window_pis.issubset(collected_nodes | augmented_window_pis)))

checks.append(("augmented contains original window_pis",
               window_pis.issubset(augmented_window_pis)))

checks.append(("collected non-empty",
               len(collected_nodes) > 0))

checks.append(("reduced_tfo non-empty",
               len(reduced_tfo_nodes) > 0))

checks.append(("reduced_window_pos non-empty",
               len(reduced_window_pos) > 0))

checks.append(("window_pis_count matches",
               d["window_pis_count"] == len(window_pis)))

checks.append(("window_pos_count matches",
               d["window_pos_count"] == len(window_pos)))

checks.append(("marked_count matches",
               d["marked_count"] == len(marked_nodes)))

checks.append(("reduced_tfo_count matches",
               d["reduced_tfo_count"] == len(reduced_tfo_nodes)))

checks.append(("reduced_window_pos_count matches",
               d["reduced_window_pos_count"] == len(reduced_window_pos)))

checks.append(("collected_count matches",
               d["collected_count"] == len(collected_nodes)))

checks.append(("augmented_window_pis_count matches",
               d["augmented_window_pis_count"] == len(augmented_window_pis)))

failed = False
for name, ok in checks:
    print(f"[{'OK' if ok else 'FAIL'}] {name}")
    if not ok:
        failed = True

if failed:
    sys.exit(1)
else:
    print("\nJSON/invariant checks passed.")
