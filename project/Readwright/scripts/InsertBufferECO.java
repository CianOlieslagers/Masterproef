import com.xilinx.rapidwright.design.*;
import com.xilinx.rapidwright.device.*;
import com.xilinx.rapidwright.edif.*;
import java.util.*;
import com.xilinx.rapidwright.eco.ECOTools;


import com.xilinx.rapidwright.rwroute.PartialRouter;
public class InsertBufferECO {

    public static void main(String[] args) {
        // --- 1. VARIABELEN INITIALISEREN ---
        String inputDcp = "";
        String outputDcp = "";
        String lutBName = "";
        String netName = "";
        String targetSlice = "";
        String mode = "commit"; // Standaardmodus = backwards compatible
        String sinkLogicalPin = "I0";
        String tag = "";

        String routeMode = "non_timing";   // default = huidig gedrag
        boolean softPreserve = false;      // default = bestaande routing strikt bewaren

        String explicitBufferName = "";
        String explicitSplitNetName = "";

        int srcX = 0, srcY = 0, destX = 0, destY = 0;

        // --- 2. SLIMME ARGUMENT PARSER (Backwards Compatible) ---
        // Als er argumenten zijn en het eerste argument begint NIET met "--",
        // dan gaan we ervan uit dat het je oude bash-script is.
        if (args.length > 0 && !args[0].startsWith("--")) {
            if (args.length != 5) {
                System.out.println("Gebruik (Legacy): java InsertBufferECO <input.dcp> <output.dcp> <lutB_name> <net_name> <target_slice>");
                System.out.println("Gebruik (Nieuw):  java InsertBufferECO --mode virtual --dcp <input.dcp> --net <net_name> --src_x <x> --src_y <y> --dest_x <x> --dest_y <y>");
                System.exit(1);
            }
            inputDcp = args[0];
            outputDcp = args[1];
            lutBName = args[2];
            netName = args[3];
            targetSlice = args[4];
            mode = "commit";
        } else {
            // Nieuwe CLI vlaggen parsen
            for (int i = 0; i < args.length; i++) {
                switch (args[i]) {
                    case "--mode": mode = args[++i]; break;
                    case "--dcp": inputDcp = args[++i]; break;
                    case "--net": netName = args[++i]; break;
                    case "--src_x": srcX = Integer.parseInt(args[++i]); break;
                    case "--src_y": srcY = Integer.parseInt(args[++i]); break;
                    case "--dest_x": destX = Integer.parseInt(args[++i]); break;
                    case "--dest_y": destY = Integer.parseInt(args[++i]); break;
                    // Future proofing voor als Python later ook de commit wil doen via vlaggen:
                    case "--out_dcp": outputDcp = args[++i]; break;
                    case "--lutB": lutBName = args[++i]; break;
                    case "--target_slice": targetSlice = args[++i]; break;
                    case "--sink_pin": sinkLogicalPin = args[++i]; break;
                    case "--tag": tag = args[++i]; break;
                    case "--buffer_name": explicitBufferName = args[++i]; break;
                    case "--split_name": explicitSplitNetName = args[++i]; break;
                    case "--route_mode": routeMode = args[++i]; break;
                    case "--soft_preserve": softPreserve = Integer.parseInt(args[++i]) != 0; break;


                }
            }
        }

        // --- 3. RAPIDWRIGHT INITIALISATIE ---
        Design design = Design.readCheckpoint(inputDcp);
        Device device = design.getDevice();

        // --- 4. BEPAAL STARTPUNT VOOR SPIRAAL ALGORITME ---
        int targetX = 0, targetY = 0;

        if (mode.equals("virtual")) {
            // In virtuele mode berekenen we het middelpunt wiskundig
            targetX = (srcX + destX) / 2;
            targetY = (srcY + destY) / 2;
        } else {
            // In commit mode halen we het uit de aangeleverde string ("SLICE_X61Y128")
            if (targetSlice == null || targetSlice.isEmpty()) {
                System.err.println("Fout: target_slice is vereist voor commit mode.");
                System.exit(1);
            }
            targetX = Integer.parseInt(targetSlice.substring(targetSlice.indexOf('X') + 1, targetSlice.indexOf('Y')));
            targetY = Integer.parseInt(targetSlice.substring(targetSlice.indexOf('Y') + 1));
        }

        // --- 5. HET SPIRAAL ALGORITME (Jouw originele logica) ---
        Site site = null;
        BEL targetBel = null;
        String letter = "";
        String[] lutLetters = {"A", "B", "C", "D"};
        int maxRadius = 15; // Zoek tot 15 coördinaten rondom het middelpunt

        ZoekLoop:
        for (int r = 0; r <= maxRadius; r++) {
            for (int dx = -r; dx <= r; dx++) {
                for (int dy = -r; dy <= r; dy++) {
                    if (Math.abs(dx) != r && Math.abs(dy) != r) continue;

                    String testSiteName = "SLICE_X" + (targetX + dx) + "Y" + (targetY + dy);
                    Site testSite = device.getSite(testSiteName);

                    if (testSite != null) {
                        SiteInst siteInst = design.getSiteInstFromSite(testSite);
                        for (String l : lutLetters) {
                            BEL bel = testSite.getBEL(l + "6LUT");
                            if (siteInst == null || siteInst.getCell(l + "6LUT") == null) {
                                site = testSite;
                                targetBel = bel;
                                letter = l;
                                break ZoekLoop;
                            }
                        }
                    }
                }
            }
        }

        if (site == null || targetBel == null) {
            System.err.println("Fout: Geen vrije LUT beschikbaar binnen een radius van " + maxRadius);
            System.exit(1);
        }

        // --- 6. SPLITSING TUSSEN VIRTUAL EN COMMIT ---

if (mode.equals("virtual")) {
            // A. Haal de definitief gevonden X/Y op
            String siteName = site.getName();
            int foundX = Integer.parseInt(siteName.substring(siteName.indexOf('X') + 1, siteName.indexOf('Y')));
            int foundY = Integer.parseInt(siteName.substring(siteName.indexOf('Y') + 1));

            // B. Bereken de fysieke Manhattan afstanden
            int md1 = Math.abs(foundX - srcX) + Math.abs(foundY - srcY);
            int md2 = Math.abs(destX - foundX) + Math.abs(destY - foundY);

            // C. Bereken de voorspelde delay (Artix-7 Unrouted Estimate)
            // Gemiddeld kost 1 Manhattan-stap op een Artix-7 ~28 picoseconden (0.028 ns)
            double delayPerTileNs = 0.028;

            double rw_delay_1_ns = md1 * delayPerTileNs;
            double rw_delay_2_ns = md2 * delayPerTileNs;

            // D. Print de JSON
            String jsonOutput = String.format(
                java.util.Locale.US,
                "RESULT_JSON: {\"lut_loc\": \"%s\", \"md1\": %d, \"md2\": %d, \"rw_delay1\": %.3f, \"rw_delay2\": %.3f}",
                siteName, md1, md2, rw_delay_1_ns, rw_delay_2_ns
            );
            System.out.println(jsonOutput);
            System.exit(0);
        }
         // ==============================================================================
        // Commit mode: echte ECO + lokale reroute
        // ==============================================================================

        System.out.println("Doellocatie op: " + site.getName() + " / " + targetBel.getName());

        EDIFNetlist netlist = design.getNetlist();

        // Fysieke objecten
        Net origNet = design.getNet(netName);
        Cell sinkCell = design.getCell(lutBName);

        if (origNet == null) {
            System.err.println("Fout: fysieke net '" + netName + "' niet gevonden.");
            System.exit(1);
        }
        if (sinkCell == null) {
            System.err.println("Fout: sink cell '" + lutBName + "' niet gevonden.");
            System.exit(1);
        }

        // Voor testcase 1 is de doelsink expliciet I0
        
        // Hiërarchische logische pin van de sink
        EDIFHierPortInst sinkHpi = netlist.getHierPortInstFromName(lutBName + "/" + sinkLogicalPin);
        if (sinkHpi == null) {
            System.err.println("Fout: hiërarchische sink pin '" + lutBName + "/" + sinkLogicalPin + "' niet gevonden.");
            System.exit(1);
        }

        // Nieuwe LUT1-buffer creëren en plaatsen
        // Nieuwe LUT1-buffer creëren en plaatsen
        String suffix = (tag == null || tag.isEmpty()) ? "" : "_" + tag;

        String newCellName;
        if (explicitBufferName != null && !explicitBufferName.isEmpty()) {
            newCellName = explicitBufferName;
        } else {
            newCellName = netName + "_buffer" + suffix;
        }

        String splitNetName;
        if (explicitSplitNetName != null && !explicitSplitNetName.isEmpty()) {
            splitNetName = explicitSplitNetName;
        } else {
            splitNetName = netName + "_split" + suffix;
        }

        String newLocation = site.getName() + "/" + targetBel.getName();

        Cell bufCell = design.createAndPlaceCell(
            newCellName,
            Unisim.LUT1,
            newLocation,
            "INIT=2'h2"
        );

        if (bufCell == null) {
            System.err.println("Fout: buffercel kon niet gecreëerd/geplaatst worden op " + newLocation);
            System.exit(1);
        }

        // 1) Disconnect exact één sink en hou verwijderde site pins bij
        Map<Net, Set<SitePinInst>> deferredRemovals = new HashMap<>();

        System.out.println("Target HPI      : " + sinkHpi);
        System.out.println("Orig pins before: " + origNet.getPins().size());

        ECOTools.disconnectNet(design, java.util.List.of(sinkHpi), deferredRemovals);

        // 2) Nieuw split-net maken
        Net splitNet = design.createNet(splitNetName);
        if (splitNet == null) {
            System.err.println("Fout: split-net '" + splitNetName + "' kon niet gemaakt worden.");
            System.exit(1);
        }

        // 3) Gebruik ECO connectNet i.p.v. Net.connect()
        //    Dit is de officiële ECO-manier en kan deferred SitePinInsts hergebruiken
        List<String> netPinList = new ArrayList<>();
        netPinList.add(netName + " " + newCellName + "/I0");
        netPinList.add(splitNetName + " " + newCellName + "/O " + lutBName + "/" + sinkLogicalPin);

        ECOTools.connectNet(design, netPinList, deferredRemovals);

        // 4) Zorg dat fysieke netnamen/site pins coherent zijn
        DesignTools.makePhysNetNamesConsistent(design);
        DesignTools.createMissingSitePinInsts(design, origNet);
        DesignTools.createMissingSitePinInsts(design, splitNet);

        // 5) Intra-site routing expliciet bijwerken op beide betrokken sites
        SiteInst bufSiteInst = design.getSiteInstFromSite(site);
        Site sinkSite = device.getSite(sinkCell.getSiteName());
        SiteInst sinkSiteInst = design.getSiteInstFromSite(sinkSite);

        if (bufSiteInst != null) {
            bufSiteInst.routeSite();
        }
        if (sinkSiteInst != null && sinkSiteInst != bufSiteInst) {
            sinkSiteInst.routeSite();
        }

        // 6) Routed-status updaten voor debug
        DesignTools.updatePinsIsRouted(origNet);
        DesignTools.updatePinsIsRouted(splitNet);

        // 7) Zoek expliciet de twee sink pins die partial routing moet afwerken
        SitePinInst bufInPin = null;
        for (SitePinInst p : origNet.getPins()) {
            if (p != null && !p.isOutPin() && site.getName().equals(p.getSiteInstName())) {
                bufInPin = p;
                break;
            }
        }

        SitePinInst sinkPinNewNet = null;
        for (SitePinInst p : splitNet.getPins()) {
            if (p != null && !p.isOutPin() && sinkCell.getSiteName().equals(p.getSiteInstName())) {
                sinkPinNewNet = p;
                break;
            }
        }

        System.out.println("Orig pins after connect : " + origNet.getPins().size());
        System.out.println("Split pins after connect: " + splitNet.getPins().size());
        System.out.println("bufInPin                : " + (bufInPin == null ? "<null>" : bufInPin.getSitePinName()));
        System.out.println("sinkPinNewNet           : " + (sinkPinNewNet == null ? "<null>" : sinkPinNewNet.getSitePinName()));

        if (bufInPin == null) {
            System.err.println("Fout: kon buffer sink-pin op origNet niet vinden.");
            System.exit(1);
        }
        if (sinkPinNewNet == null) {
            System.err.println("Fout: kon sink-pin op splitNet niet vinden.");
            System.exit(1);
        }

        List<SitePinInst> pinsToRoute = Arrays.asList(bufInPin, sinkPinNewNet);

        boolean routingCompleted = false;
boolean timingReportCrash = false;
String routingExceptionClass = "";
String routingExceptionMsg = "";

try {
    if ("timing".equalsIgnoreCase(routeMode) || "timing_driven".equalsIgnoreCase(routeMode)) {
        System.out.println("Routing mode       : partial timing-driven");
        System.out.println("Soft preserve      : " + softPreserve);
        PartialRouter.routeDesignPartialTimingDriven(design, pinsToRoute, softPreserve);
    } else if ("non_timing".equalsIgnoreCase(routeMode) || "non_timing_driven".equalsIgnoreCase(routeMode)) {
        System.out.println("Routing mode       : partial non-timing-driven");
        System.out.println("Soft preserve      : " + softPreserve);
        PartialRouter.routeDesignPartialNonTimingDriven(design, pinsToRoute, softPreserve);
    } else {
        System.err.println("Fout: onbekende route_mode = " + routeMode + " (gebruik 'non_timing' of 'timing')");
        System.exit(1);
    }
    routingCompleted = true;

} catch (IndexOutOfBoundsException e) {
    // RapidWright timing-report/critical-path corner case na ogenschijnlijk succesvolle routing
    timingReportCrash = true;
    routingCompleted = true;
    routingExceptionClass = e.getClass().getSimpleName();
    routingExceptionMsg = e.getMessage();

    System.err.println("WAARSCHUWING: routing call triggerde een exception na partial routing.");
    System.err.println("Waarschijnlijk timing-report crash in RapidWright, niet per se routing failure.");
    System.err.println("Exception: " + routingExceptionClass + " - " + routingExceptionMsg);

} catch (Exception e) {
    routingExceptionClass = e.getClass().getSimpleName();
    routingExceptionMsg = e.getMessage();
    System.err.println("Fout tijdens routing: " + routingExceptionClass + " - " + routingExceptionMsg);
    e.printStackTrace(System.err);
    System.exit(1);
}
        // 8) Routed-status opnieuw updaten na partial routing
        DesignTools.updatePinsIsRouted(origNet);
        DesignTools.updatePinsIsRouted(splitNet);
        // 5) Diagnostische info
        System.out.println("=== ECO RESULTAAT ===");
        System.out.println("Nieuwe buffercel : " + bufCell.getName());
        System.out.println("Nieuwe locatie   : " + newLocation);
        System.out.println("Orig net         : " + origNet.getName() + "  pins=" + origNet.getPins().size());
        System.out.println("Split net        : " + splitNet.getName() + "  pins=" + splitNet.getPins().size());
        System.out.println("sinkLogicalPin        : " + sinkLogicalPin);
        System.out.println("newCellName           : " + newCellName);
        System.out.println("splitNetName          : " + splitNetName);
System.out.println("routeMode             : " + routeMode);
System.out.println("softPreserve          : " + softPreserve);

        for (SitePinInst p : origNet.getPins()) {
            System.out.println("  ORIG  " + p.getSitePinName() + "  routed=" + p.isRouted());
        }
        for (SitePinInst p : splitNet.getPins()) {
            System.out.println("  SPLIT " + p.getSitePinName() + "  routed=" + p.isRouted());
        }

DesignTools.updatePinsIsRouted(origNet);
DesignTools.updatePinsIsRouted(splitNet);

boolean bufInRouted = bufInPin != null && bufInPin.isRouted();
boolean sinkNewRouted = sinkPinNewNet != null && sinkPinNewNet.isRouted();

System.out.println("Post-route routed check:");
System.out.println("  bufInPin routed      : " + bufInRouted);
System.out.println("  sinkPinNewNet routed : " + sinkNewRouted);
System.out.println("  timingReportCrash    : " + timingReportCrash);

if (!routingCompleted) {
    System.err.println("Fout: routing niet voltooid.");
    System.exit(1);
}

if (!bufInRouted || !sinkNewRouted) {
    System.err.println("Fout: minstens één target pin is niet routed na partial routing.");
    System.exit(1);
}
if (timingReportCrash) {
    System.out.println("RESULT_JSON: {\"status\":\"OK_WITH_TIMING_REPORT_CRASH\",\"route_mode\":\"" + routeMode + "\"}");
} else {
    System.out.println("RESULT_JSON: {\"status\":\"OK\",\"route_mode\":\"" + routeMode + "\"}");
}
        design.writeCheckpoint(outputDcp);
        System.out.println("ECO succesvol weggeschreven naar " + outputDcp);
    }
}
