module example_Substitution4(a, b, c, d, out);
  input  a, b, c, d;
  output out;

  // Deze drie AND-paden hebben allemaal dezelfde 'a'
  wire t1, t2, t3;

  assign t1 = a & b;
  assign t2 = a & c;
  assign t3 = a & d;

  // OR van drie termen
  // (a & b) | (a & c) | (a & d)
  assign out = t1 | t2 | t3;
endmodule
