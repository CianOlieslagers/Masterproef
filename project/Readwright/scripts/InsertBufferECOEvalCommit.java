import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.lang.reflect.Method;

import com.xilinx.rapidwright.design.Cell;
import com.xilinx.rapidwright.design.Design;
import com.xilinx.rapidwright.design.Net;
import com.xilinx.rapidwright.design.SiteInst;
import com.xilinx.rapidwright.design.SitePinInst;
import com.xilinx.rapidwright.device.BEL;
import com.xilinx.rapidwright.device.BELPin;
import com.xilinx.rapidwright.device.Device;
import com.xilinx.rapidwright.device.Site;
import com.xilinx.rapidwright.edif.EDIFCell;
import com.xilinx.rapidwright.edif.EDIFCellInst;
import com.xilinx.rapidwright.edif.EDIFDirection;
import com.xilinx.rapidwright.edif.EDIFLibrary;
import com.xilinx.rapidwright.edif.EDIFNet;
import com.xilinx.rapidwright.edif.EDIFNetlist;
import com.xilinx.rapidwright.edif.EDIFPortInst;
import com.xilinx.rapidwright.timing.TimingManager;
import com.xilinx.rapidwright.timing.TimingModel;

public class InsertBufferECOEvalCommit {

    private static final double LUT1_DELAY_NS = 0.124;
    private static final int MAX_RADIUS = 15;

    private static class ConnectionResolution {
        Net net;
        EDIFNet logNet;
        EDIFPortInst sourcePortInst;
        EDIFPortInst sinkPortInst;
        SitePinInst sourceSitePin;
        SitePinInst sinkSitePin;
    }

    public static void main(String[] args) {
        String mode = "eval_commit";
        String inputDcp = "";
        String outputDcp = "";
        String fromCellName = "";
        String lutBName = "";
        String netName = "";
        double origDelayNs = -1.0;

        int srcX = 0, srcY = 0, destX = 0, destY = 0;

        try {
            for (int i = 0; i < args.length; i++) {
                switch (args[i]) {
                    case "--mode": mode = args[++i]; break;
                    case "--dcp": inputDcp = args[++i]; break;
                    case "--out_dcp": outputDcp = args[++i]; break;
                    case "--from_cell": fromCellName = args[++i]; break;
                    case "--lutB": lutBName = args[++i]; break;
                    case "--net": netName = args[++i]; break;
                    case "--src_x": srcX = Integer.parseInt(args[++i]); break;
                    case "--src_y": srcY = Integer.parseInt(args[++i]); break;
                    case "--dest_x": destX = Integer.parseInt(args[++i]); break;
                    case "--dest_y": destY = Integer.parseInt(args[++i]); break;
                    case "--orig_delay": origDelayNs = Double.parseDouble(args[++i]); break;
                    default:
                        throw new RuntimeException("Onbekend argument: " + args[i]);
                }
            }

            if (!"eval_commit".equals(mode)) {
                throw new RuntimeException("Alleen --mode eval_commit wordt ondersteund.");
            }

            if (inputDcp.isEmpty() || outputDcp.isEmpty() || lutBName.isEmpty()
                    || fromCellName.isEmpty() || origDelayNs < 0.0) {
                throw new RuntimeException("Vereiste argumenten ontbreken.");
            }

            Design design = Design.readCheckpoint(inputDcp);
            normalizePlacedDesignBestEffort(design);

            Device device = design.getDevice();
            EDIFNetlist netlist = design.getNetlist();

            Cell srcPhys = design.getCell(fromCellName);
            if (srcPhys == null) {
                throw new RuntimeException("Broncel niet gevonden: " + fromCellName);
            }

            Cell lutBPhys = design.getCell(lutBName);
            if (lutBPhys == null) {
                throw new RuntimeException("Fysieke doelcell niet gevonden: " + lutBName);
            }

            EDIFCellInst srcLog = srcPhys.getEDIFCellInst();
            if (srcLog == null) {
                throw new RuntimeException("Logische broncel niet gevonden voor: " + fromCellName);
            }

            EDIFCellInst lutBLog = lutBPhys.getEDIFCellInst();
            if (lutBLog == null) {
                throw new RuntimeException("Logische doelcell niet gevonden voor: " + lutBName);
            }

            ConnectionResolution conn = resolveConnectionByPinToPin(design, srcPhys, srcLog, lutBPhys, lutBLog);
            if (conn == null) {
                throw new RuntimeException(
                    "Kon geen echte fysieke verbinding vinden tussen bron " +
                    fromCellName + " en doel " + lutBName
                );
            }

            if (conn.net == null) {
                throw new RuntimeException("resolveConnectionByPinToPin gaf een null fysieke net terug.");
            }

            // Extra kans geven aan post_place designs om SitePinInsts aan te maken
            tryCreateMissingSitePinInstsBestEffort(design, conn.net);

            // Resolve opnieuw nadat missing pins mogelijk zijn aangemaakt
            conn = resolveConnectionByPinToPin(design, srcPhys, srcLog, lutBPhys, lutBLog);
            if (conn == null || conn.net == null) {
                throw new RuntimeException("Na missing-site-pin normalisatie kon de verbinding niet meer geresolved worden.");
            }

            Net origPhysNet = conn.net;
            EDIFNet origLogNet = conn.logNet;
            EDIFPortInst inputPinOnB = conn.sinkPortInst;
            SitePinInst oldDestPin = conn.sinkSitePin; // MAG null zijn in post_place
            SitePinInst srcPin = conn.sourceSitePin;

            if (origLogNet == null) {
                throw new RuntimeException("Fysieke net heeft geen gekoppelde logische net.");
            }
            if (inputPinOnB == null) {
                throw new RuntimeException("Kon de logische sink port op LUT B niet bepalen.");
            }
            if (srcPin == null) {
                throw new RuntimeException("Kon de bestaande fysieke source pin niet bepalen.");
            }

            String lutBInputPortName = inputPinOnB.getName();
            if (lutBInputPortName == null || lutBInputPortName.isEmpty()) {
                throw new RuntimeException("Naam van input pin op LUT B is leeg.");
            }

            debugConnectionState("PRE-ECO", origPhysNet, origLogNet, conn, srcPhys, lutBPhys);

            int targetX = (srcX + destX) / 2;
            int targetY = (srcY + destY) / 2;

            Site site = null;
            BEL targetBel = null;
            String letter = null;

            String[] lutLetters = {"A", "B", "C", "D", "E", "F", "G", "H"};

            outer:
            for (int r = 0; r <= MAX_RADIUS; r++) {
                for (int dx = -r; dx <= r; dx++) {
                    for (int dy = -r; dy <= r; dy++) {
                        if (Math.abs(dx) != r && Math.abs(dy) != r) continue;

                        String testSiteName = "SLICE_X" + (targetX + dx) + "Y" + (targetY + dy);
                        Site testSite = device.getSite(testSiteName);
                        if (testSite == null) continue;

                        SiteInst siteInst = design.getSiteInstFromSite(testSite);
                        for (String l : lutLetters) {
                            BEL bel = testSite.getBEL(l + "6LUT");
                            if (bel == null) continue;

                            if (siteInst == null || siteInst.getCell(l + "6LUT") == null) {
                                site = testSite;
                                targetBel = bel;
                                letter = l;
                                break outer;
                            }
                        }
                    }
                }
            }

            if (site == null || targetBel == null || letter == null) {
                printRejectJson("Geen vrije LUT gevonden", null, -1, -1, -1, -1, -1, origDelayNs);
                System.exit(0);
            }

            EDIFLibrary hdiLib = netlist.getHDIPrimitivesLibrary();
            EDIFCell lut1LibCell = hdiLib.getCell("LUT1");
            if (lut1LibCell == null) {
                lut1LibCell = new EDIFCell(hdiLib, "LUT1");
                lut1LibCell.createPort("I0", EDIFDirection.INPUT, 1);
                lut1LibCell.createPort("O", EDIFDirection.OUTPUT, 1);
            }

            String baseName = netName.isEmpty() ? (fromCellName + "_to_" + lutBName) : netName;
            String safeBufName =
                    sanitizeName(baseName) + "_eco_buf_" +
                    Math.abs((site.getName() + "_" + targetBel.getName()).hashCode());

            String splitNetName =
                    sanitizeName(baseName) + "_split_" + Math.abs(safeBufName.hashCode());

            EDIFCellInst lutCLog = netlist.getTopCell().createChildCellInst(safeBufName, lut1LibCell);
            lutCLog.addProperty("INIT", "2'h2");
dumpCellInstPorts("lutCLog direct na createChildCellInst", lutCLog);
            Cell lutCPhys = design.createCell(lutCLog.getName(), lutCLog);
            design.placeCell(lutCPhys, site, targetBel);
            // Bestaande mapping behouden; mogelijke volgende blocker, maar niet de best-bewezen huidige
            lutCPhys.addPinMapping(letter + "6", "I0");
            lutCPhys.addPinMapping("O6", "O");

            // Alleen fysiek losmaken als de oude fysieke sink pin ook echt bestaat
            if (oldDestPin != null) {
                origPhysNet.unroutePin(oldDestPin);
                boolean removed = origPhysNet.removePin(oldDestPin);
                if (!removed) {
                    throw new RuntimeException("Kon oude sink pin niet verwijderen van originele net.");
                }
            }

            // Logisch losmaken moet ALTIJD blijven
            EDIFPortInst logicalSinkOnOrigNet =
        findMatchingPortInstOnNet(origLogNet, lutBLog, lutBInputPortName);

if (logicalSinkOnOrigNet == null) {
    System.out.println("=== DEBUG LOGICAL NET MEMBERS ===");
    System.out.println("origLogNet = " + origLogNet.getName());
    for (EDIFPortInst epi : origLogNet.getPortInsts()) {
        System.out.println("  member: cellInst=" +
            (epi.getCellInst() == null ? "<top>" : epi.getCellInst().getName()) +
            " name=" + epi.getName());
    }
    System.out.println("target wanted = cellInst=" +
        lutBLog.getName() + " name=" + lutBInputPortName);

    throw new RuntimeException(
        "Kon geen overeenkomende logische sink-port op origLogNet vinden voor LUT B."
    );
}

System.out.println("inputPinOnB raw          = " +
    (inputPinOnB == null ? "null" :
        ((inputPinOnB.getCellInst() == null ? "<top>" : inputPinOnB.getCellInst().getName())
        + "/" + inputPinOnB.getName())));
System.out.println("logicalSinkOnOrigNet     = " +
    (logicalSinkOnOrigNet == null ? "null" :
        ((logicalSinkOnOrigNet.getCellInst() == null ? "<top>" : logicalSinkOnOrigNet.getCellInst().getName())
        + "/" + logicalSinkOnOrigNet.getName())));


EDIFPortInst removedPortInst = origLogNet.removePortInst(logicalSinkOnOrigNet);
if (removedPortInst == null) {
    throw new RuntimeException(
        "Kon oude logische portinst niet verwijderen van originele net, hoewel ze wel gevonden werd."
    );
}

// ---------- LOGISCHE NETTEN EXPLICIET OPBOUWEN ----------

// Oude logische net blijft bestaan en moet nu LUT1.I0 voeden
dumpCellInstPorts("lutCLog", lutCLog);

// Oude logische net blijft bestaan en moet nu LUT1.I0 voeden
EDIFPortInst lutCInputLogPort = createPortInstOnNetBestEffort(origLogNet, "I0", lutCLog);
if (lutCInputLogPort == null) {
    throw new RuntimeException("Kon logische portinst LUT1/I0 niet aanmaken op origLogNet.");
}

// Nieuw logisch split-net voor LUT1.O -> LUT B input
EDIFNet splitLogNet = netlist.getTopCell().getNet(splitNetName);
if (splitLogNet != null) {
    throw new RuntimeException("Split logisch net bestaat al onverwacht: " + splitNetName);
}
splitLogNet = netlist.getTopCell().createNet(splitNetName);
if (splitLogNet == null) {
    throw new RuntimeException("Kon logisch split-net niet aanmaken.");
}

EDIFPortInst lutCOutputLogPort = createPortInstOnNetBestEffort(splitLogNet, "O", lutCLog);
if (lutCOutputLogPort == null) {
    throw new RuntimeException("Kon logische portinst LUT1/O niet aanmaken op splitLogNet.");
}

EDIFPortInst lutBInputLogPort = createPortInstOnNetBestEffort(splitLogNet, lutBInputPortName, lutBLog);
if (lutBInputLogPort == null) {
    throw new RuntimeException(
        "Kon logische portinst voor LUT B input niet aanmaken op splitLogNet: " + lutBInputPortName
    );
}

System.out.println("=== DEBUG POST-LOGICAL-REWIRE ===");
System.out.println("origLogNet name = " + origLogNet.getName());
for (EDIFPortInst epi : origLogNet.getPortInsts()) {
    System.out.println("  orig member: cellInst=" +
        (epi.getCellInst() == null ? "<top>" : epi.getCellInst().getName()) +
        " name=" + epi.getName() +
        " net=" + (epi.getNet() == null ? "null" : epi.getNet().getName()));
}

System.out.println("splitLogNet name = " + splitLogNet.getName());
for (EDIFPortInst epi : splitLogNet.getPortInsts()) {
    System.out.println("  split member: cellInst=" +
        (epi.getCellInst() == null ? "<top>" : epi.getCellInst().getName()) +
        " name=" + epi.getName() +
        " net=" + (epi.getNet() == null ? "null" : epi.getNet().getName()));
}
// ---------- FYSIEKE NETTEN OPBOUWEN ----------

// Oude fysieke net voedt nu LUT1.I0
SitePinInst lutInPin = origPhysNet.connect(lutCPhys, "I0");
if (lutInPin == null) {
    throw new RuntimeException("Kon LUT1 input niet verbinden aan originele net.");
}

// Nieuw fysiek split-net
Net splitNet = design.createNet(splitNetName);
if (splitNet == null) {
    throw new RuntimeException("Kon split-net niet aanmaken.");
}

SitePinInst lutOutPin = splitNet.connect(lutCPhys, "O");
if (lutOutPin == null) {
    throw new RuntimeException("Kon LUT1 output niet verbinden aan split-net.");
}

SitePinInst newDestPin = splitNet.connect(lutBPhys, lutBInputPortName);
if (newDestPin == null) {
    throw new RuntimeException("Kon LUT B input niet verbinden aan split-net.");
}

// ---------- DEBUG LOGISCHE CONSISTENTIE ----------

System.out.println("=== DEBUG POST-LOGICAL-REWIRE ===");
System.out.println("origLogNet name = " + origLogNet.getName());
for (EDIFPortInst epi : origLogNet.getPortInsts()) {
    System.out.println("  orig member: cellInst=" +
        (epi.getCellInst() == null ? "<top>" : epi.getCellInst().getName()) +
        " name=" + epi.getName() +
        " net=" + (epi.getNet() == null ? "null" : epi.getNet().getName()));
}

System.out.println("splitLogNet name = " + splitLogNet.getName());
for (EDIFPortInst epi : splitLogNet.getPortInsts()) {
    System.out.println("  split member: cellInst=" +
        (epi.getCellInst() == null ? "<top>" : epi.getCellInst().getName()) +
        " name=" + epi.getName() +
        " net=" + (epi.getNet() == null ? "null" : epi.getNet().getName()));
}
            // Opnieuw missing SitePinInsts proberen voor timing-doeleinden
            tryCreateMissingSitePinInstsBestEffort(design, origPhysNet);
            tryCreateMissingSitePinInstsBestEffort(design, splitNet);

            design.routeSites();

            tryCreateMissingSitePinInstsBestEffort(design, origPhysNet);
            tryCreateMissingSitePinInstsBestEffort(design, splitNet);

            System.out.println("=== DEBUG POST-CONNECT ===");
            System.out.println("origPhysNet name = " + safeName(origPhysNet));
            System.out.println("splitNet name    = " + safeName(splitNet));
            System.out.println("srcPin           = " + srcPin);
            System.out.println("oldDestPin       = " + oldDestPin);
            System.out.println("lutInPin         = " + lutInPin);
            System.out.println("lutOutPin        = " + lutOutPin);
            System.out.println("newDestPin       = " + newDestPin);
            System.out.println("orig sinks       = " + safeSinkCount(origPhysNet));
            System.out.println("split sinks      = " + safeSinkCount(splitNet));

            TimingManager tm = new TimingManager(design);
            TimingModel model = tm.getTimingModel();

            BELPin lutInBelPin = getSafeBELPin(lutCPhys, lutCLog, "I0");
            BELPin lutOutBelPin = getSafeBELPin(lutCPhys, lutCLog, "O");
            BELPin lutBDestBelPin = getSafeBELPin(lutBPhys, lutBLog, lutBInputPortName);

            debugDelayInput("delay1", srcPin, lutInPin, origPhysNet);
            debugDelayInput("delay2", lutOutPin, newDestPin, splitNet);

            float delay1Ps;
            float delay2Ps;

            if (lutInBelPin != null) {
                delay1Ps = model.calcDelay(srcPin, lutInPin, null, lutInBelPin, origPhysNet);
            } else {
                delay1Ps = model.calcDelay(srcPin, lutInPin, origPhysNet);
            }

            if (lutOutBelPin != null && lutBDestBelPin != null) {
                delay2Ps = model.calcDelay(lutOutPin, newDestPin, lutOutBelPin, lutBDestBelPin, splitNet);
            } else {
                delay2Ps = model.calcDelay(lutOutPin, newDestPin, splitNet);
            }

            double rwDelay1Ns = delay1Ps / 1000.0;
            double rwDelay2Ns = delay2Ps / 1000.0;
            double totalEstimatedNs = rwDelay1Ns + LUT1_DELAY_NS + rwDelay2Ns;

            int md1 = computeMd1(site.getName(), srcX, srcY);
            int md2 = computeMd2(site.getName(), destX, destY);

            boolean accepted = totalEstimatedNs < origDelayNs;

            if (accepted) {
                design.writeCheckpoint(outputDcp);
            }

            String json = String.format(
                Locale.US,
                "RESULT_JSON: {\"accepted\": %s, \"resolved_net\": \"%s\", \"src_port\": \"%s\", \"dst_port\": \"%s\", " +
                    "\"lut_loc\": \"%s\", \"md1\": %d, \"md2\": %d, " +
                    "\"rw_delay1\": %.3f, \"rw_delay2\": %.3f, \"lut_delay\": %.3f, " +
                    "\"orig_delay_ns\": %.3f, \"total_estimated_ns\": %.3f, \"output_dcp\": \"%s\"}",
                accepted ? "true" : "false",
                escapeJson(safeName(origPhysNet)),
                escapeJson(conn.sourcePortInst == null ? "" : conn.sourcePortInst.getName()),
                escapeJson(conn.sinkPortInst == null ? "" : conn.sinkPortInst.getName()),
                site.getName(),
                md1,
                md2,
                rwDelay1Ns,
                rwDelay2Ns,
                LUT1_DELAY_NS,
                origDelayNs,
                totalEstimatedNs,
                accepted ? outputDcp : ""
            );
            System.out.println(json);

        } catch (Exception e) {
            System.err.println("FATALE FOUT in InsertBufferECOEvalCommit:");
            e.printStackTrace(System.err);
            System.exit(1);
        }
    }




    private static ConnectionResolution resolveConnectionByPinToPin(
            Design design,
            Cell srcPhys,
            EDIFCellInst srcLog,
            Cell dstPhys,
            EDIFCellInst dstLog) {

        EDIFNetlist netlist = design.getNetlist();
        String srcParent = srcPhys.getParentHierarchicalInstName();
        String dstParent = dstPhys.getParentHierarchicalInstName();

        for (EDIFPortInst srcPort : srcLog.getPortInsts()) {
            if (!srcPort.isOutput()) continue;

            Net srcNet = netlist.getPhysicalNetFromPin(srcParent, srcPort, design);
            if (srcNet == null) continue;

            for (EDIFPortInst dstPort : dstLog.getPortInsts()) {
                if (!dstPort.isInput()) continue;

                Net dstNet = netlist.getPhysicalNetFromPin(dstParent, dstPort, design);
                if (dstNet == null) continue;

                if (!srcNet.equals(dstNet)) continue;

                ConnectionResolution r = new ConnectionResolution();
r.net = srcNet;

// Belangrijk: neem NIET blind srcNet.getLogicalNet()
// maar bepaal het logische net vanuit de sink-port op LUT B
EDIFNet sinkLogicalNet = dstPort.getNet();
if (sinkLogicalNet == null) {
    throw new RuntimeException(
        "Sink-port " + dstPort.getName() + " op " + dstLog.getName() +
        " heeft geen logisch net."
    );
}

r.logNet = sinkLogicalNet;
r.sourcePortInst = srcPort;
r.sinkPortInst = dstPort;

if (r.logNet != null) {
    System.out.println("=== DEBUG RESOLVED LOGICAL NET ===");
    System.out.println("physical net = " + r.net.getName());
    System.out.println("logical net  = " + r.logNet.getName());
    System.out.println("src port     = " + r.sourcePortInst.getName());
    System.out.println("dst port     = " + r.sinkPortInst.getName());
}
                SitePinInst sourceSitePin = srcNet.getSource();
                if (sourceSitePin == null) {
                    sourceSitePin = findConnectedSitePinOnNet(srcPhys, srcPort, srcNet);
                }

                SitePinInst sinkSitePin = findSinkPinOnDestinationSite(srcNet, dstPhys);

                r.sourceSitePin = sourceSitePin;
                r.sinkSitePin = sinkSitePin;
                return r;
            }
        }

        return null;
    }

    private static BELPin getSafeBELPin(Cell physCell, EDIFCellInst logCell, String portName) {
        EDIFPortInst epi = findPortInstByName(logCell, portName);
        if (epi == null) return null;
        try {
            return physCell.getBELPin(epi);
        } catch (Exception e) {
            return null;
        }
    }

    private static EDIFPortInst findPortInstByName(EDIFCellInst cellInst, String name) {
        for (EDIFPortInst epi : cellInst.getPortInsts()) {
            if (name.equals(epi.getName())) return epi;
        }
        return null;
    }

    private static SitePinInst findConnectedSitePinOnNet(Cell cell, EDIFPortInst portInst, Net net) {
        if (cell == null || portInst == null || net == null) return null;

        List<String> siteWires = new ArrayList<>();

        SitePinInst spi = cell.getSitePinFromPortInst(portInst, siteWires);
        if (spi != null && spi.getNet() != null && spi.getNet().equals(net)) {
            return spi;
        }

        siteWires.clear();
        List<SitePinInst> candidates = cell.getAllSitePinsFromPortInst(portInst, siteWires);
        if (candidates != null) {
            for (SitePinInst c : candidates) {
                if (c != null && c.getNet() != null && c.getNet().equals(net)) {
                    return c;
                }
            }
        }

        siteWires.clear();
        candidates = cell.getAllSitePinsFromLogicalPin(portInst.getName(), siteWires);
        if (candidates != null) {
            for (SitePinInst c : candidates) {
                if (c != null && c.getNet() != null && c.getNet().equals(net)) {
                    return c;
                }
            }
        }

        return null;
    }


private static EDIFPortInst createPortInstOnNetBestEffort(EDIFNet net, String portName, EDIFCellInst cellInst) {
    if (net == null || portName == null || cellInst == null) return null;

    // Als de portinst al op dit net zit, hergebruik ze
    for (EDIFPortInst epi : net.getPortInsts()) {
        if (epi == null) continue;
        if (epi.getCellInst() == null) continue;
        if (epi.getCellInst().equals(cellInst) && portName.equals(epi.getName())) {
            return epi;
        }
    }

    try {
        // Probeer createPortInst(String, EDIFCellInst)
        Method m = EDIFNet.class.getMethod("createPortInst", String.class, EDIFCellInst.class);
        Object obj = m.invoke(net, portName, cellInst);
        if (obj instanceof EDIFPortInst) {
            return (EDIFPortInst) obj;
        }
    } catch (NoSuchMethodException e) {
        // probeer volgende overload
    } catch (Exception e) {
        throw new RuntimeException("createPortInst(String, EDIFCellInst) faalde voor " +
            cellInst.getName() + "/" + portName + " op net " + net.getName() + ": " + e.getMessage(), e);
    }

    try {
        // Probeer createPortInst(EDIFPort, EDIFCellInst)
        if (cellInst.getCellType() == null) return null;
        if (cellInst.getCellType().getPort(portName) == null) return null;

        Method m = EDIFNet.class.getMethod(
            "createPortInst",
            cellInst.getCellType().getPort(portName).getClass(),
            EDIFCellInst.class
        );
        Object obj = m.invoke(net, cellInst.getCellType().getPort(portName), cellInst);
        if (obj instanceof EDIFPortInst) {
            return (EDIFPortInst) obj;
        }
    } catch (NoSuchMethodException e) {
        // geen bruikbare overload gevonden
    } catch (Exception e) {
        throw new RuntimeException("createPortInst(EDIFPort, EDIFCellInst) faalde voor " +
            cellInst.getName() + "/" + portName + " op net " + net.getName() + ": " + e.getMessage(), e);
    }

    return null;
}





private static EDIFPortInst findMatchingPortInstOnCell(EDIFCellInst cellInst, String portName) {
    if (cellInst == null || portName == null) return null;

    // Eerst zoeken tussen bestaande portinsts
    for (EDIFPortInst epi : cellInst.getPortInsts()) {
        if (epi == null) continue;
        if (portName.equals(epi.getName())) {
            return epi;
        }
    }

    // Geen fallback met getOrCreatePortInst(), want die bestaat blijkbaar niet in jouw jar
    return null;
}




private static void dumpCellInstPorts(String tag, EDIFCellInst cellInst) {
    System.out.println("=== DEBUG CELL PORTS: " + tag + " ===");
    if (cellInst == null) {
        System.out.println("cellInst = null");
        return;
    }

    System.out.println("cellInst name = " + cellInst.getName());
    System.out.println("cell type     = " +
        (cellInst.getCellType() == null ? "null" : cellInst.getCellType().getName()));

    System.out.println("-- portInsts on instance --");
    for (EDIFPortInst epi : cellInst.getPortInsts()) {
        if (epi == null) continue;
        System.out.println("  portInst name=" + epi.getName() +
            " net=" + (epi.getNet() == null ? "null" : epi.getNet().getName()));
    }

    if (cellInst.getCellType() != null) {
        System.out.println("-- ports on master cell --");
        cellInst.getCellType().getPorts().forEach(p ->
            System.out.println("  master port name=" + p.getName())
        );
    }
}


private static EDIFPortInst findMatchingPortInstOnNet(
        EDIFNet net,
        EDIFCellInst targetCellInst,
        String portName) {

    if (net == null || targetCellInst == null || portName == null) {
        return null;
    }

    for (EDIFPortInst epi : net.getPortInsts()) {
        if (epi == null) continue;
        if (epi.getCellInst() == null) continue;

        if (epi.getCellInst().equals(targetCellInst) &&
            portName.equals(epi.getName())) {
            return epi;
        }
    }
    return null;
}
    private static SitePinInst findSinkPinOnDestinationSite(Net net, Cell destCell) {
        if (net == null || destCell == null || destCell.getSiteInst() == null) {
            return null;
        }

        String targetSiteName = destCell.getSiteInst().getSite().getName();
        SitePinInst match = null;

        for (SitePinInst spi : net.getSinkPins()) {
            if (spi == null || spi.getSite() == null) continue;

            if (targetSiteName.equals(spi.getSite().getName())) {
                if (match != null) {
                    throw new RuntimeException(
                        "Meerdere sink pins gevonden op bestemmingssite " + targetSiteName +
                        " voor net " + net.getName()
                    );
                }
                match = spi;
            }
        }

        return match;
    }

    private static void printRejectJson(String reason, String lutLoc, int md1, int md2,
                                        double rwDelay1, double rwDelay2, double totalEst,
                                        double origDelayNs) {
        String loc = (lutLoc == null) ? "" : lutLoc;
        String json = String.format(
            Locale.US,
            "RESULT_JSON: {\"accepted\": false, \"reason\": \"%s\", \"lut_loc\": \"%s\", " +
                "\"md1\": %d, \"md2\": %d, \"rw_delay1\": %.3f, \"rw_delay2\": %.3f, " +
                "\"lut_delay\": %.3f, \"orig_delay_ns\": %.3f, \"total_estimated_ns\": %.3f}",
            escapeJson(reason),
            loc,
            md1,
            md2,
            rwDelay1,
            rwDelay2,
            LUT1_DELAY_NS,
            origDelayNs,
            totalEst
        );
        System.out.println(json);
    }

    private static String sanitizeName(String s) {
        if (s == null) return "";
        return s.replace("/", "_")
                .replace("\\", "_")
                .replace("[", "_")
                .replace("]", "_");
    }

    private static String escapeJson(String s) {
        if (s == null) return "";
        return s.replace("\"", "\\\"");
    }

    private static String safeName(Net net) {
        return net == null ? "null" : net.getName();
    }

    private static int safeSinkCount(Net net) {
        if (net == null || net.getSinkPins() == null) return -1;
        return net.getSinkPins().size();
    }

    private static int parseSiteX(String siteName) {
        return Integer.parseInt(siteName.substring(siteName.indexOf('X') + 1, siteName.indexOf('Y')));
    }

    private static int parseSiteY(String siteName) {
        return Integer.parseInt(siteName.substring(siteName.indexOf('Y') + 1));
    }

    private static int computeMd1(String siteName, int srcX, int srcY) {
        int x = parseSiteX(siteName);
        int y = parseSiteY(siteName);
        return Math.abs(x - srcX) + Math.abs(y - srcY);
    }

    private static int computeMd2(String siteName, int destX, int destY) {
        int x = parseSiteX(siteName);
        int y = parseSiteY(siteName);
        return Math.abs(destX - x) + Math.abs(destY - y);
    }

    private static void debugConnectionState(String tag, Net net, EDIFNet logNet,
                                             ConnectionResolution conn, Cell srcPhys, Cell dstPhys) {
        System.out.println("=== DEBUG " + tag + " ===");
        System.out.println("phys net      = " + safeName(net));
        System.out.println("log net       = " + (logNet == null ? "null" : logNet.getName()));
        System.out.println("src cell      = " + (srcPhys == null ? "null" : srcPhys.getName()));
        System.out.println("dst cell      = " + (dstPhys == null ? "null" : dstPhys.getName()));
        System.out.println("src port      = " + (conn == null || conn.sourcePortInst == null ? "null" : conn.sourcePortInst.getName()));
        System.out.println("dst port      = " + (conn == null || conn.sinkPortInst == null ? "null" : conn.sinkPortInst.getName()));
        System.out.println("sourceSitePin = " + (conn == null ? "null" : conn.sourceSitePin));
        System.out.println("sinkSitePin   = " + (conn == null ? "null" : conn.sinkSitePin));
        System.out.println("sink count    = " + safeSinkCount(net));
    }

    private static void debugDelayInput(String tag, SitePinInst startPin, SitePinInst endPin, Net net) {
        System.out.println("=== DEBUG DELAY INPUT: " + tag + " ===");
        System.out.println("startPin = " + startPin);
        System.out.println("endPin   = " + endPin);
        System.out.println("net      = " + safeName(net));
    }

    private static void normalizePlacedDesignBestEffort(Design design) {
        tryMakePhysNetNamesConsistentBestEffort(design);
        tryCreateMissingSitePinInstsBestEffort(design, null);
        tryCreateMissingSitePinInstsBestEffort(design);
    }

    private static void tryMakePhysNetNamesConsistentBestEffort(Design design) {
        try {
            Class<?> cls = Class.forName("com.xilinx.rapidwright.design.DesignTools");
            Method m = cls.getMethod("makePhysNetNamesConsistent", Design.class);
            m.invoke(null, design);
            System.out.println("[INFO] DesignTools.makePhysNetNamesConsistent() uitgevoerd.");
        } catch (ClassNotFoundException e) {
            System.out.println("[INFO] DesignTools class niet gevonden; ga verder zonder makePhysNetNamesConsistent().");
        } catch (NoSuchMethodException e) {
            System.out.println("[INFO] makePhysNetNamesConsistent() niet aanwezig in deze RapidWright versie.");
        } catch (Exception e) {
            System.out.println("[INFO] makePhysNetNamesConsistent() probeerde te draaien maar faalde: " + e.getMessage());
        }
    }

    private static void tryCreateMissingSitePinInstsBestEffort(Design design) {
        try {
            Class<?> cls = Class.forName("com.xilinx.rapidwright.design.DesignTools");
            Method m = cls.getMethod("createMissingSitePinInsts", Design.class);
            m.invoke(null, design);
            System.out.println("[INFO] DesignTools.createMissingSitePinInsts(design) uitgevoerd.");
        } catch (ClassNotFoundException e) {
            System.out.println("[INFO] DesignTools class niet gevonden; ga verder zonder createMissingSitePinInsts(design).");
        } catch (NoSuchMethodException e) {
            System.out.println("[INFO] createMissingSitePinInsts(design) niet aanwezig in deze RapidWright versie.");
        } catch (Exception e) {
            System.out.println("[INFO] createMissingSitePinInsts(design) probeerde te draaien maar faalde: " + e.getMessage());
        }
    }

    private static void tryCreateMissingSitePinInstsBestEffort(Design design, Net net) {
        if (net == null) return;
        try {
            Class<?> cls = Class.forName("com.xilinx.rapidwright.design.DesignTools");
            Method m = cls.getMethod("createMissingSitePinInsts", Design.class, Net.class);
            m.invoke(null, design, net);
            System.out.println("[INFO] DesignTools.createMissingSitePinInsts(design, net) uitgevoerd op net " + net.getName());
        } catch (ClassNotFoundException e) {
            System.out.println("[INFO] DesignTools class niet gevonden; ga verder zonder createMissingSitePinInsts(design, net).");
        } catch (NoSuchMethodException e) {
            System.out.println("[INFO] createMissingSitePinInsts(design, net) niet aanwezig in deze RapidWright versie.");
        } catch (Exception e) {
            System.out.println("[INFO] createMissingSitePinInsts(design, net) probeerde te draaien maar faalde op net " + net.getName() + ": " + e.getMessage());
        }
    }
}
