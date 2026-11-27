"""Repository connector for SSH access: one scope per repository, one document per commit.

Used for GitHub or GitLab when the admin gives an SSH key instead of a token (a key cannot call the platform API, so there
are no pull requests, comments or reviews here, only the commit history). The history is fetched shallow: the last
``max_commits`` commits on the first read, then only commits since the cursor (a day earlier, to be safe).
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from common.connector_base import ObjectError, ScopeCheck, ScopeFetch, SourceCheck
from common.git_ssh import SshKeyError, run_git, ssh_environment
from common.scopes import repo_path_from_link, ssh_link_host
from common.source_document import SourceType
from common.timeutil import parse_ts, to_utc_iso
from gitrepo.models import GitCommitDocument, GitFileChange

_RS, _US = "\x1e", "\x1f"
_FORMAT = f"{_RS}%H{_US}%an{_US}%cI{_US}%B{_US}"


def parse_log(text: str) -> list[dict[str, object]]:
    """Commits from ``git log --format=<_FORMAT> --name-status``."""
    commits = []
    for chunk in text.split(_RS):
        if not chunk.strip():
            continue
        sha, author, committed, message, files = (chunk.split(_US) + [""] * 5)[:5]
        changes = [line.split("\t", 1) for line in files.strip().splitlines() if "\t" in line]
        commits.append({"sha": sha.strip(), "author": author or None, "committed": committed.strip(), "message": message.strip(), "files": changes})
    return commits


class GitSshConnector:
    def __init__(
        self,
        source: SourceType,
        repositories: list[str],
        ssh_host: str,
        key: str | None,
        known_hosts: str = "",
        max_commits: int = 500,
        url_for: Callable[[str], str] | None = None,
    ) -> None:
        """``key=None`` is for tests against a local repository; the service always passes a key."""
        self.source = source
        self._repos = list(dict.fromkeys(repo_path_from_link(r) for r in repositories if r.strip()))
        self._host = ssh_host
        self._key = key
        self._known_hosts = known_hosts
        self._max = max_commits
        self._url_for = url_for or (lambda repo: f"git@{ssh_host}:{repo}.git")
        for original in repositories:
            host = ssh_link_host(original)
            if host and host.lower() != ssh_host.lower():
                raise SshKeyError(f"{original!r} is on {host}, not on {ssh_host}")

    @property
    def scopes(self) -> list[str]:
        return list(self._repos)

    def _env(self) -> AbstractAsyncContextManager[dict[str, str]]:
        if self._key is None:
            @asynccontextmanager
            async def plain():
                yield {"PATH": "/usr/bin:/bin:/usr/local/bin", "GIT_TERMINAL_PROMPT": "0", "GIT_ALLOW_PROTOCOL": "file"}

            return plain()
        return ssh_environment(self._key, self._known_hosts)

    async def check(self) -> SourceCheck:
        """Every repository answers to ``git ls-remote`` with this key."""
        results = []
        async with self._env() as env:
            for repo in self._repos:
                try:
                    await run_git(["ls-remote", "--heads", self._url_for(repo)], env, timeout=60)
                    results.append(ScopeCheck(scope=repo, ok=True, detail="reachable over SSH"))
                except Exception as exc:  # noqa: BLE001
                    results.append(ScopeCheck(scope=repo, ok=False, detail=str(exc)))
        return SourceCheck(ok=all(r.ok for r in results), detail="key accepted" if all(r.ok for r in results) else "see the scopes", scopes=results)

    async def fetch_scope(self, scope: str, cursor: str | None) -> ScopeFetch:
        since = parse_ts(cursor)
        with tempfile.TemporaryDirectory(prefix="usep-git-") as tmp:
            target = Path(tmp) / "repo"
            async with self._env() as env:
                args = ["clone", "--bare", "--single-branch", "--no-tags", "--quiet"]
                args += [f"--shallow-since={(since - timedelta(days=1)).strftime('%Y-%m-%d')}"] if since else [f"--depth={self._max}"]
                await run_git([*args, self._url_for(scope), str(target)], env)
                log = await run_git(["log", f"--format={_FORMAT}", "--name-status", f"--max-count={self._max}"], env, cwd=target)
        documents: list[GitCommitDocument] = []
        errors: list[ObjectError] = []
        for commit in reversed(parse_log(log)):  # oldest first
            version = to_utc_iso(str(commit["committed"]))
            if since and version and parse_ts(version) < since:  # type: ignore[operator]
                continue
            try:
                documents.append(
                    GitCommitDocument(
                        source=self.source, source_type="commit", source_object_id=f"{scope}@{commit['sha']}",
                        source_url=f"https://{self._host}/{scope}/commit/{commit['sha']}", retrieved_at=datetime.now(UTC),
                        raw_payload={"commit": commit}, scope=scope, source_version=version,
                        acl={"repository": scope}, title=str(commit["message"]).splitlines()[0] if commit["message"] else str(commit["sha"])[:12],
                        content=str(commit["message"]), metadata={"committed_at": version},
                        repository=scope, sha=str(commit["sha"]), author=commit["author"], committed_at=version,  # type: ignore[arg-type]
                        message=str(commit["message"]), files=[GitFileChange(status=s, path=p) for s, p in commit["files"]],  # type: ignore[misc]
                    )
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(ObjectError(scope=scope, object_id=str(commit["sha"]), source_version=version, error=str(exc)))
        return ScopeFetch(documents=documents, errors=errors)
