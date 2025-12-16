#!/usr/bin/env python3
import argparse
import os


def ensure_file(path: str, desc: str) -> None:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"[FATAL] {desc} niet gevonden: {path}")


def patch_blif_const1(orig_blif: str, out_blif: str, lut_name: str) -> None:
    """
    Zoek in de BLIF de .names-regel waarvan de LAATSTE token == lut_name.
    Vervang de volledige truth table door een constante-1 functie:
        '- - ... - 1'
    met evenveel '-' als er inputs zijn.
    """
    with open(orig_blif, "r") as f:
        lines = f.readlines()

    out_lines = []
    i = 0
    patched = False

    print("========================================")
    print(f"[INFO] Start patch_blif_const1")
    print(f"[INFO] Orig BLIF : {orig_blif}")
    print(f"[INFO] Out  BLIF : {out_blif}")
    print(f"[INFO] LUT name  : {lut_name}")
    print("========================================")

    n_lines = len(lines)
    while i < n_lines:
        line = lines[i]
        stripped = line.lstrip()

        # Check op .names
        if stripped.startswith(".names"):
            tokens = stripped.split()
            # tokens: ['.names', in1, in2, ..., out]
            if len(tokens) >= 3 and tokens[-1] == lut_name:
                # Dit is de LUT die we willen patchen
                print("----------------------------------------")
                print(f"[INFO] Gevonden .names voor {lut_name} op lijn {i}:")
                print(line.rstrip())
                num_inputs = len(tokens) - 2  # .names + inputs + output
                print(f"[INFO] #inputs = {num_inputs}")

                out_lines.append(line)  # .names-regel zelf behouden

                # Nu alle originele TT-regels overslaan
                i += 1
                while i < n_lines:
                    nxt = lines[i]
                    s = nxt.lstrip()

                    # Truth table-regels: geen '.', niet leeg, geen comment '#'
                    if s.startswith(".") or s.startswith("#") or s.strip() == "":
                        # Boundary: hier eindigt de truth table.
                        pattern_line = "-" * num_inputs + " 1\n"
                        print(f"[INFO] Schrijf nieuwe const-1 TT-regel: {pattern_line.strip()}")
                        out_lines.append(pattern_line)

                        # Deze boundary-lijn nog niet verwerken hier;
                        # laat de outer-loop hem normaal verwerken.
                        break
                    else:
                        # Oude TT-regel, overslaan
                        print(f"[DEBUG] Skip oude TT-regel: {nxt.rstrip()}")
                        i += 1

                patched = True
                # NIET i++ hier, we willen de boundary-lijn nog normaal verwerken
                continue
            else:
                # Andere .names, gewoon kopiëren
                out_lines.append(line)
                i += 1
        else:
            # Geen .names-regel, gewoon kopiëren
            out_lines.append(line)
            i += 1

    if not patched:
        print("========================================")
        print(f"[WARN] Geen .names gevonden met output '{lut_name}'.")
        print("[WARN] Origineel bestand ongewijzigd gekopieerd.")
        print("========================================")
    else:
        print("========================================")
        print(f"[INFO] Patch toegepast op LUT {lut_name}.")
        print("========================================")

    with open(out_blif, "w") as f_out:
        f_out.writelines(out_lines)


def main():
    ap = argparse.ArgumentParser(
        description=(
            "Maak een toy-patch: vervang de truth table van één LUT-output "
            "door een constante 1 functie in een BLIF-bestand."
        )
    )
    ap.add_argument(
        "--orig-blif",
        required=True,
        help="Pad naar originele BLIF (bv. example_big_300.mapped.blif).",
    )
    ap.add_argument(
        "--out-blif",
        required=True,
        help="Pad naar output BLIF met toy-patch.",
    )
    ap.add_argument(
        "--lut-name",
        required=True,
        help="Naam van de LUT-output (bv. LUT_11) die gepatcht moet worden.",
    )

    args = ap.parse_args()

    orig_blif = os.path.abspath(args.orig_blif)
    out_blif = os.path.abspath(args.out_blif)

    ensure_file(orig_blif, "Originele BLIF")

    patch_blif_const1(orig_blif, out_blif, args.lut_name)


if __name__ == "__main__":
    main()
