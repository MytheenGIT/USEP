from __future__ import annotations

import os
import stat
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from common.git_ssh import SshKeyError, load_known_hosts, ssh_environment, validate_private_key
from common.source_document import SourceType
from gitrepo.connector import GitSshConnector, parse_log

FAKE_KEY = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAABG5vbmU=\n-----END OPENSSH PRIVATE KEY-----"


def test_only_a_whole_unencrypted_private_key_is_accepted() -> None:
    assert validate_private_key(FAKE_KEY + "\r\n").endswith("-----END OPENSSH PRIVATE KEY-----\n")
    for bad in ("", "ssh-ed25519 AAAAC3Nza user@host", "-----BEGIN OPENSSH PRIVATE KEY-----\nabc", "x" * 20_000):
        with pytest.raises(SshKeyError):
            validate_private_key(bad)
    encrypted = "-----BEGIN RSA PRIVATE KEY-----\nProc-Type: 4,ENCRYPTED\nDEK-Info: AES-128-CBC,00\n\nabc\n-----END RSA PRIVATE KEY-----"
    with pytest.raises(SshKeyError, match="passphrase"):
        validate_private_key(encrypted)


def test_public_hosts_are_trusted_without_set_up_and_others_need_the_operator(tmp_path) -> None:
    from common.git_ssh import PUBLIC_HOST_KEYS, require_host_key, ssh_host_for

    assert load_known_hosts("", "") == PUBLIC_HOST_KEYS == load_known_hosts("", str(tmp_path / "missing"))
    require_host_key(load_known_hosts("", ""), "github.com")
    require_host_key(load_known_hosts("", ""), "gitlab.com")
    with pytest.raises(SshKeyError, match="git.corp.example"):
        require_host_key(load_known_hosts("", ""), "git.corp.example")
    (tmp_path / "kh").write_text("git.corp.example,10.0.0.5 ssh-ed25519 AAAA\n")
    hosts = load_known_hosts("", str(tmp_path / "kh"))
    assert hosts.startswith("git.corp.example,10.0.0.5") and hosts.endswith(PUBLIC_HOST_KEYS)
    require_host_key(hosts, "GIT.corp.example")
    assert ssh_host_for("github", "https://api.github.com") == "github.com"
    assert ssh_host_for("gitlab", "https://gitlab.corp.example/api") == "gitlab.corp.example"


async def test_the_key_lives_only_for_the_command_and_only_trusts_the_known_hosts() -> None:
    async with ssh_environment(FAKE_KEY, "github.com ssh-ed25519 AAAA\n") as env:
        command = env["GIT_SSH_COMMAND"]
        key_path = Path(command.split("-i ")[1].split(" ")[0].strip("'"))
        assert stat.S_IMODE(key_path.stat().st_mode) == 0o600 and stat.S_IMODE(key_path.parent.stat().st_mode) == 0o700
        assert "StrictHostKeyChecking=yes" in command and "BatchMode=yes" in command and "IdentitiesOnly=yes" in command
        assert env["GIT_ALLOW_PROTOCOL"] == "ssh" and env["HOME"] == str(key_path.parent)
        assert "OPENSSH PRIVATE KEY" not in " ".join(env.values())  # the key is in the file, not in the environment
    assert not key_path.exists() and not key_path.parent.exists()  # gone afterwards


def test_a_link_on_another_host_is_refused() -> None:
    with pytest.raises(SshKeyError, match="not on github.com"):
        GitSshConnector(SourceType.GITHUB, ["git@evil.example:acme/x.git"], "github.com", FAKE_KEY, "k\n")
    assert GitSshConnector(SourceType.GITHUB, ["git@github.com:acme/x.git", "acme/x", "acme/y"], "github.com", FAKE_KEY, "k\n").scopes == ["acme/x", "acme/y"]


def test_the_log_parser_reads_commits_with_their_files() -> None:
    text = "\x1eaaa\x1fDev One\x1f2026-11-01T10:00:00+00:00\x1fPAY-12 add retry\n\nbody\x1f\n\nM\tpay.py\nA\ttests/test_pay.py\n\x1ebbb\x1fDev Two\x1f2026-11-02T10:00:00+00:00\x1fsecond\x1f\n\nD\told.py\n"
    commits = parse_log(text)
    assert [c["sha"] for c in commits] == ["aaa", "bbb"]
    assert commits[0]["message"] == "PAY-12 add retry\n\nbody" and commits[0]["files"] == [["M", "pay.py"], ["A", "tests/test_pay.py"]]


def _git(*args: str, cwd: Path, **env: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env={**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", **env})


@pytest.fixture
def local_repo(tmp_path) -> Path:
    repo = tmp_path / "origin"
    repo.mkdir()
    _git("init", "-q", "-b", "main", cwd=repo)
    _git("config", "user.name", "Dev One", cwd=repo)
    _git("config", "user.email", "dev@example.test", cwd=repo)
    old = (datetime.now(UTC) - timedelta(days=20)).strftime("%Y-%m-%dT%H:%M:%S+0000")
    (repo / "a.py").write_text("one\n")
    _git("add", ".", cwd=repo)
    _git("commit", "-q", "-m", "first change", cwd=repo, GIT_AUTHOR_DATE=old, GIT_COMMITTER_DATE=old)
    (repo / "a.py").write_text("two\n")
    (repo / "b.py").write_text("new\n")
    _git("add", ".", cwd=repo)
    _git("commit", "-q", "-m", "PAY-12 retry payments\n\nmore detail", cwd=repo)
    return repo


def _connector(repo: Path) -> GitSshConnector:
    return GitSshConnector(SourceType.GITHUB, ["acme/checkout"], "github.com", None, url_for=lambda _scope: f"file://{repo}")


async def test_a_repository_is_read_into_one_document_per_commit(local_repo) -> None:
    result = await _connector(local_repo).fetch_scope("acme/checkout", None)

    assert [d.title for d in result.documents] == ["first change", "PAY-12 retry payments"]  # oldest first
    doc = result.documents[1]
    assert (doc.source, doc.source_type, doc.repository, doc.author) == (SourceType.GITHUB, "commit", "acme/checkout", "Dev One")
    assert doc.source_object_id == f"acme/checkout@{doc.sha}" and doc.source_url == f"https://github.com/acme/checkout/commit/{doc.sha}"
    assert sorted((f.status, f.path) for f in doc.files) == [("A", "b.py"), ("M", "a.py")]
    assert doc.content.endswith("more detail") and doc.acl == {"repository": "acme/checkout"}


async def test_only_commits_since_the_cursor_are_read_after_the_first_time(local_repo) -> None:
    cursor = (datetime.now(UTC) - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    result = await _connector(local_repo).fetch_scope("acme/checkout", cursor)

    assert [d.title for d in result.documents] == ["PAY-12 retry payments"]


async def test_check_reports_a_repository_it_cannot_reach(local_repo, tmp_path) -> None:
    good = await _connector(local_repo).check()
    assert good.ok and good.scopes[0].detail == "reachable over SSH"

    broken = GitSshConnector(SourceType.GITHUB, ["acme/gone"], "github.com", None, url_for=lambda _s: f"file://{tmp_path}/nope")
    result = await broken.check()
    assert not result.ok and result.scopes[0].detail.startswith("git ls-remote failed")
