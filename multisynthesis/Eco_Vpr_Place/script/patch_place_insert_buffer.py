#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


def fail(msg):
    print(f"[FAIL] {msg}", file=sys.stderr)
    sys.exit(1)


def ok(msg):
    print(f"[OK] {msg}")


def parse_place(path):
    lines = []
    blocks = {}
    occupied = {}
    last_block_number = -1

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            lines.append(line.rstrip("\n"))

    for idx, line in enumerate(lines):
        s = line.strip()

        if not s:
            continue
        if s.startswith("#"):
            continue
        if s.startswith("Netlist_File:"):
            continue
        if s.startswith("Array size:"):
            continue

        parts = s.split()
        if len(parts) < 5:
            continue

        name = parts[0]

        try:
            x = int(parts[1])
            y = int(parts[2])
            subblk = int(parts[3])
            layer = int(parts[4])
        except ValueError:
            continue

        block_number = None
        m = re.search(r"#(\d+)", line)
        if m:
            block_number = int(m.group(1))
            last_block_number = max(last_block_number, block_number)

        blocks[name] = {
            "x": x,
            "y": y,
            "subblk": subblk,
            "layer": layer,
            "line_index": idx,
            "block_number": block_number,
            "raw": line,
        }

        key = (x, y, subblk, layer)
        occupied[key] = name

    return lines, blocks, occupied, last_block_number


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in-place", required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--out-place", required=True)
    ap.add_argument("--report", required=True)
    args = ap.parse_args()

    in_place = Path(args.in_place)
    candidate_path = Path(args.candidate)
    out_place = Path(args.out_place)
    report_path = Path(args.report)

    if not in_place.exists() or in_place.stat().st_size == 0:
        fail(f"Input .place ontbreekt of is leeg: {in_place}")

    if not candidate_path.exists() or candidate_path.stat().st_size == 0:
        fail(f"Candidate JSON ontbreekt of is leeg: {candidate_path}")

    with open(candidate_path, "r", encoding="utf-8") as f:
        cand = json.load(f)

    if cand.get("status") != "OK":
        fail("Candidate status is niet OK")

    buffer_block = cand["buffer_block"]
    loc = cand["buffer_location"]

    x = int(loc["x"])
    y = int(loc["y"])
    subblk = int(loc["subblk"])
    layer = int(loc["layer"])

    lines, blocks, occupied, last_block_number = parse_place(in_place)

    if buffer_block in blocks:
        fail(f"Buffer block staat al in .place: {buffer_block}")

    key = (x, y, subblk, layer)

    if key in occupied:
        fail(
            f"Gekozen locatie is bezet: "
            f"x={x}, y={y}, subblk={subblk}, layer={layer} door {occupied[key]}"
        )

    new_block_number = last_block_number + 1

    new_line = f"{buffer_block} {x} {y} {subblk} {layer} #{new_block_number}"
    patched_lines = list(lines)

    # Voeg toe op het einde van de place-lijst.
    # Dat is veilig zolang alle bestaande regels behouden blijven.
    patched_lines.append(new_line)

    out_place.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_place, "w", encoding="utf-8") as f:
        for line in patched_lines:
            f.write(line + "\n")

    report = {
        "status": "OK",
        "input_place": str(in_place),
        "output_place": str(out_place),
        "candidate": str(candidate_path),
        "buffer_block": buffer_block,
        "buffer_location": {
            "x": x,
            "y": y,
            "subblk": subblk,
            "layer": layer,
        },
        "new_block_number": new_block_number,
        "num_blocks_before": len(blocks),
        "num_blocks_after": len(blocks) + 1,
        "added_line": new_line,
    }

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    ok(f".place gepatcht: {out_place}")
    ok(f"Report geschreven: {report_path}")
    ok(f"Toegevoegd: {new_line}")


if __name__ == "__main__":
    main()
