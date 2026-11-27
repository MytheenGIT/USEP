from pathlib import Path

import pytest

from usep.pipeline.classify import ClassificationPolicy
from usep.pipeline.egress import EgressPolicy
from usep.pipeline.policy_config import PolicyConfigError, ResolutionPolicy, load_runtime_policy
from usep.pipeline.redact import redact_text

SHIPPED = Path(__file__).resolve().parents[2] / "config" / "runtime"


def write(tmp, name, text):
    (tmp / name).write_text(text, encoding="utf-8")


def test_shipped_files_equal_the_built_in_defaults():
    p = load_runtime_policy(SHIPPED)
    assert p.classification == ClassificationPolicy() and p.egress == EgressPolicy() and p.resolution == ResolutionPolicy()
    assert p.redaction.extra_secret == () and p.redaction.extra_pii == ()


def test_missing_directory_means_defaults(tmp_path):
    assert load_runtime_policy(tmp_path / "none").egress == EgressPolicy()


def test_edits_take_effect(tmp_path):
    write(tmp_path, "egress.yaml", "max_sensitivity: 2\n")
    write(tmp_path, "classification.yaml", "label_sensitivity: {pii: 3}\n")
    write(tmp_path, "redaction.yaml", 'extra_patterns:\n  - {name: tkt, pattern: "TKT-[A-Z0-9]{8}", category: secret}\n')
    p = load_runtime_policy(tmp_path)
    assert p.egress.max_sensitivity == 2 and p.classification.label_sensitivity == {"pii": 3}
    text, rep = redact_text("see TKT-ABCD1234 now", p.redaction)
    assert "TKT-" not in text and rep.secrets == {"tkt": 1}


@pytest.mark.parametrize("name,body,msg", [
    ("egress.yaml", "max_sensitivity: 9\n", "0 to 3"),
    ("egress.yaml", "allow_owners_only: maybe\n", "true or false"),
    ("egress.yaml", "surprise: 1\n", "unknown key"),
    ("classification.yaml", "label_sensitivity: {x: 7}\n", "0 to 3"),
    ("redaction.yaml", "extra_patterns:\n  - {name: a, pattern: '(', category: secret}\n", "bad pattern"),
    ("redaction.yaml", "extra_patterns:\n  - {name: ok_name, pattern: 'x*', category: secret}\n", "empty string"),
    ("redaction.yaml", "extra_patterns:\n  - {name: ok_name, pattern: 'x', category: other}\n", "secret or pii"),
    ("resolution.yaml", "auto_link_threshold: 0.5\nreview_threshold: 0.8\n", "review_threshold"),
    ("resolution.yaml", "below_review: guess\n", "new_entity or unresolved"),
])
def test_bad_policy_fails_closed(tmp_path, name, body, msg):
    write(tmp_path, name, body)
    with pytest.raises(PolicyConfigError, match=msg):
        load_runtime_policy(tmp_path)
