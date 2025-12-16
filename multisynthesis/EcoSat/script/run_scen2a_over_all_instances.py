#!/usr/bin/env python3
import argparse
import os
import sys
import glob
import subprocess


def main():
    ap = argparse.ArgumentParser(
        description=(
            "Run Scenario 2a (run_scen2a_on_instance.py) "
            "over alle ECO-instances in een directory."
        )
    )
    ap.add_argument(
        "--instances-dir",
        required=True,
        help="Directory met *.eco_instance.json bestanden (output van run_eco_candidates.py).",
    )
    ap.add_argument(
        "--lut-cones",
        required=True,
        help="Pad naar <design>.lut_cones.json.",
    )
    ap.add_argument(
        "--orig-blif",
        required=True,
        help="Pad naar originele topologymapping BLIF (bv. example_big_300.mapped.blif).",
    )
    ap.add_argument(
        "--out-root",
        required=True,
        help="Root output directory waarin per instance een subdir komt.",
    )
    ap.add_argument(
        "--mode",
        choices=["identity", "complement"],
        default="identity",
        help="Scenario 2a patch modus (default: identity).",
    )
    ap.add_argument(
        "--patch-hex",
        default=None,
        help="Optioneel: expliciete func_hex voor de patch (overrulet mode).",
    )
    ap.add_argument(
        "--max-instances",
        type=int,
        default=0,
        help="Optioneel maximum aantal instances om te runnen (0 = geen limiet).",
    )

    args = ap.parse_args()

    # Zorg dat run_scen2a_on_instance.py gevonden wordt naast dit script
    script_dir = os.path.dirname(os.path.realpath(__file__))
    scen2a_script = os.path.join(script_dir, "run_scen2a_on_instance.py")
    if not os.path.isfile(scen2a_script):
        print(f"[FATAL] run_scen2a_on_instance.py niet gevonden in {script_dir}", file=sys.stderr)
        sys.exit(1)

    instances = sorted(
        glob.glob(os.path.join(args.instances_dir, "*.eco_instance.json"))
    )
    if not instances:
        print(f"[WARN] Geen *.eco_instance.json gevonden in {args.instances_dir}")
        sys.exit(0)

    os.makedirs(args.out_root, exist_ok=True)

    print("========================================")
    print("[INFO] Scenario 2a batch runner gestart")
    print(f"[INFO] Instances dir : {args.instances_dir}")
    print(f"[INFO] #instances    : {len(instances)}")
    print(f"[INFO] LUT-cones     : {args.lut_cones}")
    print(f"[INFO] Orig BLIF     : {args.orig_blif}")
    print(f"[INFO] Out-root      : {args.out_root}")
    print(f"[INFO] Mode          : {args.mode}")
    print(f"[INFO] patch-hex     : {args.patch_hex}")
    print(f"[INFO] max-instances : {args.max_instances} (0 = alles)")
    print("========================================")

    count = 0
    for inst_path in instances:
        base = os.path.basename(inst_path)
        name_no_ext = os.path.splitext(base)[0]

        # aparte subfolder per instance
        out_dir = os.path.join(args.out_root, name_no_ext)
        os.makedirs(out_dir, exist_ok=True)

        cmd = [
            sys.executable,
            scen2a_script,
            "--instance", inst_path,
            "--lut-cones", args.lut_cones,
            "--orig-blif", args.orig_blif,
            "--out-dir", out_dir,
            "--mode", args.mode,
        ]
        if args.patch_hex is not None:
            cmd.extend(["--patch-hex", args.patch_hex])

        print("----------------------------------------")
        print(f"[INFO] Run Scenario 2a voor instance: {inst_path}")
        print("[CMD] " + " ".join(cmd))
        print("----------------------------------------")

        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Scenario 2a faalde voor {inst_path} met exit code {e.returncode}", file=sys.stderr)

        count += 1
        if args.max_instances > 0 and count >= args.max_instances:
            print("========================================")
            print(f"[INFO] max-instances bereikt ({args.max_instances}), batch stopt hier.")
            break

    print("========================================")
    print(f"[INFO] Scenario 2a batch runner klaar. Aantal instances gerund: {count}")
    print("========================================")


if __name__ == "__main__":
    main()
