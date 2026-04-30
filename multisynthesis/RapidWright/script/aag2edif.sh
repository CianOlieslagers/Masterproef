#!/bin/bash

# Controleer of de gebruiker precies 2 argumenten heeft meegegeven
if [ "$#" -ne 2 ]; then
    echo "Fout: Onjuist aantal argumenten."
    echo "Gebruik: $0 <pad_naar_input.aag> <pad_naar_output.edf>"
    exit 1
fi

INPUT_AAG=$1
OUTPUT_EDIF=$2

echo "🚀 Start conversie van $INPUT_AAG naar $OUTPUT_EDIF..."

# Yosys in batch mode (-q voor quiet, of haal -q weg als je de logs wilt zien)


yosys -q -p "read_aiger $INPUT_AAG; synth_xilinx -flatten; clean -purge; write_edif $OUTPUT_EDIF"
# Check of het bestand daadwerkelijk is aangemaakt
if [ -f "$OUTPUT_EDIF" ]; then
    echo "✅ Succes: EDIF bestand opgeslagen op $OUTPUT_EDIF"
else
    echo "❌ Fout: EDIF bestand is niet aangemaakt. Haal de '-q' flag weg in het script om de Yosys errors te lezen."
    exit 1
fi
