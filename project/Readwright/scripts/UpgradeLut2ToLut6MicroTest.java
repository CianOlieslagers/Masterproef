import com.xilinx.rapidwright.design.Cell;
import com.xilinx.rapidwright.design.Design;
import com.xilinx.rapidwright.design.Unisim;
import com.xilinx.rapidwright.edif.EDIFCell;
import com.xilinx.rapidwright.edif.EDIFCellInst;
import com.xilinx.rapidwright.edif.EDIFNetlist;

import java.io.FileWriter;
import java.io.PrintWriter;
import java.util.Arrays;

public class UpgradeLut2ToLut6MicroTest {

    private static void die(String msg) {
        System.err.println("ERROR: " + msg);
        System.exit(1);
    }

    private static String safe(Object o) {
        return o == null ? "" : o.toString();
    }

    private static void writeJson(PrintWriter pw, String key, String value, boolean comma) {
        pw.print("  \"" + key + "\": ");
        if (value == null) {
            pw.print("null");
        } else {
            pw.print("\"" + value.replace("\\", "\\\\").replace("\"", "\\\"") + "\"");
        }
        if (comma) pw.println(",");
        else pw.println();
    }

    private static void writeJsonBool(PrintWriter pw, String key, boolean value, boolean comma) {
        pw.print("  \"" + key + "\": " + (value ? "true" : "false"));
        if (comma) pw.println(",");
        else pw.println();
    }

    public static void main(String[] args) throws Exception {
        if (args.length < 5) {
            die("Usage: java UpgradeLut2ToLut6MicroTest <input.dcp> <output.dcp> <cell_name> <new_init> <report.json>");
        }

        String inputDcp = args[0];
        String outputDcp = args[1];
        String cellName = args[2];
        String newInit = args[3];
        String reportJson = args[4];

        System.out.println("[INFO] Input DCP  : " + inputDcp);
        System.out.println("[INFO] Output DCP : " + outputDcp);
        System.out.println("[INFO] Cell       : " + cellName);
        System.out.println("[INFO] New INIT   : " + newInit);

        Design design = Design.readCheckpoint(inputDcp);
        EDIFNetlist netlist = design.getNetlist();

        Cell cell = design.getCell(cellName);
        if (cell == null) {
            die("Cell not found in design: " + cellName);
        }

        String oldType = safe(cell.getType());
        String oldBEL = safe(cell.getBELName());
        String oldSite = safe(cell.getSiteName());
        String oldInit = safe(cell.getPropertyValueString("INIT"));

        System.out.println("[INFO] Old physical type : " + oldType);
        System.out.println("[INFO] Old site/BEL      : " + oldSite + "/" + oldBEL);
        System.out.println("[INFO] Old INIT          : " + oldInit);

        EDIFCellInst edifInst = cell.getEDIFCellInst();
        if (edifInst == null) {
            die("Could not get EDIFCellInst for cell: " + cellName);
        }

        String oldEdifType = edifInst.getCellType() == null ? "" : edifInst.getCellType().getName();

        System.out.println("[INFO] Old EDIF type     : " + oldEdifType);

        EDIFCell lut6Primitive = netlist.getHDIPrimitive(Unisim.LUT6);
        if (lut6Primitive == null) {
            die("Could not get HDI primitive LUT6 from netlist");
        }

        boolean okSetEdifType = false;
        boolean okSetPhysicalType = false;
        boolean okCreatePorts = false;
        boolean okSetInit = false;
        boolean okWriteDcp = false;

        try {
            // Logical netlist upgrade: LUT2 -> LUT6.
            edifInst.setCellType(lut6Primitive);
            okSetEdifType = true;
            System.out.println("[INFO] EDIF cell type set to LUT6");
        } catch (Throwable t) {
            System.err.println("[ERROR] Failed to set EDIF cell type: " + t.getMessage());
            t.printStackTrace();
        }

        try {
            // Physical/design-level type update.
            cell.setType("LUT6");
            okSetPhysicalType = true;
            System.out.println("[INFO] Physical Cell type set to LUT6");
        } catch (Throwable t) {
            System.err.println("[ERROR] Failed to set physical cell type: " + t.getMessage());
            t.printStackTrace();
        }

        try {
            // Ensure EDIF port insts exist for I0-I5 and O.
            // getOrCreatePortInst only creates logical port insts.
            // It does not connect them to nets yet.
            for (String p : Arrays.asList("I0", "I1", "I2", "I3", "I4", "I5", "O")) {
                edifInst.getOrCreatePortInst(p);
            }
            okCreatePorts = true;
            System.out.println("[INFO] Ensured EDIF port insts I0-I5/O exist");
        } catch (Throwable t) {
            System.err.println("[ERROR] Failed to create/check EDIF port insts: " + t.getMessage());
            t.printStackTrace();
        }

        try {
            cell.addProperty("INIT", newInit);
            okSetInit = true;
            System.out.println("[INFO] INIT property set to " + newInit);
        } catch (Throwable t) {
            System.err.println("[ERROR] Failed to set INIT: " + t.getMessage());
            t.printStackTrace();
        }

        String newType = safe(cell.getType());
        String newEdifType = edifInst.getCellType() == null ? "" : edifInst.getCellType().getName();
        String newInitReadback = safe(cell.getPropertyValueString("INIT"));

        System.out.println("[INFO] New physical type : " + newType);
        System.out.println("[INFO] New EDIF type     : " + newEdifType);
        System.out.println("[INFO] New INIT readback : " + newInitReadback);

        try {
            design.writeCheckpoint(outputDcp);
            okWriteDcp = true;
            System.out.println("[INFO] Wrote DCP: " + outputDcp);
        } catch (Throwable t) {
            System.err.println("[ERROR] Failed to write DCP: " + t.getMessage());
            t.printStackTrace();
        }

        boolean pass =
                okSetEdifType &&
                okSetPhysicalType &&
                okCreatePorts &&
                okSetInit &&
                okWriteDcp &&
                "LUT6".equals(newType) &&
                "LUT6".equals(newEdifType);

        try (PrintWriter pw = new PrintWriter(new FileWriter(reportJson))) {
            pw.println("{");
            writeJson(pw, "phase", "FASE 6B.1", true);
            writeJson(pw, "status", pass ? "PASS" : "FAIL", true);
            writeJson(pw, "input_dcp", inputDcp, true);
            writeJson(pw, "output_dcp", outputDcp, true);
            writeJson(pw, "cell", cellName, true);
            writeJson(pw, "old_physical_type", oldType, true);
            writeJson(pw, "old_edif_type", oldEdifType, true);
            writeJson(pw, "old_site", oldSite, true);
            writeJson(pw, "old_bel", oldBEL, true);
            writeJson(pw, "old_init", oldInit, true);
            writeJson(pw, "new_requested_init", newInit, true);
            writeJson(pw, "new_physical_type", newType, true);
            writeJson(pw, "new_edif_type", newEdifType, true);
            writeJson(pw, "new_init_readback", newInitReadback, true);
            writeJsonBool(pw, "ok_set_edif_type", okSetEdifType, true);
            writeJsonBool(pw, "ok_set_physical_type", okSetPhysicalType, true);
            writeJsonBool(pw, "ok_create_ports", okCreatePorts, true);
            writeJsonBool(pw, "ok_set_init", okSetInit, true);
            writeJsonBool(pw, "ok_write_dcp", okWriteDcp, false);
            pw.println("}");
        }

        System.out.println("RESULT_JSON: " + reportJson);
        System.out.println(pass ? "PHASE6B1_PASS" : "PHASE6B1_FAIL");

        if (!pass) {
            System.exit(2);
        }
    }
}
