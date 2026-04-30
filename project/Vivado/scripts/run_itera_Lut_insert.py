import os
import sys
import json
import csv
import argparse
import logging
import subprocess
import datetime


# --- CONFIGURATIE & LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

LUT_DELAY_NS = 0.124
MAX_ITERATIES = 20

# --- 1. HULPFUNCTIES ---

def load_candidates(run_dir, top_n=50):
    """
    Leest de baseline JSON in en pakt de Top N langste netten.
    """
    # Let op: We lezen uit reports_baseline!
    target_file = os.path.join(run_dir, "reports_baseline", "lut_connections.json")

    logging.info(f"Kandidaten laden vanuit: {target_file}")

    if not os.path.exists(target_file):
        logging.error(f"Kan doelbestand niet vinden: {target_file}")
        sys.exit(1)

    try:
        with open(target_file, 'r') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        logging.error(f"Fout bij het parsen van JSON: {e}")
        sys.exit(1)

    candidates = []

    # De lijst is al gesorteerd, dus we pakken gewoon de eerste 'top_n' elementen
    for item in data[:top_n]:
        # OPMERKING: De echte delay staat niet in deze JSON (alleen de afstand).
        # Voor onze MVP (Minimum Viable Product) vullen we de 'baseline_delay_ns'
        # daarom tijdelijk in met onze dummy schatting, zodat de wiskunde later klopt.
        dummy_baseline_delay = estimate_delay(item["distance"])

        candidates.append({
            "net_name": item["net"],
            "to_cell": item["to"],
            "manhattan_dist": item["distance"],
            "baseline_delay_ns": dummy_baseline_delay,
            "coords": item["coords"] # Heel handig om straks aan Java door te geven!
        })

    logging.info(f"Succesvol {len(candidates)} kandidaten geladen (Top {top_n} geselecteerd).")
    return candidates

def estimate_delay(manhattan_distance):
    """
    De Dummy Delay Estimator.
    Zet een Manhattan-afstand om in een delay (ns).
    """
    # Dummy formule: 0.1ns per Manhattan stap
    return manhattan_distance * 1.5

def run_rapidwright_virtual_placement(net_name, coords, baseline_dcp):
    """
    Vraagt Java (RapidWright) om een vrije LUT te zoeken met het spiraal-algoritme,
    zonder de wijziging definitief op te slaan.
    """
    logging.debug(f"RapidWright aanroepen voor virtuele plaatsing van: {net_name}")

    # Haal de coördinaten uit de JSON dictionary
    src_x, src_y = coords["src"]
    dest_x, dest_y = coords["dest"]

    # PAS DIT AAN NAAR JOUW MAPPENSTRUCTUUR!
    RW_CLASSPATH = "/home/cian/Masterproef/project/Readwright/scripts:/home/cian/Masterproef/rapidwright-2023.1.0-standalone-lin64.jar"

    java_command = [
        "java",
        "-cp", RW_CLASSPATH,
        "InsertBufferECO",
        "--mode", "virtual",
        "--dcp", baseline_dcp,
        "--net", net_name,
        "--src_x", str(src_x),
        "--src_y", str(src_y),
        "--dest_x", str(dest_x),
        "--dest_y", str(dest_y)
    ]

    try:
        # Run het Java commando
        result = subprocess.run(java_command, capture_output=True, text=True, check=True)

        # Lees de output regel voor regel op zoek naar onze specifieke JSON output
        # In de try-block van run_rapidwright_virtual_placement:
        for line in result.stdout.splitlines():
            if line.startswith("RESULT_JSON:"):
                json_str = line.replace("RESULT_JSON:", "").strip()
                data = json.loads(json_str)
                # We geven nu een dictionary terug in plaats van losse variabelen, 
                # dat is veel robuuster als we veel data doorgeven!
                return data
        logging.error(f"Geen geldige RESULT_JSON gevonden voor {net_name}. Java output:\n{result.stdout}")
        return None, None, None

    except subprocess.CalledProcessError as e:
        logging.error(f"RapidWright crashte tijdens virtuele plaatsing van {net_name}!")
        logging.error(f"Foutmelding: {e.stderr}")
        return None, None, None

def evaluate_cost(originele_delay, delay_route1, lut_delay, delay_route2):
    """De kern-wiskunde: is de nieuwe situatie sneller?"""
    nieuwe_totale_delay = delay_route1 + lut_delay + delay_route2
    verbetering = originele_delay - nieuwe_totale_delay

    is_beter = nieuwe_totale_delay < originele_delay
    return is_beter, verbetering

def commit_eco(net_name, to_cell, lut_locatie, input_dcp, output_dcp):
    """
    Roept RapidWright aan in 'commit' modus om de netlist aan te passen
    en een nieuwe .dcp op te slaan.
    """
    logging.info(f"ECO COMMIT: {net_name} wordt opgesplitst via {lut_locatie}. Opslaan als {output_dcp}")

    # Gebruik weer dezelfde CLASSPATH als in je virtual functie
    RW_CLASSPATH = "/home/cian/Masterproef/project/Readwright/scripts:/home/cian/Masterproef/rapidwright-2023.1.0-standalone-lin64.jar"

    java_command = [
        "java",
        "-cp", RW_CLASSPATH,
        "InsertBufferECO",
        "--mode", "commit",
        "--dcp", input_dcp,
        "--out_dcp", output_dcp,
        "--net", net_name,
        "--lutB", to_cell,
        "--target_slice", lut_locatie
    ]

    try:
        result = subprocess.run(java_command, capture_output=True, text=True, check=True)
        logging.info(f"RapidWright succesvol weggeschreven voor {net_name}.")
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"RapidWright crashte tijdens COMMIT van {net_name}!")
        logging.error(f"Foutmelding: {e.stderr}")
        return False


# --- 2. DE MASTER LOOP ---

def main():
    # Setup de argument parser
    parser = argparse.ArgumentParser(description="Iteratieve ECO Optimizer voor FPGA Wire Delay")
    parser.add_argument(
        "run_dir", 
        help="Pad naar de baseline run map (bijv. results/run_lut_insertion/2026-04-18_16-43-20/)"
    )
    parser.add_argument( # <--- NIEUWE VLAG VOOR MODUS
        "--estimator", 
        choices=["rapidwright", "custom"], 
        default="custom",
        help="Kies welk delay model gebruikt moet worden."
    )
    
    args = parser.parse_args()
    run_dir = os.path.abspath(args.run_dir)
    estimator_mode = args.estimator

    if not os.path.isdir(run_dir):
        logging.error(f"De opgegeven map bestaat niet: {run_dir}")
        sys.exit(1)

    # --- NIEUW: OUTPUT MAPSTRUCTUUR AANMAKEN ---
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    project_root = os.path.abspath(os.path.join(run_dir, "../../..")) # Gaat terug naar ~/Masterproef/project/
    
    # Maak: results/run_itera_lut_insert/2026-04-19_10-52-11/dcp/
    out_run_dir = os.path.join(project_root, "results", "run_itera_lut_insert", timestamp)
    out_dcp_dir = os.path.join(out_run_dir, "dcp")
    os.makedirs(out_dcp_dir, exist_ok=True)

    logging.info(f"Start Iteratieve ECO (Modus: {estimator_mode})")
    logging.info(f"Output wordt weggeschreven naar: {out_run_dir}")
    
    # 1. Laad de kandidaten
    candidates = load_candidates(run_dir)
    succesvolle_ecos = 0
    
    # Haal originele baseline DCP op
    baseline_dcp = os.path.join(run_dir, "baseline_impl", "checkpoints", "post_place_timingexp.dcp")
    # 2. De Iteratieve Loop
    for kandidaat in candidates:
        if succesvolle_ecos >= MAX_ITERATIES:
            logging.info(f"Maximale iteraties ({MAX_ITERATIES}) bereikt. Stop loop.")
            break

        net = kandidaat["net_name"]
        orig_delay = kandidaat["baseline_delay_ns"]
        logging.info(f"--- Evalueren van kandidaat: {net} (Huidige delay: {orig_delay}ns) ---")

        # A. Virtuele Plaatsing in RapidWright
        # A. Virtuele Plaatsing in RapidWright
        rw_data = run_rapidwright_virtual_placement(net, kandidaat["coords"], baseline_dcp)
        
        if rw_data is None:
            logging.warning(f"Kon geen locatie berekenen voor {net}. Skip net.")
            continue
            
        md1 = rw_data["md1"]
        md2 = rw_data["md2"]
        lut_loc = rw_data["lut_loc"]

        # B. Delay Estimatie (Afhankelijk van gekozen modus)
        if estimator_mode == "custom":
            geschatte_delay_1 = estimate_delay(md1)
            geschatte_delay_2 = estimate_delay(md2)
        elif estimator_mode == "rapidwright":
            # Trek de RapidWright TimingManager waarden direct uit de Java JSON!
            geschatte_delay_1 = rw_data["rw_delay1"]
            geschatte_delay_2 = rw_data["rw_delay2"]
        # C. Cost Evaluatie
        is_succes, gain = evaluate_cost(orig_delay, geschatte_delay_1, LUT_DELAY_NS, geschatte_delay_2)

        # D. Beslissing
        if is_succes:
            logging.info(f"SUCCES! Verwachte winst: {gain:.2f}ns. Voer ECO uit.")
            
            # --- NIEUW: Pad naar de nieuwe, geïsoleerde output map ---
            nieuwe_dcp = os.path.join(out_dcp_dir, f"eco_iteratie_{succesvolle_ecos + 1}.dcp")
            
            success = commit_eco(net, kandidaat["to_cell"], lut_loc, baseline_dcp, nieuwe_dcp)
            
            if success:
                baseline_dcp = nieuwe_dcp 
                succesvolle_ecos += 1
        else:
            logging.warning(f"GEWEIGERD. Nieuwe delay zou {abs(gain):.2f}ns TRAGER zijn. Skip net.")
    # 3. Afsluiting
    logging.info(f"Iteratieve loop voltooid. Totaal {succesvolle_ecos} LUTs succesvol geplaatst.")
    # TODO: Vertel RapidWright om de finale iteratieve_eco_final.dcp op te slaan.

if __name__ == "__main__":
    main()
