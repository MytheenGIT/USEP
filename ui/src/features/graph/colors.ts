const PALETTE = ["#2563eb", "#0d9488", "#7c3aed", "#db2777", "#ca8a04", "#4d7c0f", "#ea580c", "#0891b2", "#9333ea", "#be123c", "#475569", "#15803d"];

/** Stable colour per concept name, so the same concept always looks the same. Text labels carry the meaning too. */
export function conceptColor(concept: string): string {
  let h = 0;
  for (const ch of concept) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return PALETTE[h % PALETTE.length];
}
