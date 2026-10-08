// Verifies WCAG AA contrast (4.5:1 text, 3:1 non-text) for the token pairs in src/styles.css.
// Run: npm run contrast. Exits non-zero when a pair fails, and prints the ratios documented in the CSS.
const T = {
  bg: "#FFFFFF", surface: "#F6F5F2", line: "#DAD7CF", lineStrong: "#8C887C",
  text: "#1B1B19", muted: "#55534D", primary: "#1E3A5F", primaryDark: "#142A47", primaryTint: "#E6ECF3",
  accent: "#9A4200", accentTint: "#F8ECDF", onPrimary: "#FFFFFF",
};
const lum = (h) => {
  const c = [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
};
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
const pairs = [
  ["text on bg", "text", "bg", 4.5], ["text on surface", "text", "surface", 4.5],
  ["muted on bg", "muted", "bg", 4.5], ["muted on surface", "muted", "surface", 4.5],
  ["primary on bg", "primary", "bg", 4.5], ["primary on surface", "primary", "surface", 4.5],
  ["primary on primary-tint", "primary", "primaryTint", 4.5], ["text on primary-tint", "text", "primaryTint", 4.5],
  ["on-primary on primary", "onPrimary", "primary", 4.5], ["on-primary on primary-dark", "onPrimary", "primaryDark", 4.5],
  ["accent on bg", "accent", "bg", 4.5], ["accent on surface", "accent", "surface", 4.5],
  ["accent on accent-tint", "accent", "accentTint", 4.5], ["text on accent-tint", "text", "accentTint", 4.5],
  ["line-strong on bg (inputs, 3:1)", "lineStrong", "bg", 3.0], ["primary on bg (focus ring, 3:1)", "primary", "bg", 3.0],
];
let bad = 0;
for (const [name, f, b, min] of pairs) {
  const r = ratio(T[f], T[b]);
  const ok = r >= min; if (!ok) bad++;
  console.log(`${ok ? "pass" : "FAIL"}  ${r.toFixed(2).padStart(5)}:1  (min ${min})  ${name}  ${T[f]} on ${T[b]}`);
}
process.exit(bad ? 1 : 0);
