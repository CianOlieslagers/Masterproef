import com.xilinx.rapidwright.design.Cell;
import com.xilinx.rapidwright.design.Design;
import com.xilinx.rapidwright.design.Unisim;
import com.xilinx.rapidwright.edif.EDIFCell;
import com.xilinx.rapidwright.edif.EDIFCellInst;
import com.xilinx.rapidwright.edif.EDIFNetlist;

import java.io.FileWriter;
import java.io.PrintWriter;
import java.math.BigInteger;
import java.util.Arrays;
import java.util.List;

public class Phase6B2SetTypedLuts {

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

    private static int lutSize(String ref) {
        if (ref == null || !ref.matches("LUT[1-6]")) {
            die("Unsupported logical_ref: " + ref);
        }
        return Integer.parseInt(ref.substring(3));
    }

    private static String compactInit(String init, String logicalRef) {
        int k = lutSize(logicalRef);
        int bits = 1 << k;
        int hexDigits = Math.max(1, (bits + 3) / 4);

        String s = init.trim();

        int idx = s.indexOf("'h");
        if (idx >= 0) {
            s = s.substring(idx + 2);
        }

        s = s.replace("_", "");

        BigInteger value = new BigInteger(s, 16);
        BigInteger mask = BigInteger.ONE.shiftLeft(bits).subtract(BigInteger.ONE);
        BigInteger compact = value.and(mask);

        return bits + "'h" + compact.toString(16).toUpperCase();
    }

    private static Unisim unisimFor(String logicalRef) {
        try {
            return Unisim.valueOf(logicalRef);
        } catch (Exception e) {
            die("Cannot map logical_ref to Unisim: " + logicalRef);
            return null;
        }
    }

    private static void processCell(
            Design design,
            EDIFNetlist netlist,
            String cellName,
            String logicalRef,
            String init
    ) {
        Cell cell = design.getCell(cellName);
        if (cell == null) {
            die("Cell not found: " + cellName);
        }

        EDIFCellInst edifInst = cell.getEDIFCellInst();
        if (edifInst == null) {
            die("No EDIFCellInst for " + cellName);
        }

        String newInit = compactInit(init, logicalRef);
        Unisim targetUnisim = unisimFor(logicalRef);

        EDIFCell targetPrimitive = netlist.getHDIPrimitive(targetUnisim);
        if (targetPrimitive == null) {
            die("Could not get HDI primitive for " + logicalRef);
        }

        System.out.println("[INFO] Processing " + cellName);
        System.out.println("       old physical type = " + cell.getType());
        System.out.println("       old EDIF type     = " + edifInst.getCellType().getName());
        System.out.println("       requested type    = " + logicalRef);
        System.out.println("       site/BEL          = " + cell.getSiteName() + "/" + cell.getBELName());
        System.out.println("       old/new INIT      = " + init + " -> " + newInit);

        edifInst.setCellType(targetPrimitive);
        cell.setType(logicalRef);

        int k = lutSize(logicalRef);

        for (int i = 0; i < k; i++) {
            edifInst.getOrCreatePortInst("I" + i);
        }
        edifInst.getOrCreatePortInst("O");

        cell.addProperty("INIT", newInit);

        System.out.println("       new physical type = " + cell.getType());
        System.out.println("       new EDIF type     = " + edifInst.getCellType().getName());
        System.out.println("       final INIT        = " + cell.getPropertyValueString("INIT"));
    }

    public static void main(String[] args) throws Exception {
        if (args.length < 6 || ((args.length - 3) % 3 != 0)) {
            die("Usage: java Phase6B2SetTypedLuts <input.dcp> <output_stage1.dcp> <report.json> <cell1> <logical_ref1> <init1> [<cell2> <logical_ref2> <init2> ...]");
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
            int cellsSeen = 0;

            for (int i = 3; i < args.length; i += 3) {
                String cellName = args[i];
                String logicalRef = args[i + 1];
                String init = args[i + 2];

                processCell(design, netlist, cellName, logicalRef, init);
                cellsSeen++;
            }

            design.writeCheckpoint(outputDcp);
            System.out.println("[INFO] Wrote stage1 DCP: " + outputDcp);
            System.out.println("[INFO] cells_seen=" + cellsSeen);

        } catch (Throwable t) {
            pass = false;
            failMsg = t.getMessage();
            t.printStackTrace();
        }

        try (PrintWriter pw = new PrintWriter(new FileWriter(reportJson))) {
            pw.println("{");
            json(pw, "phase", "FASE 6B.2 typed stage1", true);
            json(pw, "status", pass ? "PASS" : "FAIL", true);
            json(pw, "input_dcp", inputDcp, true);
            json(pw, "output_dcp", outputDcp, true);
            json(pw, "fail_message", failMsg == null ? "" : failMsg, true);
            jsonBool(pw, "ok_write_dcp", pass, false);
            pw.println("}");
        }

        System.out.println("RESULT_JSON: " + reportJson);
        System.out.println(pass ? "PHASE6B2_TYPED_STAGE1_PASS" : "PHASE6B2_TYPED_STAGE1_FAIL");

        if (!pass) {
            System.exit(2);
        }
    }
}
