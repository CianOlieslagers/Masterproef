#!/usr/bin/env python3
import re, json, argparse, csv, os
from collections import Counter

# === Meerdere header-varianten ===
RX_PATH_HDRS = [
    re.compile(r'^\s*Path\s+#(\d+)\b', re.I),
    re.compile(r'^\s*#\s*Path\s+(\d+)\b', re.I),
    re.compile(r'^\s*Path\s+(\d+)\b', re.I),
]

# 'slack' met of zonder dubbele punt en met evt. (MET/VIOLATED)
RX_SLACK  = re.compile(r'^\s*slack(?:\s*\([^)]+\))?\s*:?\s*([-\d.eE]+)\s*$', re.I)
# 'Delay' als aanwezig
RX_DELAY  = re.compile(r'^\s*(?:Path\s+delay|Delay)(?:\s*\(ns\))?\s*:?\s*([-\d.eE]+)\s*$', re.I)

RX_START  = re.compile(r'^\s*Startpoint\s*:\s*(.+?)\s*$', re.I)
RX_END    = re.compile(r'^\s*Endpoint\s*:\s*(.+?)\s*$', re.I)

# Expliciete netregels
RX_NET    = re.compile(r'\bNet:\s*([^\s(]+)')

# Fallbacks
RX_DATA_ARRIVAL  = re.compile(r'^\s*data\s+arrival\s+time\s*([-\d.eE]+)\s*$', re.I)
RX_DATA_REQUIRED = re.compile(r'^\s*data\s+required\s+time\s*([-\d.eE]+)\s*$', re.I)
RX_PATH_TYPE     = re.compile(r'^\s*Path\s+Type\s*:\s*(\w+)\s*$', re.I)

# **Nieuwe** fallback: haal "signaalnamen" uit knoopregels zoals
#   'b[33].inpad[0]' , 'f[33].in[2]' , 'out:f[127].outpad[0]'
RX_NODE_TOKEN = re.compile(
    r'(?:(?:in|out):)?'       # optioneel 'in:' of 'out:'
    r'([^\s\.:]+(?:\[[0-9]+\])?)'  # -> capture b[33], f[127], a[0], ...
    r'\.(?:in|out|inpad|outpad)\[\d+\]'
)

def parse_report(path, max_paths=None):
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    paths, cur = [], None

    def is_path_header(ln):
        for rx in RX_PATH_HDRS:
            m = rx.match(ln)
            if m:
                return int(m.group(1))
        return None

    for ln in lines:
        idx = is_path_header(ln)
        if idx is not None:
            if cur:
                paths.append(cur)
                if max_paths and len(paths) >= max_paths:
                    break
            cur = {
                "index": idx,
                "slack_ns": None,
                "delay_ns": None,
                "startpoint": None,
                "endpoint": None,
                "path_type": None,
                "nets": [],
                "_arrival": None,
                "_required": None,
                "_tokens": [],   # <-- voor fallback
            }
            continue

        if not cur:
            continue

        if (m := RX_SLACK.match(ln)): cur["slack_ns"] = float(m.group(1)); continue
        if (m := RX_DELAY.match(ln)): cur["delay_ns"] = float(m.group(1)); continue
        if (m := RX_START.match(ln)): cur["startpoint"] = m.group(1).strip(); continue
        if (m := RX_END.match(ln)):   cur["endpoint"]  = m.group(1).strip(); continue
        if (m := RX_PATH_TYPE.match(ln)): cur["path_type"] = m.group(1).lower(); continue
        if (m := RX_DATA_ARRIVAL.match(ln)):  cur["_arrival"]  = float(m.group(1)); continue
        if (m := RX_DATA_REQUIRED.match(ln)): cur["_required"] = float(m.group(1)); continue

        # Expliciete Net:-labels
        for nm in RX_NET.findall(ln):
            cur["nets"].append(nm)

        # Node-token fallback (signaalnaam vóór '.in[...]' / '.out[...]')
        for t in RX_NODE_TOKEN.findall(ln):
            cur["_tokens"].append(t)

    if cur and (not max_paths or len(paths) < max_paths):
        paths.append(cur)

    # Dedup + fallbacks
    for p in paths:
        # 1) nets dedup
        seen, ordered = set(), []
        for n in p["nets"]:
            if n not in seen:
                seen.add(n); ordered.append(n)
        p["nets"] = ordered

        # 2) indien geen expliciete Net:-regels, gebruik token-heuristiek
        if not p["nets"] and p.get("_tokens"):
            seen2, out2 = set(), []
            for t in p["_tokens"]:
                if t not in seen2:
                    seen2.add(t); out2.append(t)
            p["nets"] = out2

        # 3) delay fallback
        if p.get("delay_ns") is None and p.get("_arrival") is not None:
            p["delay_ns"] = float(p["_arrival"])

        # opschonen
        p.pop("_arrival", None); p.pop("_required", None); p.pop("_tokens", None)

    return paths

def write_outputs(paths, outdir, src_report):
    os.makedirs(outdir, exist_ok=True)

    csv_paths = os.path.join(outdir, "report_top_paths.csv")
    with open(csv_paths, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["path_index","slack_ns","delay_ns","startpoint","endpoint","num_nets","nets","source_report"])
        for p in paths:
            w.writerow([
                p.get("index"),
                p.get("slack_ns"),
                p.get("delay_ns"),
                p.get("startpoint") or "",
                p.get("endpoint") or "",
                len(p.get("nets", [])),
                " ".join(p.get("nets", [])),
                os.path.basename(src_report)
            ])

    cnt = Counter(); first_rank = {}
    for rank, p in enumerate(paths, 1):
        for n in p.get("nets", []):
            cnt[n] += 1
            first_rank.setdefault(n, rank)

    nets_sorted = sorted(cnt.items(), key=lambda x: (-x[1], first_rank[x[0]], x[0]))

    csv_nets = os.path.join(outdir, "trace_selected_nets.csv")
    with open(csv_nets, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["net","count_in_top_paths","first_seen_path_rank","source_report"])
        for n, c in nets_sorted:
            w.writerow([n, c, first_rank[n], os.path.basename(src_report)])

    txt_nets = os.path.join(outdir, "trace_selected_nets.txt")
    with open(txt_nets, "w", encoding="utf-8") as f:
        for n, _ in nets_sorted:
            f.write(f"{n}\n")

    json_out = os.path.join(outdir, "trace_selected_nets.json")
    out = {
        "format": "vpr_timing_topN:v1",
        "n_paths": len(paths),
        "source_report": os.path.basename(src_report),
        "paths": paths,
        "nets_ranked": [{"net": n, "count": c, "first_seen_path_rank": first_rank[n]} for n, c in nets_sorted]
    }
    with open(json_out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)

    return {"csv_paths": csv_paths, "csv_nets": csv_nets, "txt_nets": txt_nets, "json": json_out}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", help="pad naar timing report (.rpt)")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--npaths", type=int, default=200)
    ap.add_argument("--searchdir", help="directory om automatisch een bruikbaar report te zoeken")
    args = ap.parse_args()

    candidates = []
    if args.report: candidates.append(args.report)
    if args.searchdir:
        base = args.searchdir
        candidates += [
            os.path.join(base, "report_timing.setup.rpt"),
            os.path.join(base, "pre_pack.report_timing.setup.rpt"),
            os.path.join(base, "report_unconstrained_timing.setup.rpt"),
            os.path.join(base, "report_timing.hold.rpt"),
            os.path.join(base, "report_unconstrained_timing.hold.rpt"),
        ]

    picked = None
    for rp in candidates:
        if not rp or not os.path.isfile(rp): continue
        ps = parse_report(rp, max_paths=args.npaths)
        if ps:
            picked = (rp, ps); break

    if not picked:
        raise SystemExit("Geen paden gevonden in meegegeven/beschikbare reports.")

    rp, paths = picked
    outs = write_outputs(paths, args.outdir, rp)
    print(f"OK: {len(paths)} paden geparset uit {os.path.basename(rp)}")
    for k, v in outs.items():
        print(f"- {k}: {v}")

if __name__ == "__main__":
    main()
