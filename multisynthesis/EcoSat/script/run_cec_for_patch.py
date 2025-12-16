#!/usr/bin/env python3
import argparse
import os
import subprocess


def ensure_file(path: str, desc: str) -> None:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"[FATAL] {desc} niet gevonden: {path}")


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def run_abc_simple(abc_bin: str, cmd: str, label: str) -> None:
    """
    Generieke ABC-call (voor BLIF->AIG).
    """
    print("========================================")
    print(f"[ABC] {label}")
    print("----------------------------------------")
    print(f"{abc_bin} -c \"{cmd}\"")
    print("========================================")

    result = subprocess.run(
        [abc_bin, "-c", cmd],
        text=True,
        capture_output=True,
        check=False,
    )

    print("----------- ABC STDOUT -----------------")
    print(result.stdout)
    print("----------- ABC STDERR -----------------")
    print(result.stderr)
    print("----------------------------------------")

    if result.returncode != 0:
        raise SystemExit(
            f"[FATAL] ABC command '{label}' faalde met exit code {result.returncode}."
        )


def run_abc_cec(abc_bin: str, orig_aig: str, patch_aig: str) -> bool:
    """
    Draai 'cec orig_aig patch_aig' en bepaal op basis van STDOUT
    of de netwerken equivalent zijn.
    """
    cmd = f"cec {orig_aig} {patch_aig}"
    label = "CEC orig vs patch"

    print("========================================")
    print(f"[ABC] {label}")
    print("----------------------------------------")
    print(f"{abc_bin} -c \"{cmd}\"")
    print("========================================")

    result = subprocess.run(
        [abc_bin, "-c", cmd],
        text=True,
        capture_output=True,
        check=False,
    )

    print("----------- ABC STDOUT -----------------")
    print(result.stdout)
    print("----------- ABC STDERR -----------------")
    print(result.stderr)
    print("----------------------------------------")

    if result.returncode != 0:
        # ABC geeft soms non-zero bij interne fouten
        raise SystemExit(
            f"[FATAL] ABC CEC faalde met exit code {result.returncode}."
        )

    out = result.stdout

    # Heuristiek: typische ABC-messages
    if "Networks are NOT EQUIVALENT" in out:
        print("[INFO] CEC-resultaat: NIET equivalent (ABC rapporteert verschil).")
        return False
    if "Networks are equivalent" in out:
        print("[INFO] CEC-resultaat: Equivalent (ABC).")
        return True

    # Fallback: geen duidelijke message gevonden
    print("[WARN] Kon geen duidelijke CEC-conclusie vinden in ABC-output.")
    return False


def main():
    ap = argparse.ArgumentParser(
        description=(
            "Voer een CEC-check uit tussen een originele BLIF-netlist en een "
            "gepatchte BLIF-netlist via ABC (cec orig.aig patch.aig)."
        )
    )
    ap.add_argument(
        "--orig-blif",
        required=True,
        help="Pad naar originele BLIF (bv. example_big_300.mapped.blif).",
    )
    ap.add_argument(
        "--patch-blif",
        required=True,
        help="Pad naar gepatchte BLIF (mag in eerste instantie dezelfde zijn als orig).",
    )
    ap.add_argument(
        "--out-dir",
        required=True,
        help="Output-directory voor orig.aig, patch.aig en logs.",
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

    orig_blif = os.path.abspath(args.orig_blif)
    patch_blif = os.path.abspath(args.patch_blif)
    out_dir = os.path.abspath(args.out_dir)

    ensure_file(orig_blif, "Originele BLIF")
    ensure_file(patch_blif, "Gepatchte BLIF")
    ensure_dir(out_dir)

    # ABC pad
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
    ensure_file(abc_bin, "ABC binary")

    print("========================================")
    print("[INFO] run_cec_for_patch gestart")
    print(f"[INFO] Orig BLIF    : {orig_blif}")
    print(f"[INFO] Patch BLIF   : {patch_blif}")
    print(f"[INFO] Output dir   : {out_dir}")
    print(f"[INFO] ABC bin      : {abc_bin}")
    print("========================================")

    orig_aig = os.path.join(out_dir, "orig.aig")
    patch_aig = os.path.join(out_dir, "patch.aig")

    # 1) Origineel: BLIF -> AIG
    cmd_orig = f"read {orig_blif}; strash; write_aiger {orig_aig}; print_stats"
    run_abc_simple(abc_bin, cmd_orig, label="BLIF → AIG (orig)")

    # 2) Patch: BLIF -> AIG
    cmd_patch = f"read {patch_blif}; strash; write_aiger {patch_aig}; print_stats"
    run_abc_simple(abc_bin, cmd_patch, label="BLIF → AIG (patch)")

    # 3) CEC tussen beide AIGs
    eq = run_abc_cec(abc_bin, orig_aig, patch_aig)

    print("========================================")
    if eq:
        print("[INFO] EINDELIJK RESULTAAT: orig ≡ patch (equivalent).")
    else:
        print("[INFO] EINDELIJK RESULTAAT: orig ≠ patch (NIET equivalent).")
    print(f"[INFO] AIG-bestanden:")
    print(f"       orig : {orig_aig}")
    print(f"       patch: {patch_aig}")
    print("========================================")


if __name__ == "__main__":
    main()
