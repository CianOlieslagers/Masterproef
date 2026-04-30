import java.util.ArrayList;
import java.util.List;

import com.xilinx.rapidwright.design.Cell;
import com.xilinx.rapidwright.design.Design;
import com.xilinx.rapidwright.design.Net;
import com.xilinx.rapidwright.design.SitePinInst;
import com.xilinx.rapidwright.edif.EDIFHierPortInst;
import com.xilinx.rapidwright.tests.CodePerfTracker;
import com.xilinx.rapidwright.design.DesignTools;


public class DcpEcoDiagnose {

    public static void main(String[] args) {
        if (args.length < 2) {
            System.err.println("Gebruik: java DcpEcoDiagnose <dcp_path> <name1> [name2] [name3] ...");
            System.exit(1);
        }

        String inputDcp = args[0];

        CodePerfTracker t = new CodePerfTracker("DCP ECO Diagnose");
        t.useGCToTrackMemory(true);

        t.start("Read DCP");
        Design design = Design.readCheckpoint(inputDcp, CodePerfTracker.SILENT);
	DesignTools.updatePinsIsRouted(design);


        System.out.println("Design name : " + design.getName());
        System.out.println("Part        : " + design.getPartName());
        System.out.println();

        t.stop().start("Global stats");
        printGlobalStats(design);

        for (int i = 1; i < args.length; i++) {
            String query = args[i];
            System.out.println();
            System.out.println("==================================================");
            System.out.println("QUERY: " + query);
            System.out.println("==================================================");

            diagnoseNet(design, query);
            diagnoseCell(design, query);
            diagnoseNameMatches(design, query);
        }

        t.stop().printSummary();
    }

    private static void printGlobalStats(Design design) {
        int totalNets = 0;
        int netsWithZeroPins = 0;
        int netsWithUnroutedPins = 0;
        int totalPins = 0;
        int totalUnroutedPins = 0;

        for (Net net : design.getNets()) {
            if (net == null) continue;
            totalNets++;

            List<SitePinInst> pins = net.getPins();
            if (pins == null || pins.isEmpty()) {
                netsWithZeroPins++;
                continue;
            }

            boolean hasUnrouted = false;
            for (SitePinInst pin : pins) {
                if (pin == null) continue;
                totalPins++;
                if (!pin.isRouted()) {
                    totalUnroutedPins++;
                    hasUnrouted = true;
                }
            }

            if (hasUnrouted) {
                netsWithUnroutedPins++;
            }
        }

        System.out.println("=== GLOBAL STATS ===");
        System.out.println("Total nets              : " + totalNets);
        System.out.println("Nets with 0 pins        : " + netsWithZeroPins);
        System.out.println("Nets with unrouted pins : " + netsWithUnroutedPins);
        System.out.println("Total physical pins     : " + totalPins);
        System.out.println("Total unrouted pins     : " + totalUnroutedPins);
    }

    private static void diagnoseNet(Design design, String netName) {
        Net net = design.getNet(netName);

        if (net == null) {
            System.out.println("Net '" + netName + "' bestaat niet.");
            return;
        }

        System.out.println("=== NET ===");
        System.out.println("Net name: " + net.getName());

        List<SitePinInst> pins = net.getPins();
        int pinCount = (pins == null) ? 0 : pins.size();
        System.out.println("Aantal fysieke pins: " + pinCount);

        if (pins != null && !pins.isEmpty()) {
        for (SitePinInst pin : pins) {
    String dir = pin.isOutPin() ? "OUT" : "IN ";
    String routed = pin.isRouted() ? "routed" : "UNROUTED";
    String sitePin = safe(pin.getSitePinName());
    String siteInst = safe(pin.getSiteInstName());

    System.out.print("  " + dir + "  " + sitePin + "   [" + routed + "]   siteInst=" + siteInst);

    if (!pin.isOutPin()) {
        try {
            int pipCount = DesignTools.getConnectionPIPs(pin).size();
            System.out.print("   connPIPs=" + pipCount);
        } catch (Exception e) {
            System.out.print("   connPIPs=<err>");
        }
    }
    System.out.println();
}    
       }

        try {
            List<EDIFHierPortInst> logicalPins = design.getNetlist().getPhysicalPins(net);
            System.out.println("Aantal logical/EDIF pins: " + logicalPins.size());
            for (EDIFHierPortInst p : logicalPins) {
                System.out.println("  " + p);
            }
        } catch (Exception e) {
            System.out.println("Kon logical/EDIF pins niet ophalen: " + e.getClass().getSimpleName() + " - " + e.getMessage());
        }
    }

    private static void diagnoseCell(Design design, String cellName) {
        Cell cell = design.getCell(cellName);

        if (cell == null) {
            System.out.println("Cell '" + cellName + "' bestaat niet.");
            return;
        }

        System.out.println("=== CELL ===");
        System.out.println("Cell name : " + cell.getName());
        System.out.println("Cell type : " + cell.getType());
        System.out.println("Placed    : " + cell.isPlaced());

        try {
            System.out.println("Site      : " + cell.getSiteName());
        } catch (Exception e) {
            System.out.println("Site      : <niet beschikbaar>");
        }

        try {
            System.out.println("BEL       : " + cell.getBELName());
        } catch (Exception e) {
            System.out.println("BEL       : <niet beschikbaar>");
        }
    }

    private static void diagnoseNameMatches(Design design, String pattern) {
        System.out.println("=== MATCHING NETS ===");
        int count = 0;
        for (Net net : design.getNets()) {
            if (net == null || net.getName() == null) continue;
            if (net.getName().contains(pattern)) {
                count++;
                int pinCount = (net.getPins() == null) ? 0 : net.getPins().size();
                System.out.println("  " + net.getName() + "   pins=" + pinCount);
            }
        }
        if (count == 0) {
            System.out.println("  geen");
        }

        System.out.println("=== MATCHING CELLS ===");
        List<String> matches = new ArrayList<>();
        try {
            for (Cell c : design.getCells()) {
                if (c != null && c.getName() != null && c.getName().contains(pattern)) {
                    matches.add(c.getName());
                }
            }
        } catch (Exception e) {
            System.out.println("  Kon cell-iteratie niet uitvoeren: " + e.getClass().getSimpleName() + " - " + e.getMessage());
            return;
        }

        if (matches.isEmpty()) {
            System.out.println("  geen");
        } else {
            for (String m : matches) {
                System.out.println("  " + m);
            }
        }
    }

    private static String safe(String s) {
        return s == null ? "<null>" : s;
    }
}
