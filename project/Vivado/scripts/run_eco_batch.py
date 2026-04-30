#!/usr/bin/env python3
import csv
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from collections import Counter
import time 



def log(msg):
    print(msg, flush=True)


def expand_with_local_vars(value, local_vars):
    # Eerst shell/env variabelen
    value = os.path.expandvars(value)

    # Daarna variabelen die eerder in hetzelfde conf-bestand stonden
    for _ in range(10):  # kleine safety limit
        old_value = value
        for k, v in local_vars.items():
            value = value.replace(f"${k}", v)
            value = value.replace(f"${{{k}}}", v)
        if value == old_value:
            break
    return value

def safe_object_name(s):
    # maak namen veilig voor RapidWright-objectcreatie
    s = re.sub(r'[^A-Za-z0-9_\[\]]+', '_', s)
    s = re.sub(r'_+', '_', s).strip('_')
    return s


def has_alias_style_net(c):
    net = c.get("net") or ""
    return net.endswith("_n_0") or "_n_" in net

def is_lut_to_lut(c):
    src_t = (c.get("source_cell_type") or "").upper()
    dst_t = (c.get("sink_cell_type") or "").upper()
    return src_t.startswith("LUT") and dst_t.startswith("LUT")

def validate_candidate_via_dcp(rw_jar, scripts_dir, dcp_path, net_name, source_cell, sink_cell, sink_pin, log_path):
    cmd = [
        "java",
        "-cp", f".:{rw_jar}",
        "ValidateEcoCandidate",
        str(dcp_path),
        str(net_name),
        str(source_cell),
        str(sink_cell),
        str(sink_pin),
    ]
    code, text = run_cmd(cmd, log_path, cwd=scripts_dir)
    result = extract_result_json(text)
    if code == 0 and result is not None:
        return result, text
    return None, text

def should_skip_candidate(c):
    # Snelle metadata-filter: alleen gebruiken als de JSON deze info heeft.
    src_t = (c.get("source_cell_type") or "").upper()
    dst_t = (c.get("sink_cell_type") or "").upper()

    if src_t and not src_t.startswith("LUT"):
        return True, "SKIPPED_SOURCE_NOT_LUT_METADATA"

    if dst_t and not dst_t.startswith("LUT"):
        return True, "SKIPPED_SINK_NOT_LUT_METADATA"

    return False, None

def parse_conf(path):
    data = {}
    for raw in Path(path).read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue

        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")

        v = expand_with_local_vars(v, data)
        data[k] = v

    return data

def resolve_sink_pin_via_dcp(rw_jar, scripts_dir, dcp_path, net_name, sink_cell, log_path):
    cmd = [
        "java",
        "-cp", f".:{rw_jar}",
        "ResolveSinkPin",
        str(dcp_path),
        str(net_name),
        str(sink_cell),
    ]
    code, text = run_cmd(cmd, log_path, cwd=scripts_dir)
    result = extract_result_json(text)
    if code == 0 and result and result.get("status") == "OK":
        return result.get("sink_pin"), text
    return None, text


def candidate_is_structurally_usable(c):
    return bool(c.get("net")) and bool(c.get("sink_cell")) and bool(c.get("target_slice"))

def run_cmd(cmd, log_path, cwd=None):
    log(f"[CMD] {' '.join(map(str, cmd))}")
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )
    Path(log_path).write_text(proc.stdout)
    return proc.returncode, proc.stdout

def extract_result_json(text):
    m = re.search(r"RESULT_JSON:\s*(\{.*\})", text)
    if not m:
        return None
    return json.loads(m.group(1))


def derive_target_slice(candidate):
    # 1) expliciet target_slice
    ts = candidate.get("target_slice")
    if ts:
        return ts

    # 2) midpoint van coords
    coords = candidate.get("coords", {})
    src = coords.get("src")
    dest = coords.get("dest")

    if (
        isinstance(src, list) and len(src) == 2 and
        isinstance(dest, list) and len(dest) == 2 and
        all(isinstance(v, int) for v in src + dest)
    ):
        mx = (src[0] + dest[0]) // 2
        my = (src[1] + dest[1]) // 2
        return f"SLICE_X{mx}Y{my}"

    return None


def normalize_candidate(c, idx, default_lut_delay_ps):
    cid = str(c.get("id", f"iter_{idx:04d}"))

    net = c.get("net")
    sink_cell = c.get("sink_cell") or c.get("to_cell")
    sink_pin = c.get("sink_pin") or c.get("to_pin")
    target_slice = derive_target_slice(c)
    lut_delay_ps = float(c.get("lut_delay_ps", default_lut_delay_ps))

    # Bewaar ook de oorspronkelijke velden
    from_raw = c.get("from")
    to_raw = c.get("to")
    distance = c.get("distance")
    coords = c.get("coords", {})

    eco_ready = True
    issues = []

    if not net:
        eco_ready = False
        issues.append("missing_net")

    if not sink_cell:
        eco_ready = False
        issues.append("missing_sink_cell")

    if not target_slice:
        eco_ready = False
        issues.append("missing_target_slice")

    if not sink_pin:
        issues.append("missing_sink_pin")

    return {
        "id": cid,
        "net": net,
        "sink_cell": sink_cell,
        "sink_pin": sink_pin,
        "target_slice": target_slice,
        "lut_delay_ps": lut_delay_ps,
        "from": from_raw,
        "to": to_raw,
        "distance": distance,
        "coords": coords,
        "eco_ready": eco_ready,
        "issues": issues,

        # metadata bewaren
        "source_cell": c.get("source_cell") or from_raw,
        "source_cell_type": c.get("source_cell_type"),
        "sink_cell_type": c.get("sink_cell_type"),
        "source_site": c.get("source_site"),
        "sink_site": c.get("sink_site"),
    }

def copy_if_exists(src, dst):
    if Path(src).exists():
        shutil.copy2(src, dst)


def main():
    if len(sys.argv) != 2:
        print("Gebruik: python3 run_eco_batch.py <config.conf>")
        sys.exit(1)

    conf = parse_conf(sys.argv[1])

    required = [
        "PROJ_DIR",
        "RAPIDWRIGHT_JAR",
        "CANDIDATES_JSON",
        "BASELINE_DCP",
    ]
    for k in required:
        if k not in conf:
            raise RuntimeError(f"Ontbrekende configvariabele: {k}")

    proj_dir = Path(conf["PROJ_DIR"])
    rw_jar = conf["RAPIDWRIGHT_JAR"]
    scripts_dir = proj_dir / "Readwright" / "scripts"

    candidates_json = Path(conf["CANDIDATES_JSON"])
    baseline_dcp = Path(conf["BASELINE_DCP"])

    default_lut_delay_ps = float(conf.get("LUT_DELAY_PS", "120.0"))
    advance_on_success = conf.get("ADVANCE_ON_SUCCESS", "1") == "1"
    advance_only_if_improved = conf.get("ADVANCE_ONLY_IF_IMPROVED", "0") == "1"
    route_mode = conf.get("ROUTE_MODE", "non_timing").strip()
    soft_preserve = conf.get("SOFT_PRESERVE", "0").strip() == "1"

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    out_root = proj_dir / "results" / "run_eco_batch" / timestamp
    logs_dir = out_root / "logs"
    iters_dir = out_root / "iterations"

    out_root.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    iters_dir.mkdir(parents=True, exist_ok=True)

    baseline_original_dcp = out_root / "baseline_original.dcp"
    current_base_dcp = out_root / "current_base.dcp"
    latest_single_eval_dcp = out_root / "latest_single_eval.dcp"

    summary_csv = out_root / "summary.csv"
    summary_json = out_root / "summary.json"

    shutil.copy2(baseline_dcp, baseline_original_dcp)
    shutil.copy2(baseline_dcp, current_base_dcp)

    log("========================================")
    log("           ECO BATCH START              ")
    log("========================================")
    log(f"Config file        : {sys.argv[1]}")
    log(f"Baseline DCP       : {baseline_dcp}")
    log(f"Candidates JSON    : {candidates_json}")
    log(f"Output root        : {out_root}")
    log(f"LUT_DELAY_PS       : {default_lut_delay_ps}")
    log(f"ADVANCE_ON_SUCCESS : {advance_on_success}")
    log(f"ADV_ONLY_IF_IMPR   : {advance_only_if_improved}")
    log(f"ROUTE_MODE         : {route_mode}")
    log(f"SOFT_PRESERVE      : {soft_preserve}")
    log("========================================")

    # Java compileren
    log("[INIT] javac compileren...")
    

    javac_cmd = [
        "javac",
        "-cp", f".:{rw_jar}",
        "InsertBufferECO.java",
        "EcoDelayComparator.java",
        "ResolveSinkPin.java",
        "ValidateEcoCandidate.java",
    ]

    code, text = run_cmd(javac_cmd, logs_dir / "javac.log", cwd=scripts_dir)
    if code != 0:
        print(text)
        raise RuntimeError("javac compilatie mislukt")
    log("[INIT] javac OK")

    max_candidates_raw = conf.get("MAX_CANDIDATES", "0").strip()
    max_candidates = int(max_candidates_raw) if max_candidates_raw else 0

    candidates_raw = json.loads(candidates_json.read_text())
    candidates = [
        normalize_candidate(c, i + 1, default_lut_delay_ps)
        for i, c in enumerate(candidates_raw)
    ]

    if max_candidates > 0:
        candidates = candidates[:max_candidates]

    log(f"[INIT] totaal in JSON : {len(candidates_raw)}")
    log(f"[INIT] te verwerken   : {len(candidates)}")

    rows = []

    for i, c in enumerate(candidates, start=1):
        iter_start = time.time()

        tag = f"iter_{i:04d}"
        iter_dir = iters_dir / tag
        iter_dir.mkdir(parents=True, exist_ok=True)

        base_before_dcp = iter_dir / "base_before.dcp"
        single_eval_dcp = iter_dir / "single_eval.dcp"
        cumulative_after_dcp = iter_dir / "cumulative_after.dcp"

        insert_log = iter_dir / "insert.log"
        compare_log = iter_dir / "compare.log"
        candidate_json_path = iter_dir / "candidate.json"

        candidate_json_path.write_text(json.dumps(c, indent=2))
        shutil.copy2(current_base_dcp, base_before_dcp)

        safe_net = safe_object_name(c["net"])
        buffer_cell = f"{safe_net}_buffer_{tag}"
        split_net = f"{safe_net}_split_{tag}"

        log("")
        log("--------------------------------------------------")
        log(f"[ITER {i}/{len(candidates)}] id={c['id']}")
        log(f"  net            : {c.get('net')}")
        log(f"  from           : {c.get('from')}")
        log(f"  to             : {c.get('to')}")
        log(f"  sink_cell      : {c.get('sink_cell')}")
        log(f"  sink_pin       : {c.get('sink_pin')}")
        log(f"  target_slice   : {c.get('target_slice')}")
        log(f"  distance       : {c.get('distance')}")
        log(f"  source_type    : {c.get('source_cell_type')}")
        log(f"  sink_type      : {c.get('sink_cell_type')}")
        log(f"  alias_style_net: {has_alias_style_net(c)}")
        log(f"  is_lut_to_lut  : {is_lut_to_lut(c)}")
        log("--------------------------------------------------")

        row = {
            "iter": i,
            "id": c["id"],
            "status": "UNKNOWN",
            "eco_ready": int(bool(c["eco_ready"])),
            "issues": "|".join(c["issues"]),
            "net": c["net"],
            "from": c["from"],
            "to": c["to"],
            "sink_cell": c["sink_cell"],
            "sink_pin": c["sink_pin"],
            "target_slice": c["target_slice"],
            "distance": c["distance"],
            "buffer_cell": buffer_cell,
            "split_net": split_net,
            "lut_delay_ps": c["lut_delay_ps"],
            "advanced_baseline": 0,
            "baseline_ps": "",
            "eco_seg1_ps": "",
            "eco_seg2_ps": "",
            "eco_interconnect_ps": "",
            "eco_total_ps": "",
            "delta_interconnect_ps": "",
            "delta_total_ps": "",
            "base_before_dcp": str(base_before_dcp),
            "single_eval_dcp": str(single_eval_dcp),
            "cumulative_after_dcp": str(cumulative_after_dcp),
            "alias_style_net": int(has_alias_style_net(c)),
            "is_lut_to_lut": int(is_lut_to_lut(c)),
            "source_cell_type": c.get("source_cell_type"),
            "sink_cell_type": c.get("sink_cell_type"),
            "validated_source_type": "",
            "validated_sink_type": "",
            "validated_source_site": "",
            "validated_sink_site": "",
            "validated_source_bel": "",
            "validated_sink_bel": "",
            "validated_source_output_physical_pin": "",
            "validated_sink_physical_pin": "",
            "validated_net_physical_source": "",
            "validation_reason": "",
            "source_cell": c.get("source_cell"),
            "route_mode": route_mode,
            "soft_preserve": int(soft_preserve)}

        skip, reason = should_skip_candidate(c)
        if skip:
            row["status"] = reason
            shutil.copy2(current_base_dcp, cumulative_after_dcp)
            rows.append(row)
            log(f"[ITER {i}/{len(candidates)}] SKIP -> {reason}")
            log(f"[ITER {i}/{len(candidates)}] done in {time.time() - iter_start:.2f}s")
            continue

        if not candidate_is_structurally_usable(c):
            row["status"] = "SKIPPED_NOT_STRUCTURALLY_USABLE"
            shutil.copy2(current_base_dcp, cumulative_after_dcp)
            rows.append(row)
            log(f"[ITER {i}/{len(candidates)}] SKIP -> NOT_STRUCTURALLY_USABLE")
            log(f"[ITER {i}/{len(candidates)}] done in {time.time() - iter_start:.2f}s")
            continue

        # Probeer sink_pin dynamisch uit current_base.dcp te halen als die ontbreekt
        if not c["sink_pin"]:
            log(f"[ITER {i}/{len(candidates)}] resolving sink pin from DCP...")
            resolve_log = iter_dir / "resolve_sink_pin.log"
            resolved_pin, resolve_text = resolve_sink_pin_via_dcp(
                rw_jar=rw_jar,
                scripts_dir=scripts_dir,
                dcp_path=current_base_dcp,
                net_name=c["net"],
                sink_cell=c["sink_cell"],
                log_path=resolve_log,
            )
            if resolved_pin:
                c["sink_pin"] = resolved_pin
                row["sink_pin"] = resolved_pin
                log(f"[ITER {i}/{len(candidates)}] resolved sink pin = {resolved_pin}")
            else:
                row["status"] = "SKIPPED_SINK_PIN_UNRESOLVED"
                shutil.copy2(current_base_dcp, cumulative_after_dcp)
                rows.append(row)
                log(f"[ITER {i}/{len(candidates)}] SKIP -> SINK_PIN_UNRESOLVED")
                log(f"[ITER {i}/{len(candidates)}] done in {time.time() - iter_start:.2f}s")
                continue

        # Harde DCP-validatie: alleen echte fabric LUT->LUT kandidaten toelaten
        validate_log = iter_dir / "validate_candidate.log"
        validation_result, validation_text = validate_candidate_via_dcp(
            rw_jar=rw_jar,
            scripts_dir=scripts_dir,
            dcp_path=current_base_dcp,
            net_name=c["net"],
            source_cell=c["source_cell"],
            sink_cell=c["sink_cell"],
            sink_pin=c["sink_pin"],
            log_path=validate_log,
        )
        if validation_result is None:
            row["status"] = "SKIPPED_VALIDATION_FAILED"
            shutil.copy2(current_base_dcp, cumulative_after_dcp)
            rows.append(row)
            log(f"[ITER {i}/{len(candidates)}] SKIP -> VALIDATION_FAILED")
            log(f"[ITER {i}/{len(candidates)}] done in {time.time() - iter_start:.2f}s")
            continue

        row["validated_source_type"] = validation_result.get("source_type")
        row["validated_sink_type"] = validation_result.get("sink_type")
        row["validated_source_site"] = validation_result.get("source_site")
        row["validated_sink_site"] = validation_result.get("sink_site")
        row["validated_source_bel"] = validation_result.get("source_bel")
        row["validated_sink_bel"] = validation_result.get("sink_bel")
        row["validated_source_output_physical_pin"] = validation_result.get("source_output_physical_pin")
        row["validated_sink_physical_pin"] = validation_result.get("sink_physical_pin")
        row["validated_net_physical_source"] = validation_result.get("net_physical_source")
        row["validation_reason"] = validation_result.get("reason")
        if not validation_result.get("valid", False):
            row["status"] = f"SKIPPED_{validation_result.get('reason', 'INVALID_CANDIDATE')}"
            shutil.copy2(current_base_dcp, cumulative_after_dcp)
            rows.append(row)
            log(f"[ITER {i}/{len(candidates)}] SKIP -> {row['status']}")
            log(f"[ITER {i}/{len(candidates)}] done in {time.time() - iter_start:.2f}s")
            continue


        # 1) ECO insertion op current_base -> single_eval
        insert_cmd = [
            "java",
            "-cp", f".:{rw_jar}",
            "InsertBufferECO",
            "--mode", "commit",
            "--dcp", str(current_base_dcp),
            "--out_dcp", str(single_eval_dcp),
            "--lutB", c["sink_cell"],
            "--net", c["net"],
            "--target_slice", c["target_slice"],
            "--sink_pin", c["sink_pin"],
            "--tag", tag,
            "--buffer_name", buffer_cell,
            "--split_name", split_net,
            "--route_mode", route_mode,
            "--soft_preserve", "1" if soft_preserve else "0",
        ]        
        log(f"[ITER {i}/{len(candidates)}] running InsertBufferECO...")
        code, text = run_cmd(insert_cmd, insert_log, cwd=scripts_dir)
        if code != 0 or not single_eval_dcp.exists():
            row["status"] = "INSERT_FAILED"
            shutil.copy2(current_base_dcp, cumulative_after_dcp)
            rows.append(row)
            log(f"[ITER {i}/{len(candidates)}] INSERT_FAILED")
            log(f"[ITER {i}/{len(candidates)}] done in {time.time() - iter_start:.2f}s")
            continue

        shutil.copy2(single_eval_dcp, latest_single_eval_dcp)
        log(f"[ITER {i}/{len(candidates)}] insertion OK")

        # 2) Delay comparison
        compare_cmd = [
            "java",
            "-cp", f".:{rw_jar}",
            "EcoDelayComparator",
            str(current_base_dcp),
            str(single_eval_dcp),
            c["net"],
            split_net,
            buffer_cell,
            c["sink_cell"],
            c["sink_pin"],
            str(c["lut_delay_ps"]),
        ]
        log(f"[ITER {i}/{len(candidates)}] running EcoDelayComparator...")
        code, text = run_cmd(compare_cmd, compare_log, cwd=scripts_dir)
        if code != 0:
            row["status"] = "COMPARE_FAILED"
            shutil.copy2(current_base_dcp, cumulative_after_dcp)
            rows.append(row)
            log(f"[ITER {i}/{len(candidates)}] COMPARE_FAILED")
            log(f"[ITER {i}/{len(candidates)}] done in {time.time() - iter_start:.2f}s")
            continue

        log(f"[ITER {i}/{len(candidates)}] compare OK")

        result = extract_result_json(text)
        if result is None:
            row["status"] = "RESULT_PARSE_FAILED"
            shutil.copy2(current_base_dcp, cumulative_after_dcp)
            rows.append(row)
            log(f"[ITER {i}/{len(candidates)}] RESULT_PARSE_FAILED")
            log(f"[ITER {i}/{len(candidates)}] done in {time.time() - iter_start:.2f}s")
            continue

        row["status"] = "OK"
        row["baseline_ps"] = result["baseline_ps"]
        row["eco_seg1_ps"] = result["eco_seg1_ps"]
        row["eco_seg2_ps"] = result["eco_seg2_ps"]
        row["eco_interconnect_ps"] = result["eco_interconnect_ps"]
        row["eco_total_ps"] = result["eco_total_ps"]
        row["delta_interconnect_ps"] = result["delta_interconnect_ps"]
        row["delta_total_ps"] = result["delta_total_ps"]

        log(
            f"[ITER {i}/{len(candidates)}] RESULT "
            f"baseline_ps={row['baseline_ps']} "
            f"eco_total_ps={row['eco_total_ps']} "
            f"delta_total_ps={row['delta_total_ps']}"
        )

        should_advance = advance_on_success
        if advance_only_if_improved and float(result["delta_total_ps"]) >= 0.0:
            should_advance = False

        if should_advance:
            shutil.copy2(single_eval_dcp, current_base_dcp)
            row["advanced_baseline"] = 1

        shutil.copy2(current_base_dcp, cumulative_after_dcp)
        rows.append(row)

        log(f"[ITER {i}/{len(candidates)}] status={row['status']} advanced={row['advanced_baseline']}")
        log(f"[ITER {i}/{len(candidates)}] done in {time.time() - iter_start:.2f}s")

    fieldnames = [
        "iter",
        "id",
        "status",
        "eco_ready",
        "issues",
        "net",
        "from",
        "to",
        "sink_cell",
        "sink_pin",
        "target_slice",
        "distance",
        "buffer_cell",
        "split_net",
        "lut_delay_ps",
        "advanced_baseline",
        "baseline_ps",
        "eco_seg1_ps",
        "eco_seg2_ps",
        "eco_interconnect_ps",
        "eco_total_ps",
        "delta_interconnect_ps",
        "delta_total_ps",
        "base_before_dcp",
        "single_eval_dcp",
        "cumulative_after_dcp",
        "source_cell_type",
        "sink_cell_type",
        "alias_style_net",
        "is_lut_to_lut",
        "route_mode",
        "soft_preserve",
        "source_cell",
        "validated_source_type",
        "validated_sink_type",
        "validated_source_site",
        "validated_sink_site",
        "validated_source_bel",
        "validated_sink_bel",
        "validated_source_output_physical_pin",
        "validated_sink_physical_pin",
        "validated_net_physical_source",
        "validation_reason",
    ]

    with summary_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    summary_json.write_text(json.dumps(rows, indent=2))

    # ------------------------------
    # Globale statistieken
    # ------------------------------
    status_counter = Counter(r["status"] for r in rows)

    stats = {
        "total_candidates_seen": len(candidates_raw),
        "total_candidates_processed": len(candidates),
        "status_counts": dict(status_counter),
        "num_ok": sum(1 for r in rows if r["status"] == "OK"),
        "num_insert_failed": sum(1 for r in rows if r["status"] == "INSERT_FAILED"),
        "num_compare_failed": sum(1 for r in rows if r["status"] == "COMPARE_FAILED"),
        "num_skipped_logical_alias": sum(1 for r in rows if r["status"] == "SKIPPED_LOGICAL_ALIAS_NET"),
        "num_skipped_non_lut_to_lut": sum(1 for r in rows if r["status"] == "SKIPPED_NON_LUT_TO_LUT"),
        "num_skipped_sink_pin_unresolved": sum(1 for r in rows if r["status"] == "SKIPPED_SINK_PIN_UNRESOLVED"),
        "num_advanced_baseline": sum(1 for r in rows if int(r["advanced_baseline"]) == 1),
    }

    ok_rows = [r for r in rows if r["status"] == "OK"]

    if ok_rows:
        deltas_total = [float(r["delta_total_ps"]) for r in ok_rows]
        deltas_inter = [float(r["delta_interconnect_ps"]) for r in ok_rows]

        stats["ok_negative_total"] = sum(1 for d in deltas_total if d < 0.0)
        stats["ok_positive_total"] = sum(1 for d in deltas_total if d > 0.0)
        stats["ok_zero_total"] = sum(1 for d in deltas_total if d == 0.0)

        stats["best_total_gain_ps"] = min(deltas_total)
        stats["worst_total_gain_ps"] = max(deltas_total)
        stats["best_interconnect_gain_ps"] = min(deltas_inter)
        stats["worst_interconnect_gain_ps"] = max(deltas_inter)
    else:
        stats["ok_negative_total"] = 0
        stats["ok_positive_total"] = 0
        stats["ok_zero_total"] = 0
        stats["best_total_gain_ps"] = None
        stats["worst_total_gain_ps"] = None
        stats["best_interconnect_gain_ps"] = None
        stats["worst_interconnect_gain_ps"] = None

    summary_stats_json = out_root / "summary_stats.json"
    summary_stats_txt = out_root / "summary_stats.txt"

    summary_stats_json.write_text(json.dumps(stats, indent=2))

    with summary_stats_txt.open("w") as f:
        f.write("=== ECO BATCH STATS ===\n")
        for k, v in stats.items():
            f.write(f"{k}: {v}\n")

    log("")
    log("========================================")
    log("Batch klaar.")
    log("========================================")
    log(f"Output folder        : {out_root}")
    log(f"Baseline original    : {baseline_original_dcp}")
    log(f"Current base DCP     : {current_base_dcp}")
    log(f"Latest single eval   : {latest_single_eval_dcp}")
    log(f"Summary CSV          : {summary_csv}")
    log(f"Summary JSON         : {summary_json}")
    log(f"Summary stats JSON   : {summary_stats_json}")
    log(f"Summary stats TXT    : {summary_stats_txt}")
    log("")
    log("=== KERNSTATISTIEKEN ===")
    for k, v in stats["status_counts"].items():
        log(f"{k}: {v}")
    log(f"num_ok: {stats['num_ok']}")
    log(f"num_advanced_baseline: {stats['num_advanced_baseline']}")
    log(f"best_total_gain_ps: {stats['best_total_gain_ps']}")
    log(f"worst_total_gain_ps: {stats['worst_total_gain_ps']}")

if __name__ == "__main__":
    main()
