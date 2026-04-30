import com.xilinx.rapidwright.design.Cell;
import com.xilinx.rapidwright.design.Design;
import com.xilinx.rapidwright.design.Unisim;
import com.xilinx.rapidwright.edif.EDIFCell;
import com.xilinx.rapidwright.edif.EDIFCellInst;
import com.xilinx.rapidwright.edif.EDIFNetlist;

import java.io.FileWriter;
import java.io.PrintWriter;
import java.util.Arrays;

public class Phase6B2UpgradeAndSetInits {

    private static void die(String msg) {
        System.err.println("ERROR: " + msg);
        System.exit(1);
    }

    private static String esc(String s) {
        if (s == null) return "";
        return s.replace("\\", "\\\\").replace("\"", "\\\"");
    }

    private static void json(PrintWriter pw, String k, String v, boolean comma) {
        pw.print("  \"" + esc(k) + "\": \"" + esc(v) + "\"");
        pw.println(comma ? "," : "");
    }

    private static void jsonBool(PrintWriter pw, String k, boolean v, boolean comma) {
        pw.print("  \"" + esc(k) + "\": " + (v ? "true" : "false"));
        pw.println(comma ? "," : "");
    }

    private static void processCell(Design design, EDIFNetlist netlist, String cellName, String init) {
        Cell cell = design.getCell(cellName);
        if (cell == null) {
            die("Cell not found: " + cellName);
        }

        EDIFCellInst edifInst = cell.getEDIFCellInst();
        if (edifInst == null) {
            die("No EDIFCellInst for " + cellName);
        }

        EDIFCell lut6 = netlist.getHDIPrimitive(Unisim.LUT6);
        if (lut6 == null) {
            die("Could not get LUT6 HDI primitive");
        }

        System.out.println("[INFO] Processing " + cellName);
        System.out.println("       old physical type = " + cell.getType());
        System.out.println("       old EDIF type     = " + edifInst.getCellType().getName());
        System.out.println("       site/BEL          = " + cell.getSiteName() + "/" + cell.getBELName());

        edifInst.setCellType(lut6);
        cell.setType("LUT6");

        for (String p : Arrays.asList("I0", "I1", "I2", "I3", "I4", "I5", "O")) {
            edifInst.getOrCreatePortInst(p);
        }

        cell.addProperty("INIT", init);

        System.out.println("       new physical type = " + cell.getType());
        System.out.println("       new EDIF type     = " + edifInst.getCellType().getName());
        System.out.println("       new INIT          = " + cell.getPropertyValueString("INIT"));
    }

    public static void main(String[] args) throws Exception {
        if (args.length < 7 || ((args.length - 3) % 2 != 0)) {
            die("Usage: java Phase6B2UpgradeAndSetInits <input.dcp> <output_stage1.dcp> <report.json> <cell1> <init1> [<cell2> <init2> ...]");
        }

        String inputDcp = args[0];
        String outputDcp = args[1];
        String reportJson = args[2];

        System.out.println("[INFO] Input DCP  : " + inputDcp);
        System.out.println("[INFO] Output DCP : " + outputDcp);

        Design design = Design.readCheckpoint(inputDcp);
        EDIFNetlist netlist = design.getNetlist();

        boolean pass = true;
        String failMsg = "";

        try {
            for (int i = 3; i < args.length; i += 2) {
                String cellName = args[i];
                String init = args[i + 1];
                processCell(design, netlist, cellName, init);
            }

            design.writeCheckpoint(outputDcp);
            System.out.println("[INFO] Wrote stage1 DCP: " + outputDcp);
        } catch (Throwable t) {
            pass = false;
            failMsg = t.getMessage();
            t.printStackTrace();
        }

        try (PrintWriter pw = new PrintWriter(new FileWriter(reportJson))) {
            pw.println("{");
            json(pw, "phase", "FASE 6B.2 stage1", true);
            json(pw, "status", pass ? "PASS" : "FAIL", true);
            json(pw, "input_dcp", inputDcp, true);
            json(pw, "output_dcp", outputDcp, true);
            json(pw, "fail_message", failMsg == null ? "" : failMsg, true);
            jsonBool(pw, "ok_write_dcp", pass, false);
            pw.println("}");
        }

        System.out.println("RESULT_JSON: " + reportJson);
        System.out.println(pass ? "PHASE6B2_STAGE1_PASS" : "PHASE6B2_STAGE1_FAIL");

        if (!pass) {
            System.exit(2);
        }
    }
}
