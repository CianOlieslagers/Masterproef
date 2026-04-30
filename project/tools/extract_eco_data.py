import os
import json
import argparse
import re

def main():
    parser = argparse.ArgumentParser(description="Extraheer ECO delay data uit compare.log bestanden.")
    parser.add_argument(
        "input_folder", 
        help="Pad naar de useful_iterations map (bijv. /pad/naar/useful_iterations)"
    )
    args = parser.parse_args()

    source_dir = os.path.abspath(args.input_folder)
    base_dir = os.path.dirname(source_dir) # Map erboven voor de output bestanden
    
    # Output bestanden
    favorable_json_path = os.path.join(base_dir, "verbeterde_eco_resultaten.json")
    unfavorable_json_path = os.path.join(base_dir, "verslechterde_eco_resultaten.json")

    verbeterde_iteraties = []
    verslechterde_iteraties = []

    print(f"Scannen van logs in: {source_dir}...\n")

    for iter_folder in sorted(os.listdir(source_dir)):
        iter_path = os.path.join(source_dir, iter_folder)

        if not os.path.isdir(iter_path) or not iter_folder.startswith("iter_"):
            continue

        log_path = os.path.join(iter_path, "compare.log")
        if not os.path.exists(log_path):
            continue

        # Basis dictionary met de naam van de iteratie
        iter_data = {"iteration_id": iter_folder}

        with open(log_path, 'r', encoding='utf-8') as f:
            content = f.read()

            # 1. Zoek de RESULT_JSON regel en parse de data
            json_match = re.search(r'RESULT_JSON:\s*(\{.*?\})', content)
            if json_match:
                try:
                    metrics = json.loads(json_match.group(1))
                    iter_data.update(metrics)
                except json.JSONDecodeError:
                    print(f"Waarschuwing: Kon JSON niet lezen in {iter_folder}")

            # 2. Extraheer extra nuttige informatie met Regex (Net, Source, Sink, Buffer Site)
            net_match = re.search(r'Baseline direct:.*?net\s*=\s*(\S+)', content, re.DOTALL)
            if net_match: iter_data['net'] = net_match.group(1)

            source_match = re.search(r'Baseline direct:.*?source\s*=\s*(\S+)', content, re.DOTALL)
            if source_match: iter_data['source'] = source_match.group(1)

            sink_match = re.search(r'Baseline direct:.*?sink\s*=\s*(\S+)', content, re.DOTALL)
            if sink_match: iter_data['sink'] = sink_match.group(1)
            
            buffer_match = re.search(r'ECO LUT internal:.*?site\s*=\s*(\S+)', content, re.DOTALL)
            if buffer_match: iter_data['buffer_site'] = buffer_match.group(1)

        # 3. Splits de logica: Is de baseline beter (groter) dan de ECO delay?
        # We checken of de keys bestaan om errors te voorkomen
        if "baseline_ps" in iter_data and "eco_total_ps" in iter_data:
            if iter_data["baseline_ps"] > iter_data["eco_total_ps"]:
                verbeterde_iteraties.append(iter_data)
            else:
                verslechterde_iteraties.append(iter_data)
        else:
            # Als de data mist om een of andere reden, zetten we hem bij de rest
            verslechterde_iteraties.append(iter_data)

    # 4. Schrijf de data weg naar twee mooie JSON bestanden
    with open(favorable_json_path, 'w', encoding='utf-8') as f:
        json.dump(verbeterde_iteraties, f, indent=4)
        
    with open(unfavorable_json_path, 'w', encoding='utf-8') as f:
        json.dump(verslechterde_iteraties, f, indent=4)

    print(f"Klaar! Resultaten weggeschreven:")
    print(f"  - Verbeterd (Baseline > ECO) : {len(verbeterde_iteraties)} iteraties -> {favorable_json_path}")
    print(f"  - Rest (Baseline <= ECO)     : {len(verslechterde_iteraties)} iteraties -> {unfavorable_json_path}")

if __name__ == "__main__":
    main()
