module example_4S_mid (a, b, c, d, f);
  input  a, b, c, d;
  output f;

  wire t1, t2, t3, t4, t5, t6;

  // Eerste laag: AND-combinaties
  assign t1 = a & b;
  assign t2 = c & d;

  // Tweede laag: XOR-paden
  assign t3 = a ^ c;
  assign t4 = b ^ d;

  // Derde laag: mix van de vorige resultaten
  assign t5 = t1 | t2;
  assign t6 = t3 & ~t4;

  // Output: twee paden die samenkomen
  assign f = (t5 & ~t6) | (t6 & ~t2);
endmodule
