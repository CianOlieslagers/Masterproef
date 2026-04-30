import java.util.List;

import org.jgrapht.GraphPath;

import com.xilinx.rapidwright.design.Design;
import com.xilinx.rapidwright.design.Net;
import com.xilinx.rapidwright.design.SitePinInst;
import com.xilinx.rapidwright.edif.EDIFHierPortInst;
import com.xilinx.rapidwright.tests.CodePerfTracker;
import com.xilinx.rapidwright.timing.TimingEdge;
import com.xilinx.rapidwright.timing.TimingManager;
import com.xilinx.rapidwright.timing.TimingModel;
import com.xilinx.rapidwright.timing.TimingVertex;

public class EcoTimingManagerTest {

    private static final String OUTPUT_DCP =
        "/home/cian/Masterproef/project/results/run_lut_insertion/2026-04-19_18-27-57/"
      + "dcp/eco_timing_manager_test.dcp";

    public static void main(String[] args) {
        if (args.length < 2) {
            System.err.println("Gebruik: java EcoTimingManagerTest <dcp_path> <net_name>");
            System.exit(1);
        }

        String inputDcp = args[0];
        String targetNetName = args[1];

        CodePerfTracker t = new CodePerfTracker("ECO Timing Manager Test");
        t.useGCToTrackMemory(true);

        t.start("Read DCP");
        Design design = Design.readCheckpoint(inputDcp, CodePerfTracker.SILENT);

        System.out.println("Design name : " + design.getName());
        System.out.println("Part        : " + design.getPartName());
        System.out.println();

        t.stop().start("Baseline timing");

        TimingManager tm = new TimingManager(design);
        tm.getTimingGraph().buildGraphPaths();

        GraphPath<TimingVertex, TimingEdge> path = tm.getTimingGraph().getMaxDelayPath();

        if (path == null) {
            System.out.println("Geen max delay path gevonden.");
        } else {
            System.out.println("Critical path = " + (int) path.getWeight() + " ps");
        }
        System.out.println();

        t.stop().start("Find target net");
        Net net = design.getNet(targetNetName);
        if (net == null) {
            throw new RuntimeException("Net niet gevonden: " + targetNetName);
        }

        System.out.println("Target net: " + net.getName());
        System.out.println("Aantal fysieke pins op net: " + net.getPins().size());
        System.out.println();

        SitePinInst src = findSourcePin(net);
        List<SitePinInst> sinks = findSinkPins(net);

        if (src == null) {
    System.out.println("Geen source pin gevonden op net " + targetNetName);
} else {
    System.out.println("=== PHYSICAL PINS ===");
    System.out.println("Source: " + src.getSitePinName());
    for (SitePinInst s : sinks) {
        System.out.println("Sink  : " + s.getSitePinName());
    }
    System.out.println();
}
        System.out.println("=== PHYSICAL PINS ===");
        System.out.println("Source: " + src.getSitePinName());
        for (SitePinInst s : sinks) {
            System.out.println("Sink  : " + s.getSitePinName());
        }
        System.out.println();

        t.stop().start("Logical pins from EDIF");
        List<EDIFHierPortInst> logicalPins = design.getNetlist().getPhysicalPins(net);
        System.out.println("=== LOGICAL/EDIF PINS ===");
        for (EDIFHierPortInst p : logicalPins) {
            System.out.println(p);
        }
        System.out.println();

        t.stop().start("Local delay estimates");
        TimingModel model = tm.getTimingModel();
        System.out.println("=== LOCAL NET DELAYS ===");
        for (SitePinInst s : sinks) {
            float delayPs = model.calcDelay(src, s, net);
            System.out.printf("%s -> %s : %.1f ps%n",
                    src.getSitePinName(),
                    s.getSitePinName(),
                    delayPs);
        }
        System.out.println();

        t.stop().start("Write DCP");
        design.writeCheckpoint(OUTPUT_DCP, CodePerfTracker.SILENT);

        t.stop().printSummary();
        System.out.println("Checkpoint geschreven naar: " + OUTPUT_DCP);
    }

    private static SitePinInst findSourcePin(Net net) {
        for (SitePinInst p : net.getPins()) {
            if (p.isOutPin()) {
                return p;
            }
        }
        return null;
    }

    private static java.util.List<SitePinInst> findSinkPins(Net net) {
        java.util.List<SitePinInst> sinks = new java.util.ArrayList<>();
        for (SitePinInst p : net.getPins()) {
            if (!p.isOutPin()) {
                sinks.add(p);
            }
        }
        return sinks;
    }
}
