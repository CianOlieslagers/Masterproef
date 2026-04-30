import java.util.ArrayList;
import java.util.List;

import com.xilinx.rapidwright.design.Design;
import com.xilinx.rapidwright.design.Net;
import com.xilinx.rapidwright.edif.EDIFHierPortInst;
import com.xilinx.rapidwright.tests.CodePerfTracker;

public class ResolveSinkPin {

    public static void main(String[] args) {
        if (args.length != 3) {
            System.err.println("Gebruik: java ResolveSinkPin <dcp_path> <net_name> <sink_cell_name>");
            System.exit(1);
        }

        String dcpPath = args[0];
        String netName = args[1];
        String sinkCellName = args[2];

        try {
            Design design = Design.readCheckpoint(dcpPath, CodePerfTracker.SILENT);
            Net net = design.getNet(netName);

            if (net == null) {
                System.out.println("RESULT_JSON: {\"status\":\"NET_NOT_FOUND\"}");
                System.exit(2);
            }

            List<EDIFHierPortInst> pins = design.getNetlist().getPhysicalPins(net);
            List<String> matches = new ArrayList<>();

            for (EDIFHierPortInst p : pins) {
                if (p == null) continue;

                // Voorbeeld string: f[61]_INST_0_i_4/I0
                String s = p.toString();
                if (s.startsWith(sinkCellName + "/")) {
                    String pin = s.substring((sinkCellName + "/").length());
                    matches.add(pin);
                }
            }

            if (matches.isEmpty()) {
                System.out.println("RESULT_JSON: {\"status\":\"NO_MATCH\"}");
                System.exit(3);
            }

            if (matches.size() > 1) {
                StringBuilder sb = new StringBuilder();
                sb.append("{\"status\":\"AMBIGUOUS\",\"matches\":[");
                for (int i = 0; i < matches.size(); i++) {
                    if (i > 0) sb.append(",");
                    sb.append("\"").append(matches.get(i)).append("\"");
                }
                sb.append("]}");
                System.out.println("RESULT_JSON: " + sb.toString());
                System.exit(4);
            }

            String sinkPin = matches.get(0);
            System.out.println("RESULT_JSON: {\"status\":\"OK\",\"sink_pin\":\"" + sinkPin + "\"}");

        } catch (Exception e) {
            System.out.println("RESULT_JSON: {\"status\":\"ERROR\",\"message\":\"" +
                e.getClass().getSimpleName() + ": " + escape(e.getMessage()) + "\"}");
            System.exit(5);
        }
    }

    private static String escape(String s) {
        if (s == null) return "";
        return s.replace("\\", "\\\\").replace("\"", "\\\"");
    }
}
