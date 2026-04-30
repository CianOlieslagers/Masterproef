import com.xilinx.rapidwright.design.*;
import com.xilinx.rapidwright.device.*;
import com.xilinx.rapidwright.edif.*;

import com.xilinx.rapidwright.eco.ECOTools;


import com.xilinx.rapidwright.rwroute.PartialRouter;
public class  Lut_Insert_ECO {

    public static void main(String[] args) {
        // --- 1. VARIABELEN INITIALISEREN ---
        String inputDcp = "";
        String outputDcp = "";
        String lutBName = "";
        String netName = "";
        String targetSlice = "";
        String mode = "commit"; // Standaardmodus = backwards compatible

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
        String sinkLogicalPin = "I0";

        // Hiërarchische logische pin van de sink
        EDIFHierPortInst sinkHpi = netlist.getHierPortInstFromName(lutBName + "/" + sinkLogicalPin);
        if (sinkHpi == null) {
            System.err.println("Fout: hiërarchische sink pin '" + lutBName + "/" + sinkLogicalPin + "' niet gevonden.");
            System.exit(1);
        }

        // Nieuwe LUT1-buffer creëren en plaatsen
        String newCellName = netName + "_buffer";
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

        // 1) Exact één sink losmaken van het oude net
        // Dit doet de logische + fysieke ontkoppeling
        ECOTools.disconnectNet(design, sinkHpi);

        // 2) Oude net opnieuw laten eindigen op buffer input
        origNet.connect(bufCell, "I0");

        // 3) Nieuw split-net maken: buffer output -> originele sink
        String splitNetName = netName + "_split";
        Net splitNet = design.createNet(splitNetName);
        if (splitNet == null) {
            System.err.println("Fout: split-net '" + splitNetName + "' kon niet gemaakt worden.");
            System.exit(1);
        }

        splitNet.connect(bufCell, "O");
        splitNet.connect(sinkCell, sinkLogicalPin);

        // 4) Enkel de nieuwe sinks lokaal routen
        java.util.List<String> tmp = new java.util.ArrayList<>();

        SitePinInst bufInPin = bufCell.getSitePinFromLogicalPin("I0", tmp);
        tmp.clear();
        SitePinInst sinkPinNewNet = sinkCell.getSitePinFromLogicalPin(sinkLogicalPin, tmp);

        if (bufInPin == null) {
            System.err.println("Fout: kon fysieke pin van buffer I0 niet bepalen.");
            System.exit(1);
        }
        if (sinkPinNewNet == null) {
            System.err.println("Fout: kon fysieke pin van sink " + lutBName + "/" + sinkLogicalPin + " niet bepalen.");
            System.exit(1);
        }

        java.util.List<SitePinInst> pinsToRoute = java.util.Arrays.asList(bufInPin, sinkPinNewNet);

        PartialRouter.routeDesignPartialNonTimingDriven(design, pinsToRoute);
        // 5) Diagnostische info
        System.out.println("=== ECO RESULTAAT ===");
        System.out.println("Nieuwe buffercel : " + bufCell.getName());
        System.out.println("Nieuwe locatie   : " + newLocation);
        System.out.println("Orig net         : " + origNet.getName() + "  pins=" + origNet.getPins().size());
        System.out.println("Split net        : " + splitNet.getName() + "  pins=" + splitNet.getPins().size());

        for (SitePinInst p : origNet.getPins()) {
            System.out.println("  ORIG  " + p.getSitePinName() + "  routed=" + p.isRouted());
        }
        for (SitePinInst p : splitNet.getPins()) {
            System.out.println("  SPLIT " + p.getSitePinName() + "  routed=" + p.isRouted());
        }

        design.writeCheckpoint(outputDcp);
        System.out.println("ECO succesvol weggeschreven naar " + outputDcp);
    }
}
