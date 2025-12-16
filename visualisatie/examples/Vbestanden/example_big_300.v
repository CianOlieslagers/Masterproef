module example_big_300 (a, b, c, d, e, g, f);
  input  a, b, c, d, e, g;
  output f;

  // Veel scalar nodes, opgebouwd in lagen
  wire n1,  n2,  n3,  n4,  n5,  n6,  n7,  n8,  n9,  n10;
  wire n11, n12, n13, n14, n15, n16, n17, n18, n19, n20;
  wire n21, n22, n23, n24, n25, n26, n27, n28, n29, n30;
  wire n31, n32, n33, n34, n35, n36, n37, n38, n39, n40;
  wire n41, n42, n43, n44, n45, n46, n47, n48, n49, n50;
  wire n51, n52, n53, n54, n55, n56, n57, n58, n59, n60;
  wire n61, n62, n63, n64, n65, n66, n67, n68, n69, n70;
  wire n71, n72, n73, n74, n75, n76, n77, n78, n79, n80;

  // Laag 1 – combinaties van primaire inputs
  assign n1  = (a & b) ^ (c & d);
  assign n2  = (a | c) & (b ^ e);
  assign n3  = (d & e) | (a ^ g);
  assign n4  = (b & d) ^ (c | g);
  assign n5  = (a & ~e) | (b ^ g);
  assign n6  = (c ^ d) & (e | a);
  assign n7  = (b | e) ^ (c & g);
  assign n8  = (a ^ d) & (b | g);
  assign n9  = (c & e) ^ (d | g);
  assign n10 = (a | b) & (c ^ g);

  // Laag 2 – gebruik n1..n10
  assign n11 = (n1 & n2) ^ (n3 | a);
  assign n12 = (n2 ^ n3) & (n4 | b);
  assign n13 = (n3 & n4) ^ (n5 | c);
  assign n14 = (n4 ^ n5) & (n6 | d);
  assign n15 = (n5 & n6) ^ (n7 | e);
  assign n16 = (n6 ^ n7) & (n8 | g);
  assign n17 = (n7 & n8) ^ (n9 | a);
  assign n18 = (n8 ^ n9) & (n10 | b);
  assign n19 = (n9 & n10) ^ (n1 | c);
  assign n20 = (n10 ^ n1) & (n2 | d);

  // Laag 3 – meer menging
  assign n21 = (n11 | n12) ^ (n13 & a);
  assign n22 = (n12 & n13) | (n14 ^ b);
  assign n23 = (n13 | n14) ^ (n15 & c);
  assign n24 = (n14 & n15) | (n16 ^ d);
  assign n25 = (n15 | n16) ^ (n17 & e);
  assign n26 = (n16 & n17) | (n18 ^ g);
  assign n27 = (n17 | n18) ^ (n19 & a);
  assign n28 = (n18 & n19) | (n20 ^ b);
  assign n29 = (n19 | n20) ^ (n11 & c);
  assign n30 = (n20 & n11) | (n12 ^ d);

  // Laag 4
  assign n31 = (n21 & n22) ^ (n23 | e);
  assign n32 = (n22 ^ n23) & (n24 | g);
  assign n33 = (n23 & n24) ^ (n25 | a);
  assign n34 = (n24 ^ n25) & (n26 | b);
  assign n35 = (n25 & n26) ^ (n27 | c);
  assign n36 = (n26 ^ n27) & (n28 | d);
  assign n37 = (n27 & n28) ^ (n29 | e);
  assign n38 = (n28 ^ n29) & (n30 | g);
  assign n39 = (n29 & n30) ^ (n21 | a);
  assign n40 = (n30 ^ n21) & (n22 | b);

  // Laag 5
  assign n41 = (n31 | n32) ^ (n33 & c);
  assign n42 = (n32 & n33) | (n34 ^ d);
  assign n43 = (n33 | n34) ^ (n35 & e);
  assign n44 = (n34 & n35) | (n36 ^ g);
  assign n45 = (n35 | n36) ^ (n37 & a);
  assign n46 = (n36 & n37) | (n38 ^ b);
  assign n47 = (n37 | n38) ^ (n39 & c);
  assign n48 = (n38 & n39) | (n40 ^ d);
  assign n49 = (n39 | n40) ^ (n31 & e);
  assign n50 = (n40 & n31) | (n32 ^ g);

  // Laag 6
  assign n51 = (n41 & n42) ^ (n43 | a);
  assign n52 = (n42 ^ n43) & (n44 | b);
  assign n53 = (n43 & n44) ^ (n45 | c);
  assign n54 = (n44 ^ n45) & (n46 | d);
  assign n55 = (n45 & n46) ^ (n47 | e);
  assign n56 = (n46 ^ n47) & (n48 | g);
  assign n57 = (n47 & n48) ^ (n49 | a);
  assign n58 = (n48 ^ n49) & (n50 | b);
  assign n59 = (n49 & n50) ^ (n41 | c);
  assign n60 = (n50 ^ n41) & (n42 | d);

  // Laag 7
  assign n61 = (n51 | n52) ^ (n53 & e);
  assign n62 = (n52 & n53) | (n54 ^ g);
  assign n63 = (n53 | n54) ^ (n55 & a);
  assign n64 = (n54 & n55) | (n56 ^ b);
  assign n65 = (n55 | n56) ^ (n57 & c);
  assign n66 = (n56 & n57) | (n58 ^ d);
  assign n67 = (n57 | n58) ^ (n59 & e);
  assign n68 = (n58 & n59) | (n60 ^ g);
  assign n69 = (n59 | n60) ^ (n51 & a);
  assign n70 = (n60 & n51) | (n52 ^ b);

  // Laag 8 – laatste menglaag
  assign n71 = (n61 & n62) ^ (n63 | c);
  assign n72 = (n62 ^ n63) & (n64 | d);
  assign n73 = (n63 & n64) ^ (n65 | e);
  assign n74 = (n64 ^ n65) & (n66 | g);
  assign n75 = (n65 & n66) ^ (n67 | a);
  assign n76 = (n66 ^ n67) & (n68 | b);
  assign n77 = (n67 & n68) ^ (n69 | c);
  assign n78 = (n68 ^ n69) & (n70 | d);
  assign n79 = (n69 & n70) ^ (n61 | e);
  assign n80 = (n70 ^ n61) & (n62 | g);

  // Output – combineer de laatste nodes
  assign f = (n71 & n73) ^ (n75 | n77) ^ (n79 & n80);

endmodule
