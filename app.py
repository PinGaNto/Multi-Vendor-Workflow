"""Workflow Control Center — monthly creator-vendor QA, review and leaderboard.

Run:  pip install streamlit pandas openpyxl pyyaml
      streamlit run app.py

Inputs (uploaded files, or Generate Demo Data) → Start QA & Processing → QA Results → Human Review → Finalize →
Leaderboard / Reports. Demo data runs through exactly the same steps; it only uses its own workspace
(demo_workspace/) so the real month-by-month memory (memory/) is never touched.
"""
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import yaml

import demo_data
from leaderboard_html import render
from pipeline import ROOT, Pipeline, read_table, run_uploaded
from request_template import write_request
from review import read_decisions, resume_df

CFG = yaml.safe_load((ROOT / "config.yaml").read_text())
VENDORS = list(CFG["vendors"])
DECISIONS = sorted({d for v in CFG["review"]["decisions"].values() for d in v})
SLOT_NAMES = {"request": "Requested creator list", **{v: v.replace("_", " ").title() for v in VENDORS}}

st.set_page_config(page_title="Workflow Control Center", layout="wide")
st.markdown("""<style>
.demo-banner{border:2px solid #EA580C;background:#FFF1E6;color:#0A0A0A;border-radius:10px;padding:10px 14px;margin:6px 0 12px}
.demo-banner b{color:#C2410C;letter-spacing:.04em}
.badge{display:inline-block;font-size:12px;font-weight:700;padding:2px 8px;border-radius:999px}
.badge.demo{background:#EA580C;color:#fff} .badge.up{background:#0A0A0A;color:#fff}
.steps{display:flex;gap:6px;flex-wrap:wrap;margin:4px 0 18px}
.step{font-size:13px;font-weight:600;padding:6px 12px;border-radius:999px;border:1px solid #E4E4E4;color:#5C5C5C}
.step.done{background:#0A0A0A;color:#fff;border-color:#0A0A0A} .step.now{background:#EA580C;color:#fff;border-color:#EA580C}
</style>""", unsafe_allow_html=True)

ss = st.session_state
ss.setdefault("inputs", [])            # [{"path": Path, "source": "uploaded" | "demo"}]
ss.setdefault("demo", None)            # demo_data.generate(...) result while demo inputs are loaded
ss.setdefault("upkey", 0)
ss.setdefault("tmp", tempfile.mkdtemp())
p = ss.get("p")

# ------------------------------------------------------------------ header + where we are
st.title("Workflow Control Center")
stage = 0 if not p else {"awaiting_review": 2, "ready": 3, "finalized": 4}.get(p.status, 1)
steps = ["Inputs", "QA & Processing", "Human Review", "Finalize", "Leaderboard / Reports"]
st.markdown('<div class="steps">' + "".join(
    f'<span class="step {"done" if i < stage else "now" if i == stage else ""}">{i + 1}. {s}</span>'
    for i, s in enumerate(steps)) + "</div>", unsafe_allow_html=True)


def reset_all():
    demo_data.reset()
    for k in ("inputs", "demo", "p", "review_problems"):
        ss.pop(k, None)
    ss.upkey += 1
    ss.tmp = tempfile.mkdtemp()


# ------------------------------------------------------------------ 1. inputs
st.subheader("1. Inputs")
demo = ss.demo
c_month, c_tpl = st.columns([1, 3])
month = c_month.text_input("Month", value=demo["month"] if demo else date.today().strftime("%Y-%m"),
                           disabled=bool(demo), help="YYYY-MM. Re-running a month replaces it.")
tpl = Path(ss.tmp) / "creator_request_template.xlsx"
write_request(tpl, CFG["platforms"])
c_tpl.download_button("Download request template", tpl.read_bytes(), file_name="creator_request_template.xlsx")

c_up, c_btn = st.columns([3, 1])
uploads = c_up.file_uploader("Upload this month's files (request list + vendor files, any names)",
                             type=["xlsx", "csv"], accept_multiple_files=True, key=f"up{ss.upkey}")
with c_btn:
    st.write("")
    if st.button("Generate Demo Data", type="secondary", use_container_width=True,
                 help="Creates a complete synthetic dataset (request list, Vendor A/B/C, 3 months of history) "
                      "and loads it into the input slots below."):
        reset_all()
        ss.demo = demo_data.generate(month if month else None)
        ss.inputs = [{"path": f, "source": "demo"} for f in ss.demo["files"]]
        st.rerun()
    if st.button("Reset Demo", type="tertiary", use_container_width=True,
                 help="Clears inputs, QA results, review decisions and generated outputs."):
        reset_all()
        st.rerun()

if uploads:                                         # uploads replace any demo inputs
    if ss.demo:
        demo_data.reset()
        ss.demo, ss.inputs = None, []
        ss.pop("p", None)
    known = {i["path"].name for i in ss.inputs}
    for f in uploads:
        if f.name not in known:
            path = Path(ss.tmp) / f.name
            path.write_bytes(f.getbuffer())
            ss.inputs.append({"path": path, "source": "uploaded"})

demo = ss.demo
if demo:
    m = demo["manifest"]
    st.markdown(f'<div class="demo-banner"><b>{demo_data.LABEL}</b> · generated {m["generated"]} (seed {m["seed"]}). '
                f'Invented creators, "demo" handles and DEMO- IDs; no real creators, vendors or company data. '
                f'History for {", ".join(m["history_months"])} is synthetic too.</div>', unsafe_allow_html=True)
    with st.expander("Seeded QA scenarios in this demo dataset"):
        rows = [{"scenario": k.split("_", 1)[1].replace("_", " "), "creator": x["creator"], "channel": x["platform"],
                 "what's seeded": x["what"]} for k, xs in m["scenarios"].items() for x in xs]
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

# input slots: same slots for uploaded and demo files
assign = {}
if ss.inputs:
    mem_dir = demo["memory_dir"] if demo else None
    probe = Pipeline(files=[i["path"] for i in ss.inputs], month=month, memory_dir=mem_dir)
    slots = []
    for i in ss.inputs:
        pth = i["path"]
        df = read_table(pth, "Request")
        sheets = pd.ExcelFile(pth).sheet_names if pth.suffix != ".csv" else []
        if probe.registry.is_request(df, probe.key, probe.platforms, probe.aliases, sheets):
            slot, match = "request", 1.0
        else:
            idr = probe.registry.identify(read_table(pth), pth.name)
            slot, match = (idr["vendor"] or "unrecognised"), idr["confidence"]
        slots.append({"slot": SLOT_NAMES.get(slot, "Unrecognised"), "file": pth.name, "rows": len(read_table(pth)),
                      "source": "Synthetic Demo Data" if i["source"] == "demo" else "Uploaded", "match": match})
        if slot == "unrecognised":
            choice = st.selectbox(f"Which vendor sent {pth.name}?", ["(skip this file)"] + VENDORS, key=f"as_{pth.name}")
            if choice in VENDORS:
                assign[pth.name] = choice
    order = list(SLOT_NAMES.values()) + ["Unrecognised"]
    sdf = pd.DataFrame(slots).sort_values("slot", key=lambda s: s.map(order.index))
    st.dataframe(sdf, hide_index=True, use_container_width=True,
                 column_config={"match": st.column_config.ProgressColumn("match", min_value=0, max_value=1, format="%.0f%%")})
    filled = set(sdf["slot"])
    missing = [n for n in SLOT_NAMES.values() if n not in filled]
    if missing:
        st.caption("Empty slots: " + ", ".join(missing) + ". The run continues without a missing vendor.")
    ready = "Requested creator list" in filled and any(SLOT_NAMES[v] in filled for v in VENDORS)
    if st.button("Start QA & Processing", type="primary", disabled=not ready or bool(p and p.status != "new")):
        out_dir = demo["out_dir"] if demo else Path(ss.tmp) / "output" / month
        try:
            with st.spinner("Matching creators, scoring vendors, cross-vendor QA, fallback, history checks…"):
                ss.p = run_uploaded([i["path"] for i in ss.inputs], month, out_dir=out_dir, assign=assign,
                                    memory_dir=mem_dir, auto_finalize=False)
        except ValueError as e:
            st.error(str(e))
        st.rerun()
else:
    st.info("Upload this month's files, or click **Generate Demo Data** to load a synthetic dataset.")

p = ss.get("p")
if not p:
    st.stop()

# ------------------------------------------------------------------ 2. QA results
st.subheader("2. QA results")
fl = p.flags.frame()
status = p.flags.creator_status()
n_req = len(p.req_creators)
c = st.columns(5)
c[0].metric("GREEN creators", n_req - len(status), help="No QA issue; processed automatically")
c[1].metric("YELLOW creators", sum(v == "YELLOW" for v in status.values()), help="Warnings only; processed automatically")
c[2].metric("RED creators", sum(v == "RED" for v in status.values()), help="Something held back for review")
c[3].metric("Blocked items open", len(p.flags.open_red()))
c[4].metric("Warnings", int((fl["severity"] == "YELLOW").sum()) if len(fl) else 0)
if len(fl):
    st.dataframe(fl.groupby(["severity", "code"]).size().rename("count").reset_index(), hide_index=True)
    with st.expander("Warnings (recorded, not blocking)"):
        w = fl[fl["severity"] == "YELLOW"][["id", "code", "creator_id", "platform", "field", "source_used", "explanation"]]
        st.dataframe(w, hide_index=True, use_container_width=True)
st.download_button("Download QA report", p.qa_report_path.read_bytes(), file_name=p.qa_report_path.name)

# ------------------------------------------------------------------ 3. human review
if p.status == "awaiting_review":
    st.subheader(f"3. Human review — {len(p.flags.open_red())} blocked item(s)")
    st.caption("Only these creator-channels / metrics are held back; everything else is processed. "
               "Pick a decision per row. Rows left empty stay open.")
    vendors = list(p.cfg["vendors"])
    red = pd.DataFrame([{"Review ID": f.id, "Creator": f.creator_id, "Channel": f.platform,
                         "Field(s)": "whole channel" if f.field == "identity" else ", ".join([f.field, *f.dependents]),
                         "Reason": f.code,
                         **{v: (("@" + f.values[v]) if f.code == "IDENTITY_MATCH_UNCERTAIN" else f"{f.values[v]:,.4g}")
                            if v in f.values else "" for v in vendors},
                         "Explanation": f.explanation, "Recommended action": f.action,
                         "Decision": None, "Manual value": None, "Note": ""} for f in p.flags.open_red()])
    edited = st.data_editor(red, hide_index=True, use_container_width=True, key="review_editor",
                            disabled=[col for col in red.columns if col not in ("Decision", "Manual value", "Note")],
                            column_config={"Decision": st.column_config.SelectboxColumn("Decision", options=DECISIONS),
                                           "Manual value": st.column_config.NumberColumn("Manual value")})
    reviewer = st.text_input("Reviewer name")
    if st.button("Apply decisions", type="primary"):
        ss.p, ss.review_problems = resume_df(p, edited, reviewer, finalize=False)
        st.rerun()
    with st.expander("Or review offline in Excel"):
        st.caption("Download the QA report, fill the 'Blocked — review' tab, and upload it here.")
        form = st.file_uploader("Filled review form", type=["xlsx"], key=f"form{ss.upkey}")
        if form and st.button("Apply decisions from file"):
            path = Path(ss.tmp) / f"review_{p.month}.xlsx"
            path.write_bytes(form.getbuffer())
            ss.p, ss.review_problems = resume_df(p, read_decisions(path), reviewer, finalize=False)
            st.rerun()
for pr in ss.get("review_problems", []) or []:
    st.warning(pr)

# ------------------------------------------------------------------ 4. finalize
if p.status == "ready":
    st.subheader("4. Finalize")
    resolved = sum(1 for f in p.flags.flags if f.severity == "RED" and f.status == "resolved")
    st.success(f"No blocked items open ({resolved} resolved at review). Warnings stay in the data and don't block.")
    if st.button("Finalize & build leaderboard", type="primary"):
        with st.spinner("Finalizing master dataset, percentiles, scores and leaderboard…"):
            p.finalize()
        st.rerun()

# ------------------------------------------------------------------ 5. leaderboard / reports
if p.status == "finalized":
    st.subheader(f"5. Leaderboard / reports — {p.month}")
    if demo:
        st.markdown(f'<div class="demo-banner"><b>{demo_data.LABEL}</b> · these results come from synthetic demo inputs.</div>',
                    unsafe_allow_html=True)
    c = st.columns(4)
    c[0].metric("Creators requested", f"{len(p.req_creators):,}", f"{len(p.req_pairs):,} channels", delta_color="off")
    c[1].metric("Creators complete", f"{len(p.leaderboard):,}", f"{p.final['creators_complete']:.1%}", delta_color="off")
    c[2].metric("Channels ranked", f"{len(p.channel_board):,}", f"{p.final['channels_complete']:.1%} of requested", delta_color="off")
    c[3].metric("Creators still missing data", f"{p.creators_with_gaps:,}")
    d1, d2 = st.columns(2)
    d1.download_button("Download filled Excel", p.workbook_path.read_bytes(), file_name=p.workbook_path.name, type="primary")
    d2.download_button("Download final QA report", p.qa_report_path.read_bytes(), file_name=p.qa_report_path.name)
    tab_lb, tab_rel, tab_flags, tab_log, tab_gaps = st.tabs(["Leaderboard", "Vendor reliability", "QA flags",
                                                            "Decision log", "Gaps"])
    with tab_lb:
        st.caption("Click any creator to open their profile with month-by-month scores and data checks.")
        components.html(render(p), height=1300, scrolling=True)
    with tab_rel:
        rc = p.cfg["qa"]["reliability"]
        st.caption(f"3-month reliability = {rc['qa_score_weight']:.0%} × average QA score + "
                   f"{rc['review_accuracy_weight']:.0%} × review accuracy (share of reviewed disputes where the vendor's "
                   f"value was kept). Tiering uses {1 - p.cfg['qa']['history_weight']:.0%} this month + "
                   f"{p.cfg['qa']['history_weight']:.0%} reliability.")
        st.dataframe(pd.DataFrame([{"vendor": n, "tier": pr.tier or "excluded", "this month": pr.current_score,
                                    "QA average (3 mo)": pr.qa_avg_3m, "review accuracy (3 mo)": pr.review_accuracy,
                                    "disputes reviewed": pr.disputes_reviewed, "3-month reliability": pr.history_score,
                                    "blended score": pr.score, "consistency": pr.consistency}
                                   for n, pr in sorted(p.profiles.items(), key=lambda kv: kv[1].tier or 9)]), hide_index=True)
        vh = p.vendor_history.df.pivot(index="month", columns="vendor", values="current_score")
        st.line_chart(vh)
    with tab_flags:
        st.dataframe(fl[["id", "severity", "code", "creator_id", "platform", "field", "status", "decision", "explanation"]],
                     hide_index=True, use_container_width=True)
    with tab_log:
        for e in p.agent.log:
            st.markdown(f"**{e['step']}** → {e['decision']}: {e['reason']}")
    with tab_gaps:
        st.dataframe(p.gaps, hide_index=True)
