import json
import sys
import os

def check_care_set_json(file_path):
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"❌ Fout bij laden van bestand: {e}")
        return

    pivot = data.get("pivot", "Onbekend")
    s_count = data.get("s_count", 0)
    s_list = data.get("S", [])
    care_minterms = data.get("care_minterms", [])

    print(f"=== Analyse van Pivot {pivot} ===")

    # 1. Check lengte van bitstrings
    # In de paper is s_count de grootte van de lokale inputruimte Y [cite: 65, 88, 195]
    wrong_lengths = [m for m in care_minterms if len(m) != s_count]
    if not wrong_lengths:
        print(f"✅ Lengte: Alle bitstrings zijn exact {s_count} bits lang.")
    else:
        print(f"❌ Lengte: {len(wrong_lengths)} strings hebben een foutieve lengte!")
        print(f"   Verwacht: {s_count}, Gevonden o.a.: {len(wrong_lengths[0])}")

    # 2. Check voor duplicaten
    # Simulatie verzamelt unieke care minterms 
    unique_minterms = set(care_minterms)
    num_total = len(care_minterms)
    num_unique = len(unique_minterms)
    
    if num_total == num_unique:
        print(f"✅ Duplicaten: Geen dubbele entries gevonden ({num_total} unieke minterms).")
    else:
        duplicates = num_total - num_unique
        print(f"❌ Duplicaten: {duplicates} dubbele strings gevonden!")
        # Toon een voorbeeld van een duplicaat voor debugging
        seen = set()
        for m in care_minterms:
            if m in seen:
                print(f"   Voorbeeld duplicaat: {m}")
                break
            seen.add(m)

    # 3. Check of S vast en gesorteerd is
    # Consistentie in de set Y is cruciaal voor de ALL-SAT formulering [cite: 88, 184]
    if s_list == sorted(s_list):
        print(f"✅ S-Volgorde: De lijst S is correct gesorteerd.")
    else:
        print(f"❌ S-Volgorde: De lijst S is NIET gesorteerd!")

    print("=" * 30)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Gebruik: python3 check_json.py <jouw_bestand.json>")
    else:
        check_care_set_json(sys.argv[1])
