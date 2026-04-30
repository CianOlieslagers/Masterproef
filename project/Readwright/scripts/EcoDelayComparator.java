import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

import com.xilinx.rapidwright.design.Cell;
import com.xilinx.rapidwright.design.Design;
import com.xilinx.rapidwright.design.DesignTools;
import com.xilinx.rapidwright.design.Net;
import com.xilinx.rapidwright.design.SiteInst;
import com.xilinx.rapidwright.design.SitePinInst;
import com.xilinx.rapidwright.device.SiteTypeEnum;
import com.xilinx.rapidwright.tests.CodePerfTracker;
import com.xilinx.rapidwright.timing.DelayModel;
import com.xilinx.rapidwright.timing.TimingManager;
import com.xilinx.rapidwright.timing.TimingModel;

public class EcoDelayComparator {

    private static class DelayResult {
        String dcpPath;
        String netName;
        String sourceSitePin;
        String sinkSitePin;
        float delayPs;

        DelayResult(String dcpPath, String netName, String sourceSitePin, String sinkSitePin, float delayPs) {
            this.dcpPath = dcpPath;
            this.netName = netName;
            this.sourceSitePin = sourceSitePin;
            this.sinkSitePin = sinkSitePin;
            this.delayPs = delayPs;
        }
    }

    private static class InternalDelayResult {
        String bufferCell;
        String belName;
        String siteName;
        String siteType;
        String inputSitePin;
        String inputBelPin;
        String outputBelPin;
        String outputSitePin;
        float inputIntraSitePs;
        float logicPs;
        float outputIntraSitePs;
        float totalPs;

        InternalDelayResult(
                String bufferCell,
                String belName,
                String siteName,
                String siteType,
                String inputSitePin,
                String inputBelPin,
                String outputBelPin,
                String outputSitePin,
                float inputIntraSitePs,
                float logicPs,
                float outputIntraSitePs
        ) {
            this.bufferCell = bufferCell;
            this.belName = belName;
            this.siteName = siteName;
            this.siteType = siteType;
            this.inputSitePin = inputSitePin;
            this.inputBelPin = inputBelPin;
            this.outputBelPin = outputBelPin;
            this.outputSitePin = outputSitePin;
            this.inputIntraSitePs = inputIntraSitePs;
            this.logicPs = logicPs;
            this.outputIntraSitePs = outputIntraSitePs;
            this.totalPs = inputIntraSitePs + logicPs + outputIntraSitePs;
        }
    }

    public static void main(String[] args) {
        if (args.length != 8) {
            System.err.println("Gebruik:");
            System.err.println("java EcoDelayComparator <baseline_dcp> <eco_dcp> <baseline_net> <split_net> <buffer_cell> <sink_cell> <sink_pin> <lut_delay_ps_ignored>");
            System.exit(1);
        }

        String baselineDcp = args[0];
        String ecoDcp      = args[1];
        String baselineNet = args[2];
        String splitNet    = args[3];
        String bufferCell  = args[4];
        String sinkCell    = args[5];
        String sinkPin     = args[6];

        // We lezen hem nog in voor compatibiliteit met je huidige script,
        // maar gebruiken hem niet meer in de berekening.
        float legacyLutDelayPs = Float.parseFloat(args[7]);

        CodePerfTracker t = new CodePerfTracker("ECO Delay Comparator");
        t.useGCToTrackMemory(true);

        try {
            DelayResult baseline = measureNetDelayToCellPin(
                    baselineDcp, baselineNet, sinkCell, sinkPin, "BASELINE direct");

            DelayResult ecoSeg1 = measureNetDelayToCellPin(
                    ecoDcp, baselineNet, bufferCell, "I0", "ECO segment 1");

            DelayResult ecoSeg2 = measureNetDelayToCellPin(
                    ecoDcp, splitNet, sinkCell, sinkPin, "ECO segment 2");

            InternalDelayResult ecoInternal = measureBufferInternalDelay(
                    ecoDcp, baselineNet, splitNet, bufferCell, "I0", "O", "ECO LUT internal");

            float ecoInterconnectPs = ecoSeg1.delayPs + ecoSeg2.delayPs;
            float ecoTotalWithInternalPs = ecoSeg1.delayPs + ecoInternal.totalPs + ecoSeg2.delayPs;

            float deltaInterconnectPs = ecoInterconnectPs - baseline.delayPs;
            float deltaTotalPs = ecoTotalWithInternalPs - baseline.delayPs;

            System.out.println();
            System.out.println("==================================================");
            System.out.println("RESULTAAT");
            System.out.println("==================================================");
            printResult("Baseline direct", baseline);
            printResult("ECO segment 1", ecoSeg1);
            printResult("ECO segment 2", ecoSeg2);
            printInternalDelayResult("ECO LUT internal", ecoInternal);

            System.out.println();
            System.out.printf(Locale.US, "legacy_lut_delay_ps         = %.3f  (niet meer gebruikt)%n", legacyLutDelayPs);
            System.out.printf(Locale.US, "eco_total_interconnect_ps   = %.3f%n", ecoInterconnectPs);
            System.out.printf(Locale.US, "eco_total_with_internal_ps  = %.3f%n", ecoTotalWithInternalPs);
            System.out.printf(Locale.US, "delta_interconnect_ps       = %.3f%n", deltaInterconnectPs);
            System.out.printf(Locale.US, "delta_total_ps              = %.3f%n", deltaTotalPs);

            if (deltaTotalPs < 0.0f) {
                System.out.println("BESLISSING_TOTAL: ECO is gunstig inclusief RapidWright internal LUT delay.");
            } else if (deltaTotalPs > 0.0f) {
                System.out.println("BESLISSING_TOTAL: ECO is ongunstig inclusief RapidWright internal LUT delay.");
            } else {
                System.out.println("BESLISSING_TOTAL: ECO is gelijk inclusief RapidWright internal LUT delay.");
            }

            System.out.println();
            System.out.printf(
                Locale.US,
                "RESULT_JSON: {\"baseline_ps\": %.3f, \"eco_seg1_ps\": %.3f, \"eco_internal_input_intrasite_ps\": %.3f, \"eco_internal_logic_ps\": %.3f, \"eco_internal_output_intrasite_ps\": %.3f, \"eco_internal_total_ps\": %.3f, \"eco_seg2_ps\": %.3f, \"eco_interconnect_ps\": %.3f, \"eco_total_ps\": %.3f, \"delta_interconnect_ps\": %.3f, \"delta_total_ps\": %.3f}%n",
                baseline.delayPs,
                ecoSeg1.delayPs,
                ecoInternal.inputIntraSitePs,
                ecoInternal.logicPs,
                ecoInternal.outputIntraSitePs,
                ecoInternal.totalPs,
                ecoSeg2.delayPs,
                ecoInterconnectPs,
                ecoTotalWithInternalPs,
                deltaInterconnectPs,
                deltaTotalPs
            );

            t.printSummary();

        } catch (Exception e) {
            System.err.println("FOUT: " + e.getClass().getSimpleName() + " - " + e.getMessage());
            e.printStackTrace(System.err);
            System.exit(2);
        }
    }

    private static DelayResult measureNetDelayToCellPin(
            String dcpPath,
            String netName,
            String sinkCellName,
            String sinkLogicalPin,
            String label
    ) {
        System.out.println();
        System.out.println("--------------------------------------------------");
        System.out.println(label);
        System.out.println("--------------------------------------------------");
        System.out.println("DCP       : " + dcpPath);
        System.out.println("Net       : " + netName);
        System.out.println("Sink cell : " + sinkCellName);
        System.out.println("Sink pin  : " + sinkLogicalPin);

        Design design = Design.readCheckpoint(dcpPath, CodePerfTracker.SILENT);
        DesignTools.updatePinsIsRouted(design);

        Net net = design.getNet(netName);
        if (net == null) {
            throw new RuntimeException("Net niet gevonden: " + netName);
        }

        Cell sinkCell = design.getCell(sinkCellName);
        if (sinkCell == null) {
            throw new RuntimeException("Cell niet gevonden: " + sinkCellName);
        }

        SitePinInst sourcePin = net.getSource();
        if (sourcePin == null) {
            throw new RuntimeException("Net heeft geen source pin: " + netName);
        }

        List<String> siteWires = new ArrayList<>();
        SitePinInst sinkPin = sinkCell.getSitePinFromLogicalPin(sinkLogicalPin, siteWires);
        if (sinkPin == null) {
            throw new RuntimeException("Kon fysieke sink-pin niet bepalen voor " + sinkCellName + "/" + sinkLogicalPin);
        }

        TimingManager tm = new TimingManager(design);
        TimingModel timingModel = tm.getTimingModel();
        float delayPs = timingModel.calcDelay(sourcePin, sinkPin, net);

        System.out.println("Source physical pin : " + sourcePin.getSiteInstName() + "." + sourcePin.getSitePinName());
        System.out.println("Sink physical pin   : " + sinkPin.getSiteInstName() + "." + sinkPin.getSitePinName());
        System.out.printf(Locale.US, "Delay (ps)          : %.3f%n", delayPs);
        System.out.printf(Locale.US, "Delay (ns)          : %.6f%n", delayPs / 1000.0);

        return new DelayResult(
                dcpPath,
                netName,
                sourcePin.getSiteInstName() + "." + sourcePin.getSitePinName(),
                sinkPin.getSiteInstName() + "." + sinkPin.getSitePinName(),
                delayPs
        );
    }

    private static InternalDelayResult measureBufferInternalDelay(
            String ecoDcp,
            String entryNetName,
            String exitNetName,
            String bufferCellName,
            String inputLogicalPin,
            String outputLogicalPin,
            String label
    ) {
        System.out.println();
        System.out.println("--------------------------------------------------");
        System.out.println(label);
        System.out.println("--------------------------------------------------");

        Design design = Design.readCheckpoint(ecoDcp, CodePerfTracker.SILENT);
        DesignTools.updatePinsIsRouted(design);

        Cell bufferCell = design.getCell(bufferCellName);
        if (bufferCell == null) {
            throw new RuntimeException("Buffer cell niet gevonden: " + bufferCellName);
        }

        SiteInst siteInst = bufferCell.getSiteInst();
        if (siteInst == null) {
            throw new RuntimeException("Buffer cell heeft geen SiteInst: " + bufferCellName);
        }

        String belName = bufferCell.getBELName();
        if (belName == null) {
            throw new RuntimeException("Buffer cell heeft geen BEL naam: " + bufferCellName);
        }

        SiteTypeEnum siteType = siteInst.getSiteTypeEnum();
        TimingManager tm = new TimingManager(design);
        TimingModel timingModel = tm.getTimingModel();
        DelayModel delayModel = timingModel.getDelayModel();

        // 1) Welke fysieke BEL-pinnen gebruikt deze LUT echt?
        String inputBelPinName = bufferCell.getPhysicalPinMapping(inputLogicalPin);
        String outputBelPinName = bufferCell.getPhysicalPinMapping(outputLogicalPin);

        if (inputBelPinName == null) {
            throw new RuntimeException("Geen fysieke input BEL-pin mapping voor " + bufferCellName + "/" + inputLogicalPin);
        }
        if (outputBelPinName == null) {
            throw new RuntimeException("Geen fysieke output BEL-pin mapping voor " + bufferCellName + "/" + outputLogicalPin);
        }

        // 2) Entry en exit site pins halen uit de echte ECO-netten
        Net entryNet = design.getNet(entryNetName);
        if (entryNet == null) {
            throw new RuntimeException("Entry net niet gevonden: " + entryNetName);
        }

        Net exitNet = design.getNet(exitNetName);
        if (exitNet == null) {
            throw new RuntimeException("Exit net niet gevonden: " + exitNetName);
        }

        List<String> inSiteWires = new ArrayList<>();
        SitePinInst inputSitePin = bufferCell.getSitePinFromLogicalPin(inputLogicalPin, inSiteWires);
        if (inputSitePin == null) {
            throw new RuntimeException("Kon input SitePinInst niet bepalen voor " + bufferCellName + "/" + inputLogicalPin);
        }

        SitePinInst outputSitePin = exitNet.getSource();
        if (outputSitePin == null) {
            throw new RuntimeException("Exit net heeft geen source pin: " + exitNetName);
        }

        // 3) DelayModel calls
        short belIdx = delayModel.getBELIndex(belName);

        short logicPsShort = delayModel.getLogicDelay(
                belIdx,
                inputBelPinName,
                outputBelPinName
        );
        if (logicPsShort < 0) {
            throw new RuntimeException(
                    "Geen geldige LUT logic arc gevonden voor BEL=" + belName +
                    " inputBelPin=" + inputBelPinName +
                    " outputBelPin=" + outputBelPinName
            );
        }

        Short inputIntraPsShort = delayModel.getIntraSiteDelay(
                siteType,
                inputSitePin.getName(),
                belName + "/" + inputBelPinName
        );
        if (inputIntraPsShort == null || inputIntraPsShort < 0) {
            throw new RuntimeException(
                    "Geen geldige intra-site entry arc gevonden: " +
                    inputSitePin.getName() + " -> " + belName + "/" + inputBelPinName
            );
        }

        Short outputIntraPsShort = delayModel.getIntraSiteDelay(
                siteType,
                belName + "/" + outputBelPinName,
                outputSitePin.getName()
        );
        if (outputIntraPsShort == null || outputIntraPsShort < 0) {
            throw new RuntimeException(
                    "Geen geldige intra-site exit arc gevonden: " +
                    belName + "/" + outputBelPinName + " -> " + outputSitePin.getName()
            );
        }

        float inputIntraPs = inputIntraPsShort.floatValue();
        float logicPs = logicPsShort;
        float outputIntraPs = outputIntraPsShort.floatValue();

        System.out.println("Buffer cell         : " + bufferCellName);
        System.out.println("Site                : " + siteInst.getName());
        System.out.println("Site type           : " + siteType);
        System.out.println("BEL                 : " + belName);
        System.out.println("Input site pin      : " + inputSitePin.getName());
        System.out.println("Input BEL pin       : " + inputBelPinName);
        System.out.println("Output BEL pin      : " + outputBelPinName);
        System.out.println("Output site pin     : " + outputSitePin.getName());
        System.out.printf(Locale.US, "Input intra-site ps : %.3f%n", inputIntraPs);
        System.out.printf(Locale.US, "Logic LUT ps        : %.3f%n", logicPs);
        System.out.printf(Locale.US, "Output intra-site ps: %.3f%n", outputIntraPs);
        System.out.printf(Locale.US, "Internal total ps   : %.3f%n", inputIntraPs + logicPs + outputIntraPs);

        return new InternalDelayResult(
                bufferCellName,
                belName,
                siteInst.getName(),
                siteType.toString(),
                inputSitePin.getName(),
                inputBelPinName,
                outputBelPinName,
                outputSitePin.getName(),
                inputIntraPs,
                logicPs,
                outputIntraPs
        );
    }

    private static void printResult(String label, DelayResult r) {
        System.out.println(label + ":");
        System.out.println("  dcp        = " + r.dcpPath);
        System.out.println("  net        = " + r.netName);
        System.out.println("  source     = " + r.sourceSitePin);
        System.out.println("  sink       = " + r.sinkSitePin);
        System.out.printf(Locale.US, "  delay_ps   = %.3f%n", r.delayPs);
        System.out.printf(Locale.US, "  delay_ns   = %.6f%n", r.delayPs / 1000.0);
    }

    private static void printInternalDelayResult(String label, InternalDelayResult r) {
        System.out.println(label + ":");
        System.out.println("  buffer_cell          = " + r.bufferCell);
        System.out.println("  site                 = " + r.siteName);
        System.out.println("  site_type            = " + r.siteType);
        System.out.println("  bel                  = " + r.belName);
        System.out.println("  input_site_pin       = " + r.inputSitePin);
        System.out.println("  input_bel_pin        = " + r.inputBelPin);
        System.out.println("  output_bel_pin       = " + r.outputBelPin);
        System.out.println("  output_site_pin      = " + r.outputSitePin);
        System.out.printf(Locale.US, "  input_intrasite_ps   = %.3f%n", r.inputIntraSitePs);
        System.out.printf(Locale.US, "  logic_ps             = %.3f%n", r.logicPs);
        System.out.printf(Locale.US, "  output_intrasite_ps  = %.3f%n", r.outputIntraSitePs);
        System.out.printf(Locale.US, "  total_internal_ps    = %.3f%n", r.totalPs);
    }
}
