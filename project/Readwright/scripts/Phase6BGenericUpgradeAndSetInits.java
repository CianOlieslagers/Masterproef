import com.xilinx.rapidwright.design.Design;
import com.xilinx.rapidwright.design.Cell;
import com.xilinx.rapidwright.edif.EDIFCell;
import com.xilinx.rapidwright.edif.EDIFCellInst;
import com.xilinx.rapidwright.edif.EDIFLibrary;
import com.xilinx.rapidwright.edif.EDIFNetlist;

import java.io.*;
import java.nio.file.*;
import java.util.*;

public class Phase6BGenericUpgradeAndSetInits {

    static class NodeRow {
        String abcNode;
        String physicalCell;
        String originalRef;
        String effectiveRef;
        boolean requiresUpgrade;
        String newInitEffective;
    }

    static String esc(String s) {
        if (s == null) return "";
        return s.replace("\\", "\\\\").replace("\"", "\\\"");
    }

    static List<String> parseCsvLine(String line) {
        List<String> out = new ArrayList<>();
        StringBuilder cur = new StringBuilder();
        boolean inQuotes = false;

        for (int i = 0; i < line.length(); i++) {
            char c = line.charAt(i);

            if (inQuotes) {
                if (c == '"') {
                    if (i + 1 < line.length() && line.charAt(i + 1) == '"') {
                        cur.append('"');
                        i++;
                    } else {
                        inQuotes = false;
                    }
                } else {
                    cur.append(c);
                }
            } else {
                if (c == '"') {
                    inQuotes = true;
                } else if (c == ',') {
                    out.add(cur.toString());
                    cur.setLength(0);
                } else {
                    cur.append(c);
                }
            }
        }

        out.add(cur.toString());
        return out;
    }

    static List<NodeRow> readNodesCsv(String csvPath) throws IOException {
        List<String> lines = Files.readAllLines(Paths.get(csvPath));
        if (lines.isEmpty()) throw new RuntimeException("CSV is empty: " + csvPath);

        List<String> header = parseCsvLine(lines.get(0));
        Map<String, Integer> idx = new HashMap<>();

        for (int i = 0; i < header.size(); i++) {
            idx.put(header.get(i), i);
        }

        String[] required = {
            "abc_node",
            "physical_cell",
            "original_ref",
            "effective_ref",
            "requires_upgrade",
            "new_INIT_effective"
        };

        for (String r : required) {
            if (!idx.containsKey(r)) {
                throw new RuntimeException("Missing CSV column: " + r);
            }
        }

        List<NodeRow> rows = new ArrayList<>();

        for (int li = 1; li < lines.size(); li++) {
            String line = lines.get(li).trim();
            if (line.isEmpty()) continue;

            List<String> vals = parseCsvLine(line);

            NodeRow r = new NodeRow();
            r.abcNode = vals.get(idx.get("abc_node"));
            r.physicalCell = vals.get(idx.get("physical_cell"));
            r.originalRef = vals.get(idx.get("original_ref"));
            r.effectiveRef = vals.get(idx.get("effective_ref"));
            r.requiresUpgrade = vals.get(idx.get("requires_upgrade")).trim().equals("1")
                             || vals.get(idx.get("requires_upgrade")).trim().equalsIgnoreCase("true");
            r.newInitEffective = vals.get(idx.get("new_INIT_effective"));

            rows.add(r);
        }

        return rows;
    }

    static EDIFCell findPrimitiveCell(EDIFNetlist netlist, String refName) {
        // Meestal zitten LUT1-LUT6 in hdi_primitives.
        for (EDIFLibrary lib : netlist.getLibraries()) {
            EDIFCell c = lib.getCell(refName);
            if (c != null) return c;
        }
        return null;
    }

    static String cellTypeName(Cell c) {
        try {
            EDIFCellInst eci = c.getEDIFCellInst();
            if (eci != null && eci.getCellType() != null) {
                return eci.getCellType().getName();
            }
        } catch (Exception e) {
            // ignore
        }
        return "";
    }

    public static void main(String[] args) throws Exception {
        if (args.length < 4) {
            System.err.println("Usage:");
            System.err.println("  java Phase6BGenericUpgradeAndSetInits <in.dcp> <phase6a_generic_nodes.csv> <out.dcp> <report.json>");
            System.exit(1);
        }

        String inDcp = args[0];
        String nodesCsv = args[1];
        String outDcp = args[2];
        String reportJson = args[3];

        List<NodeRow> rows = readNodesCsv(nodesCsv);

        Design design = Design.readCheckpoint(inDcp);
        EDIFNetlist netlist = design.getNetlist();

        int cellsSeen = 0;
        int upgradesApplied = 0;
        int initsSet = 0;
        int errors = 0;

        List<String> reportItems = new ArrayList<>();

        for (NodeRow r : rows) {
            Cell cell = design.getCell(r.physicalCell);

            if (cell == null) {
                errors++;
                reportItems.add("{\"cell\":\"" + esc(r.physicalCell) + "\",\"status\":\"ERROR\",\"message\":\"cell not found\"}");
                continue;
            }

            cellsSeen++;

            String beforeType = cellTypeName(cell);

            try {
                if (r.requiresUpgrade || !beforeType.equals(r.effectiveRef)) {
                    EDIFCell newType = findPrimitiveCell(netlist, r.effectiveRef);

                    if (newType == null) {
                        errors++;
                        reportItems.add(
                            "{\"cell\":\"" + esc(r.physicalCell) +
                            "\",\"status\":\"ERROR\",\"message\":\"primitive type not found: " +
                            esc(r.effectiveRef) + "\"}"
                        );
                        continue;
                    }

                    EDIFCellInst eci = cell.getEDIFCellInst();

                    if (eci == null) {
                        errors++;
                        reportItems.add(
                            "{\"cell\":\"" + esc(r.physicalCell) +
                            "\",\"status\":\"ERROR\",\"message\":\"EDIFCellInst is null\"}"
                        );
                        continue;
                    }

                    eci.setCellType(newType);
                    upgradesApplied++;
                }

                cell.addProperty("INIT", r.newInitEffective);
                initsSet++;

                String afterType = cellTypeName(cell);

                reportItems.add(
                    "{"
                    + "\"abc_node\":\"" + esc(r.abcNode) + "\","
                    + "\"cell\":\"" + esc(r.physicalCell) + "\","
                    + "\"status\":\"OK\","
                    + "\"before_type\":\"" + esc(beforeType) + "\","
                    + "\"effective_ref\":\"" + esc(r.effectiveRef) + "\","
                    + "\"after_type\":\"" + esc(afterType) + "\","
                    + "\"requires_upgrade\":" + r.requiresUpgrade + ","
                    + "\"init\":\"" + esc(r.newInitEffective) + "\""
                    + "}"
                );

            } catch (Exception e) {
                errors++;
                reportItems.add(
                    "{"
                    + "\"cell\":\"" + esc(r.physicalCell) + "\","
                    + "\"status\":\"ERROR\","
                    + "\"message\":\"" + esc(e.toString()) + "\""
                    + "}"
                );
            }
        }

        if (errors == 0) {
            design.writeCheckpoint(outDcp);
        }

        try (PrintWriter pw = new PrintWriter(new FileWriter(reportJson))) {
            pw.println("{");
            pw.println("  \"phase\": \"FASE 6B GENERIC STAGE1\",");
            pw.println("  \"input_dcp\": \"" + esc(inDcp) + "\",");
            pw.println("  \"nodes_csv\": \"" + esc(nodesCsv) + "\",");
            pw.println("  \"output_dcp\": \"" + esc(outDcp) + "\",");
            pw.println("  \"cells_seen\": " + cellsSeen + ",");
            pw.println("  \"upgrades_applied\": " + upgradesApplied + ",");
            pw.println("  \"inits_set\": " + initsSet + ",");
            pw.println("  \"errors\": " + errors + ",");
            pw.println("  \"status\": \"" + (errors == 0 ? "PASS" : "FAIL") + "\",");
            pw.println("  \"items\": [");
            for (int i = 0; i < reportItems.size(); i++) {
                pw.print("    " + reportItems.get(i));
                if (i + 1 < reportItems.size()) pw.println(",");
                else pw.println();
            }
            pw.println("  ]");
            pw.println("}");
        }

        if (errors != 0) {
            System.err.println("PHASE6B_GENERIC_STAGE1_FAIL errors=" + errors);
            System.exit(2);
        }

        System.out.println("PHASE6B_GENERIC_STAGE1_PASS");
        System.out.println("Output DCP: " + outDcp);
        System.out.println("Report   : " + reportJson);
    }
}
