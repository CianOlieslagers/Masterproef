module example_4S_mid (a, b, c, d, f);
  input  a, b, c, d;
  output f;

  wire t1, t2, t3, t4, t5, t6;
  wire u1, u2;

  // Eerste laag: AND-combinaties
  assign t1 = a & b;
  assign t2 = c & d;

  // Tweede laag: XOR-paden
  assign t3 = a ^ c;
  assign t4 = b ^ d;

  // Derde laag: mix van de vorige resultaten
  assign t5 = t1 | t2;
  assign t6 = t3 & ~t4;

  // Extra tussenwires zodat RHS simpel blijft
  assign u1 = t5 & ~t6;
  assign u2 = t6 & ~t2;

  // Output: OR van twee simpele termen
  assign f = u1 | u2;
endmodule
