"""The local demo is documentation that runs: keep its dummy data and stated outcomes honest."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_demo_runs_and_matches_what_the_dummy_data_claims():
    out = subprocess.run([sys.executable, str(ROOT / "scripts/demo_local.py"), "--show"], capture_output=True, text=True,
                         cwd=ROOT, timeout=60)
    assert out.returncode == 0, out.stderr
    text = out.stdout
    assert "handled 18 raw events | entities 12 | edges 1 | link edges 6 | evidence-only 2 | quarantined 4" in text
    assert "quarantine reasons: {'Q-STATE': 2, 'Q-UNMAPPED': 2}" in text
    for expected in ("node Change ABC-2 sens=3", "node Change ABC-6 sens=2 acl=known", "edge implements ABC-2 -> ABC-1",
                     "edge references 5!7 -> ABC-3 prov=jira_key_in_branch", "edge documents 101 -> https://gitlab.example.com/pay/checkout"):
        assert expected in text
