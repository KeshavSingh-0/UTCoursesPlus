// Verifies WCAG AA contrast (4.5:1 for text, 3:1 for non-text) for the colour tokens in src/styles.css.
// Run: npm run contrast. Exits non-zero if any pair fails, and prints the ratios documented in the CSS.
const T = {
  bg: "#FFFFFF", page: "#EDF0F5", surface: "#F5F6F9", line: "#D5DAE3", lineStrong: "#7E8798",
  text: "#171A21", muted: "#4B5365",
  navy900: "#0E2238", navy700: "#1B3A5C", navy100: "#E2E9F3", navy200: "#C9D6E8",
  orange600: "#B34A00", orange700: "#963D00", orange100: "#FDEADB",
  teal700: "#0B6B61", teal100: "#D5F0EA", amber800: "#7A4B00", amber100: "#FBEBC4", red700: "#B3261E", red100: "#FCE3E0",
  white: "#FFFFFF", sidebarMuted: "#B9C7DA",
  cBlue: "#1D4F91", cBlueT: "#DCE8FA", cOrange: "#9A4200", cOrangeT: "#FDE6D2", cTeal: "#0B665E", cTealT: "#D3F0EA",
  cPurple: "#593795", cPurpleT: "#E9E1F8", cRose: "#A0224D", cRoseT: "#FADCE6", cOlive: "#51640F", cOliveT: "#E5EDC9",
  cSky: "#145F7F", cSkyT: "#D6EDF7", cGold: "#765200", cGoldT: "#F6E9BC",
};
const lum = (h) => {
  const c = [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
};
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
const pairs = [
  ["text on bg", "text", "bg"], ["text on page", "text", "page"], ["text on surface", "text", "surface"],
  ["muted on bg", "muted", "bg"], ["muted on page", "muted", "page"], ["muted on surface", "muted", "surface"],
  ["navy on bg (links, headings)", "navy700", "bg"], ["navy on navy tint", "navy700", "navy100"], ["navy900 on navy200", "navy900", "navy200"],
  ["white on navy900 (sidebar)", "white", "navy900"], ["sidebar muted on navy900", "sidebarMuted", "navy900"], ["white on navy700 (active nav)", "white", "navy700"],
  ["white on orange600 (primary button)", "white", "orange600"], ["white on orange700 (button hover)", "white", "orange700"],
  ["orange700 on bg (accent text)", "orange700", "bg"], ["orange700 on orange tint", "orange700", "orange100"], ["text on orange tint", "text", "orange100"],
  ["teal on bg (Open)", "teal700", "bg"], ["teal on teal tint", "teal700", "teal100"],
  ["amber on bg (Waitlisted)", "amber800", "bg"], ["amber on amber tint", "amber800", "amber100"],
  ["red on bg (Closed, errors)", "red700", "bg"], ["red on red tint", "red700", "red100"],
  ["cBlue on tint", "cBlue", "cBlueT"], ["cOrange on tint", "cOrange", "cOrangeT"], ["cTeal on tint", "cTeal", "cTealT"],
  ["cPurple on tint", "cPurple", "cPurpleT"], ["cRose on tint", "cRose", "cRoseT"], ["cOlive on tint", "cOlive", "cOliveT"],
  ["cSky on tint", "cSky", "cSkyT"], ["cGold on tint", "cGold", "cGoldT"],
  ["text on every course tint (blue)", "text", "cBlueT"], ["text on course tint (olive)", "text", "cOliveT"],
  ["line-strong on bg (input border, 3:1)", "lineStrong", "bg"], ["orange600 on bg (focus ring, 3:1)", "orange600", "bg"],
  ["navy700 on page (3:1 focus)", "navy700", "page"],
];
let bad = 0;
for (const [name, f, b] of pairs) {
  const min = /3:1/.test(name) ? 3.0 : 4.5;
  const r = ratio(T[f], T[b]);
  const ok = r >= min; if (!ok) bad++;
  console.log(`${ok ? "pass" : "FAIL"}  ${r.toFixed(2).padStart(5)}:1  (min ${min})  ${name}  ${T[f]} on ${T[b]}`);
}
process.exit(bad ? 1 : 0);
