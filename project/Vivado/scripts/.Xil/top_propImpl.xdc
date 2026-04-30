set_property SRC_FILE_INFO {cfile:/home/cian/Masterproef/project/Vivado/constraints/timing_exp.xdc rfile:../../constraints/timing_exp.xdc id:1} [current_design]
set_property src_info {type:XDC file:1 line:3 export:INPUT save:INPUT read:READ} [current_design]
set_max_delay 5.0 -datapath_only -from [get_ports {a[*] b[*]}] -to   [get_ports {f[*]}]
