"""Process every monthly drop in data/inbox/ in date order, building up the memory month by month.

    python run_monthly.py            # all months not yet processed (re-running a month replaces its memory)
    python run_monthly.py --reset    # forget everything learned and start again from the first month
    python run_monthly.py --reset --demo-review   # sample data: simulated reviewer clears each month's review gate
"""
import argparse
import shutil
from pathlib import Path

import yaml

from pipeline import ROOT, Pipeline

ap = argparse.ArgumentParser()
ap.add_argument("--reset", action="store_true", help="clear memory/ before running")
ap.add_argument("--inbox", default=str(ROOT / "data" / "inbox"))
ap.add_argument("--demo-review", action="store_true", help="sample data only: let the simulated reviewer resolve blocked items")
a = ap.parse_args()
mem = ROOT / yaml.safe_load((ROOT / "config.yaml").read_text()).get("memory_dir", "memory")
if a.reset and mem.exists():
    shutil.rmtree(mem)
for folder in sorted(p for p in Path(a.inbox).iterdir() if p.is_dir()):
    print(f"\n=== {folder.name} ===")
    p = Pipeline(inbox=folder).run()
    if p.status == "awaiting_review":
        if not a.demo_review:
            print(f"Stopped at the review gate for {folder.name}. Resolve with review.py, then re-run for later months.")
            break
        import demo_review
        demo_review.resume(folder.name, demo_review.fill(folder.name))
