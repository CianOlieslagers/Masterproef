import com.xilinx.rapidwright.design.*;
import com.xilinx.rapidwright.device.*;
import com.xilinx.rapidwright.edif.*;
public class InsertBufferECO {

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
        }        // ==============================================================================
        // Vanaf hier wordt ALLES genegeerd in virtual mode, en alleen uitgevoerd in commit mode
        // ==============================================================================

        System.out.println("Doellocatie op: " + site.getName() + " / " + targetBel.getName());

        EDIFNetlist netlist = design.getNetlist();
        EDIFCellInst lutB_log = netlist.getCellInstFromHierName(lutBName);
        EDIFNet origNet_log = netlist.getNetFromHierName(netName);

        if (lutB_log == null || origNet_log == null) {
            System.err.println("Fout: LUT B of Net niet gevonden in de EDIF netlist!");
            System.exit(1);
        }

        EDIFLibrary hdiLib = netlist.getHDIPrimitivesLibrary();
        EDIFCell lut1LibCell = hdiLib.getCell("LUT1");

        if (lut1LibCell == null) {
            System.out.println("Let op: LUT1 definitie ontbreekt in DCP. Handmatig aanmaken...");
            lut1LibCell = new EDIFCell(hdiLib, "LUT1");
            lut1LibCell.createPort("I0", EDIFDirection.INPUT, 1);
            lut1LibCell.createPort("O",  EDIFDirection.OUTPUT, 1);
        }

        EDIFCellInst lutC_log = netlist.getTopCell().createChildCellInst(netName + "_buffer", lut1LibCell);
        lutC_log.addProperty("INIT", "2'h2"); 

        EDIFPortInst inputPinOnB = null;
        for (EDIFPortInst epi : origNet_log.getPortInsts()) {
            if (epi.getCellInst() != null && epi.getCellInst().equals(lutB_log) && epi.isInput()) {
                inputPinOnB = epi;
                break;
            }
        }

        if (inputPinOnB != null) {
            origNet_log.removePortInst(inputPinOnB);
            origNet_log.createPortInst("I0", lutC_log);
            EDIFNet newNet_log = netlist.getTopCell().createNet(netName + "_split");
            newNet_log.createPortInst("O", lutC_log); 
            newNet_log.addPortInst(inputPinOnB);      
        } else {
            System.err.println("Fout: Kon de input pin van LUT B op deze net niet vinden.");
            System.exit(1);
        }

        Cell lutC_phys = design.createCell(lutC_log.getName(), lutC_log);
        design.placeCell(lutC_phys, site, targetBel);
        lutC_phys.addPinMapping("I0", letter + "6");
        lutC_phys.addPinMapping("O", "O6");

        design.writeCheckpoint(outputDcp);
        System.out.println("ECO succesvol weggeschreven naar " + outputDcp);
    }
}
