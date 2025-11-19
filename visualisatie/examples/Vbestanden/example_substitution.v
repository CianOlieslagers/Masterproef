module example_Substitution_simple(a, b, c, d, e, f, g, h, out);
  input  a, b, c, d, e, f, g, h;
  output out;

  // Intermediate signals (ABC-compatibel: alleen declaratie)
  wire t_ab1, t_ab2;
  wire t_left;
  wire u_ef1, u_ef2;
  wire u_right;

  // --- LINKER CONE: kan sterk gesimplificeerd worden ---
  // t_ab1 = a & b & ~c
  assign t_ab1 = a & b & ~c;

  // t_ab2 = a & b & ~c & d  (absorptie: t_ab1 already covers this)
  assign t_ab2 = a & b & ~c & d;

  // T = t_ab1 | t_ab2  => algebraïsch gewoon a & b & ~c
  assign t_left = t_ab1 | t_ab2;

  // --- RECHTER CONE: ook sterk simplificeerbaar ---
  // u_ef1 = e | f
  assign u_ef1 = e | f;

  // u_ef2 = e | f | g
  assign u_ef2 = e | f | g;

  // U = (e | f) & (e | f | g) => gewoon (e | f)
  assign u_right = u_ef1 & u_ef2;

  // --- OUTPUT: typische substitutie-identiteit ---
  // (T & U) | (T & ~U) = T
  assign out = (t_left & u_right) | (t_left & ~u_right);
endmodule
