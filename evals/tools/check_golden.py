"""Checks a golden set file against the item template (HLD 9) and the ontology query templates.

Run: python evals/tools/check_golden.py [file ...]   (default: every evals/golden/*.yaml)
Exit code 0 means every file passes. Synthetic placeholders are allowed; structure is not negotiable.
"""
import re
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT.parent / "ontology" / "templates"
PACKS = ROOT.parent / "ontology" / "packs"
FIELDS = ["id", "domain", "template", "difficulty", "question", "expected_entities", "expected_claims",
          "required_evidence", "requester_role", "must_not_include", "sme_owner", "created", "last_reviewed"]
DIFFICULTY = {"easy", "medium", "hard"}
SOURCES = {"git", "jira", "confluence"}
MIN_ITEMS = 150          # HLD 9: at least 150 per domain at pilot start
MIN_ABAC = 10            # items with a non-empty must_not_include
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def check(path):
    errors = []
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    items = (doc or {}).get("items")
    if not isinstance(items, list):
        return [f"{path.name}: top level must hold an 'items' list"]
    tpl = {p.stem for p in TEMPLATES.glob("*.yml")} | {p.stem for p in PACKS.glob("*/*/templates/*.yml")}   # core and pack templates (D2)
    domain = path.stem.replace("golden_set_", "")
    seen_ids, seen_q, nums = set(), {}, []
    for it in items:
        i = it.get("id", "?")
        if list(it.keys()) != FIELDS:
            errors.append(f"{i}: fields must be exactly {FIELDS} in that order")
            continue
        if not re.fullmatch(rf"{domain[:3]}-\d{{3}}", i):
            errors.append(f"{i}: id must be {domain[:3]}-NNN")
        else:
            nums.append(int(i.split("-")[1]))
        if i in seen_ids:
            errors.append(f"{i}: duplicate id")
        seen_ids.add(i)
        if it["domain"] != domain:
            errors.append(f"{i}: domain must be {domain}")
        name, _, ver = it["template"].partition("@")
        if name not in tpl or not ver:
            errors.append(f"{i}: template {it['template']} is not in ontology/templates with a version")
        if it["difficulty"] not in DIFFICULTY:
            errors.append(f"{i}: difficulty must be one of {sorted(DIFFICULTY)}")
        q = it["question"].strip().lower()
        if q in seen_q:
            errors.append(f"{i}: same question as {seen_q[q]}")
        seen_q[q] = i
        for f in ("expected_entities", "expected_claims", "required_evidence"):
            if not it[f]:
                errors.append(f"{i}: {f} is empty")
        for e in it["required_evidence"]:
            if set(e) != {"source_system", "source_id"} or e["source_system"] not in SOURCES:
                errors.append(f"{i}: evidence needs source_system in {sorted(SOURCES)} and source_id")
        for f in ("expected_entities", "must_not_include"):
            if any(not isinstance(x, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", x) for x in it[f]):
                errors.append(f"{i}: {f} must be lowercase hyphenated entity keys")
        if set(it["expected_entities"]) & set(it["must_not_include"]) and it["expected_entities"] != it["must_not_include"]:
            errors.append(f"{i}: an entity is both expected and forbidden")
        for f in ("created", "last_reviewed"):
            if not DATE.match(str(it[f])):
                errors.append(f"{i}: {f} must be YYYY-MM-DD")
        if not it["sme_owner"]:
            errors.append(f"{i}: sme_owner is empty")
    if nums != list(range(1, len(nums) + 1)):
        errors.append("ids must run 001..N with no gaps, in order")
    claims = Counter(c for it in items for c in it.get("expected_claims", []))
    for c, k in claims.items():
        if k > 1:
            errors.append(f"claim repeated {k} times: {c[:70]}")
    if len(items) < MIN_ITEMS:
        errors.append(f"{len(items)} items, floor is {MIN_ITEMS} (HLD 9)")
    abac = sum(1 for it in items if it.get("must_not_include"))
    if abac < MIN_ABAC:
        errors.append(f"only {abac} permission-aware items, need at least {MIN_ABAC}")
    for name in sorted(tpl):
        if not any(it.get("template", "").startswith(name + "@") for it in items):
            errors.append(f"no item uses template {name}")
        for d in DIFFICULTY:
            if not any(it.get("template", "").startswith(name + "@") and it.get("difficulty") == d for it in items):
                errors.append(f"template {name} has no {d} item")
    print(f"{path.name}: {len(items)} items, {abac} permission-aware, {len(errors)} problems")
    return errors


def main(argv):
    files = [Path(a) for a in argv] or sorted((ROOT / "golden").glob("golden_set_*.yaml"))
    errors = [e for f in files for e in check(f)]
    for e in errors:
        print("  FAIL", e)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
