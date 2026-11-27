"""Checks the properties ADR-20 relies on in platform-iac/registry/template.yaml. Not a substitute for cfn-lint."""
from pathlib import Path

import yaml

TEMPLATE = Path(__file__).resolve().parents[2] / "platform-iac" / "registry" / "template.yaml"


class _Loader(yaml.SafeLoader):
    pass


def _tag(loader, suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return {suffix: loader.construct_scalar(node)}
    if isinstance(node, yaml.SequenceNode):
        return {suffix: loader.construct_sequence(node, deep=True)}
    return {suffix: loader.construct_mapping(node, deep=True)}


_Loader.add_multi_constructor("!", _tag)


def _t():
    return yaml.load(TEMPLATE.read_text(encoding="utf-8"), Loader=_Loader)["Resources"]


def test_signing_key_is_asymmetric_sign_only():
    p = _t()["SigningKey"]["Properties"]
    assert p["KeyUsage"] == "SIGN_VERIFY" and p["KeySpec"] == "ECC_NIST_P256"


def test_only_publisher_can_sign_and_admin_cannot():
    stmts = {s["Sid"]: s for s in _t()["SigningKey"]["Properties"]["KeyPolicy"]["Statement"]}
    assert "kms:Sign" not in stmts["AdministerNotSign"]["Action"]
    assert stmts["NobodyElseSigns"]["Effect"] == "Deny" and "NotPrincipal" in stmts["NobodyElseSigns"]


def test_bucket_is_locked_versioned_private_and_retained():
    r = _t()["RegistryBucket"]
    p = r["Properties"]
    assert r["DeletionPolicy"] == "Retain" and p["ObjectLockEnabled"] is True
    assert p["VersioningConfiguration"]["Status"] == "Enabled"
    assert all(p["PublicAccessBlockConfiguration"].values())


def test_bucket_policy_denies_deletes_and_plain_http():
    stmts = {s["Sid"]: s for s in _t()["RegistryBucketPolicy"]["Properties"]["PolicyDocument"]["Statement"]}
    assert "s3:DeleteObject" in stmts["NoDeletes"]["Action"] and "s3:BypassGovernanceRetention" in stmts["NoDeletes"]["Action"]
    assert stmts["TlsOnly"]["Condition"]["Bool"]["aws:SecureTransport"] == "false"


def test_publisher_trusts_only_the_release_environment():
    cond = _t()["PublisherRole"]["Properties"]["AssumeRolePolicyDocument"]["Statement"][0]["Condition"]["StringEquals"]
    assert "token.actions.githubusercontent.com:sub" in cond


def test_reader_policy_is_read_only():
    for s in _t()["RegistryReaderPolicy"]["Properties"]["PolicyDocument"]["Statement"]:
        assert not any(a.startswith(("s3:Put", "s3:Delete", "kms:Sign")) for a in s["Action"])
