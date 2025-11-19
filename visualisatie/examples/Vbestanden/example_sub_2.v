module example_SubstTiny(a, b, out);
  input  a, b;
  output out;

  // Twee AND-paden met dezelfde "a", maar complementaire b
  wire t1, t2;

  assign t1 = a & b;     // pad 1
  assign t2 = a & ~b;    // pad 2

  // Output: OR van beide
  // (a & b) | (a & ~b) = a
  assign out = t1 | t2;
endmodule
