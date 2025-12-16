#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
from typing import Any, Dict


def load_json(path: str) -> Any:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"[FATAL] JSON-bestand niet gevonden: {path}")
    with open(path, "r") as f:
        return json.load(f)


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def main():
    ap = argparse.ArgumentParser(
        description=(
            "Extraheer lokale AIG-cones rond dst en pitstop voor één ECO-instance "
            "met behulp van ABC (cone -N ...)."
        )
    )
    ap.add_argument(
        "--instance",
        required=True,
        help="Pad naar *.eco_instance.json (uit run_eco_candidates.py).",
    )
    ap.add_argument(
        "--design-aig",
        required=True,
        help="Pad naar de globale AIG (bv. example_big_300.clean.postopt.aig).",
    )
    ap.add_argument(
        "--out-dir",
        required=True,
        help="Output-directory voor de geëxtraheerde cones.",
    )
    ap.add_argument(
        "--abc-bin",
        required=False,
        help=(
            "Pad naar ABC binary. Indien niet gezet, wordt $ABC_BIN of "
            "$HOME/Masterproef/vtr-verilog-to-routing/abc/abc gebruikt."
        ),
    )

    args = ap.parse_args()

    instance_path = os.path.abspath(args.instance)
    design_aig = os.path.abspath(args.design_aig)
    out_dir = os.path.abspath(args.out_dir)

    ensure_dir(out_dir)

    # ABC-pad bepalen
    if args.abc_bin:
        abc_bin = args.abc_bin
    else:
        env_abc = os.environ.get("ABC_BIN")
        if env_abc:
            abc_bin = env_abc
        else:
            home = os.environ.get("HOME", "")
            abc_bin = os.path.join(
                home, "Masterproef", "vtr-verilog-to-routing", "abc", "abc"
            )

    abc_bin = os.path.abspath(abc_bin)

    print("========================================")
    print("[INFO] extract_cones_for_instances gestart")
    print(f"[INFO] Instance JSON : {instance_path}")
    print(f"[INFO] Design AIG    : {design_aig}")
    print(f"[INFO] Output dir    : {out_dir}")
    print(f"[INFO] ABC bin       : {abc_bin}")
    print("========================================")

    if not os.path.isfile(design_aig):
        raise FileNotFoundError(f"[FATAL] design-aig niet gevonden: {design_aig}")
    if not os.path.isfile(instance_path):
        raise FileNotFoundError(f"[FATAL] instance JSON niet gevonden: {instance_path}")
    if not os.path.isfile(abc_bin):
        raise FileNotFoundError(f"[FATAL] ABC binary niet gevonden: {abc_bin}")

    # Instance inladen
    inst = load_json(instance_path)
    fmt = inst.get("format", "unknown")
    design_name = inst.get("design", "unknown_design")
    conn_idx = inst.get("connection_index", -1)
    pit_idx = inst.get("pitstop_index", -1)

    print(f"[INFO] Instance format  : {fmt}")
    print(f"[INFO] Design          : {design_name}")
    print(f"[INFO] Connection index: {conn_idx}")
    print(f"[INFO] Pitstop index   : {pit_idx}")

    dst = inst.get("dst", {}) or {}
    pit = inst.get("pitstop", {}) or {}

    dst_lut_name = dst.get("lut_name") or dst.get("block") or "UNKNOWN_DST"
    pit_lut_name = pit.get("lut_name") or pit.get("block") or "UNKNOWN_PIT"

    dst_root = dst.get("lut_root")
    pit_root = pit.get("lut_root")

    print("----------------------------------------")
    print(f"[INFO] dst.lut_name : {dst_lut_name}")
    print(f"[INFO] dst.lut_root : {dst_root}")
    print(f"[INFO] pit.lut_name : {pit_lut_name}")
    print(f"[INFO] pit.lut_root : {pit_root}")
    print("----------------------------------------")

    if dst_root is None:
        raise ValueError("[FATAL] dst.lut_root is None in instance JSON.")
    if pit_root is None:
        raise ValueError("[FATAL] pitstop.lut_root is None in instance JSON.")

    # Output-bestanden
    dst_cone_aig = os.path.join(out_dir, "dst_cone.aig")
    pit_cone_aig = os.path.join(out_dir, "pit_cone.aig")
    joint_cone_aig = os.path.join(out_dir, "joint_cone.aig")

    # ABC-script opbouwen
    # Let op: we gebruiken cone -N met komma-gescheiden lijst voor joint cone.
    abc_script_lines = [
        f"read {design_aig}",
        "strash",
        # dst cone
        f"cone -N {int(dst_root)} -O {dst_cone_aig}",
        # pit cone
        f"cone -N {int(pit_root)} -O {pit_cone_aig}",
        # joint cone
        f"cone -N {int(dst_root)},{int(pit_root)} -O {joint_cone_aig}",
        "print_stats",
    ]
    abc_script = "; ".join(abc_script_lines)

    print("[INFO] ABC command:")
    print("========================================")
    print(f"{abc_bin} -c \"{abc_script}\"")
    print("========================================")

    # ABC aanroepen
    try:
        result = subprocess.run(
            [abc_bin, "-c", abc_script],
            text=True,
            capture_output=True,
            check=False,  # we check zelf de returncode
        )
    except Exception as e:
        print(f"[FATAL] Fout bij uitvoeren van ABC: {e}")
        raise

    print("----------- ABC STDOUT -----------------")
    print(result.stdout)
    print("----------- ABC STDERR -----------------")
    print(result.stderr)
    print("----------------------------------------")

    if result.returncode != 0:
        print(f"[ERROR] ABC gaf een niet-nul exit code: {result.returncode}")
        raise SystemExit(
            "[FATAL] ABC cone-extractie is mislukt. Zie bovenstaande output."
        )

    # Controleren of de files effectief geschreven zijn
    missing = []
    for p in [dst_cone_aig, pit_cone_aig, joint_cone_aig]:
        if not os.path.isfile(p):
            missing.append(p)

    if missing:
        print("[ERROR] Niet alle cone-bestanden werden gevonden na ABC-run.")
        for m in missing:
            print(f"  -> ontbreekt: {m}")
        raise SystemExit("[FATAL] Cone-extractie onvolledig, zie fouten hierboven.")

    print("========================================")
    print("[INFO] Cone-extractie geslaagd.")
    print(f"[INFO] dst_cone  : {dst_cone_aig}")
    print(f"[INFO] pit_cone  : {pit_cone_aig}")
    print(f"[INFO] joint_cone: {joint_cone_aig}")
    print("========================================")


if __name__ == "__main__":
    main()

