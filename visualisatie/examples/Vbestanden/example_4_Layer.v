module example_small (a, b, c, d, e, g, f);
  input  a, b, c, d, e, g;
  output f;

  // Minder scalar nodes, maar nog steeds gelaagde structuur
  wire n1,  n2,  n3,  n4,  n5;
  wire n6,  n7,  n8,  n9,  n10;
  wire n11, n12, n13, n14, n15;
  wire n16, n17, n18, n19, n20;

  // Laag 1 – combinaties van primaire inputs
  assign n1 = (a & b) ^ (c & d);
  assign n2 = (a | c) & (b ^ e);
  assign n3 = (d & e) | (a ^ g);
  assign n4 = (b & d) ^ (c | g);
  assign n5 = (a & ~e) | (b ^ g);

  // Laag 2 – gebruik n1..n5
  assign n6  = (n1 & n2) ^ (n3 | a);
  assign n7  = (n2 ^ n3) & (n4 | b);
  assign n8  = (n3 & n4) ^ (n5 | c);
  assign n9  = (n4 ^ n5) & (n1 | d);
  assign n10 = (n5 & n1) ^ (n2 | e);

  // Laag 3 – meer menging
  assign n11 = (n6 | n7) ^ (n8 & a);
  assign n12 = (n7 & n8) | (n9 ^ b);
  assign n13 = (n8 | n9) ^ (n10 & c);
  assign n14 = (n9 & n10) | (n6 ^ d);
  assign n15 = (n10 | n6) ^ (n7 & e);

  // Laag 4 – laatste menglaag
  assign n16 = (n11 & n12) ^ (n13 | c);
  assign n17 = (n12 ^ n13) & (n14 | d);
  assign n18 = (n13 & n14) ^ (n15 | e);
  assign n19 = (n14 ^ n15) & (n11 | g);
  assign n20 = (n15 & n11) ^ (n12 | a);

  // Output – combineer laatste nodes
  assign f = (n16 & n18) ^ (n17 | n19) ^ (n20 & n13);

endmodule
