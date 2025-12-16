#!/usr/bin/env python3
import json
import argparse
import re
from typing import Dict, Set, Tuple


# ---------- Stap 1: mid_luts → LUT-namen ----------

def net_to_lut_name(net_name: str):
    """
    Map een netnaam uit mid_luts naar een LUT-naam.

    - 'LUT_11'    -> 'LUT_11'    (reeds een LUT-naam)
    - 'new_n11'   -> 'LUT_11'    (LUT-output-net uit BLIF)
    - andere zoals 'pi2', 'po0', 'gnd' -> None (geen LUT)
    """
    if not isinstance(net_name, str):
        return None

    # Case 1: al in de vorm 'LUT_<nummer>'
    m = re.fullmatch(r"LUT_(\d+)", net_name)
    if m:
        return net_name

    # Case 2: BLIF-intermediair net: new_n<nr>
    m = re.fullmatch(r"new_n(\d+)", net_name)
    if m:
        return f"LUT_{m.group(1)}"

    # Andere netnamen (pi2, po0, po1, gnd, vcc, ...) beschouwen we niet als LUT
    return None


def load_mid_lut_sets(mid_luts_path: str, index: int):
    """
    Leest example_big_300.mid_luts.json.
    Neemt de entry op positie `index` en geeft:
      src_luts    = {"LUT_x"}
      dst_luts    = {"LUT_y"}
      pitstop_luts= {"LUT_a","LUT_b",...}
    terug.

    We verwachten dat src/dst/mid 'new_nXX' of 'LUT_XX' zijn.
    """
    with open(mid_luts_path) as f:
        data = json.load(f)

    if not isinstance(data, list) or not data:
        raise ValueError(f"{mid_luts_path} bevat geen lijst met entries")

    if index < 0 or index >= len(data):
        raise ValueError(f"mid-index {index} is buiten bereik (0..{len(data)-1})")

    entry = data[index]

    raw_src = entry.get("src", "")
    raw_dst = entry.get("dst", "")

    src_lut = net_to_lut_name(raw_src)
    dst_lut = net_to_lut_name(raw_dst)

    pitstop_luts: Set[str] = set()
    for mp in entry.get("midpoints", []):
        raw_mid = mp.get("mid", "")
        mid_lut = net_to_lut_name(raw_mid)
        if mid_lut:
            pitstop_luts.add(mid_lut)

    if not src_lut or not dst_lut or not pitstop_luts:
        raise ValueError(
            f"Entry {index} in {mid_luts_path} heeft geen geldige src/dst/mid "
            f"(src='{raw_src}', dst='{raw_dst}', mids={entry.get('midpoints', [])})."
        )

    return {src_lut}, {dst_lut}, pitstop_luts


# ---------- Stap 2: lut_cones → LUT-naam → AIG-nodes ----------

def load_lut_to_nodes_map(lut_cones_path: str) -> Dict[str, Set[str]]:
    """
    Leest example_big_300.lut_cones.json en bouwt:
      lut_to_nodes["LUT_11"] = {"N11", "N7", "N8", ...}

    We nemen de unie van:
      - lut_root
      - leaves[]
      - internal_nodes[]
    en zetten ints → "N<nr>" zodat het matcht met graph_json node IDs.
    """
    with open(lut_cones_path) as f:
        data = json.load(f)

    lut_cones = data.get("lut_cones", [])
    lut_to_nodes: Dict[str, Set[str]] = {}

    for cone in lut_cones:
        lut_name = cone.get("lut_name")
        if not lut_name:
            continue

        root = cone.get("lut_root")
        leaves = cone.get("leaves", [])
        internal = cone.get("internal_nodes", [])

        node_ids: Set[str] = set()

        def to_nid(x):
            # ints → "N<nr>", strings die al met "N" starten laten we staan
            if isinstance(x, int):
                return f"N{x}"
            elif isinstance(x, str) and x.startswith("N"):
                return x
            else:
                # fallback: toch "N<waarde>" proberen
                try:
                    return f"N{int(x)}"
                except Exception:
                    return str(x)

        if root is not None:
            node_ids.add(to_nid(root))
        for v in leaves:
            node_ids.add(to_nid(v))
        for v in internal:
            node_ids.add(to_nid(v))

        lut_to_nodes[lut_name] = node_ids

    return lut_to_nodes


# ---------- Stap 3: van LUT-namen naar node-sets ----------

def compute_node_sets(
    src_luts: Set[str],
    dst_luts: Set[str],
    pitstop_luts: Set[str],
    lut_to_nodes: Dict[str, Set[str]],
) -> Tuple[Set[str], Set[str], Set[str]]:
    """
    Berekent drie verzamelingen van AIG-node-IDs:
      src_nodes, dst_nodes, pit_nodes

    Standaard:
      - Neem simpelweg lut_to_nodes["LUT_x"].
    Fallback:
      - Als LUT_naam niet bestaat, zoek via numeric suffix "N<nr>" in alle cones.

    Exclusiviteit: src > dst > pitstop.
    """

    def expand_lut_name(ln: str) -> Set[str]:
        # 1) direct via LUT-naam (ideale, nieuwe case)
        if ln in lut_to_nodes:
            return set(lut_to_nodes[ln])

        # 2) fallback via node-ID in cones (oude safety-net)
        m = re.search(r"(\d+)$", ln)
        if not m:
            return set()

        nid = f"N{int(m.group(1))}"
        result: Set[str] = set()
        for _, node_set in lut_to_nodes.items():
            if nid in node_set:
                result |= node_set

        return result

    src_nodes: Set[str] = set()
    dst_nodes: Set[str] = set()
    pit_nodes: Set[str] = set()

    missing_src = []
    for ln in src_luts:
        nodes = expand_lut_name(ln)
        if nodes:
            src_nodes |= nodes
        else:
            missing_src.append(ln)

    missing_dst = []
    for ln in dst_luts:
        nodes = expand_lut_name(ln)
        if nodes:
            dst_nodes |= nodes
        else:
            missing_dst.append(ln)

    missing_pit = []
    for ln in pitstop_luts:
        nodes = expand_lut_name(ln)
        if nodes:
            pit_nodes |= nodes
        else:
            missing_pit.append(ln)

    if missing_src:
        print(f"[WARN] Geen nodes gevonden voor src LUTs (naam + fallback): {missing_src}")
    if missing_dst:
        print(f"[WARN] Geen nodes gevonden voor dst LUTs (naam + fallback): {missing_dst}")
    if missing_pit:
        print(f"[WARN] Geen nodes gevonden voor pitstop LUTs (naam + fallback): {missing_pit}")

    # exclusief: src > dst > pitstop
    dst_nodes -= src_nodes
    pit_nodes -= src_nodes
    pit_nodes -= dst_nodes

    return src_nodes, dst_nodes, pit_nodes


# ---------- Stap 4: annoteren van de AIG-JSON ----------

def annotate_graph(
    graph_json_path: str,
    out_json_path: str,
    src_nodes: Set[str],
    dst_nodes: Set[str],
    pit_nodes: Set[str],
):
    """
    Schrijft 'role' voor elke node in graph_json:
      src      (rood)
      dst      (groen)
      pitstop  (paars)
      normal   (blauw)
    """
    with open(graph_json_path) as f:
        g = json.load(f)

    for node in g.get("nodes", []):
        nid = node["id"]
        if nid in src_nodes:
            node["role"] = "src"
        elif nid in dst_nodes:
            node["role"] = "dst"
        elif nid in pit_nodes:
            node["role"] = "pitstop"
        else:
            node["role"] = "normal"

    with open(out_json_path, "w") as f:
        json.dump(g, f, indent=2)

    print(
        f"[OK] Annotated: src={len(src_nodes)}, dst={len(dst_nodes)}, pitstop={len(pit_nodes)}"
    )


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser(
        description="Annoteer AIG-JSON met rollen op basis van mid_luts + lut_cones (via LUT-namen)."
    )
    ap.add_argument("--graph", required=True, help="Basis AIG-JSON (uit dot_json.py)")
    ap.add_argument("--lut-cones", required=True, help="mt_lut_cones JSON")
    ap.add_argument("--mid-luts", required=True, help="mid_luts JSON")
    ap.add_argument(
        "--mid-index",
        type=int,
        default=0,
        help="Index van de entry in mid_luts.json (standaard 0)",
    )
    ap.add_argument(
        "--out",
        required=True,
        help="Output JSON met 'role'-veld per node",
    )

    args = ap.parse_args()

    # 1) mid_luts → LUT-namen
    src_luts, dst_luts, pitstop_luts = load_mid_lut_sets(args.mid_luts, args.mid_index)
    print(f"[INFO] src LUTs    : {sorted(src_luts)}")
    print(f"[INFO] dst LUTs    : {sorted(dst_luts)}")
    print(f"[INFO] pitstop LUTs: {sorted(pitstop_luts)}")

    # 2) lut_cones → LUT-naam → node-set
    lut_to_nodes = load_lut_to_nodes_map(args.lut_cones)
    print(f"[INFO] LUTs in lut_cones: {len(lut_to_nodes)}")

    # 3) node-sets
    src_nodes, dst_nodes, pit_nodes = compute_node_sets(
        src_luts, dst_luts, pitstop_luts, lut_to_nodes
    )

    # 4) annoteren
    annotate_graph(args.graph, args.out, src_nodes, dst_nodes, pit_nodes)


if __name__ == "__main__":
    main()
