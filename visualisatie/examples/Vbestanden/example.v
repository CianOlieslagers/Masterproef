module example_rewrite (a, b, c, f);
  input  a, b, c;
  output f;

  wire t1, t2, t3;

  assign t1 = a & b;
  assign t2 = a & c;
  assign t3 = b & c;

  assign f = t1 | t2 | t3;
endmodule
