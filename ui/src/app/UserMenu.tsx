import { useEffect, useRef, useState } from "react";
import { BrandLogo, Icon } from "../shared/ui";
import { ThemeChoice } from "./theme";

const THEMES: { value: ThemeChoice; label: string }[] = [
  { value: "system", label: "System" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

interface Props {
  username: string;
  theme: ThemeChoice;
  onTheme: (t: ThemeChoice) => void;
  onSignOut: () => void;
}

/** The round KF badge with the user's name. Click it to open the account menu: profile, theme, sign out. */
export function UserMenu({ username, theme, onTheme, onSignOut }: Props) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointer = (e: MouseEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { setOpen(false); trigger.current?.focus(); }
    };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="user-menu" ref={root}>
      <button ref={trigger} type="button" className="user-trigger" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <BrandLogo brand="kf" size={36} />
        <span className="user-name">{username}</span>
        <Icon name="chevronDown" size={16} />
      </button>

      {open && (
        <div className="menu" role="menu" aria-label="Account">
          <div className="menu-profile">
            <BrandLogo brand="kf" size={52} />
            <div>
              <div className="menu-name">{username}</div>
              <div className="muted small">Administrator</div>
            </div>
          </div>
          <div className="menu-section" role="group" aria-label="Theme">
            <div className="menu-label">Theme</div>
            <div className="segmented">
              {THEMES.map((t) => (
                <button key={t.value} type="button" role="menuitemradio" aria-checked={theme === t.value} className={theme === t.value ? "seg active" : "seg"} onClick={() => onTheme(t.value)}>
                  {t.label}
                </button>
              ))}
            </div>
          </div>
          <button type="button" role="menuitem" className="menu-item" onClick={() => { setOpen(false); onSignOut(); }}>Sign out</button>
        </div>
      )}
    </div>
  );
}
