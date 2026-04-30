import csv
import json
import os
import re
import sys


PIN_RE = re.compile(
    r"^(I\d+|O\d*|[A-H]\d|[A-H]_O|[A-H]MUX|HMUX|CLK|CE|SR|D|Q)$"
)


def first_nonempty(row, keys):
    for k in keys:
        v = row.get(k)
        if v is not None and str(v).strip() != "":
            return str(v).strip()
    return None


def resolve_cell_name(raw_name, cell_to_site):
    """
    Probeer een naam te mappen op een cellenaam uit cells.csv.
    We strippen trapsgewijs suffixen na '/' tot er een match is.
    """
    if raw_name is None:
        return None

    raw_name = str(raw_name).strip()
    if raw_name in cell_to_site:
        return raw_name

    parts = raw_name.split("/")
    for i in range(len(parts) - 1, 0, -1):
        candidate = "/".join(parts[:i])
        if candidate in cell_to_site:
            return candidate

    return None


def split_possible_cell_and_pin(raw_name):
    """
    Alleen als het laatste segment echt op een pin lijkt, splitsen we.
    Anders laten we de naam ongemoeid.
    """
    if raw_name is None:
        return None, None

    raw_name = str(raw_name).strip()
    if "/" not in raw_name:
        return raw_name, None

    prefix, last = raw_name.rsplit("/", 1)
    if PIN_RE.match(last):
        return prefix, last

    return raw_name, None


def load_cells(cells_file):
    cell_to_site = {}
    cell_meta = {}

    print(f"Reading {cells_file}...")
    with open(cells_file, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("name")
            site_name = row.get("site_name")
            if not name:
                continue
            cell_to_site[name] = site_name
            cell_meta[name] = {
                "site_name": site_name,
                "bel_name": row.get("bel_name"),
                "cell_type": row.get("type") or row.get("ref_name") or row.get("cell_type"),
            }

    return cell_to_site, cell_meta


def load_site_coords(placements_file):
    site_coords = {}

    print(f"Reading {placements_file}...")
    with open(placements_file, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("name")
            if not name:
                continue
            try:
                x = int(row["instance_x"])
                y = int(row["instance_y"])
                site_coords[name] = (x, y)
            except Exception:
                pass

    return site_coords


def midpoint_slice(x1, y1, x2, y2):
    mx = (x1 + x2) // 2
    my = (y1 + y2) // 2
    return f"SLICE_X{mx}Y{my}"


def generate_lut_connections_json(base_path):
    cells_file = os.path.join(base_path, "cells.csv")
    placements_file = os.path.join(base_path, "placements.csv")
    connectivity_file = os.path.join(base_path, "connectivity.csv")
    output_file = os.path.join(base_path, "lut_connections.json")

    try:
        cell_to_site, cell_meta = load_cells(cells_file)
        site_coords = load_site_coords(placements_file)
    except Exception as e:
        print(f"Error loading input files: {e}")
        return

    connections = []
    skipped = 0

    print(f"Reading {connectivity_file} and calculating distances...")
    try:
        with open(connectivity_file, "r") as f:
            reader = csv.DictReader(f)
            for idx, row in enumerate(reader, start=1):
                net = first_nonempty(row, ["net", "net_name"])
                from_raw = first_nonempty(row, ["from", "from_cell", "src", "src_cell"])
                to_raw = first_nonempty(row, ["to", "to_cell", "sink", "dst", "dst_cell"])

                if not net or not from_raw or not to_raw:
                    skipped += 1
                    continue

                # Expliciete pinvelden indien aanwezig
                from_pin_explicit = first_nonempty(
                    row, ["from_pin", "src_pin", "source_pin", "from_port"]
                )
                to_pin_explicit = first_nonempty(
                    row, ["to_pin", "sink_pin", "dst_pin", "target_pin", "to_port"]
                )

                # Alleen als laatste segment op een pin lijkt, mogen we automatisch splitsen
                from_split_cell, from_split_pin = split_possible_cell_and_pin(from_raw)
                to_split_cell, to_split_pin = split_possible_cell_and_pin(to_raw)

                source_cell_guess = resolve_cell_name(from_split_cell, cell_to_site)
                sink_cell_guess = resolve_cell_name(to_split_cell, cell_to_site)

                source_pin_guess = from_pin_explicit or from_split_pin
                sink_pin_guess = to_pin_explicit or to_split_pin

                if not source_cell_guess or not sink_cell_guess:
                    skipped += 1
                    continue

                src_site = cell_to_site.get(source_cell_guess)
                dest_site = cell_to_site.get(sink_cell_guess)

                if src_site not in site_coords or dest_site not in site_coords:
                    skipped += 1
                    continue

                x1, y1 = site_coords[src_site]
                x2, y2 = site_coords[dest_site]
                dist = abs(x1 - x2) + abs(y1 - y2)

                eco_ready = sink_pin_guess is not None

                connections.append({
                    "id": f"cand_{idx:06d}",
                    "net": net,
                    "from": from_raw,
                    "to": to_raw,
                    "distance": dist,
                    "coords": {
                        "src": [x1, y1],
                        "dest": [x2, y2]
                    },

                    # Nieuwe velden voor ECO-flow
                    "source_cell": source_cell_guess,
                    "source_pin": source_pin_guess,
                    "source_site": src_site,
                    "sink_cell": sink_cell_guess,
                    "sink_pin": sink_pin_guess,
                    "sink_site": dest_site,
                    "target_slice": midpoint_slice(x1, y1, x2, y2),
                    "eco_ready": eco_ready,

                    # Handige metadata
                    "source_cell_type": cell_meta.get(source_cell_guess, {}).get("cell_type"),
                    "sink_cell_type": cell_meta.get(sink_cell_guess, {}).get("cell_type"),
                    "source_bel": cell_meta.get(source_cell_guess, {}).get("bel_name"),
                    "sink_bel": cell_meta.get(sink_cell_guess, {}).get("bel_name"),
                })

    except Exception as e:
        print(f"Error processing connections: {e}")
        return

    print("Sorting connections by distance...")
    connections.sort(key=lambda x: x["distance"], reverse=True)

    print(f"Saving to {output_file}...")
    try:
        with open(output_file, "w") as f:
            json.dump(connections, f, indent=2)
        print(f"Succes! {len(connections)} connecties verwerkt in {output_file}.")
        print(f"Overgeslagen records: {skipped}")
        eco_ready_count = sum(1 for c in connections if c.get("eco_ready"))
        print(f"ECO-ready kandidaten: {eco_ready_count}/{len(connections)}")
    except Exception as e:
        print(f"Error saving JSON: {e}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        target_dir = sys.argv[1]
    else:
        target_dir = os.path.expanduser("~/Masterproef/project/Vivado/reports/dcp_summary")

    generate_lut_connections_json(target_dir)
