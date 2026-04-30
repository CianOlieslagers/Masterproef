import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

import com.xilinx.rapidwright.design.Design;
import com.xilinx.rapidwright.design.Net;
import com.xilinx.rapidwright.design.SitePinInst;
import com.xilinx.rapidwright.rwroute.PartialRouter;
import com.xilinx.rapidwright.tests.CodePerfTracker;

public class RouteExistingUnroutedPins {

    public static void main(String[] args) {
        if (args.length < 2) {
            System.err.println("Gebruik: java RouteExistingUnroutedPins <input_dcp> <output_dcp>");
            System.exit(1);
        }

        String inputDcp = args[0];
        String outputDcp = args[1];

        CodePerfTracker t = new CodePerfTracker("Route Existing Unrouted Pins");
        t.useGCToTrackMemory(true);

        t.start("Read DCP");
        Design design = Design.readCheckpoint(inputDcp, CodePerfTracker.SILENT);

        System.out.println("Design name : " + design.getName());
        System.out.println("Part        : " + design.getPartName());
        System.out.println();

        t.stop().start("Collect unrouted physical pins");

        Set<SitePinInst> unroutedSet = new LinkedHashSet<>();

        for (Net net : design.getNets()) {
            if (net == null) continue;
            for (SitePinInst pin : net.getPins()) {
                if (pin != null && !pin.isRouted()) {
                    unroutedSet.add(pin);
                }
            }
        }

        List<SitePinInst> unroutedPins = new ArrayList<>(unroutedSet);

        System.out.println("Aantal bestaande unrouted fysieke pins: " + unroutedPins.size());
        for (SitePinInst pin : unroutedPins) {
            System.out.println("  " + pin);
        }
        System.out.println();

        t.stop().start("Partial route unrouted physical pins");
        PartialRouter.routeDesignPartialNonTimingDriven(design, unroutedPins, false);

        t.stop().start("Collect unrouted pins after routing");

        Set<SitePinInst> unroutedAfterSet = new LinkedHashSet<>();
        for (Net net : design.getNets()) {
            if (net == null) continue;
            for (SitePinInst pin : net.getPins()) {
                if (pin != null && !pin.isRouted()) {
                    unroutedAfterSet.add(pin);
                }
            }
        }

        List<SitePinInst> unroutedAfter = new ArrayList<>(unroutedAfterSet);

        System.out.println("Aantal unrouted fysieke pins na routing: " + unroutedAfter.size());
        for (SitePinInst pin : unroutedAfter) {
            System.out.println("  NOG UNROUTED: " + pin);
        }
        System.out.println();

        t.stop().start("Write DCP");
        design.writeCheckpoint(outputDcp, CodePerfTracker.SILENT);

        t.stop().printSummary();
        System.out.println("Nieuwe DCP geschreven naar: " + outputDcp);
    }
}
