#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
from typing import Any, Dict, List


def load_json(path: str) -> Any:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"[FATAL] JSON-bestand niet gevonden: {path}")
    with open(path, "r") as f:
        return json.load(f)


def normalize_hex(h: str) -> str:
    h = str(h).strip().lower()
    if h.startswith("0x"):
        h = h[2:]
    return h


def complement_hex(func_hex: str) -> str:
    """
    Neem het bitwise complement van een hex truth table, met behoud van lengte.
    """
    func_hex = normalize_hex(func_hex)
    v = int(func_hex, 16)
    # mask met evenveel bits als de hex lengte
    mask = (1 << (4 * len(func_hex))) - 1
    comp = mask ^ v
    comp_hex = f"{comp:0{len(func_hex)}x}"  # met leading zeros
    return comp_hex


def const_hex(func_hex: str, value: int) -> str:
    """
    Maak een constante 0 of 1 truth table met dezelfde lengte (in hex chars)
    als func_hex. value = 0 of 1.
    """
    func_hex = normalize_hex(func_hex)
    n_chars = len(func_hex)
    if value == 0:
        return "0" * n_chars
    else:
        return "f" * n_chars


def find_lut_func_hex(lut_cones_path: str, lut_name: str) -> str:
    data = load_json(lut_cones_path)
    lut_cones: List[Dict[str, Any]] = data.get("lut_cones", [])
    for cone in lut_cones:
        if cone.get("lut_name") == lut_name:
            fh = cone.get("func_hex")
            if fh is None:
                raise RuntimeError(
                    f"[FATAL] func_hex ontbreekt voor {lut_name} in {lut_cones_path}"
                )
            return normalize_hex(fh)
    raise RuntimeError(
        f"[FATAL] LUT '{lut_name}' niet gevonden in {lut_cones_path}"
    )


def main():
    ap = argparse.ArgumentParser(
        description=(
            "Scenario 2a op één ECO-instance: "
            "patch de pitstop-LUT met een gekozen func_hex-variant "
            "en draai CEC (orig vs patch)."
        )
    )
    ap.add_argument(
        "--instance",
        required=True,
        help="Pad naar één *.eco_instance.json (uit run_eco_candidates.py).",
    )
    ap.add_argument(
        "--lut-cones",
        required=True,
        help="Pad naar <design>.lut_cones.json (voor originele func_hex).",
    )
    ap.add_argument(
        "--orig-blif",
        required=True,
        help="Originele topologymapping BLIF (bv. example_big_300.mapped.blif).",
    )
    ap.add_argument(
        "--out-dir",
        required=True,
        help="Output-directory voor gepatchte BLIF + CEC-resultaten.",
    )
    ap.add_argument(
        "--mode",
        choices=["identity", "complement", "const0", "const1"],
        default="complement",
        help=(
            "Hoe de nieuwe func_hex moet worden afgeleid "
            "uit de originele (default: complement)."
        ),
    )
    ap.add_argument(
        "--patch-hex",
        default=None,
        help=(
            "Overschrijf de automatisch bepaalde func_hex met deze hexstring. "
            "Als gezet, wint dit over --mode."
        ),
    )

    args = ap.parse_args()

    instance_path = os.path.abspath(args.instance)
    lut_cones_path = os.path.abspath(args.lut_cones)
    orig_blif = os.path.abspath(args.orig_blif)
    out_dir = os.path.abspath(args.out_dir)
    mode = args.mode
    patch_hex_override = args.patch_hex

    os.makedirs(out_dir, exist_ok=True)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    patch_lut_script = os.path.join(script_dir, "patch_lut_from_hex.py")
    cec_script = os.path.join(script_dir, "run_cec_for_patch.py")

    if not os.path.isfile(patch_lut_script):
        raise FileNotFoundError(f"[FATAL] patch_lut_from_hex.py niet gevonden in {script_dir}")
    if not os.path.isfile(cec_script):
        raise FileNotFoundError(f"[FATAL] run_cec_for_patch.py niet gevonden in {script_dir}")

    # ------------------------------------------------
    # 1) Instance inladen
    # ------------------------------------------------
    inst = load_json(instance_path)

    fmt = inst.get("format")
    design_name = inst.get("design", "unknown_design")
    conn_idx = inst.get("connection_index", -1)
    pit_idx = inst.get("pitstop_index", -1)

    pit = inst.get("pitstop", {})
    pit_lut_name = pit.get("lut_name")

    print("========================================")
    print("[INFO] Scenario 2a op ECO-instance")
    print("----------------------------------------")
    print(f"[INFO] Instance JSON   : {instance_path}")
    print(f"[INFO] Format          : {fmt}")
    print(f"[INFO] Design          : {design_name}")
    print(f"[INFO] Connection index: {conn_idx}")
    print(f"[INFO] Pitstop index   : {pit_idx}")
    print(f"[INFO] Pit LUT name    : {pit_lut_name}")
    print(f"[INFO] LUT-cones JSON  : {lut_cones_path}")
    print(f"[INFO] Orig BLIF       : {orig_blif}")
    print(f"[INFO] Output dir      : {out_dir}")
    print(f"[INFO] Mode            : {mode}")
    print(f"[INFO] patch-hex       : {patch_hex_override}")
    print("========================================")

    if not pit_lut_name:
        raise RuntimeError("[FATAL] pitstop.lut_name ontbreekt in instance JSON.")

    # ------------------------------------------------
    # 2) Originele func_hex ophalen
    # ------------------------------------------------
    orig_hex = find_lut_func_hex(lut_cones_path, pit_lut_name)
    print(f"[INFO] Originele func_hex voor {pit_lut_name}: {orig_hex}")

    # ------------------------------------------------
    # 3) Nieuwe func_hex bepalen
    # ------------------------------------------------
    if patch_hex_override is not None:
        new_hex = normalize_hex(patch_hex_override)
        print(f"[INFO] Nieuwe func_hex via --patch-hex: {new_hex}")
    else:
        if mode == "identity":
            new_hex = orig_hex
            print("[INFO] Mode=identity → func_hex blijft identiek.")
        elif mode == "complement":
            new_hex = complement_hex(orig_hex)
            print(f"[INFO] Mode=complement → nieuwe func_hex: {new_hex}")
        elif mode == "const0":
            new_hex = const_hex(orig_hex, 0)
            print(f"[INFO] Mode=const0 → nieuwe func_hex: {new_hex}")
        elif mode == "const1":
            new_hex = const_hex(orig_hex, 1)
            print(f"[INFO] Mode=const1 → nieuwe func_hex: {new_hex}")
        else:
            raise RuntimeError(f"[FATAL] Onbekende mode: {mode}")

    # ------------------------------------------------
    # 4) Gepatchte BLIF pad bepalen
    # ------------------------------------------------
    inst_tag = f"conn{conn_idx:03d}.pit{pit_idx:03d}"
    base_orig = os.path.splitext(os.path.basename(orig_blif))[0]
    patched_blif = os.path.join(
        out_dir,
        f"{base_orig}.{inst_tag}.{mode}.mapped.blif",
    )

    print("========================================")
    print("[INFO] Stap 1: BLIF patchen met nieuwe LUT-functie …")
    print("----------------------------------------")
    print(f"[INFO] patch_lut_from_hex.py : {patch_lut_script}")
    print(f"[INFO] Orig BLIF             : {orig_blif}")
    print(f"[INFO] Patched BLIF          : {patched_blif}")
    print(f"[INFO] LUT name              : {pit_lut_name}")
    print(f"[INFO] Nieuwe func_hex       : {new_hex}")
    print("========================================")

    patch_cmd = [
        "python3",
        patch_lut_script,
        "--orig-blif", orig_blif,
        "--out-blif", patched_blif,
        "--lut-name", pit_lut_name,
        "--func-hex", new_hex,
    ]

    print("----------- PATCH CMD ------------------")
    print(" ".join(patch_cmd))
    print("----------------------------------------")

    res = subprocess.run(patch_cmd)
    if res.returncode != 0:
        raise RuntimeError("[FATAL] patch_lut_from_hex.py faalde (returncode != 0).")

    # ------------------------------------------------
    # 5) CEC runnen: orig vs patch
    # ------------------------------------------------
    cec_out_dir = os.path.join(out_dir, f"cec_{inst_tag}_{mode}")
    os.makedirs(cec_out_dir, exist_ok=True)

    print("========================================")
    print("[INFO] Stap 2: CEC-check (orig vs patch) …")
    print("----------------------------------------")
    print(f"[INFO] run_cec_for_patch.py : {cec_script}")
    print(f"[INFO] CEC output dir       : {cec_out_dir}")
    print("========================================")

    cec_cmd = [
        "python3",
        cec_script,
        "--orig-blif", orig_blif,
        "--patch-blif", patched_blif,
        "--out-dir", cec_out_dir,
    ]

    print("----------- CEC CMD --------------------")
    print(" ".join(cec_cmd))
    print("----------------------------------------")

    res2 = subprocess.run(cec_cmd)
    if res2.returncode != 0:
        print("[WARN] run_cec_for_patch.py gaf returncode != 0 (CEC mismatch is mogelijk bewust).")

    print("========================================")
    print("[INFO] Scenario 2a run_scen2a_on_instance klaar.")
    print("[INFO] Check bovenstaande ABC/CEC-logs voor Equivalent/NOT EQUIVALENT.")
    print("========================================")


if __name__ == "__main__":
    main()
