import sys
import json
import os

def verify(baseline_dir, eco_dir, net_naam, lut_b_naam):
    base_json = os.path.join(baseline_dir, 'lut_connections.json')
    eco_json = os.path.join(eco_dir, 'lut_connections.json')

    with open(base_json, 'r') as f:
        base_data = json.load(f)
    with open(eco_json, 'r') as f:
        eco_data = json.load(f)

    print("\n=============================================")
    print("           ECO VERIFICATIE RAPPORT           ")
    print("=============================================")
    print(f"Aantal originele connecties: {len(base_data)}")
    print(f"Aantal connecties na ECO:    {len(eco_data)}\n")

    # 1. Check algemene toename
    if len(eco_data) > len(base_data):
        print("[✓] Totaal aantal connecties is correct gestegen.")
    else:
        print("[X] Totaal aantal connecties is NIET gestegen!")

    # 2. Check of originele connectie weg is
    orig_found_in_eco = any(c['net'] == net_naam and c['to'] == lut_b_naam for c in eco_data)
    if not orig_found_in_eco:
        print(f"[✓] Originele connectie ({net_naam} -> {lut_b_naam}) is succesvol verbroken.")
    else:
        print(f"[X] Originele connectie bestaat nog steeds!")

    # 3. BEWIJS DAT DE NIEUWE CONNECTIES BESTAAN
    # Op basis van onze Java code conventies:
    lut_c_naam = net_naam + "_buffer"
    nieuwe_net_naam = net_naam + "_split"

    # 3a: Bestaat de verbinding van LUT A naar de nieuwe buffer (LUT C)?
    # We verwachten dat de originele net nu als 'to' de nieuwe buffer heeft
    verbinding_naar_c = any(c['net'] == net_naam and c['to'] == lut_c_naam for c in eco_data)

    # 3b: Bestaat de verbinding van de nieuwe buffer (LUT C) naar LUT B?
    # We verwachten een nieuwe net die vertrekt bij LUT C en aankomt bij LUT B
    verbinding_van_c_naar_b = any(
        c['net'] == nieuwe_net_naam and 
        c['from'] == lut_c_naam and 
        c['to'] == lut_b_naam 
        for c in eco_data
    )

    if verbinding_naar_c:
        print(f"[✓] Succes: Oude net gaat nu netjes de nieuwe buffer in ({lut_c_naam}).")
    else:
        print(f"[X] FOUT: Kon de connectie naar de nieuwe buffer NIET vinden!")

    if verbinding_van_c_naar_b:
        print(f"[✓] Succes: Buffer is correct verbonden met target LUT ({lut_c_naam} -> {lut_b_naam}).")
    else:
        print(f"[X] FOUT: Kon de connectie van de buffer naar de target LUT NIET vinden!")

    # 4. EINDOORDEEL
    print("\n---------------------------------------------")
    if not orig_found_in_eco and verbinding_naar_c and verbinding_van_c_naar_b:
        print(">>> CONCLUSIE: ECO is 100% SUCCESVOL! <<<")
    else:
        print(">>> CONCLUSIE: ECO is MISLUKT of ONVOLLEDIG! <<<")
    print("=============================================\n")


if __name__ == "__main__":
    # We verwachten nu 4 argumenten in plaats van 2
    if len(sys.argv) != 5:
        print("Gebruik: python3 verify_eco.py <baseline_dir> <eco_dir> <net_naam> <lut_b_naam>")
        sys.exit(1)
    
    baseline = sys.argv[1]
    eco = sys.argv[2]
    TARGET_NET = sys.argv[3]
    TARGET_LUT_B = sys.argv[4]
    
    verify(baseline, eco, TARGET_NET, TARGET_LUT_B)
