import { useState } from "react";

export type Brand = "ust" | "kf";

// Logo files are served from ui/public/brand. SVG is tried first, then PNG. If neither exists, the name is shown as text,
// so the layout never breaks while a logo is missing.
const SOURCES: Record<Brand, string[]> = {
  ust: ["/brand/ust-logo.svg", "/brand/ust-logo.png"],
  kf: ["/brand/kf-logo.svg", "/brand/kf-logo.png"],
};
const NAME: Record<Brand, string> = { ust: "UST", kf: "KF" };

interface Props {
  brand: Brand;
  /** UST: the logo's height in px. KF: the diameter of the round badge in px. */
  size?: number;
  className?: string;
}

/**
 * UST is a plain mark that follows the theme (black on light, white on dark, via --logo-filter).
 * KF is a round profile-style badge whose backing follows the theme (--avatar-bg).
 */
export function BrandLogo({ brand, size = brand === "kf" ? 40 : 32, className = "" }: Props) {
  const [attempt, setAttempt] = useState(0);
  const src = SOURCES[brand][attempt];
  const image = src
    ? <img src={src} alt={NAME[brand]} onError={() => setAttempt((a) => a + 1)} draggable={false} />
    : <span className="logo-fallback" aria-label={NAME[brand]}>{NAME[brand]}</span>;

  if (brand === "kf") {
    return <span className={`logo-avatar ${className}`.trim()} style={{ width: size, height: size }}>{image}</span>;
  }
  return <span className={`logo-mark ${className}`.trim()} style={{ height: size }}>{image}</span>;
}
