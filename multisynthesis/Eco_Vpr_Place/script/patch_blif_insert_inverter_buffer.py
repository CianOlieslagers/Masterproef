#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path


def fail(msg):
    print(f"[FAIL] {msg}", file=sys.stderr)
    sys.exit(1)


def ok(msg):
    print(f"[OK] {msg}")


def parse_names_blocks(lines):
    blocks = []
    i = 0

    while i < len(lines):
        line = lines[i]
        s = line.strip()

        if not s.startswith(".names"):
            i += 1
            continue

        parts = s.split()
        output = parts[-1]
        inputs = parts[1:-1]

        table_lines = []
        j = i + 1

        while j < len(lines):
            sj = lines[j].strip()
            if sj.startswith("."):
                break
            table_lines.append(lines[j])
            j += 1

        blocks.append({
            "start": i,
            "end": j,
            "output": output,
            "inputs": inputs,
            "table_lines": table_lines,
            "header": line,
        })

        i = j

    return blocks


def flip_pattern_bit(pattern, bit_index):
    chars = list(pattern)

    if bit_index >= len(chars):
        fail(f"bit_index {bit_index} buiten patroon {pattern}")

    if chars[bit_index] == "0":
        chars[bit_index] = "1"
    elif chars[bit_index] == "1":
        chars[bit_index] = "0"
    elif chars[bit_index] == "-":
        chars[bit_index] = "-"
    else:
        fail(f"Onbekend teken in truth-table patroon: {chars[bit_index]}")

    return "".join(chars)


def flip_truth_table_input(table_lines, input_index):
    new_lines = []

    for line in table_lines:
        raw = line.rstrip("\n")
        s = raw.strip()

        if not s:
            new_lines.append(line)
            continue

        parts = s.split()

        if len(parts) == 1:
            # Constant LUT case, not expected here.
            fail(f"Truth-table lijn zonder outputwaarde niet ondersteund: {raw}")

        pattern = parts[0]
        out_val = parts[1]

        new_pattern = flip_pattern_bit(pattern, input_index)

        new_lines.append(f"{new_pattern} {out_val}\n")

    return new_lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in-blif", required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--out-blif", required=True)
    ap.add_argument("--report", required=True)
    args = ap.parse_args()

    in_blif = Path(args.in_blif)
    cand_path = Path(args.candidate)
    out_blif = Path(args.out_blif)
    report_path = Path(args.report)

    with open(cand_path, "r", encoding="utf-8") as f:
        cand = json.load(f)

    old_net = cand["old_net"]
    sink_block = cand["sink_block"]
    buffer_net = cand["buffer_net"]

    with open(in_blif, "r", encoding="utf-8") as f:
        lines = f.readlines()

    blocks = parse_names_blocks(lines)

    sink_blocks = [b for b in blocks if b["output"] == sink_block]

    if len(sink_blocks) != 1:
        fail(f"Verwacht exact 1 sink block {sink_block}, gevonden {len(sink_blocks)}")

    sink = sink_blocks[0]

    if old_net not in sink["inputs"]:
        fail(f"{old_net} zit niet in inputs van {sink_block}")

    old_input_index = sink["inputs"].index(old_net)

    new_sink_inputs = [
        buffer_net if x == old_net else x
        for x in sink["inputs"]
    ]

    new_sink_header = ".names " + " ".join(new_sink_inputs + [sink_block]) + "\n"

    new_sink_table = flip_truth_table_input(
        sink["table_lines"],
        old_input_index
    )

    inverter_lines = [
        f".names {old_net} {buffer_net}\n",
        "0 1\n",
    ]

    patched = []

    for idx, line in enumerate(lines):
        if idx == sink["start"]:
            patched.extend(inverter_lines)
            patched.append(new_sink_header)
            patched.extend(new_sink_table)
        elif sink["start"] < idx < sink["end"]:
            continue
        else:
            patched.append(line)

    out_blif.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_blif, "w", encoding="utf-8") as f:
        f.writelines(patched)

    report = {
        "status": "OK",
        "mode": "inverter_buffer_with_sink_truth_table_compensation",
        "old_net": old_net,
        "buffer_net": buffer_net,
        "sink_block": sink_block,
        "old_input_index_in_sink": old_input_index,
        "sink_inputs_before": sink["inputs"],
        "sink_inputs_after": new_sink_inputs,
        "sink_table_before": [x.rstrip("\n") for x in sink["table_lines"]],
        "sink_table_after": [x.rstrip("\n") for x in new_sink_table],
        "inserted_inverter": [
            f".names {old_net} {buffer_net}",
            "0 1"
        ],
    }

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    ok(f"BLIF inverter-ECO gepatcht: {out_blif}")
    ok(f"Report geschreven: {report_path}")
    ok(f"Inverter toegevoegd: {old_net} -> NOT -> {buffer_net}")
    ok(f"Sink-input index geflipt: {old_input_index}")


if __name__ == "__main__":
    main()
