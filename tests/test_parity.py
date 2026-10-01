"""Parity check: the browser Control Center (web/engine.js) and the Python pipeline, run on the same files and memory,
must agree on QA flags, vendor scores, tiers, review outcomes and final creator scores.

    python tests/test_parity.py [seed ...]        (needs playwright + chromium)
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pandas as pd                                       # noqa: E402
from playwright.sync_api import sync_playwright           # noqa: E402

import demo_data                                          # noqa: E402
import leaderboard_html as L                              # noqa: E402
import pipeline                                           # noqa: E402
from review import resume_df                              # noqa: E402

MONTH = "2026-10"


def pick(code: str, values: dict) -> str:                # the same reviewer decision on both sides
    if code == "IDENTITY_MATCH_UNCERTAIN":
        return "SELECT_VENDOR_A" if "vendor_a" in values else "REJECT_MATCH"
    return "SELECT_VENDOR_A" if "vendor_a" in values else "EXCLUDE"


def python_side(files, mem):
    p = pipeline.run_uploaded(files, MONTH, out_dir=Path(tempfile.mkdtemp()), memory_dir=mem, auto_finalize=False)
    stage1 = summarize_py(p)
    dec = pd.DataFrame([{"Review ID": f.id, "Decision": pick(f.code, f.values)} for f in p.flags.open_red()])
    p, problems = resume_df(p, dec, "parity")
    while p.flags.open_red():                            # a confirmed match can surface new items
        dec = pd.DataFrame([{"Review ID": f.id, "Decision": pick(f.code, f.values)} for f in p.flags.open_red()])
        p, problems = resume_df(p, dec, "parity")
    scores = {r["creator_id"]: {m: (None if pd.isna(r[m]) else round(float(r[m]), 1)) for m in p.metrics}
              for r in p.leaderboard.to_dict("records")}
    return p, stage1, scores


def summarize_py(p):
    codes = {}
    for f in p.flags.flags:
        codes[f.code] = codes.get(f.code, 0) + 1
    return {"codes": codes, "tiers": list(p.tiers),
            "vendors": {n: [round(pr.current_score, 3), None if pr.history_score is None else round(pr.history_score, 3),
                            round(pr.score, 3)] for n, pr in p.profiles.items()},
            "red": sorted((f.creator_id, f.platform, f.field, f.code) for f in p.flags.flags if f.severity == "RED"),
            "complete": round(p.final["channels_complete"], 4)}


JS_SUMMARY = """() => { const R = __CC.run, codes = {}; R.flags.forEach(f => codes[f.code] = (codes[f.code] || 0) + 1);
  return {codes, tiers: R.tiers,
    vendors: Object.fromEntries(Object.values(R.profiles).map(P => [P.name, [+P.current_score.toFixed(3), P.history_score == null ? null : +P.history_score.toFixed(3), +P.score.toFixed(3)]])),
    red: R.flags.filter(f => f.severity === "RED").map(f => [f.creator_id, f.platform, f.field, f.code]).sort(),
    complete: +R.final.channels_complete.toFixed(4)}; }"""
JS_DECIDE = """() => { const rows = [...document.querySelectorAll('#cc-review tr[data-f]')];
  rows.forEach(tr => { const f = __CC.run.flags.find(x => x.id === tr.dataset.f), s = tr.querySelector('select');
    s.value = f.code === 'IDENTITY_MATCH_UNCERTAIN' ? ('vendor_a' in f.values ? 'SELECT_VENDOR_A' : 'REJECT_MATCH') : ('vendor_a' in f.values ? 'SELECT_VENDOR_A' : 'EXCLUDE'); });
  return rows.length; }"""


def js_side(page_path, files):
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(page_path.as_uri())
        pg.fill("#cc-month", MONTH)
        pg.set_input_files("#cc-file", [str(f) for f in files])
        pg.wait_for_function("!document.getElementById('cc-start').disabled", timeout=20000)
        pg.click("#cc-start")
        pg.wait_for_function("window.__CC.run && window.__CC.run.final", timeout=60000)
        stage1 = pg.evaluate(JS_SUMMARY)
        for _ in range(5):
            if not pg.evaluate(JS_DECIDE):
                break
            pg.click("#cc-apply")
            pg.wait_for_timeout(500)
        pg.click("#cc-fin")
        pg.wait_for_function("window.__CC.result", timeout=30000)
        scores = pg.evaluate("() => Object.fromEntries(__CC.result.rows.map(r => [r.id, r.scores]))")
        b.close()
    assert not errs, errs
    return stage1, scores


def check(seed: int) -> bool:
    work = Path(tempfile.mkdtemp())
    demo = demo_data.generate(month=MONTH, seed=seed, workspace=work / "demo")
    files = list(demo["files"].values()) if isinstance(demo["files"], dict) else list(demo["files"])
    snap = work / "memory_snapshot"
    shutil.copytree(demo["memory_dir"], snap)
    p, py1, py_scores = python_side(files, demo["memory_dir"])
    p.memory_dir = snap                                    # the page embeds memory as it was before the run
    page = work / "page.html"
    page.write_text(L.render(p), encoding="utf-8")
    js1, js_scores = js_side(page, files)
    ok = True
    for k in ["codes", "tiers", "vendors", "red", "complete"]:
        a, b = py1[k], js1[k]
        if k == "red":
            a, b = [list(x) for x in a], [list(x) for x in b]
        same = a == b if k != "vendors" else all(all((x is None and y is None) or (x is not None and y is not None and abs(x - y) <= 0.002)
                                                     for x, y in zip(a[v], b[v])) for v in a)
        ok &= same
        print(f"  {k:9} {'OK ' if same else 'DIFF'}", "" if same else f"\n    python {a}\n    js     {b}")
    diffs = [(c, py_scores.get(c), js_scores.get(c)) for c in set(py_scores) | set(js_scores)
             if c not in py_scores or c not in js_scores
             or any(abs((py_scores[c][m] or 0) - (js_scores[c][m] or 0)) > 0.11 for m in py_scores[c])]
    print(f"  scores    {'OK ' if not diffs else 'DIFF'} ({len(py_scores)} python vs {len(js_scores)} js creators ranked)" +
          ("" if not diffs else "\n    " + "\n    ".join(map(str, diffs[:8]))))
    return ok and not diffs


if __name__ == "__main__":
    seeds = [int(s) for s in sys.argv[1:]] or [7, 11, 23]
    results = {}
    for s in seeds:
        print(f"seed {s}")
        results[s] = check(s)
    print(json.dumps(results))
    sys.exit(0 if all(results.values()) else 1)
