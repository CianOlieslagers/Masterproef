#!/usr/bin/env python3
import argparse
import os
from typing import List


def normalize_hex(h: str) -> str:
    """
    Normaliseer hex-string:
      - strip spaties
      - lowercase
      - geen '0x' prefix
    """
    h = h.strip().lower()
    if h.startswith("0x"):
        h = h[2:]
    return h


def hex_to_tt_bits(func_hex: str, num_vars: int) -> List[int]:
    """
    Zet een hex truth table om naar een lijst van bits (0/1) van lengte 2^num_vars.

    Conventie:
      - index = sum_j assignment[j] << j
      - j = 0 komt overeen met de EERSTE input in de .names-lijn
        (dus BLIF input-volgorde == variabele-volgorde).

    Dit is dezelfde conventie als in je eval_tt / funcs_match_on_overlap code.
    """
    func_hex = normalize_hex(func_hex)
    v = int(func_hex, 16)

    tt_size = 1 << num_vars  # 2^num_vars
    # sanity check: hex moet genoeg bits bevatten
    max_bits = 4 * len(func_hex)
    if tt_size > max_bits:
        raise ValueError(
            f"func_hex heeft te weinig bits voor {num_vars} variabelen: "
            f"2^{num_vars} = {tt_size} > {max_bits} (4 * len(hex))"
        )

    bits = []
    for idx in range(tt_size):
        bit = (v >> idx) & 1
        bits.append(bit)

    return bits


def tt_bits_to_blif_rows(bits: List[int], num_vars: int) -> List[str]:
    """
    Maak BLIF .names-rijen uit een truth table:

      bits[idx] = 1 => we maken een rij 'pat 1'
      waarbij pat een string is met 0/1 per input.

    index → bits:
      - idx = sum_j x_j << j
      - bit j = x_j
      - x_0 is de waarde van input 0 (eerste input in .names)
    """
    rows: List[str] = []
    tt_size = 1 << num_vars

    if len(bits) != tt_size:
        raise ValueError(
            f"Lengte bits ({len(bits)}) != 2^{num_vars} ({tt_size})."
        )

    for idx in range(tt_size):
        if bits[idx] != 1:
            continue

        # bouw pattern string
        chars = []
        for j in range(num_vars):
            bit = (idx >> j) & 1
            chars.append("1" if bit else "0")
        pat = "".join(chars)
        rows.append(f"{pat} 1\n")

    return rows


def patch_lut_in_blif(
    orig_blif: str,
    out_blif: str,
    lut_name: str,
    func_hex: str,
) -> None:
    """
    Vind de .names-block voor 'lut_name' in orig_blif en vervang de truth table
    door een nieuwe die overeenkomt met func_hex.
    """
    lut_name = lut_name.strip()
    func_hex = normalize_hex(func_hex)

    if not os.path.isfile(orig_blif):
        raise FileNotFoundError(f"Orig BLIF niet gevonden: {orig_blif}")

    with open(orig_blif, "r") as f:
        lines = f.readlines()

    new_lines: List[str] = []
    i = 0
    found_names = False
    patched = False

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Zoek naar ".names ... <lut_name>"
        if stripped.startswith(".names"):
            tokens = stripped.split()
            # tokens: [".names", in1, in2, ..., out]
            if len(tokens) >= 3 and tokens[-1] == lut_name:
                found_names = True
                print("========================================")
                print(f"[INFO] Gevonden .names voor {lut_name} op lijn {i}:")
                print(line.rstrip())
                # inputs = tokens[1:-1]
                inputs = tokens[1:-1]
                num_inputs = len(inputs)
                print(f"[INFO] #inputs = {num_inputs}")

                # schrijf de .names-lijn zelf door
                new_lines.append(line)

                # skip de oude TT-rijen
                i += 1
                while i < len(lines):
                    nxt = lines[i]
                    nxt_strip = nxt.strip()
                    # stop als we bij een nieuwe directive komen (.names, .model, .end, ...)
                    if nxt_strip.startswith(".") or nxt_strip == "":
                        break
                    # anders veronderstellen we een TT-regel
                    print(f"[DEBUG] Skip oude TT-regel: {nxt_strip}")
                    i += 1

                # nu genereren we nieuwe TT-rijen uit func_hex
                print("[INFO] Genereer nieuwe TT uit func_hex =", func_hex)
                bits = hex_to_tt_bits(func_hex, num_inputs)
                new_rows = tt_bits_to_blif_rows(bits, num_inputs)

                if not new_rows:
                    print("[WARN] Nieuwe TT heeft geen '1'-minterms → constante 0 functie.")
                else:
                    for row in new_rows:
                        print(f"[DEBUG] Nieuwe TT-regel: {row.strip()}")
                        new_lines.append(row)

                patched = True
                # NIET i += 1 hier, want we hebben al gesprongen in de while
                continue  # ga verder met de while, zonder i++ aan het einde

        # als geen .names-block van deze LUT, gewoon lijn doorzetten
        new_lines.append(line)
        i += 1

    if not found_names:
        raise RuntimeError(f"[FATAL] Geen .names-block gevonden voor LUT '{lut_name}' in {orig_blif}")

    if not patched:
        raise RuntimeError(f"[FATAL] .names-block gevonden maar patch niet toegepast voor LUT '{lut_name}'")

    with open(out_blif, "w") as f_out:
        f_out.writelines(new_lines)

    print("========================================")
    print(f"[INFO] Patch toegepast op LUT {lut_name}.")
    print(f"[INFO] Output BLIF: {out_blif}")
    print("========================================")


def main():
    ap = argparse.ArgumentParser(
        description=(
            "Patch een LUT (.names-blok) in een BLIF-bestand met een nieuwe functie "
            "gegeven als func_hex truth table."
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
        help="Pad naar output BLIF (gepatchte versie).",
    )
    ap.add_argument(
        "--lut-name",
        required=True,
        help="Naam van de LUT-output (bv. LUT_11).",
    )
    ap.add_argument(
        "--func-hex",
        required=True,
        help="Truth table in hex voor de nieuwe LUT-functie (bv. 8777).",
    )

    args = ap.parse_args()

    patch_lut_in_blif(
        orig_blif=os.path.abspath(args.orig_blif),
        out_blif=os.path.abspath(args.out_blif),
        lut_name=args.lut_name,
        func_hex=args.func_hex,
    )


if __name__ == "__main__":
    main()
