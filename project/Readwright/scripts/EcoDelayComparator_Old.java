import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

import com.xilinx.rapidwright.design.Cell;
import com.xilinx.rapidwright.design.Design;
import com.xilinx.rapidwright.design.DesignTools;
import com.xilinx.rapidwright.design.Net;
import com.xilinx.rapidwright.design.SitePinInst;
import com.xilinx.rapidwright.tests.CodePerfTracker;
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

    public static void main(String[] args) {
        if (args.length != 8) {
            System.err.println("Gebruik:");
            System.err.println("java EcoDelayComparator <baseline_dcp> <eco_dcp> <baseline_net> <split_net> <buffer_cell> <sink_cell> <sink_pin> <lut_delay_ps>");
            System.exit(1);
        }

        String baselineDcp = args[0];
        String ecoDcp      = args[1];
        String baselineNet = args[2];
        String splitNet    = args[3];
        String bufferCell  = args[4];
        String sinkCell    = args[5];
        String sinkPin     = args[6];
        float lutDelayPs   = Float.parseFloat(args[7]);

        CodePerfTracker t = new CodePerfTracker("ECO Delay Comparator");
        t.useGCToTrackMemory(true);

        try {
            DelayResult baseline = measureNetDelayToCellPin(
                    baselineDcp, baselineNet, sinkCell, sinkPin, "BASELINE direct");

            DelayResult ecoSeg1 = measureNetDelayToCellPin(
                    ecoDcp, baselineNet, bufferCell, "I0", "ECO segment 1");

            DelayResult ecoSeg2 = measureNetDelayToCellPin(
                    ecoDcp, splitNet, sinkCell, sinkPin, "ECO segment 2");

            float ecoInterconnectPs = ecoSeg1.delayPs + ecoSeg2.delayPs;
            float ecoTotalWithLutPs = ecoInterconnectPs + lutDelayPs;

            float deltaInterconnectPs = ecoInterconnectPs - baseline.delayPs;
            float deltaTotalPs = ecoTotalWithLutPs - baseline.delayPs;

            System.out.println();
            System.out.println("==================================================");
            System.out.println("RESULTAAT");
            System.out.println("==================================================");
            printResult("Baseline direct", baseline);
            printResult("ECO segment 1", ecoSeg1);
            printResult("ECO segment 2", ecoSeg2);

            System.out.println();
            System.out.printf(Locale.US, "lut_delay_ps               = %.3f%n", lutDelayPs);
            System.out.printf(Locale.US, "eco_total_interconnect_ps  = %.3f%n", ecoInterconnectPs);
            System.out.printf(Locale.US, "eco_total_with_lut_ps      = %.3f%n", ecoTotalWithLutPs);
            System.out.printf(Locale.US, "delta_interconnect_ps      = %.3f%n", deltaInterconnectPs);
            System.out.printf(Locale.US, "delta_total_ps             = %.3f%n", deltaTotalPs);

            if (deltaTotalPs < 0.0f) {
                System.out.println("BESLISSING_TOTAL: ECO is gunstig inclusief LUT-delay.");
            } else if (deltaTotalPs > 0.0f) {
                System.out.println("BESLISSING_TOTAL: ECO is ongunstig inclusief LUT-delay.");
            } else {
                System.out.println("BESLISSING_TOTAL: ECO is gelijk inclusief LUT-delay.");
            }

            System.out.println();
            System.out.printf(
                Locale.US,
                "RESULT_JSON: {\"baseline_ps\": %.3f, \"eco_seg1_ps\": %.3f, \"eco_seg2_ps\": %.3f, \"lut_delay_ps\": %.3f, \"eco_interconnect_ps\": %.3f, \"eco_total_ps\": %.3f, \"delta_interconnect_ps\": %.3f, \"delta_total_ps\": %.3f}%n",
                baseline.delayPs, ecoSeg1.delayPs, ecoSeg2.delayPs, lutDelayPs,
                ecoInterconnectPs, ecoTotalWithLutPs, deltaInterconnectPs, deltaTotalPs
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

    private static void printResult(String label, DelayResult r) {
        System.out.println(label + ":");
        System.out.println("  dcp        = " + r.dcpPath);
        System.out.println("  net        = " + r.netName);
        System.out.println("  source     = " + r.sourceSitePin);
        System.out.println("  sink       = " + r.sinkSitePin);
        System.out.printf(Locale.US, "  delay_ps   = %.3f%n", r.delayPs);
        System.out.printf(Locale.US, "  delay_ns   = %.6f%n", r.delayPs / 1000.0);
    }
}
