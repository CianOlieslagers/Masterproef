#!/bin/bash

# --- CONTROLEER OP ARGUMENT ---
if [ -z "$1" ]; then
    echo "Fout: Geen configuratiebestand opgegeven."
    echo "Gebruik: ./project/Vivado/scripts/run_lut_insertion.sh <config_file.conf>"
    exit 1
fi

CONFIG_FILE="$1"

# --- LAAD DE VARIABELEN IN ---
if [ -f "$CONFIG_FILE" ]; then
    source "$CONFIG_FILE"
else
    echo "Fout: Configuratiebestand '$CONFIG_FILE' niet gevonden."
    exit 1
fi

# --- DYNAMISCHE DIRECTORY STRUCTUUR AANMAKEN ---
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
COMMAND_NAME="run_lut_insertion"
RESULT_DIR="$PROJ_DIR/results/$COMMAND_NAME/$TIMESTAMP"

# Definieer de submappen voor deze specifieke run
IMPL_DIR="$RESULT_DIR/baseline_impl"
ECO_DCP="$RESULT_DIR/dcp/test_eco_output.dcp"
REPORT_DIR_BEFORE="$RESULT_DIR/reports_baseline"
REPORT_DIR_AFTER="$RESULT_DIR/reports_eco"
LOG_DIR="$RESULT_DIR/logs"

# Maak de mappen aan
mkdir -p "$IMPL_DIR"
mkdir -p "$RESULT_DIR/dcp"
mkdir -p "$REPORT_DIR_BEFORE"
mkdir -p "$REPORT_DIR_AFTER"
mkdir -p "$LOG_DIR"

echo "========================================"
echo "      START VOLLEDIGE ECO PIPELINE      "
echo "========================================"
echo "Target Net:  $TARGET_NET"
echo "Target Sink: $TARGET_LUT_B"
echo "Target Loc:  $TARGET_SLICE"
echo "Output Map:  $RESULT_DIR"
echo "========================================"

# --- STAP 0: VIVADO IMPLEMENTATIE (VERILOG -> DCP) ---
echo -e "\n[STAP 0] Genereren Basis Implementatie (Synthese & Place)..."
vivado -mode batch -log "$LOG_DIR/vivado_impl.log" -journal "$LOG_DIR/vivado_impl.jou" -source "$PROJ_DIR/Vivado/scripts/run_impl_timing.tcl" -tclargs "$IMPL_DIR" "$SRC_FILE" "$TOP_MODULE" "$PART_NUMBER" "$XDC_FILE"


# Koppel de zojuist gegenereerde DCP aan onze ORIGINAL_DCP variabele
ORIGINAL_DCP="$IMPL_DIR/checkpoints/post_place_timingexp.dcp"

# Kleine veiligheidscheck om te zien of Stap 0 is gelukt
if [ ! -f "$ORIGINAL_DCP" ]; then
    echo "CRITIEKE FOUT: Vivado heeft de post_place_timingexp.dcp niet kunnen genereren!"
    echo "Kijk in $LOG_DIR/vivado_impl.log voor details."
    exit 1
fi

# --- STAP 1: BASELINE DATA EXTRACTIE ---
echo -e "\n[STAP 1] Data Extractie van Original DCP..."
$ECO_DIR/scripts/pipeline/export_dcp_summary.sh "$ORIGINAL_DCP" "$REPORT_DIR_BEFORE"
vivado -mode batch -log "$LOG_DIR/vivado_baseline_extract.log" -journal "$LOG_DIR/vivado_baseline_extract.jou" -source "$PROJ_DIR/Vivado/scripts/old/extract_connectivity.tcl" -tclargs "$ORIGINAL_DCP" "$REPORT_DIR_BEFORE/connectivity.csv"
python3 "$PROJ_DIR/Vivado/scripts/generate_Json_Full.py" "$REPORT_DIR_BEFORE"


# --- STAP 2: DE AANPASSING (RAPIDWRIGHT ECO) ---
echo -e "\n[STAP 2] RapidWright ECO Uitvoeren..."
cd "$MASTER_DIR" || exit
java -cp "$RAPIDWRIGHT_JAR:$PROJ_DIR/Readwright/scripts" InsertBufferECO \
  "$ORIGINAL_DCP" \
  "$ECO_DCP" \
  "$TARGET_LUT_B" \
  "$TARGET_NET" \
  "$TARGET_SLICE" > "$LOG_DIR/rapidwright_eco.log" 2>&1


# --- STAP 3: VERIFICATIE DATA EXTRACTIE (NA DE ECO) ---
echo -e "\n[STAP 3] Data Extractie van Modified DCP..."
$ECO_DIR/scripts/pipeline/export_dcp_summary.sh "$ECO_DCP" "$REPORT_DIR_AFTER"
vivado -mode batch -log "$LOG_DIR/vivado_eco_extract.log" -journal "$LOG_DIR/vivado_eco_extract.jou" -source "$PROJ_DIR/Vivado/scripts/old/extract_connectivity.tcl" -tclargs "$ECO_DCP" "$REPORT_DIR_AFTER/connectivity.csv"
python3 "$PROJ_DIR/Vivado/scripts/generate_Json_Full.py" "$REPORT_DIR_AFTER"


# --- STAP 4: DE VERGELIJKING ---
echo -e "\n[STAP 4] Vergelijking & Verificatie..."
python3 "$PROJ_DIR/Vivado/scripts/verify/verify_lut_insertion.py" "$REPORT_DIR_BEFORE" "$REPORT_DIR_AFTER" "$TARGET_NET" "$TARGET_LUT_B" | tee "$LOG_DIR/verification_result.log"

# --- STAP 5: VIVADO ROUTING & TIMING CHECK ---
echo -e "\n[STAP 5] Fysieke Verificatie in Vivado (Routing & Timing)..."
VERIFY_DIR="$RESULT_DIR/final_verification"
mkdir -p "$VERIFY_DIR"

vivado -mode batch -log "$LOG_DIR/vivado_eco_verify.log" -journal "$LOG_DIR/vivado_eco_verify.jou" -source "$PROJ_DIR/Vivado/scripts/verify/verify_lut_insert_routing.tcl" -tclargs "$ECO_DCP" "$VERIFY_DIR"

# Simpele check of het TCL script succesvol de final DCP heeft gemaakt
if [ -f "$VERIFY_DIR/final_routed_eco.dcp" ]; then
    echo "[SUCCES] Vivado heeft de ECO geaccepteerd en succesvol gerouteerd!"
    echo "         Timing rapport staat in: $VERIFY_DIR/eco_post_route_timing.rpt"
else
    echo "[FOUT] Vivado weigert de ECO te routen. Check $LOG_DIR/vivado_eco_verify.log voor DRC errors!"
fi


echo "========================================"
echo " Pipeline succesvol voltooid!           "
echo " Alle resultaten staan in:              "
echo " $RESULT_DIR                            "
echo "========================================"
