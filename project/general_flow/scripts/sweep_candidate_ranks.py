#!/usr/bin/env python3
import argparse
import copy
import csv
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml


def read_key_value_file(path: Path):
    data = {}
    if not path.exists():
        return data

    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        k, v = line.split("=", 1)
        data[k.strip()] = v.strip()
    return data


def load_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(errors="replace"))
    except Exception:
        return None


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def find_new_run_dir(runs_root: Path, before_dirs: set):
    if not runs_root.exists():
        return None

    after_dirs = {p for p in runs_root.iterdir() if p.is_dir()}
    new_dirs = list(after_dirs - before_dirs)

    if not new_dirs:
        return None

    new_dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return new_dirs[0]


def write_yaml(path: Path, data: dict):
    with path.open("w") as f:
        yaml.safe_dump(data, f, sort_keys=False)


def write_summary_csv(path: Path, rows: list):
    fields = [
        "rank",
        "return_code",
        "run_dir",

        "phase2_status",
        "source_cell",
        "sink_cell",
        "source_pin",
        "sink_pin",
        "selected_net",
        "selected_delay_ps",
        "num_luts",
        "num_internal_edges",
        "num_boundary_inputs",
        "num_boundary_outputs",

        "phase5b2_fast_status",
        "exact_candidate_count",
        "kept_candidate_count",
        "baseline_score",
        "best_candidate_id",
        "best_score_without_penalties",
        "best_score_with_penalties",
        "estimated_improvement",
        "templates_checked",
        "elapsed_seconds",

        "selected_candidate_id",
        "selected_candidate_status",
        "selected_score_without_penalties",
        "selected_score_with_penalties",
        "selected_root",
        "selected_helper1",
        "selected_helper2",
        "upgrade_count",
        "output_driver_changed",
        "changed_pin_count",

        "console_log",
        "config_path",
        "error",
    ]

    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fields})


def parse_run_outputs(rank: int, return_code: int, run_dir: Path, config_path: Path, console_log: Path):
    row = {
        "rank": rank,
        "return_code": return_code,
        "run_dir": str(run_dir) if run_dir else "",
        "console_log": str(console_log),
        "config_path": str(config_path),
        "error": "",
    }

    if run_dir is None:
        row["error"] = "no_run_dir_created"
        return row

    phase2_summary = read_key_value_file(run_dir / "02_phase2_window" / "phase2_window_summary.txt")
    phase5_summary = read_key_value_file(run_dir / "05_phase5_candidate_search" / "phase5b2_fast_summary.txt")
    selected_candidate = load_json(run_dir / "05_phase5_candidate_search" / "phase5b2_fast_selected_candidate.json")

    # Phase 2 fields
    for k in [
        "phase2_status",
        "source_cell",
        "sink_cell",
        "source_pin",
        "sink_pin",
        "selected_net",
        "selected_delay_ps",
        "num_luts",
        "num_internal_edges",
        "num_boundary_inputs",
        "num_boundary_outputs",
    ]:
        row[k] = phase2_summary.get(k, "")

    # Phase 5 summary fields
    for k in [
        "phase5b2_fast_status",
        "exact_candidate_count",
        "kept_candidate_count",
        "baseline_score",
        "best_candidate_id",
        "best_score_without_penalties",
        "best_score_with_penalties",
        "estimated_improvement",
        "templates_checked",
        "elapsed_seconds",
    ]:
        row[k] = phase5_summary.get(k, "")

    # Selected candidate details
    if selected_candidate:
        row["selected_candidate_id"] = selected_candidate.get("candidate_id", "")
        row["selected_candidate_status"] = selected_candidate.get("phase5b2_fast_status", "")
        row["selected_score_without_penalties"] = selected_candidate.get("score_without_penalties", "")
        row["selected_score_with_penalties"] = selected_candidate.get("score_with_penalties", "")
        row["upgrade_count"] = selected_candidate.get("upgrade_count", "")
        row["output_driver_changed"] = selected_candidate.get("output_driver_changed", "")

        cost = selected_candidate.get("cost", {})
        row["changed_pin_count"] = cost.get("changed_pin_count", "")

        roles = selected_candidate.get("roles", {})
        row["selected_root"] = roles.get("root", {}).get("cell", "")
        row["selected_helper1"] = roles.get("helper1", {}).get("cell", "")
        row["selected_helper2"] = roles.get("helper2", {}).get("cell", "")

    if not phase5_summary:
        row["error"] = "missing_phase5_summary"

    return row


def is_improved(row: dict):
    return str(row.get("estimated_improvement", "")).strip() in {"1", "true", "True"} or \
        row.get("phase5b2_fast_status") == "PASS_IMPROVED_ESTIMATE"


def main():
    parser = argparse.ArgumentParser(
        description="Sweep unique Phase 1 candidate ranks by generating configs and running the general ECO flow."
    )
    parser.add_argument("base_config", help="Base YAML config file")
    parser.add_argument("--max-rank", type=int, required=True, help="Test ranks 1..max-rank")
    parser.add_argument("--start-rank", type=int, default=1, help="First rank to test")
    parser.add_argument("--until", default="phase5", help="Run general flow until this phase, default phase5")
    parser.add_argument(
        "--flow-script",
        default="/home/cian/Masterproef/project/general_flow/scripts/run_general_eco_flow.py",
        help="Path to run_general_eco_flow.py",
    )
    parser.add_argument(
        "--sweep-root",
        default=None,
        help="Optional explicit sweep output directory. Default: <base output_root>/candidate_sweep_<timestamp>",
    )
    parser.add_argument(
        "--stop-on-first-improvement",
        action="store_true",
        help="Stop when a rank gives estimated_improvement=1",
    )
    args = parser.parse_args()

    base_config_path = Path(args.base_config).resolve()
    flow_script = Path(args.flow_script).resolve()

    if not base_config_path.exists():
        raise FileNotFoundError(f"Base config not found: {base_config_path}")

    if not flow_script.exists():
        raise FileNotFoundError(f"Flow script not found: {flow_script}")

    with base_config_path.open("r") as f:
        base_config = yaml.safe_load(f)

    base_run_name = base_config.get("run", {}).get("name", "eco")
    base_output_root = Path(base_config.get("run", {}).get("output_root", ".")).resolve()

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    if args.sweep_root:
        sweep_root = Path(args.sweep_root).resolve()
    else:
        sweep_root = base_output_root / f"candidate_sweep_{timestamp}_{base_run_name}"

    configs_dir = sweep_root / "configs"
    runs_dir = sweep_root / "runs"
    logs_dir = sweep_root / "logs"
    summary_dir = sweep_root / "summary"

    for d in [configs_dir, runs_dir, logs_dir, summary_dir]:
        ensure_dir(d)

    summary_csv = summary_dir / "candidate_sweep_summary.csv"
    improved_csv = summary_dir / "improved_candidates.csv"

    rows = []

    print(f"[sweep] base_config = {base_config_path}")
    print(f"[sweep] sweep_root  = {sweep_root}")
    print(f"[sweep] ranks       = {args.start_rank}..{args.max_rank}")
    print(f"[sweep] until       = {args.until}")
    print()

    for rank in range(args.start_rank, args.max_rank + 1):
        print(f"[sweep] === rank {rank}/{args.max_rank} ===", flush=True)

        cfg = copy.deepcopy(base_config)

        cfg.setdefault("run", {})
        cfg.setdefault("phase1", {})

        cfg["run"]["name"] = f"{base_run_name}_rank{rank:03d}"
        cfg["run"]["output_root"] = str(runs_dir)
        cfg["run"]["timestamped_output"] = True

        # Laat de general flow gerust stoppen bij phase5 als er geen improvement is.
        # Dit script vangt die non-zero return code op en parseert toch de outputs.
        cfg["run"]["stop_on_phase_fail"] = True

        cfg["phase1"]["candidate_rank"] = rank

        cfg_path = configs_dir / f"config_rank_{rank:03d}.yaml"
        write_yaml(cfg_path, cfg)

        console_log = logs_dir / f"rank_{rank:03d}.console.log"

        before_dirs = {p for p in runs_dir.iterdir() if p.is_dir()} if runs_dir.exists() else set()

        cmd = [
            sys.executable,
            str(flow_script),
            str(cfg_path),
            "--until",
            args.until,
        ]

        with console_log.open("w") as logfh:
            logfh.write("[CMD] " + " ".join(cmd) + "\n\n")
            logfh.flush()

            proc = subprocess.run(
                cmd,
                stdout=logfh,
                stderr=subprocess.STDOUT,
                text=True,
            )

        run_dir = find_new_run_dir(runs_dir, before_dirs)

        row = parse_run_outputs(
            rank=rank,
            return_code=proc.returncode,
            run_dir=run_dir,
            config_path=cfg_path,
            console_log=console_log,
        )

        rows.append(row)

        write_summary_csv(summary_csv, rows)
        write_summary_csv(improved_csv, [r for r in rows if is_improved(r)])

        print(
            "[sweep] rank={rank} rc={rc} phase5={phase5} improved={imp} "
            "edge={src}->{dst} delay_ps={delay} best_penalty_score={score}".format(
                rank=rank,
                rc=proc.returncode,
                phase5=row.get("phase5b2_fast_status", ""),
                imp=row.get("estimated_improvement", ""),
                src=row.get("source_cell", ""),
                dst=row.get("sink_cell", ""),
                delay=row.get("selected_delay_ps", ""),
                score=row.get("best_score_with_penalties", ""),
            ),
            flush=True,
        )

        if is_improved(row):
            print(f"[sweep] IMPROVED candidate found at rank {rank}", flush=True)
            if args.stop_on_first_improvement:
                break

    improved_rows = [r for r in rows if is_improved(r)]

    print()
    print("[sweep] DONE")
    print(f"[sweep] summary_csv  = {summary_csv}")
    print(f"[sweep] improved_csv = {improved_csv}")
    print(f"[sweep] improved_count = {len(improved_rows)}")

    if improved_rows:
        print()
        print("[sweep] Improved ranks:")
        for r in improved_rows:
            print(
                f"  rank={r['rank']} "
                f"edge={r.get('source_cell')}->{r.get('sink_cell')} "
                f"baseline={r.get('baseline_score')} "
                f"score_with_penalties={r.get('best_score_with_penalties')} "
                f"run={r.get('run_dir')}"
            )


if __name__ == "__main__":
    main()
