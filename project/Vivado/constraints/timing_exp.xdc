# timing_exp.xdc

set_max_delay 5.0 -datapath_only \
  -from [get_ports {a[*] b[*]}] \
  -to   [get_ports {f[*]}]
