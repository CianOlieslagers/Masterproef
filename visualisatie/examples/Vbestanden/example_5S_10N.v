module example_5S_10N (a, b, c, d, e, g, f);
  input  a, b, c, d, e, g;
  output f;

  // Eerste laag: basis ANDs
  wire t1, t2, t3;
  assign t1 = a & b;
  assign t2 = c & d;
  assign t3 = e & g;

  // Tweede laag
  wire t4, t5, t6;
  assign t4 = t1 & c;
  assign t5 = t2 & ~e;
  assign t6 = t3 & ~a;

  // Derde laag
  wire t7, t8;
  assign t7 = t4 | t5;
  assign t8 = t5 ^ t6;

  // Output
  assign f = (t7 & ~g) | (t8 & t1);

endmodule
