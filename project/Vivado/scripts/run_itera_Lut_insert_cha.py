import os
import sys
import json
import argparse
import logging
import subprocess
import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

DEFAULT_TOP_N = 50
DEFAULT_MAX_ITERATIES = 20


def get_baseline_delay_ns(item: dict) -> float:
    """
    Gebruik eerst een echte vooraf berekende delay als die aanwezig is.
    Zo niet: val terug op de distance-based estimate.
    """

    possible_keys = [
        "baseline_delay_ns",
        "delay_ns",
        "net_delay_ns",
        "timing_ns",
        "delay"
    ]

    for key in possible_keys:
        if key in item:
            try:
                return float(item[key])
            except (TypeError, ValueError):
                logging.error(f"Delay veld '{key}' bestaat maar is niet numeriek: {item[key]}")
                sys.exit(1)

    # Fallback: jouw huidige JSON bevat alleen distance
    if "distance" in item:
        try:
            distance = float(item["distance"])
            return distance * 1.5
        except (TypeError, ValueError):
            logging.error(f"Distance veld is niet numeriek: {item['distance']}")
            sys.exit(1)

    logging.error(
        "Geen bruikbare delay of distance gevonden in lut_connections.json.\n"
        f"Item was: {json.dumps(item, indent=2)}"
    )
    sys.exit(1)


def load_candidates(run_dir: str, top_n: int = DEFAULT_TOP_N):
    """
    Leest dezelfde baseline JSON in als je originele script,
    maar gebruikt nu de reeds berekende delay i.p.v. een dummy estimate.
    """
    target_file = os.path.join(run_dir, "reports_baseline", "lut_connections.json")
    logging.info(f"Kandidaten laden vanuit: {target_file}")

    if not os.path.exists(target_file):
        logging.error(f"Kan doelbestand niet vinden: {target_file}")
        sys.exit(1)

    try:
        with open(target_file, "r") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        logging.error(f"Fout bij het parsen van JSON: {e}")
        sys.exit(1)

    candidates = []
    for item in data[:top_n]:
        baseline_delay_ns = get_baseline_delay_ns(item)
        if "net" not in item or "to" not in item or "distance" not in item or "coords" not in item:
            logging.error(f"JSON item mist verplichte velden: {json.dumps(item, indent=2)}")
            sys.exit(1)

        candidates.append({
            "net_name": item["net"],
            "from_cell": item["from"],
            "to_cell": item["to"],
            "manhattan_dist": item["distance"],
            "baseline_delay_ns": baseline_delay_ns,
            "coords": item["coords"]
        })

    logging.info(f"Succesvol {len(candidates)} kandidaten geladen (Top {top_n} geselecteerd).")
    return candidates


def parse_result_json(stdout: str):
    for line in stdout.splitlines():
        if line.startswith("RESULT_JSON:"):
            json_str = line.replace("RESULT_JSON:", "", 1).strip()
            return json.loads(json_str)
    return None


def run_java_eval_commit(candidate, input_dcp: str, output_dcp: str, rw_classpath: str, java_class: str):
    coords = candidate["coords"]
    src_x, src_y = coords["src"]
    dest_x, dest_y = coords["dest"]

    java_command = [
        "java",
        "-cp", rw_classpath,
        java_class,
        "--mode", "eval_commit",
        "--dcp", input_dcp,
        "--out_dcp", output_dcp,
        "--net", candidate["net_name"],
        "--from_cell", candidate["from_cell"],
        "--lutB", candidate["to_cell"],
        "--src_x", str(src_x),
        "--src_y", str(src_y),
        "--dest_x", str(dest_x),
        "--dest_y", str(dest_y),
        "--orig_delay", str(candidate["baseline_delay_ns"])
    ]

    try:
        result = subprocess.run(
            java_command,
            capture_output=True,
            text=True,
            check=True
        )
    except subprocess.CalledProcessError as e:
        logging.error(f"Java crashte bij kandidaat {candidate['net_name']}")
        logging.error(f"STDERR:\n{e.stderr}")
        logging.error(f"STDOUT:\n{e.stdout}")
        return None

    data = parse_result_json(result.stdout)
    if data is None:
        logging.error(f"Geen RESULT_JSON gevonden voor {candidate['net_name']}")
        logging.error(f"Java output:\n{result.stdout}")
        return None

    return data


def build_output_dirs(run_dir: str):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    project_root = os.path.abspath(os.path.join(run_dir, "../../.."))
    out_run_dir = os.path.join(project_root, "results", "run_itera_lut_insert", timestamp)
    out_dcp_dir = os.path.join(out_run_dir, "dcp")
    os.makedirs(out_dcp_dir, exist_ok=True)
    return out_run_dir, out_dcp_dir


def run_single_mode(candidates, baseline_dcp, out_dcp_dir, rw_classpath, java_class):
    """
    Probeert kandidaten in volgorde en stopt na de eerste succesvolle commit.
    """
    for idx, candidate in enumerate(candidates, start=1):
        net = candidate["net_name"]
        orig_delay = candidate["baseline_delay_ns"]
        logging.info(f"[single] Evalueren van kandidaat {idx}: {net} (baseline delay: {orig_delay:.3f} ns)")

        nieuwe_dcp = os.path.join(out_dcp_dir, "eco_iteratie_1.dcp")

        result = run_java_eval_commit(
            candidate=candidate,
            input_dcp=baseline_dcp,
            output_dcp=nieuwe_dcp,
            rw_classpath=rw_classpath,
            java_class=java_class
        )

        if result is None:
            logging.warning(f"[single] Skip wegens Java/parsing probleem: {net}")
            continue

        accepted = bool(result.get("accepted", False))
        total_est = result.get("total_estimated_ns", None)

        if accepted:
            logging.info(f"[single] SUCCES: {net} geaccepteerd. Nieuwe geschatte delay: {total_est:.3f} ns")
            return {
                "success": True,
                "iterations": 1,
                "final_dcp": nieuwe_dcp,
                "result": result
            }

        logging.info(f"[single] GEWEIGERD: {net}")

    return {
        "success": False,
        "iterations": 0,
        "final_dcp": baseline_dcp,
        "result": None
    }


def run_batch_mode(candidates, baseline_dcp, out_dcp_dir, rw_classpath, java_class, max_iteraties):
    """
    Probeert meerdere aanpassingen.
    Let op: baseline_delay_ns per kandidaat blijft de initieel ingelezen waarde uit de JSON.
    Dat is bewust een verouderd model na elke succesvolle commit.
    """
    succesvolle_ecos = 0
    current_dcp = baseline_dcp

    for idx, candidate in enumerate(candidates, start=1):
        if succesvolle_ecos >= max_iteraties:
            logging.info(f"[batch] Max iteraties ({max_iteraties}) bereikt.")
            break

        net = candidate["net_name"]
        orig_delay = candidate["baseline_delay_ns"]
        logging.info(f"[batch] Evalueren van kandidaat {idx}: {net} (baseline delay: {orig_delay:.3f} ns)")

        nieuwe_dcp = os.path.join(out_dcp_dir, f"eco_iteratie_{succesvolle_ecos + 1}.dcp")

        result = run_java_eval_commit(
            candidate=candidate,
            input_dcp=current_dcp,
            output_dcp=nieuwe_dcp,
            rw_classpath=rw_classpath,
            java_class=java_class
        )

        if result is None:
            logging.warning(f"[batch] Skip wegens Java/parsing probleem: {net}")
            continue

        accepted = bool(result.get("accepted", False))
        total_est = result.get("total_estimated_ns", None)

        if accepted:
            succesvolle_ecos += 1
            current_dcp = nieuwe_dcp
            logging.info(f"[batch] SUCCES: {net} geaccepteerd. Nieuwe geschatte delay: {total_est:.3f} ns")
        else:
            logging.info(f"[batch] GEWEIGERD: {net}")

    return {
        "success": succesvolle_ecos > 0,
        "iterations": succesvolle_ecos,
        "final_dcp": current_dcp
    }


def main():
    parser = argparse.ArgumentParser(description="Nieuwe iteratieve ECO optimizer (v2)")
    parser.add_argument(
        "run_dir",
        help="Pad naar baseline run map (bv. results/run_lut_insertion/<timestamp>/)"
    )
    parser.add_argument(
        "--mode",
        choices=["single", "batch"],
        default="batch",
        help="single = max 1 succesvolle aanpassing, batch = meerdere aanpassingen"
    )
    parser.add_argument(
        "--top_n",
        type=int,
        default=DEFAULT_TOP_N,
        help="Aantal kandidaten uit lut_connections.json"
    )
    parser.add_argument(
        "--max_iteraties",
        type=int,
        default=DEFAULT_MAX_ITERATIES,
        help="Maximum aantal commits in batch mode"
    )
    parser.add_argument(
        "--classpath",
        default="/home/cian/Masterproef/project/Readwright/scripts:/home/cian/Masterproef/rapidwright-2023.1.0-standalone-lin64.jar",
        help="Java classpath"
    )
    parser.add_argument(
        "--java_class",
        default="InsertBufferECOEvalCommit",
        help="Naam van de Java main class"
    )

    args = parser.parse_args()

    run_dir = os.path.abspath(args.run_dir)
    if not os.path.isdir(run_dir):
        logging.error(f"De opgegeven map bestaat niet: {run_dir}")
        sys.exit(1)

    out_run_dir, out_dcp_dir = build_output_dirs(run_dir)
    logging.info(f"Start nieuwe ECO flow in mode: {args.mode}")
    logging.info(f"Output wordt weggeschreven naar: {out_run_dir}")

    candidates = load_candidates(run_dir, top_n=args.top_n)

    baseline_dcp = os.path.join(run_dir, "baseline_impl", "checkpoints", "post_place_timingexp.dcp")
    if not os.path.exists(baseline_dcp):
        logging.error(f"Baseline DCP niet gevonden: {baseline_dcp}")
        sys.exit(1)

    if args.mode == "single":
        result = run_single_mode(
            candidates=candidates,
            baseline_dcp=baseline_dcp,
            out_dcp_dir=out_dcp_dir,
            rw_classpath=args.classpath,
            java_class=args.java_class
        )
    else:
        result = run_batch_mode(
            candidates=candidates,
            baseline_dcp=baseline_dcp,
            out_dcp_dir=out_dcp_dir,
            rw_classpath=args.classpath,
            java_class=args.java_class,
            max_iteraties=args.max_iteraties
        )

    logging.info("Flow voltooid.")
    logging.info(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
