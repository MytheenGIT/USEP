# evals: golden sets, regression suites, red-team suites

Layer L8 evaluation assets (HLD 9). Definitions only: no tenant data, no scores, no source-system data.

| Folder | Holds | Status |
|---|---|---|
| `golden/` | One golden set per domain. `golden_set_engineering.yaml` is the first | Draft, synthetic |
| `regression/` | Regression suites | Empty until Sprint 4 |
| `red-team/` | Red-team suites | Empty until Sprint 4 |
| `tools/check_golden.py` | Structure checks for golden sets | Runs locally and in CI |
| `tests/` | pytest proof that the checker rejects bad input | |

## Golden set rules (HLD 9)

- At least 150 items per domain at pilot start, growing to 300. Items follow `templates/golden-set-item.yaml`.
- Every ontology query template has at least one easy, one medium and one hard item.
- At least 10 items are permission-aware: a low-privilege `requester_role` and a non-empty `must_not_include` naming restricted entities. Those entities must not appear in the answer or the evidence (ADR-06).
- Items are held out from prompt and template tuning. Review each item quarterly and after every major ontology release.

## Status: synthetic draft (open item OI-49)

Entity names, evidence IDs and expected claims are proposals written before any source system is connected. Each SME must check every item against pilot data before it scores recall at K = 8 or evidence support. Replace the `sme_owner` role placeholder with a named person. Do not publish scores from this set until both are done.

## Run

```bash
python evals/tools/check_golden.py
python -m pytest evals/tests -q
```
