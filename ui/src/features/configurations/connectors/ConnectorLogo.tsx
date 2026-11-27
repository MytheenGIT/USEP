import { useState } from "react";

/**
 * The connector's brand mark on a small white tile, so each brand colour stays correct in both themes.
 * Files live in ui/public/brand/connectors/<key>.svg. The mark is decorative (the name is always shown beside it),
 * and a missing file falls back to the first letter instead of a broken image.
 */
export function ConnectorLogo({ connector, size = 32 }: { connector: string; size?: number }) {
  const [failed, setFailed] = useState(false);
  return (
    <span className="connector-logo" style={{ width: size, height: size, fontSize: Math.round(size * 0.45) }} aria-hidden="true">
      {failed ? connector.charAt(0).toUpperCase() : <img src={`/brand/connectors/${connector}.svg`} alt="" onError={() => setFailed(true)} draggable={false} />}
    </span>
  );
}
