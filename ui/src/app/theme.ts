import { useLayoutEffect, useState } from "react";

export type ThemeChoice = "system" | "light" | "dark";
const KEY = "usep-theme";

function read(): ThemeChoice {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

/** Light, dark or follow the system. Only this display preference is stored in the browser; never a token. */
export function useTheme(): { theme: ThemeChoice; setTheme: (t: ThemeChoice) => void } {
  const [theme, setTheme] = useState<ThemeChoice>(read);
  // layout effect: the attribute must be set before child effects read CSS variables (the graph canvas does)
  useLayoutEffect(() => {
    if (theme === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", theme);
    try {
      if (theme === "system") localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, theme);
    } catch {
      /* storage unavailable: the choice lasts for this page only */
    }
  }, [theme]);
  return { theme, setTheme };
}
