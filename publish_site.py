"""Build the public website (GitHub Pages serves docs/): the latest finalized month's leaderboard page,
with the Workflow Control Center at the top.

    python publish_site.py [--month 2026-09]
then commit and push docs/.
"""
import argparse
from pathlib import Path

import leaderboard_html as L
import pipeline

ROOT = Path(__file__).parent

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", help="YYYY-MM (default: latest month in output/ with a saved run)")
    a = ap.parse_args()
    month = a.month or sorted(d.name for d in (ROOT / "output").iterdir() if (d / "state.pkl").exists())[-1]
    p = pipeline.Pipeline.load_state(month)
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    L.write_leaderboard_html(p, docs / "index.html")
    (docs / ".nojekyll").write_text("")
    print(f"docs/index.html built from {month}")
