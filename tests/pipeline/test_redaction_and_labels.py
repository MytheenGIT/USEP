"""Redaction, sensitivity and ACL labelling."""
import json

import pytest

from tests.pipeline.helpers import (jira, published, raw_event)
from usep.pipeline.redact import redact_text




def test_secret_is_redacted_everywhere_and_raises_sensitivity(env):
    s3, _, w = env
    secret = "AKIAABCDEFGHIJKLMNOP"
    w.handle(raw_event(s3, "jira", "ABC-5", jira("ABC-5", "Task", "Done", desc=f"use key {secret} and password: hunter2xx")))
    blob = b"".join(v for k, v in s3.objects.items() if not k.startswith("raw/"))
    assert secret.encode() not in blob and b"hunter2xx" not in blob
    p = published(s3, "entity.product")[0]["payload"]
    assert p["labels"]["sensitivity"] == 3 and p["labels"]["redaction"]["secrets"]["aws_access_key"] == 1
    ev = json.loads(next(v for k, v in s3.objects.items() if k.startswith("evidence/")))
    assert "[REDACTED:aws_access_key]" in ev["text"]


def test_acl_unknown_means_owners_only_and_issue_security_is_known(env):
    s3, _, w = env
    w.handle(raw_event(s3, "jira", "ABC-6", jira("ABC-6", "Task", "Done")))
    w.handle(raw_event(s3, "jira", "ABC-7", jira("ABC-7", "Task", "Done", security="Finance")))
    by_id = {e["payload"]["attributes"]["source_id"]: e["payload"] for e in published(s3, "entity.product")}
    a, b = by_id["ABC-6"], by_id["ABC-7"]
    assert a["labels"]["acl_state"] == "unknown" and a["labels"]["owners_only"] and a["labels"]["sensitivity"] == 1
    assert b["labels"]["acl_state"] == "known" and b["attributes"]["acl_ref"] == "jira_issue_security:security_level:Finance"
    assert b["labels"]["sensitivity"] == 2


def test_label_pci_raises_sensitivity(env):
    s3, _, w = env
    w.handle(raw_event(s3, "jira", "ABC-8", jira("ABC-8", "Task", "Done", labels=["PCI"])))
    assert published(s3, "entity.product")[0]["payload"]["labels"]["sensitivity"] == 3


@pytest.mark.parametrize("text,kind", [
    ("-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----", "private_key"),
    ("postgres://app:s3cretpw@db/x", "connection_string_password"),
    ("Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456", "bearer_token"),
    ("token glpat-abcdefghijklmnopqrstu", "gitlab_token"),
])
def test_redaction_kinds(text, kind):
    out, rep = redact_text(text)
    assert kind in rep.secrets and "s3cretpw" not in out and "abcdefghijklmnopqrstuvwxyz" not in out


def test_redaction_luhn_and_email():
    out, rep = redact_text("card 4111 1111 1111 1111, order 1234 5678 9012 3456, mail a.b@corp.com")
    assert rep.pii == {"email": 1, "card_number": 1} and "1234 5678 9012 3456" in out

