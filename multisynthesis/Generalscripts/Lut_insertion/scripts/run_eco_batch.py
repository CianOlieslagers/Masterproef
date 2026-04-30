#!/usr/bin/env python3
import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import yaml
except ImportError:
    print("[FAIL] PyYAML ontbreekt. Installeer met: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


# ============================================================
# Basic helpers
# ============================================================

def fail(msg):
    print(f"[FAIL] {msg}", file=sys.stderr)
    sys.exit(1)


def ok(msg):
    print(f"[OK] {msg}")


def info(msg):
    print(f"[INFO] {msg}")


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def ensure_file(path, label):
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        fail(f"{label} ontbreekt of is leeg: {path}")
    return path


def run_cmd(cmd, cwd, log_path, allow_fail=False):
    cwd = Path(cwd)
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    with open(log_path, "w", encoding="utf-8") as log:
        p = subprocess.run(
            cmd,
            cwd=str(cwd),
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )

    if p.returncode != 0 and not allow_fail:
        print(f"[FAIL] Command faalde met exitcode {p.returncode}")
        print(f"[FAIL] Log: {log_path}")
        try:
            print(log_path.read_text(encoding="utf-8", errors="replace")[-4000:])
        except Exception:
            pass
        sys.exit(p.returncode)

    return p.returncode


def rel_or_abs(root, p):
    p = Path(p)
    if p.is_absolute():
        return p
    return Path(root) / p


def copy_config(config_path, run_root):
    shutil.copy2(config_path, Path(run_root) / "config.yaml")


# ============================================================
# Parsers
# ============================================================

def parse_place(path):
    blocks = {}
    occupied = {}
    array_size = None
    header_lines = []

    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            s = line.strip()

            if line_no <= 5:
                header_lines.append(line.rstrip("\n"))

            if s.startswith("Array size:"):
                m = re.search(r"Array size:\s+(\d+)\s+x\s+(\d+)", s)
                if m:
                    array_size = (int(m.group(1)), int(m.group(2)))
                continue

            if not s or s.startswith("#") or s.startswith("Netlist_File:"):
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
                fail(f"Ongeldige .place regel {line_no}: {line.rstrip()}")

            if name in blocks:
                fail(f"Dubbele blocknaam in .place: {name}")

            key = (x, y, subblk, layer)
            if key in occupied:
                fail(f"Dubbele locatie in .place: {key}: {occupied[key]} en {name}")

            blocks[name] = {
                "x": x,
                "y": y,
                "subblk": subblk,
                "layer": layer,
                "line": line_no,
            }
            occupied[key] = name

    if array_size is None:
        fail(f"Kon Array size niet lezen uit {path}")

    return blocks, occupied, array_size, header_lines


def parse_blif(path):
    blocks = {}
    inputs = []
    outputs = []

    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        s = lines[i].strip()

        if not s or s.startswith("#"):
            i += 1
            continue

        if s.startswith(".inputs"):
            inputs.extend(s.split()[1:])
            i += 1
            continue

        if s.startswith(".outputs"):
            outputs.extend(s.split()[1:])
            i += 1
            continue

        if s.startswith(".names"):
            parts = s.split()
            out = parts[-1]
            ins = parts[1:-1]

            table = []
            j = i + 1
            while j < len(lines):
                sj = lines[j].strip()
                if sj.startswith("."):
                    break
                table.append(lines[j])
                j += 1

            if out in blocks:
                fail(f"Dubbele .names-output in BLIF: {out}")

            blocks[out] = {
                "inputs": ins,
                "table": table,
                "start": i,
                "end": j,
                "header": lines[i],
            }

            i = j
            continue

        i += 1

    return {
        "inputs": inputs,
        "outputs": outputs,
        "blocks": blocks,
        "lines": lines,
    }


def parse_net_top_blocks(path):
    tree = ET.parse(path)
    root = tree.getroot()

    blocks = {}
    for child in root:
        if child.tag != "block":
            continue

        name = child.attrib.get("name")
        instance = child.attrib.get("instance")

        inputs_I = []
        outputs_O = []
        primitive_outputs = []

        inputs_node = child.find("inputs")
        if inputs_node is not None:
            for port in inputs_node.findall("port"):
                if port.attrib.get("name") == "I" and port.text:
                    inputs_I = port.text.split()

        outputs_node = child.find("outputs")
        if outputs_node is not None:
            for port in outputs_node.findall("port"):
                if port.attrib.get("name") == "O" and port.text:
                    outputs_O = port.text.split()

        for elem in child.iter("block"):
            if elem.attrib.get("instance") == "lut[0]":
                out_node = elem.find("outputs")
                if out_node is not None:
                    for port in out_node.findall("port"):
                        if port.attrib.get("name") == "out" and port.text:
                            primitive_outputs = port.text.split()

        blocks[name] = {
            "instance": instance,
            "inputs_I": inputs_I,
            "outputs_O": outputs_O,
            "primitive_outputs": primitive_outputs,
        }

    return blocks


def read_connection_csv(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows

def write_timing_rows_csv(path, baseline_rows, patched_rows):
    """
    Schrijft de volledige gerapporteerde timingpaden weg.
    Let op: dit zijn de paden die VPR rapporteert in report_timing.setup.rpt.
    """
    path = Path(path)

    with open(path, "w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "variant",
            "step",
            "node",
            "incremental_delay_ns",
            "arrival_ns",
        ]

        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for i, r in enumerate(baseline_rows):
            writer.writerow({
                "variant": "baseline",
                "step": i,
                "node": r["node"],
                "incremental_delay_ns": r["incr_ns"],
                "arrival_ns": r["arrival_ns"],
            })

        for i, r in enumerate(patched_rows):
            writer.writerow({
                "variant": "patched",
                "step": i,
                "node": r["node"],
                "incremental_delay_ns": r["incr_ns"],
                "arrival_ns": r["arrival_ns"],
            })


def write_timing_compare_json(path, candidate, baseline_global, patched_global, baseline_rows, patched_rows, local_base, local_patch):
    """
    Schrijft een volledige timingvergelijking per iteratie.
    Dit is nuttiger dan alles in summary.csv te proppen.
    """
    path = Path(path)

    data = {
        "candidate": {
            "source": candidate["source_block"],
            "sink": candidate["sink_block"],
            "eco_block": candidate["buffer_block"],
            "direct_manhattan": candidate["buffer_location"]["direct_manhattan"],
            "split_manhattan": candidate["buffer_location"]["split_total_manhattan"],
            "extra_manhattan": candidate["buffer_location"]["extra_manhattan"],
            "buffer_strategy": candidate["buffer_location"].get("strategy"),
            "buffer_location": candidate["buffer_location"],
        },
        "global_timing": {
            "baseline": baseline_global,
            "patched": patched_global,
            "delta": {
                "cpd_ns": (
                    patched_global.get("cpd_ns") - baseline_global.get("cpd_ns")
                    if patched_global.get("cpd_ns") is not None and baseline_global.get("cpd_ns") is not None
                    else None
                ),
                "fmax_mhz": (
                    patched_global.get("fmax_mhz") - baseline_global.get("fmax_mhz")
                    if patched_global.get("fmax_mhz") is not None and baseline_global.get("fmax_mhz") is not None
                    else None
                ),
                "swns_ns": (
                    patched_global.get("swns_ns") - baseline_global.get("swns_ns")
                    if patched_global.get("swns_ns") is not None and baseline_global.get("swns_ns") is not None
                    else None
                ),
            }
        },
        "local_connection_timing": {
            "baseline": local_base,
            "patched": local_patch,
            "delta_ns": (
                local_patch.get("direct_or_total_delay_ns") - local_base.get("direct_or_total_delay_ns")
                if local_patch.get("direct_or_total_delay_ns") is not None and local_base.get("direct_or_total_delay_ns") is not None
                else None
            )
        },
        "reported_timing_paths": {
            "baseline": baseline_rows,
            "patched": patched_rows,
        }
    }

    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ============================================================
# Candidate selection
# ============================================================

def manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def spiral_offsets(max_radius):
    """
    Square spiral offsets:
      (0,0)
      (0,1), (1,1), (1,0), (1,-1), ...
    """
    yield (0, 0)

    for r in range(1, max_radius + 1):
        # start boven het centrum
        x, y = 0, r
        yield (x, y)

        # rechts
        for x in range(1, r + 1):
            yield (x, r)

        # naar beneden
        for y in range(r - 1, -r - 1, -1):
            yield (r, y)

        # naar links
        for x in range(r - 1, -r - 1, -1):
            yield (x, -r)

        # naar boven
        for y in range(-r + 1, r + 1):
            yield (-r, y)


def find_free_buffer_location(src_xy, dst_xy, occupied, array_size, max_extra, search_radius, allow_spiral_fallback=True, spiral_max_radius=80):
    """
    Eerst: normale lokale zoekstrategie met max_extra_manhattan.
    Daarna: spiral fallback vanaf het geometrische midden, zonder max_extra beperking.

    Resultaat bevat altijd:
      strategy
      direct_manhattan
      split_total_manhattan
      extra_manhattan
    """
    width, height = array_size
    direct = manhattan(src_xy, dst_xy)

    mid_x = round((src_xy[0] + dst_xy[0]) / 2)
    mid_y = round((src_xy[1] + dst_xy[1]) / 2)

    def valid_free_location(x, y):
        # Vermijd IO-rand en buiten FPGA.
        if x < 1 or x > width - 2:
            return False
        if y < 1 or y > height - 2:
            return False

        key = (x, y, 0, 0)
        return key not in occupied

    def make_loc(x, y, strategy):
        d1 = manhattan(src_xy, (x, y))
        d2 = manhattan((x, y), dst_xy)
        total = d1 + d2
        extra = total - direct

        return {
            "x": x,
            "y": y,
            "subblk": 0,
            "layer": 0,
            "source_to_buffer_manhattan": d1,
            "buffer_to_sink_manhattan": d2,
            "split_total_manhattan": total,
            "direct_manhattan": direct,
            "extra_manhattan": extra,
            "balance": abs(d1 - d2),
            "midpoint_distance": manhattan((x, y), (mid_x, mid_y)),
            "strategy": strategy,
        }

    # --------------------------------------------------------
    # 1. Eerst: bounded search met max_extra_manhattan
    # --------------------------------------------------------

    candidates = []

    min_x = max(1, min(src_xy[0], dst_xy[0]) - search_radius)
    max_x = min(width - 2, max(src_xy[0], dst_xy[0]) + search_radius)
    min_y = max(1, min(src_xy[1], dst_xy[1]) - search_radius)
    max_y = min(height - 2, max(src_xy[1], dst_xy[1]) + search_radius)

    for x in range(min_x, max_x + 1):
        for y in range(min_y, max_y + 1):
            if not valid_free_location(x, y):
                continue

            loc = make_loc(x, y, "bounded_search")

            if loc["extra_manhattan"] <= max_extra:
                candidates.append(loc)

    if candidates:
        candidates.sort(key=lambda c: (
            c["extra_manhattan"],
            c["midpoint_distance"],
            c["balance"],
            c["x"],
            c["y"],
        ))
        return candidates[0]

    # --------------------------------------------------------
    # 2. Fallback: spiral vanaf midpoint
    # --------------------------------------------------------

    if not allow_spiral_fallback:
        return None

    for dx, dy in spiral_offsets(spiral_max_radius):
        x = mid_x + dx
        y = mid_y + dy

        if not valid_free_location(x, y):
            continue

        return make_loc(x, y, "spiral_fallback")

    return None

def build_candidate(row, iteration, base_blif, base_net, base_place, cfg):
    src = row["src"]
    dst = row["dst"]

    blif = parse_blif(base_blif)
    net_blocks = parse_net_top_blocks(base_net)
    place_blocks, occupied, array_size, _ = parse_place(base_place)

    reasons = []

    if not src.startswith("LUT_"):
        reasons.append("source is geen LUT")
    if not dst.startswith("LUT_"):
        reasons.append("sink is geen LUT")
    if src not in blif["blocks"]:
        reasons.append("source ontbreekt als BLIF-output")
    if dst not in blif["blocks"]:
        reasons.append("sink ontbreekt als BLIF-output")
    if src not in net_blocks:
        reasons.append("source ontbreekt in .net")
    if dst not in net_blocks:
        reasons.append("sink ontbreekt in .net")
    if src not in place_blocks:
        reasons.append("source ontbreekt in .place")
    if dst not in place_blocks:
        reasons.append("sink ontbreekt in .place")

    if dst in blif["blocks"] and src not in blif["blocks"][dst]["inputs"]:
        reasons.append("sink gebruikt source niet in BLIF")
    if dst in net_blocks and src not in net_blocks[dst]["inputs_I"]:
        reasons.append("sink gebruikt source niet in .net I-port")

    if reasons:
        return None, reasons

    src_xy = (place_blocks[src]["x"], place_blocks[src]["y"])
    dst_xy = (place_blocks[dst]["x"], place_blocks[dst]["y"])

    loc = find_free_buffer_location(
    src_xy,
    dst_xy,
    occupied,
    array_size,
    max_extra=cfg["selection"].get("max_extra_manhattan", 4),
    search_radius=cfg["selection"].get("search_radius", 8),
    allow_spiral_fallback=cfg["selection"].get("allow_spiral_fallback", True),
    spiral_max_radius=cfg["selection"].get("spiral_max_radius", 80),
    )

    if loc is None:
        return None, ["geen vrije bufferlocatie gevonden"]

    buffer_block = f"ECO_INV_{iteration:03d}_{src}_TO_{dst}"
    buffer_net = buffer_block

    cand = {
        "status": "OK",
        "iteration": iteration,
        "rank": int(row["rank"]),
        "source_block": src,
        "sink_block": dst,
        "old_net": src,
        "buffer_block": buffer_block,
        "buffer_net": buffer_net,
        "source": {
            "x": src_xy[0],
            "y": src_xy[1],
            "subblk": place_blocks[src]["subblk"],
            "layer": place_blocks[src]["layer"],
        },
        "sink": {
            "x": dst_xy[0],
            "y": dst_xy[1],
            "subblk": place_blocks[dst]["subblk"],
            "layer": place_blocks[dst]["layer"],
        },
        "buffer_location": loc,
        "csv": row,
    }

    return cand, []


# ============================================================
# BLIF inverter patch
# ============================================================

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
        fail(f"Onbekend truth-table teken: {chars[bit_index]} in {pattern}")

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
        if len(parts) < 2:
            fail(f"Truth-table lijn niet ondersteund: {raw}")

        pattern = parts[0]
        out_val = parts[1]

        new_pattern = flip_pattern_bit(pattern, input_index)
        new_lines.append(f"{new_pattern} {out_val}\n")

    return new_lines


def patch_blif_inverter(base_blif, candidate, out_blif, report_path):
    parsed = parse_blif(base_blif)
    lines = parsed["lines"]
    blocks = parsed["blocks"]

    old_net = candidate["old_net"]
    sink = candidate["sink_block"]
    buffer_net = candidate["buffer_net"]

    if sink not in blocks:
        fail(f"sink ontbreekt in BLIF: {sink}")

    sink_block = blocks[sink]

    if old_net not in sink_block["inputs"]:
        fail(f"{old_net} zit niet in sink-inputs van {sink}")

    input_index = sink_block["inputs"].index(old_net)

    new_inputs = [
        buffer_net if x == old_net else x
        for x in sink_block["inputs"]
    ]

    new_header = ".names " + " ".join(new_inputs + [sink]) + "\n"
    new_table = flip_truth_table_input(sink_block["table"], input_index)

    inverter_lines = [
        f".names {old_net} {buffer_net}\n",
        "0 1\n",
    ]

    patched = []
    start = sink_block["start"]
    end = sink_block["end"]

    for idx, line in enumerate(lines):
        if idx == start:
            patched.extend(inverter_lines)
            patched.append(new_header)
            patched.extend(new_table)
        elif start < idx < end:
            continue
        else:
            patched.append(line)

    out_blif = Path(out_blif)
    out_blif.parent.mkdir(parents=True, exist_ok=True)
    out_blif.write_text("".join(patched), encoding="utf-8")

    report = {
        "status": "OK",
        "mode": "inverter_compensated",
        "old_net": old_net,
        "buffer_net": buffer_net,
        "sink_block": sink,
        "old_input_index_in_sink": input_index,
        "sink_inputs_before": sink_block["inputs"],
        "sink_inputs_after": new_inputs,
        "sink_table_before": [x.rstrip("\n") for x in sink_block["table"]],
        "sink_table_after": [x.rstrip("\n") for x in new_table],
        "inserted_inverter": [
            f".names {old_net} {buffer_net}",
            "0 1"
        ],
    }

    Path(report_path).write_text(json.dumps(report, indent=2), encoding="utf-8")


# ============================================================
# Equivalence check
# ============================================================

def run_equivalence(base_blif, patched_blif, work_dir, cfg):
    work_dir = Path(work_dir)
    abc = cfg["tools"]["abc_bin"]
    equiv = cfg["tools"]["mt_aig_equiv_bin"]

    base_aig = work_dir / "base_from_blif.aig"
    patched_aig = work_dir / "patched_from_blif.aig"

    run_cmd(
        [
            abc,
            "-c",
            f"read_blif {base_blif}; strash; write_aiger {base_aig};"
        ],
        cwd=work_dir,
        log_path=work_dir / "abc_base.log",
    )

    run_cmd(
        [
            abc,
            "-c",
            f"read_blif {patched_blif}; strash; write_aiger {patched_aig};"
        ],
        cwd=work_dir,
        log_path=work_dir / "abc_patched.log",
    )

    rc = run_cmd(
        [equiv, str(base_aig), str(patched_aig)],
        cwd=work_dir,
        log_path=work_dir / "equiv.log",
        allow_fail=True,
    )

    return rc == 0


# ============================================================
# VPR pack / route
# ============================================================

def run_vpr_pack(patched_blif, pack_dir, cfg):
    pack_dir = Path(pack_dir)
    pack_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        cfg["tools"]["vpr_bin"],
        cfg["tools"]["arch_xml"],
        str(patched_blif),
        "--pack",
        "--route_chan_width",
        str(cfg["experiment"].get("route_chan_width", 100)),
        "--echo_file",
        "on",
    ]

    run_cmd(cmd, cwd=pack_dir, log_path=pack_dir / "pack.log")

    nets = sorted(pack_dir.glob("*.net"))
    if not nets:
        fail(f"VPR pack maakte geen .net in {pack_dir}")

    # Neem de grootste/meest recente .net; normaal is er maar één.
    nets.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return nets[0]


def patch_place_with_buffer(base_place, candidate, out_place):
    lines = Path(base_place).read_text(encoding="utf-8").splitlines()
    blocks, occupied, _, _ = parse_place(base_place)

    b = candidate["buffer_block"]
    loc = candidate["buffer_location"]
    x = int(loc["x"])
    y = int(loc["y"])
    subblk = int(loc["subblk"])
    layer = int(loc["layer"])

    if b in blocks:
        fail(f"buffer staat al in .place: {b}")

    key = (x, y, subblk, layer)
    if key in occupied:
        fail(f"bufferlocatie bezet: {key} door {occupied[key]}")

    max_no = -1
    for line in lines:
        m = re.search(r"#(\d+)", line)
        if m:
            max_no = max(max_no, int(m.group(1)))

    new_line = f"{b} {x} {y} {subblk} {layer} #{max_no + 1}"

    out_place = Path(out_place)
    out_place.parent.mkdir(parents=True, exist_ok=True)
    out_place.write_text("\n".join(lines + [new_line]) + "\n", encoding="utf-8")


def check_net_place_match(net, place, candidate):
    net_blocks = parse_net_top_blocks(net)
    place_blocks, _, _, _ = parse_place(place)

    net_names = set(net_blocks)
    place_names = set(place_blocks)

    if net_names != place_names:
        return False, {
            "missing_in_place": sorted(net_names - place_names),
            "extra_in_place": sorted(place_names - net_names),
        }

    b = candidate["buffer_block"]
    if b not in net_names or b not in place_names:
        return False, {"reason": "buffer ontbreekt in net of place"}

    return True, {}


def run_vpr_route(blif, net, place, route_dir, route_name, cfg):
    route_dir = Path(route_dir)
    route_dir.mkdir(parents=True, exist_ok=True)

    route_file = route_dir / route_name
    log_file = route_dir / "route.log"

    cmd = [
        cfg["tools"]["vpr_bin"],
        cfg["tools"]["arch_xml"],
        str(blif),
        "--route",
        "--verify_file_digests",
        "off",
        "--net_file",
        str(net),
        "--place_file",
        str(place),
        "--route_file",
        str(route_file),
        "--route_chan_width",
        str(cfg["experiment"].get("route_chan_width", 100)),
        "--echo_file",
        "on",
    ]

    if cfg["experiment"].get("timing_report_npaths") is not None:
        cmd.extend(["--timing_report_npaths", str(cfg["experiment"]["timing_report_npaths"])])

    rc = run_cmd(cmd, cwd=route_dir, log_path=log_file, allow_fail=True)

    success = (
        rc == 0
        and route_file.exists()
        and route_file.stat().st_size > 0
    )

    return success, route_file, log_file


# ============================================================
# Timing parsing
# ============================================================

def extract_global_timing(log_path):
    txt = Path(log_path).read_text(encoding="utf-8", errors="replace")

    cpd = None
    fmax = None
    swns = None
    stns = None

    m = re.search(r"Final critical path delay \(least slack\):\s+([0-9.]+)\s+ns,\s+Fmax:\s+([0-9.]+)\s+MHz", txt)
    if m:
        cpd = float(m.group(1))
        fmax = float(m.group(2))

    m = re.search(r"Final setup Worst Negative Slack \(sWNS\):\s+(-?[0-9.]+)\s+ns", txt)
    if m:
        swns = float(m.group(1))

    m = re.search(r"Final setup Total Negative Slack \(sTNS\):\s+(-?[0-9.]+)\s+ns", txt)
    if m:
        stns = float(m.group(1))

    return {
        "cpd_ns": cpd,
        "fmax_mhz": fmax,
        "swns_ns": swns,
        "stns_ns": stns,
    }


def extract_timing_rows(rpt_path):
    rpt_path = Path(rpt_path)
    if not rpt_path.exists():
        return []

    rows = []
    pattern = re.compile(r"^\s*(\S.*?\))\s+(-?[0-9.]+)\s+(-?[0-9.]+)\s*$")

    for line in rpt_path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = pattern.match(line)
        if not m:
            continue

        rows.append({
            "node": m.group(1).strip(),
            "incr_ns": float(m.group(2)),
            "arrival_ns": float(m.group(3)),
        })

    return rows


def find_exact_node(rows, block, pin_kind):
    prefix = block + "." + pin_kind

    for r in rows:
        node_token = r["node"].split()[0]
        if node_token.startswith(prefix + "["):
            return r

    return None


def compute_local_delay_from_report(rows, src, sink, eco=None):
    src_out = find_exact_node(rows, src, "out")
    sink_in = find_exact_node(rows, sink, "in")

    result = {
        "available": False,
        "source_out_arrival": None,
        "sink_in_arrival": None,
        "direct_or_total_delay_ns": None,
    }

    if src_out and sink_in:
        result["available"] = True
        result["source_out_arrival"] = src_out["arrival_ns"]
        result["sink_in_arrival"] = sink_in["arrival_ns"]
        result["direct_or_total_delay_ns"] = sink_in["arrival_ns"] - src_out["arrival_ns"]

    if eco:
        eco_in = find_exact_node(rows, eco, "in")
        eco_out = find_exact_node(rows, eco, "out")

        result["eco_source_to_in_ns"] = None
        result["eco_lut_delay_ns"] = None
        result["eco_out_to_sink_ns"] = None

        if src_out and eco_in:
            result["eco_source_to_in_ns"] = eco_in["arrival_ns"] - src_out["arrival_ns"]
        if eco_in and eco_out:
            result["eco_lut_delay_ns"] = eco_out["arrival_ns"] - eco_in["arrival_ns"]
        if eco_out and sink_in:
            result["eco_out_to_sink_ns"] = sink_in["arrival_ns"] - eco_out["arrival_ns"]

    return result


def copy_timing_reports(route_dir, iter_dir):
    for name in [
        "report_timing.setup.rpt",
        "report_timing.hold.rpt",
        "report_unconstrained_timing.setup.rpt",
        "report_unconstrained_timing.hold.rpt",
    ]:
        src = Path(route_dir) / name
        if src.exists():
            shutil.copy2(src, Path(iter_dir) / name)


# ============================================================
# Summary writing
# ============================================================

SUMMARY_FIELDS = [
    "iteration",
    "rank",
    "source",
    "sink",
    "eco_block",
    "status",
    "mode_cumulative",
    "route_policy",
    "direct_manhattan",
    "split_manhattan",
    "extra_manhattan",
    "buffer_strategy",
    "baseline_cpd_ns",
    "patched_cpd_ns",
    "delta_cpd_ns",
    "baseline_fmax_mhz",
    "patched_fmax_mhz",
    "delta_fmax_mhz",
    "baseline_swns_ns",
    "patched_swns_ns",
    "local_baseline_delay_ns",
    "local_patched_delay_ns",
    "local_delta_ns",
    "route_success",
    "equiv_success",
    "notes",
]


def write_summary_csv(path, rows):
    path = Path(path)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k) for k in SUMMARY_FIELDS})


# ============================================================
# Main experiment loop
# ============================================================

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()

    cfg = load_yaml(args.config)

    eco_root = Path(cfg["design"]["eco_root"])
    run_name = cfg["outputs"]["run_name"]
    run_root = eco_root / "eco_batch_runs" / run_name

    if run_root.exists():
        if cfg["outputs"].get("overwrite", False):
            shutil.rmtree(run_root)
        else:
            fail(f"Run-map bestaat al: {run_root}")

    run_root.mkdir(parents=True, exist_ok=True)
    copy_config(args.config, run_root)

    baseline_blif = ensure_file(rel_or_abs(eco_root, cfg["inputs"]["baseline_blif"]), "baseline_blif")
    baseline_net = ensure_file(rel_or_abs(eco_root, cfg["inputs"]["baseline_net"]), "baseline_net")
    baseline_place = ensure_file(rel_or_abs(eco_root, cfg["inputs"]["baseline_place"]), "baseline_place")
    baseline_log = ensure_file(rel_or_abs(eco_root, cfg["inputs"]["baseline_route_log"]), "baseline_route_log")
    baseline_rpt = ensure_file(rel_or_abs(eco_root, cfg["inputs"]["baseline_timing_rpt"]), "baseline_timing_rpt")
    top_csv = ensure_file(rel_or_abs(eco_root, cfg["inputs"]["top_connections_csv"]), "top_connections_csv")

    cumulative = bool(cfg["experiment"].get("cumulative", False))
    route_policy = cfg["experiment"].get("route_policy", "per_iteration")

    if route_policy == "final_only" and not cumulative:
        fail("route_policy='final_only' is niet zinvol met cumulative=false. Gebruik cumulative=true of route_policy='per_iteration'.")

    rows = read_connection_csv(top_csv)
    max_n = int(cfg["experiment"].get("max_connections", len(rows)))
    rows = rows[:min(max_n, len(rows))]

    info(f"Aantal CSV-kandidaten beschikbaar voor deze run: {len(rows)}")

    summary = []
    summary_json = []

    current_blif = baseline_blif
    current_net = baseline_net
    current_place = baseline_place
    current_log = baseline_log
    current_rpt = baseline_rpt

    baseline_global_original = extract_global_timing(baseline_log)

    for idx, row in enumerate(rows, start=1):
        iter_dir = run_root / f"iter_{idx:03d}"
        iter_dir.mkdir(parents=True, exist_ok=True)

        info(f"=== Iteratie {idx}: {row.get('src')} -> {row.get('dst')} ===")

        candidate, reject_reasons = build_candidate(
            row,
            iteration=idx,
            base_blif=current_blif if cumulative else baseline_blif,
            base_net=current_net if cumulative else baseline_net,
            base_place=current_place if cumulative else baseline_place,
            cfg=cfg,
        )

        if candidate is None:
            result = {
                "iteration": idx,
                "rank": row.get("rank"),
                "source": row.get("src"),
                "sink": row.get("dst"),
                "eco_block": None,
                "status": "SKIPPED",
                "mode_cumulative": cumulative,
                "route_policy": route_policy,
                "route_success": False,
                "equiv_success": False,
                "notes": "; ".join(reject_reasons),
                "buffer_strategy": candidate["buffer_location"].get("strategy"),
            }
            summary.append(result)
            summary_json.append(result)
            continue

        cand_path = iter_dir / "candidate.json"
        cand_path.write_text(json.dumps(candidate, indent=2), encoding="utf-8")

        base_blif_for_iter = current_blif if cumulative else baseline_blif
        base_net_for_iter = current_net if cumulative else baseline_net
        base_place_for_iter = current_place if cumulative else baseline_place
        base_log_for_iter = current_log if cumulative else baseline_log
        base_rpt_for_iter = current_rpt if cumulative else baseline_rpt

        patched_blif = iter_dir / "patched.blif"
        patch_report = iter_dir / "patch_blif_report.json"

        patch_blif_inverter(
            base_blif_for_iter,
            candidate,
            patched_blif,
            patch_report,
        )

        equiv_success = run_equivalence(
            base_blif_for_iter,
            patched_blif,
            iter_dir,
            cfg,
        )

        if not equiv_success:
            result = {
                "iteration": idx,
                "rank": candidate["rank"],
                "source": candidate["source_block"],
                "sink": candidate["sink_block"],
                "eco_block": candidate["buffer_block"],
                "status": "FAILED_EQUIV",
                "mode_cumulative": cumulative,
                "route_policy": route_policy,
                "direct_manhattan": candidate["buffer_location"]["direct_manhattan"],
                "split_manhattan": candidate["buffer_location"]["split_total_manhattan"],
                "buffer_strategy": candidate["buffer_location"].get("strategy"),                
                "extra_manhattan": candidate["buffer_location"]["extra_manhattan"],
                "baseline_cpd_ns": baseline_global.get("cpd_ns"),
                "route_success": False,
                "equiv_success": False,
                "notes": "Equivalentiecheck faalde",
                "buffer_strategy": candidate["buffer_location"].get("strategy"),
            }
            summary.append(result)
            summary_json.append(result)
            continue

        pack_dir = iter_dir / "pack"
        packed_net = run_vpr_pack(patched_blif, pack_dir, cfg)

        patched_place = iter_dir / "patched.place"
        patch_place_with_buffer(base_place_for_iter, candidate, patched_place)

        match_ok, match_info = check_net_place_match(packed_net, patched_place, candidate)
        if not match_ok:
            result = {
                "iteration": idx,
                "rank": candidate["rank"],
                "source": candidate["source_block"],
                "sink": candidate["sink_block"],
                "eco_block": candidate["buffer_block"],
                "status": "FAILED_NET_PLACE_MATCH",
                "mode_cumulative": cumulative,
                "route_policy": route_policy,
                "direct_manhattan": candidate["buffer_location"]["direct_manhattan"],
                "split_manhattan": candidate["buffer_location"]["split_total_manhattan"],
                "extra_manhattan": candidate["buffer_location"]["extra_manhattan"],
                "route_success": False,
                "equiv_success": equiv_success,
                "notes": json.dumps(match_info),
            }
            summary.append(result)
            summary_json.append(result)
            continue

        route_success = False
        patched_global = {}
        local_base = {}
        local_patch = {}
        route_log = None
        patched_rpt = None

        should_route = route_policy == "per_iteration"

        if should_route:
            route_dir = iter_dir / "route"
            route_success, route_file, route_log = run_vpr_route(
                patched_blif,
                packed_net,
                patched_place,
                route_dir,
                "patched.route",
                cfg,
            )

            if route_success:
                copy_timing_reports(route_dir, iter_dir)
                patched_rpt = route_dir / "report_timing.setup.rpt"

                patched_global = extract_global_timing(route_log)
                baseline_global_for_timing = extract_global_timing(base_log_for_iter)

                base_rows = extract_timing_rows(base_rpt_for_iter)
                patch_rows = extract_timing_rows(patched_rpt)

                local_base = compute_local_delay_from_report(
                    base_rows,
                    candidate["source_block"],
                    candidate["sink_block"],
                    eco=None,
                )

                local_patch = compute_local_delay_from_report(
                    patch_rows,
                    candidate["source_block"],
                    candidate["sink_block"],
                    eco=candidate["buffer_block"],
                )

                write_timing_rows_csv(
                    iter_dir / "timing_paths.csv",
                    base_rows,
                    patch_rows,
                )

                write_timing_compare_json(
                    iter_dir / "timing_compare.json",
                    candidate,
                    baseline_global_for_timing,
                    patched_global,
                    base_rows,
                    patch_rows,
                    local_base,
                    local_patch,
                )
        baseline_global = extract_global_timing(base_log_for_iter)

        delta_cpd = None
        delta_fmax = None
        if route_success and baseline_global.get("cpd_ns") is not None and patched_global.get("cpd_ns") is not None:
            delta_cpd = patched_global["cpd_ns"] - baseline_global["cpd_ns"]

        if route_success and baseline_global.get("fmax_mhz") is not None and patched_global.get("fmax_mhz") is not None:
            delta_fmax = patched_global["fmax_mhz"] - baseline_global["fmax_mhz"]

        local_base_delay = local_base.get("direct_or_total_delay_ns") if local_base else None
        local_patch_delay = local_patch.get("direct_or_total_delay_ns") if local_patch else None
        local_delta = None

        if local_base_delay is not None and local_patch_delay is not None:
            local_delta = local_patch_delay - local_base_delay

        status = "OK"
        if should_route and not route_success:
            status = "FAILED_ROUTE"

        result = {
            "iteration": idx,
            "rank": candidate["rank"],
            "source": candidate["source_block"],
            "sink": candidate["sink_block"],
            "eco_block": candidate["buffer_block"],
            "status": status,
            "mode_cumulative": cumulative,
            "route_policy": route_policy,
            "direct_manhattan": candidate["buffer_location"]["direct_manhattan"],
            "split_manhattan": candidate["buffer_location"]["split_total_manhattan"],
            "extra_manhattan": candidate["buffer_location"]["extra_manhattan"],
            "baseline_cpd_ns": baseline_global.get("cpd_ns"),
            "patched_cpd_ns": patched_global.get("cpd_ns") if route_success else None,
            "delta_cpd_ns": delta_cpd,
            "baseline_fmax_mhz": baseline_global.get("fmax_mhz"),
            "patched_fmax_mhz": patched_global.get("fmax_mhz") if route_success else None,
            "delta_fmax_mhz": delta_fmax,
            "baseline_swns_ns": baseline_global.get("swns_ns"),
            "patched_swns_ns": patched_global.get("swns_ns") if route_success else None,
            "local_baseline_delay_ns": local_base_delay,
            "local_patched_delay_ns": local_patch_delay,
            "local_delta_ns": local_delta,
            "route_success": route_success if should_route else None,
            "equiv_success": equiv_success,
            "notes": "",
        }

        result_path = iter_dir / "result.json"
        result_path.write_text(json.dumps({
            "candidate": candidate,
            "result": result,
            "local_base": local_base,
            "local_patch": local_patch,
            "paths": {
                "patched_blif": str(patched_blif),
                "packed_net": str(packed_net),
                "patched_place": str(patched_place),
                "route_log": str(route_log) if route_log else None,
                "patched_rpt": str(patched_rpt) if patched_rpt else None,
            }
        }, indent=2), encoding="utf-8")

        summary.append(result)
        summary_json.append(result)

        write_summary_csv(run_root / "summary.csv", summary)
        (run_root / "summary.json").write_text(json.dumps(summary_json, indent=2), encoding="utf-8")

        # Update state in cumulative mode.
        if cumulative and status == "OK":
            current_blif = patched_blif
            current_net = packed_net
            current_place = patched_place

            if route_success:
                current_log = route_log
                current_rpt = patched_rpt

    # Final-only route
    if cumulative and route_policy == "final_only":
        final_dir = run_root / "final_route"
        final_dir.mkdir(parents=True, exist_ok=True)

        route_success, route_file, route_log = run_vpr_route(
            current_blif,
            current_net,
            current_place,
            final_dir,
            "final.route",
            cfg,
        )

        final_global = extract_global_timing(route_log) if route_success else {}

        final_summary = {
            "status": "OK" if route_success else "FAILED_ROUTE",
            "route_success": route_success,
            "baseline_original": baseline_global_original,
            "final_global": final_global,
            "delta_cpd_ns": (
                final_global.get("cpd_ns") - baseline_global_original.get("cpd_ns")
                if route_success and final_global.get("cpd_ns") is not None and baseline_global_original.get("cpd_ns") is not None
                else None
            ),
            "route_file": str(route_file),
            "route_log": str(route_log),
        }

        (run_root / "final_summary.json").write_text(json.dumps(final_summary, indent=2), encoding="utf-8")

    write_summary_csv(run_root / "summary.csv", summary)
    (run_root / "summary.json").write_text(json.dumps(summary_json, indent=2), encoding="utf-8")

    ok(f"Batch run klaar: {run_root}")
    ok(f"Summary CSV : {run_root / 'summary.csv'}")
    ok(f"Summary JSON: {run_root / 'summary.json'}")


if __name__ == "__main__":
    main()
