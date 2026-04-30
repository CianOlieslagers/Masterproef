import com.xilinx.rapidwright.design.Design;

public class ReadDcpTest {
    public static void main(String[] args) {
        String dcpPath = "/home/cian/Masterproef/results/run_lut_insertion/2026-04-21_17-34-57/baseline_impl/checkpoints/post_route_timingexp.dcp";
        String edfPath = "/home/cian/Masterproef/results/run_lut_insertion/2026-04-21_17-34-57/baseline_impl/checkpoints/post_route.edf";


        try {
            System.out.println("Probeer DCP in te lezen...");
            Design d = Design.readCheckpoint(dcpPath, edfPath);

            System.out.println("DCP succesvol ingelezen.");
            System.out.println("Design name   : " + d.getName());
            System.out.println("Part name     : " + d.getPartName());
            System.out.println("Cell count    : " + d.getCells().size());
            System.out.println("Net count     : " + d.getNets().size());
            System.out.println("SiteInst count: " + d.getSiteInsts().size());
        } catch (Exception e) {
            System.err.println("Fout bij inlezen van DCP:");
            e.printStackTrace();
        }
    }
}
