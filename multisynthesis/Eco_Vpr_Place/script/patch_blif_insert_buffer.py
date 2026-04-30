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


def parse_names_outputs(lines):
    outputs = []
    names_lines = []

    for idx, line in enumerate(lines):
        s = line.strip()
        if not s.startswith(".names"):
            continue

        parts = s.split()
        if len(parts) < 2:
            fail(f"Ongeldige .names regel op lijn {idx + 1}: {line.rstrip()}")

        output = parts[-1]
        inputs = parts[1:-1]

        outputs.append(output)
        names_lines.append({
            "line_index": idx,
            "output": output,
            "inputs": inputs,
            "raw": line.rstrip("\n"),
        })

    return outputs, names_lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in-blif", required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--out-blif", required=True)
    ap.add_argument("--report", required=True)
    args = ap.parse_args()

    in_blif = Path(args.in_blif)
    candidate_path = Path(args.candidate)
    out_blif = Path(args.out_blif)
    report_path = Path(args.report)

    if not in_blif.exists() or in_blif.stat().st_size == 0:
        fail(f"Input BLIF ontbreekt of is leeg: {in_blif}")

    if not candidate_path.exists() or candidate_path.stat().st_size == 0:
        fail(f"Candidate JSON ontbreekt of is leeg: {candidate_path}")

    with open(candidate_path, "r", encoding="utf-8") as f:
        cand = json.load(f)

    if cand.get("status") != "OK":
        fail("Candidate status is niet OK")

    old_net = cand["old_net"]
    sink_block = cand["sink_block"]
    buffer_block = cand["buffer_block"]
    buffer_net = cand["buffer_net"]

    with open(in_blif, "r", encoding="utf-8") as f:
        lines = f.readlines()

    outputs_before, names_before = parse_names_outputs(lines)

    if buffer_net in outputs_before:
        fail(f"buffer_net bestaat al als .names-output in BLIF: {buffer_net}")

    sink_matches = [n for n in names_before if n["output"] == sink_block]

    if len(sink_matches) != 1:
        fail(f"Verwacht exact 1 .names-block voor sink {sink_block}, gevonden: {len(sink_matches)}")

    sink_info = sink_matches[0]
    sink_line_idx = sink_info["line_index"]
    sink_inputs_before = sink_info["inputs"]

    if old_net not in sink_inputs_before:
        fail(f"old_net {old_net} zit niet in de inputlijst van sink {sink_block}")

    replaced_inputs = [
        buffer_net if x == old_net else x
        for x in sink_inputs_before
    ]

    if replaced_inputs.count(buffer_net) != 1:
        fail("Buffer net werd niet exact één keer toegevoegd aan sink-inputs")

    new_sink_names_line = ".names " + " ".join(replaced_inputs + [sink_block]) + "\n"

    buffer_block_lines = [
        f".names {old_net} {buffer_net}\n",
        "1 1\n",
    ]

    patched = []

    for idx, line in enumerate(lines):
        if idx == sink_line_idx:
            patched.extend(buffer_block_lines)
            patched.append(new_sink_names_line)
        else:
            patched.append(line)

    outputs_after, names_after = parse_names_outputs(patched)

    if buffer_net not in outputs_after:
        fail("buffer_net is na patch niet aanwezig als .names-output")

    sink_after = [n for n in names_after if n["output"] == sink_block]
    if len(sink_after) != 1:
        fail("Sink-block bestaat na patch niet exact één keer")

    if old_net in sink_after[0]["inputs"]:
        fail("old_net zit nog steeds rechtstreeks in de sink-inputs na patch")

    if buffer_net not in sink_after[0]["inputs"]:
        fail("buffer_net zit niet in sink-inputs na patch")

    out_blif.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_blif, "w", encoding="utf-8") as f:
        f.writelines(patched)

    report = {
        "status": "OK",
        "input_blif": str(in_blif),
        "output_blif": str(out_blif),
        "candidate": str(candidate_path),
        "old_net": old_net,
        "sink_block": sink_block,
        "buffer_block": buffer_block,
        "buffer_net": buffer_net,
        "sink_inputs_before": sink_inputs_before,
        "sink_inputs_after": sink_after[0]["inputs"],
        "num_names_before": len(outputs_before),
        "num_names_after": len(outputs_after),
        "expected_num_names_after": len(outputs_before) + 1,
        "inserted_buffer_block": [
            f".names {old_net} {buffer_net}",
            "1 1"
        ],
    }

    if len(outputs_after) != len(outputs_before) + 1:
        fail("Aantal .names-blocks is niet exact met 1 gestegen")

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    ok(f"BLIF gepatcht: {out_blif}")
    ok(f"Report geschreven: {report_path}")
    ok(f"Sink voor patch: {' '.join(sink_inputs_before)} -> {sink_block}")
    ok(f"Sink na patch  : {' '.join(sink_after[0]['inputs'])} -> {sink_block}")
    ok(f"Buffer toegevoegd: {old_net} -> {buffer_net}")


if __name__ == "__main__":
    main()
