import json
import sys
import os

def process_lut_cones(input_path, output_path):
    if not os.path.exists(input_path):
        print(f"Fout: Bestand {input_path} niet gevonden.")
        return

    with open(input_path, 'r') as f:
        data = json.load(f)

    for cone in data.get('lut_cones', []):
        root_id = cone['lut_root']
        # Sla de originele lijst op om te kunnen checken in node_functions
        original_internals = set(cone['internal_nodes'])

        # 1. Pas internal_nodes aan naar unieke strings: "nodeID_rootID"
        cone['internal_nodes'] = [f"{n}_{root_id}" for n in cone['internal_nodes']]

        # 2. Update de node_functions lijst zodat de IDs matchen
        if 'node_functions' in cone:
            for nf in cone['node_functions']:
                curr_node = nf['node']
                # Alleen interne nodes aanpassen, de root zelf is al uniek
                if curr_node in original_internals:
                    nf['node'] = f"{curr_node}_{root_id}"

    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"Succes! Unieke IDs gegenereerd in: {output_path}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Gebruik: python3 uniqueify_lut_nodes.py <input_file.json> [output_file.json]")
    else:
        infile = sys.argv[1]
        outfile = sys.argv[2] if len(sys.argv) > 2 else "processed_" + infile
        process_lut_cones(infile, outfile)
