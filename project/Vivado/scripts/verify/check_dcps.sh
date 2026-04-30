#!/bin/bash

# Controleer of de juiste argumenten zijn meegegeven
if [ "$#" -ne 2 ]; then
    echo "Gebruik: $0 <originele_dcp_bestand> <map_met_aangepaste_dcp_bestanden>"
    exit 1
fi

ORIGINELE_DCP="$1"
DCP_MAP="$2"

# Controleer of de Vivado executable beschikbaar is
if ! command -v vivado &> /dev/null; then
    echo -e "\e[31mFout: Vivado is niet gevonden in de PATH.\e[0m"
    echo "Vergeet niet Vivado in te laden (bijv. source /opt/Xilinx/Vivado/<versie>/settings64.sh)"
    exit 1
fi

# Tijdelijk Tcl-script aanmaken voor Vivado om de check uit te voeren
TCL_SCRIPT=$(mktemp)
cat << 'EOF' > "$TCL_SCRIPT"
set dcp_file [lindex $argv 0]
# Probeer de checkpoint in te lezen
if { [catch {open_checkpoint $dcp_file} result] } {
    puts "FOUT_BIJ_INLEZEN: $result"
    exit 1
} else {
    exit 0
}
EOF

echo "=================================================="
echo "DCP Validatie Script via Vivado"
echo "=================================================="

# Stap 1: Controleer eerst het originele bestand (Sanity Check)
echo -n "Controleer originele DCP ($ORIGINELE_DCP)... "
if vivado -mode batch -nolog -nojournal -source "$TCL_SCRIPT" -tclargs "$ORIGINELE_DCP" &> /dev/null; then
    echo -e "\e[32m[OK]\e[0m"
else
    echo -e "\e[31m[FOUT]\e[0m"
    echo "Kan de originele DCP niet openen! Controleer of het bestand corrupt is. Script stopt."
    rm -f "$TCL_SCRIPT"
    exit 1
fi

echo "--------------------------------------------------"
echo "Controleer aangepaste bestanden in map: '$DCP_MAP'"

# Stap 2: Loop over alle DCP bestanden in de folder
for dcp in "$DCP_MAP"/*.dcp; do
    # Controleer of de loop niet struikelt over een lege map
    if [ ! -f "$dcp" ]; then
        echo "Geen .dcp bestanden gevonden in $DCP_MAP."
        break
    fi

    echo -n "  -> Inlezen van $(basename "$dcp")... "

    # Voer Vivado uit en vang de output op
    # -nolog en -nojournal zorgen dat je map niet vol raakt met vivado.log bestanden
    VIVADO_OUT=$(vivado -mode batch -nolog -nojournal -source "$TCL_SCRIPT" -tclargs "$dcp" 2>&1)
    
    # Controleer de exit-code van het Tcl-script
    if [ $? -eq 0 ]; then
        echo -e "\e[32m[GELDIG]\e[0m"
    else
        echo -e "\e[31m[ONGELDIG]\e[0m"
        # Print de specifieke ERROR uit Vivado zodat je weet wát er mis ging via RapidWright
        echo "$VIVADO_OUT" | grep "ERROR" | head -n 2 | sed 's/^/       /'
    fi
done

# Ruim het tijdelijke Tcl-script op
rm -f "$TCL_SCRIPT"
echo "=================================================="
echo "Validatie voltooid!"
