import argparse
import os
import subprocess
import sys

# Controleer of SpydrNet beschikbaar is
try:
    import spydrnet as sdn
except ImportError:
    print("Fout: SpydrNet is niet geïnstalleerd. Installeer het via: pip install spydrnet")
    sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Converteer EDIF naar BLIF en AIG via SpydrNet en Yosys.")
    parser.add_argument("input_edif", help="Het invoer .edif bestand")
    parser.add_argument("--keep-v", action="store_true", help="Bewaar het tijdelijke Verilog bestand in plaats van het te verwijderen")
    args = parser.parse_args()

    edif_file = args.input_edif
    base_name = os.path.splitext(edif_file)[0]
    
    v_file = base_name + ".v"
    blif_file = base_name + ".blif"
    aig_file = base_name + ".aig"

    if not os.path.exists(edif_file):
        print(f"Fout: Bestand '{edif_file}' niet gevonden.")
        sys.exit(1)

    print(f"[*] Stap 1: EDIF omzetten naar Verilog ({v_file}) via SpydrNet...")
    try:
        # Lees EDIF in en schrijf het direct weer weg als Verilog
        netlist = sdn.parse(edif_file)
        sdn.compose(netlist, v_file)
    except Exception as e:
        print(f"Fout tijdens SpydrNet conversie: {e}")
        sys.exit(1)

    print(f"[*] Stap 2: Verilog omzetten naar BLIF en AIG via Yosys...")
    
    # Yosys commando's: 
    # 1. Lees de gegenereerde Verilog
    # 2. Doe een generieke synthese (raadt automatisch de top-module)
    # 3. Schrijf de BLIF file
    # 4. Map de logica naar een And-Inverter Graph (aigmap is vereist voor aiger output)
    # 5. Schrijf de AIGER file
    yosys_cmds = f"read_verilog {v_file}; synth -auto-top; write_blif {blif_file}; aigmap; write_aiger {aig_file}"
    
    try:
        # Roep Yosys stilletjes op de achtergrond aan
        subprocess.run(["yosys", "-p", yosys_cmds], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        
        print("\n[+] Succes! De volgende bestanden zijn gegenereerd:")
        print(f"    - {blif_file}")
        print(f"    - {aig_file}")
        
    except FileNotFoundError:
        print("\nFout: Yosys kon niet worden gevonden. Zorg dat het is geïnstalleerd en in je systeem PATH staat.")
    except subprocess.CalledProcessError:
        print("\nFout: Yosys liep vast tijdens de synthese. Controleer of de gegenereerde Verilog geldig is.")
    finally:
        # Ruim het tijdelijke Verilog bestand op, tenzij de user --keep-v meegaf
        if not args.keep_v and os.path.exists(v_file):
            os.remove(v_file)
            print(f"[*] Tijdelijk bestand {v_file} is weer netjes opgeruimd.")

if __name__ == "__main__":
    main()
