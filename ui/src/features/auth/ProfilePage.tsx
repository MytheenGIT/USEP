import { ThemeChoice } from "../../app/theme";
import { Button, Card, BrandLogo, Segmented } from "../../shared/ui";
import { useAuth } from "./AuthContext";

/** The signed-in admin: who they are, how the page looks for them, and a way to sign out. */
export function ProfilePage({ theme, onTheme }: { theme: ThemeChoice; onTheme: (t: ThemeChoice) => void }) {
  const { session, signOut } = useAuth();
  return (
    <>
      <div className="page-head"><div><h1>Profile</h1><p className="muted">The account you are signed in with.</p></div></div>
      <Card>
        <div className="profile">
          <BrandLogo brand="kf" size={72} />
          <div>
            <h2>{session?.username}</h2>
            <p className="muted">Administrator</p>
          </div>
        </div>
        <dl className="profile-facts">
          <div><dt>Session</dt><dd>Kept in this browser tab's memory only. Reloading the page, or signing out, ends it.</dd></div>
          <div><dt>Credentials you typed</dt><dd>Tokens and keys go to the server for one run and are never stored or shown again.</dd></div>
        </dl>
        <div className="field">
          <span className="field-title">Appearance</span>
          <Segmented<ThemeChoice> label="Theme" value={theme} onChange={onTheme} options={[{ value: "system", label: "System" }, { value: "light", label: "Light" }, { value: "dark", label: "Dark" }]} />
        </div>
        <div className="profile-actions"><Button variant="danger" onClick={() => void signOut()}>Sign out</Button></div>
      </Card>
    </>
  );
}
