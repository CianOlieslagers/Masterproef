module example_Balancing1(a, b, c, d, out);
  input  a, b, c, d;
  output out;

  wire t1, t2, t3;

  // Ongebalanceerde keten:
  // t1 = a & b
  // t2 = t1 & c = (a & b) & c
  // t3 = t2 & d = (((a & b) & c) & d)
  // out = t3
  assign t1 = a & b;
  assign t2 = t1 & c;
  assign t3 = t2 & d;
  assign out = t3;

endmodule
