"""Version digest. Packs are pinned per tenant and each package records what was in force (HLD 6.1, 6.2)."""
from __future__ import annotations

import hashlib
from pathlib import Path


def digest_files(root: Path, files: list[Path]) -> str:
    """sha256 over (relative path, file hash) pairs in sorted order.

    LF endings are enforced by .gitattributes, so the digest is the same on every machine.
    """
    h = hashlib.sha256()
    for f in sorted({p.resolve() for p in files}):
        h.update(f.relative_to(root.resolve()).as_posix().encode())
        h.update(b"\0")
        h.update(hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()
