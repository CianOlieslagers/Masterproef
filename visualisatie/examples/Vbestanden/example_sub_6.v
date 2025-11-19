module example_Substitution6(a, b, c, d, e, f, out);
  input  a, b, c, d, e, f;
  output out;

  // Basisbouwstenen
  wire t1, t2, t3;
  wire u, v;
  wire x1, x2;

  // Een paar AND-combinaties
  assign t1 = a & b;    // komt vaak terug
  assign t2 = c & d;
  assign t3 = c & e;

  // Twee OR-combinaties die t1 delen
  // u = (a&b) | (c&d)
  // v = (a&b) | (c&e)
  assign u = t1 | t2;
  assign v = t1 | t3;

  // x1: relatief complexe term
  assign x1 = u & v;

  // x2: duidelijk REDUNDANT:
  //   x2 = x1 & (t1 | f)
  // Daardoor is out = x1 | x2 in feite gewoon x1.
  assign x2 = x1 & (t1 | f);

  // Output: redundante OR (x1 OR x2) = x1
  assign out = x1 | x2;
endmodule
