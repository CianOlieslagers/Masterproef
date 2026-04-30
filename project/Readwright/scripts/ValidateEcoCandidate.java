import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

import com.xilinx.rapidwright.design.Cell;
import com.xilinx.rapidwright.design.Design;
import com.xilinx.rapidwright.design.DesignTools;
import com.xilinx.rapidwright.design.Net;
import com.xilinx.rapidwright.design.SiteInst;
import com.xilinx.rapidwright.design.SitePinInst;
import com.xilinx.rapidwright.tests.CodePerfTracker;

public class ValidateEcoCandidate {

    private static boolean isLutType(String t) {
        if (t == null) return false;
        String u = t.toUpperCase(Locale.ROOT);
        return u.matches("^LUT[1-6]$");
    }

    private static boolean isSliceSite(String siteName) {
        return siteName != null && siteName.startsWith("SLICE_");
    }

    private static boolean isLutInputPin(String p) {
        if (p == null) return false;
        return p.matches("^I[0-5]$");
    }

    public static void main(String[] args) {
        if (args.length != 5) {
            System.err.println("Gebruik:");
            System.err.println("java ValidateEcoCandidate <dcp> <net> <source_cell> <sink_cell> <sink_pin>");
            System.exit(1);
        }

        String dcpPath = args[0];
        String netName = args[1];
        String sourceCellName = args[2];
        String sinkCellName = args[3];
        String sinkLogicalPin = args[4];

        try {
            Design design = Design.readCheckpoint(dcpPath, CodePerfTracker.SILENT);
            DesignTools.updatePinsIsRouted(design);

            Net net = design.getNet(netName);
            if (net == null) {
                printResult(false, "NET_NOT_FOUND", netName, sourceCellName, sinkCellName, sinkLogicalPin,
                        "", "", "", "", "", "", "", "", "", false, false, false, false, false, false, false);
                return;
            }

            Cell sourceCell = design.getCell(sourceCellName);
            if (sourceCell == null) {
                printResult(false, "SOURCE_CELL_NOT_FOUND", netName, sourceCellName, sinkCellName, sinkLogicalPin,
                        "", "", "", "", "", "", "", "", "", false, false, false, false, false, false, false);
                return;
            }

            Cell sinkCell = design.getCell(sinkCellName);
            if (sinkCell == null) {
                printResult(false, "SINK_CELL_NOT_FOUND", netName, sourceCellName, sinkCellName, sinkLogicalPin,
                        sourceCell.getType(), "", "", "", "", "", "", "", "", false, false, false, false, false, false, false);
                return;
            }

            String sourceType = sourceCell.getType();
            String sinkType = sinkCell.getType();

            boolean sourceIsLut = isLutType(sourceType);
            boolean sinkIsLut = isLutType(sinkType);

            SiteInst sourceSiteInst = sourceCell.getSiteInst();
            SiteInst sinkSiteInst = sinkCell.getSiteInst();

            String sourceSiteName = sourceSiteInst != null ? sourceSiteInst.getName() : "";
            String sinkSiteName = sinkSiteInst != null ? sinkSiteInst.getName() : "";

            boolean sourceOnSlice = isSliceSite(sourceSiteName);
            boolean sinkOnSlice = isSliceSite(sinkSiteName);

            String sourceBelName = sourceCell.getBELName();
            String sinkBelName = sinkCell.getBELName();

            boolean sourceBelIsLut = sourceBelName != null && sourceBelName.toUpperCase(Locale.ROOT).contains("LUT");
            boolean sinkBelIsLut = sinkBelName != null && sinkBelName.toUpperCase(Locale.ROOT).contains("LUT");

            boolean sinkPinValid = isLutInputPin(sinkLogicalPin);

            // Belangrijk: source niet meer afleiden uit physical net source.
            // We gebruiken de logische source cell uit de kandidaatmetadata.
            String sourceOutputPhysicalPin = null;
            try {
                sourceOutputPhysicalPin = sourceCell.getPhysicalPinMapping("O");
            } catch (Exception e) {
                sourceOutputPhysicalPin = null;
            }
            boolean sourceOutputResolvable = sourceOutputPhysicalPin != null && !sourceOutputPhysicalPin.isEmpty();

            List<String> sinkSiteWires = new ArrayList<>();
            SitePinInst sinkSitePin = null;
            try {
                sinkSitePin = sinkCell.getSitePinFromLogicalPin(sinkLogicalPin, sinkSiteWires);
            } catch (Exception e) {
                sinkSitePin = null;
            }
            boolean sinkPinResolvable = sinkSitePin != null;

            // Optionele sanity check: zit de sink physical pin echt op het net?
            boolean sinkPinOnNet = false;
            if (sinkSitePin != null) {
                for (SitePinInst p : net.getPins()) {
                    if (p == null) continue;
                    if (p.getSiteInst() == null) continue;
                    if (sinkSitePin.getSiteInst() == null) continue;

                    String a = p.getSiteInst().getName() + "." + p.getName();
                    String b = sinkSitePin.getSiteInst().getName() + "." + sinkSitePin.getName();
                    if (a.equals(b)) {
                        sinkPinOnNet = true;
                        break;
                    }
                }
            }

            boolean valid =
                    sourceIsLut &&
                    sinkIsLut &&
                    sourceOnSlice &&
                    sinkOnSlice &&
                    sourceBelIsLut &&
                    sinkBelIsLut &&
                    sourceOutputResolvable &&
                    sinkPinValid &&
                    sinkPinResolvable;

            String reason = valid ? "OK" : buildReason(
                    sourceIsLut,
                    sinkIsLut,
                    sourceOnSlice,
                    sinkOnSlice,
                    sourceBelIsLut,
                    sinkBelIsLut,
                    sourceOutputResolvable,
                    sinkPinValid,
                    sinkPinResolvable
            );

            printResult(
                    valid,
                    reason,
                    netName,
                    sourceCellName,
                    sinkCellName,
                    sinkLogicalPin,
                    sourceType,
                    sinkType,
                    sourceSiteName,
                    sinkSiteName,
                    sourceBelName,
                    sinkBelName,
                    sourceOutputPhysicalPin != null ? sourceOutputPhysicalPin : "",
                    sinkSitePin != null ? (sinkSitePin.getSiteInst().getName() + "." + sinkSitePin.getName()) : "",
                    net.getSource() != null ? (net.getSource().getSiteInstName() + "." + net.getSource().getName()) : "",
                    sourceIsLut,
                    sinkIsLut,
                    sourceOnSlice,
                    sinkOnSlice,
                    sourceOutputResolvable,
                    sinkPinValid,
                    sinkPinResolvable || sinkPinOnNet
            );

        } catch (Exception e) {
            System.err.println("FOUT: " + e.getClass().getSimpleName() + " - " + e.getMessage());
            e.printStackTrace(System.err);
            System.exit(2);
        }
    }

    private static String buildReason(
            boolean sourceIsLut,
            boolean sinkIsLut,
            boolean sourceOnSlice,
            boolean sinkOnSlice,
            boolean sourceBelIsLut,
            boolean sinkBelIsLut,
            boolean sourceOutputResolvable,
            boolean sinkPinValid,
            boolean sinkPinResolvable
    ) {
        List<String> reasons = new ArrayList<>();

        if (!sourceIsLut) reasons.add("SOURCE_CELL_NOT_LUT");
        if (!sinkIsLut) reasons.add("SINK_CELL_NOT_LUT");
        if (!sourceOnSlice) reasons.add("SOURCE_NOT_ON_SLICE");
        if (!sinkOnSlice) reasons.add("SINK_NOT_ON_SLICE");
        if (!sourceBelIsLut) reasons.add("SOURCE_BEL_NOT_LUT");
        if (!sinkBelIsLut) reasons.add("SINK_BEL_NOT_LUT");
        if (!sourceOutputResolvable) reasons.add("SOURCE_OUTPUT_NOT_RESOLVABLE");
        if (!sinkPinValid) reasons.add("SINK_PIN_NOT_I0_TO_I5");
        if (!sinkPinResolvable) reasons.add("SINK_PIN_NOT_RESOLVABLE");

        return String.join("|", reasons);
    }

    private static void printResult(
            boolean valid,
            String reason,
            String netName,
            String sourceCellName,
            String sinkCellName,
            String sinkLogicalPin,
            String sourceType,
            String sinkType,
            String sourceSiteName,
            String sinkSiteName,
            String sourceBelName,
            String sinkBelName,
            String sourceOutputPhysicalPin,
            String sinkPhysicalPin,
            String netPhysicalSource,
            boolean sourceIsLut,
            boolean sinkIsLut,
            boolean sourceOnSlice,
            boolean sinkOnSlice,
            boolean sourceOutputResolvable,
            boolean sinkPinValid,
            boolean sinkPinResolvable
    ) {
        System.out.printf(
                Locale.US,
                "RESULT_JSON: {\"valid\": %s, \"reason\": \"%s\", \"net\": \"%s\", \"source_cell\": \"%s\", \"sink_cell\": \"%s\", \"sink_pin\": \"%s\", \"source_type\": \"%s\", \"sink_type\": \"%s\", \"source_site\": \"%s\", \"sink_site\": \"%s\", \"source_bel\": \"%s\", \"sink_bel\": \"%s\", \"source_output_physical_pin\": \"%s\", \"sink_physical_pin\": \"%s\", \"net_physical_source\": \"%s\", \"source_is_lut\": %s, \"sink_is_lut\": %s, \"source_on_slice\": %s, \"sink_on_slice\": %s, \"source_output_resolvable\": %s, \"sink_pin_valid\": %s, \"sink_pin_resolvable\": %s}%n",
                valid ? "true" : "false",
                escape(reason),
                escape(netName),
                escape(sourceCellName),
                escape(sinkCellName),
                escape(sinkLogicalPin),
                escape(sourceType),
                escape(sinkType),
                escape(sourceSiteName),
                escape(sinkSiteName),
                escape(sourceBelName),
                escape(sinkBelName),
                escape(sourceOutputPhysicalPin),
                escape(sinkPhysicalPin),
                escape(netPhysicalSource),
                sourceIsLut ? "true" : "false",
                sinkIsLut ? "true" : "false",
                sourceOnSlice ? "true" : "false",
                sinkOnSlice ? "true" : "false",
                sourceOutputResolvable ? "true" : "false",
                sinkPinValid ? "true" : "false",
                sinkPinResolvable ? "true" : "false"
        );
    }

    private static String escape(String s) {
        if (s == null) return "";
        return s.replace("\\", "\\\\").replace("\"", "\\\"");
    }
}
