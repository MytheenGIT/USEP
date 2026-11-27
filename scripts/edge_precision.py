"""Draw an edge sample for review, or score a reviewed sheet.

  python scripts/edge_precision.py sample <local bus dir> <out.csv> [--per-relation 100]
  python scripts/edge_precision.py score <reviewed.csv>
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from usep.pipeline import precision  # noqa: E402

ap = argparse.ArgumentParser()
sub = ap.add_subparsers(dest="cmd", required=True)
s = sub.add_parser("sample")
s.add_argument("bus_dir"); s.add_argument("out"); s.add_argument("--per-relation", type=int, default=100)
c = sub.add_parser("score")
c.add_argument("sheet")
a = ap.parse_args()
if a.cmd == "sample":
    rows = precision.sample(precision.edge_rows(precision.load_events(a.bus_dir)), a.per_relation)
    precision.write_sheet(rows, a.out)
    print(f"{len(rows)} edges written to {a.out}")
else:
    print(json.dumps(precision.score(a.sheet), indent=1))
