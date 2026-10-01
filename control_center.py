"""Workflow Control Center embedded at the top of the leaderboard page.

Runs the full monthly flow in the browser (web/engine.js, a port of the Python pipeline):
Inputs (upload or Generate Demo Data) → Start QA & Processing → QA results → Human review → Finalize → the leaderboard
below is rebuilt from the run. Settings, the vendor-recognition registry and a snapshot of memory are embedded, so the
browser run scores vendors and checks history exactly as the Python pipeline would.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
HISTORY_COLS = ["month", "creator_id", "platform", "follower_count", "reach_rate",
                "reach_rate__pct", "growth_rate__pct", "meaningful_eng_rate__pct"]

CSS = r"""
<style>
.cc{background:var(--panel);border:1.5px solid var(--ink);border-radius:14px;margin-bottom:28px;overflow:hidden}
.cc-head{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;padding:14px 18px;background:var(--ink);color:var(--bg)}
.cc-head h2{font:700 20px/1.1 var(--display);margin:0;letter-spacing:-.01em}
.cc-head h2 span{color:var(--accent)}
.cc-head p{margin:2px 0 0;font-size:13px;opacity:.75}
.cc-fold{font:inherit;font-size:13px;font-weight:600;color:var(--bg);background:transparent;border:1px solid currentColor;border-radius:8px;padding:5px 12px;cursor:pointer;opacity:.85}
.cc-steps{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));border-bottom:1px solid var(--line);counter-reset:s}
.cc-step{padding:10px 12px;font-size:13px;color:var(--muted);border-right:1px solid var(--line);display:flex;gap:8px;align-items:center;min-width:0}
.cc-step:last-child{border-right:0}
.cc-step b{flex:none;display:inline-grid;place-items:center;width:22px;height:22px;border-radius:50%;border:1.5px solid var(--line);font:600 12px var(--mono)}
.cc-step span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.cc-step.done{color:var(--ink)} .cc-step.done b{background:var(--ink);border-color:var(--ink);color:var(--bg)}
.cc-step.now{color:var(--ink);font-weight:600;box-shadow:inset 0 -3px 0 var(--accent)} .cc-step.now b{border-color:var(--accent);color:var(--accent-ink)}
@media (max-width:720px){.cc-steps{grid-template-columns:repeat(5,auto);overflow-x:auto}.cc-step span{display:none}.cc-step.now span{display:inline}}
.cc-body{padding:16px 18px;display:grid;gap:18px}
.cc-sec h3{font:600 15px var(--display);margin:0 0 8px;display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
.cc-sec h3 small{font:12px var(--body);color:var(--muted);font-weight:400}
.cc-row{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.cc-drop{flex:1 1 260px;display:flex;align-items:center;gap:10px;border:1.5px dashed var(--line);border-radius:10px;padding:10px 12px;font-size:13px;color:var(--muted);cursor:pointer;min-width:0}
.cc-drop:hover,.cc-drop.over{border-color:var(--accent);background:var(--accent-soft)}
.cc-drop input{position:absolute;width:1px;height:1px;opacity:0}
.cc-drop strong{color:var(--ink)}
.cc-month{display:flex;flex-direction:column;font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;gap:2px}
.cc-month input{font:inherit;font-size:14px;color:var(--ink);background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:6px 8px;text-transform:none;letter-spacing:0}
.btn{font:inherit;font-size:14px;font-weight:600;border-radius:8px;padding:9px 16px;cursor:pointer;border:1.5px solid transparent;white-space:nowrap}
.btn.primary{background:var(--accent);color:#fff;border-color:var(--accent)}
.btn.primary:hover:not([disabled]){background:var(--accent-ink);border-color:var(--accent-ink)}
.btn.secondary{background:var(--bg);color:var(--ink);border-color:var(--ink)}
.btn.secondary:hover:not([disabled]){background:var(--ink);color:var(--bg)}
.btn.tertiary{background:none;color:var(--muted);padding-inline:6px;text-decoration:underline;text-underline-offset:3px}
.btn.small{font-size:13px;padding:6px 12px}
.cc-slots{width:100%;min-width:560px;font-size:13px}
.cc-slots td{padding:7px 10px}
.cc-slots .empty-slot{color:var(--muted);font-style:italic}
.cc-tag{font:11px var(--mono);padding:2px 6px;border-radius:4px;background:var(--lo-bg);color:var(--lo);white-space:nowrap}
.cc-tag.demo{background:var(--accent-soft);color:var(--accent-ink)}
.cc-msg{font-size:13px;padding:8px 12px;border-radius:8px;border-left:3px solid var(--accent);background:var(--accent-soft)}
.cc-msg.err{border-left-color:#dc2626;background:rgba(220,38,38,.08)}
.cc-tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px}
.cc-tile{border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.cc-tile b{display:block;font:600 22px/1.15 var(--display);font-variant-numeric:tabular-nums}
.cc-tile span{font-size:12px;color:var(--muted)}
.cc-tile.g b::before,.cc-tile.y b::before,.cc-tile.r b::before{content:"";display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:8px;vertical-align:middle}
.cc-tile.g b::before{background:var(--ink)} .cc-tile.y b::before{background:var(--bar)} .cc-tile.r b::before{background:var(--accent)}
.cc-table{width:100%;min-width:640px;font-size:13px}
.cc-table td,.cc-table th{padding:7px 9px;vertical-align:top}
.cc-table .expl{color:var(--muted);font-size:12px;max-width:340px}
.cc-table select,.cc-table input{font:inherit;font-size:13px;color:var(--ink);background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:5px 6px;max-width:190px}
.cc-table input{width:110px}
.cc-vals{font:12px var(--mono);white-space:nowrap}
details.cc-more summary{cursor:pointer;font-size:13px;font-weight:600;color:var(--accent-ink);padding:4px 0}
.cc-scen{display:grid;gap:4px;font-size:13px;margin-top:6px}
.cc-scen div{display:grid;grid-template-columns:minmax(0,220px) minmax(0,1fr);gap:10px;border-top:1px solid var(--line);padding:5px 0}
@media (max-width:640px){.cc-scen div{grid-template-columns:minmax(0,1fr)}}
.cc-dl{display:flex;flex-wrap:wrap;gap:6px}
.cc-done{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
.cc[data-folded="1"] .cc-steps,.cc[data-folded="1"] .cc-body{display:none}
</style>
"""

HTML = r"""
<section class="cc" id="cc" aria-labelledby="cc-title">
  <div class="cc-head">
    <div><h2 id="cc-title">Workflow <span>Control Center</span></h2>
      <p id="cc-sub">Upload this month's files or generate demo data, run QA, review what's blocked, then publish the leaderboard below.</p></div>
    <button class="cc-fold" id="cc-fold" type="button" aria-expanded="true">Hide</button>
  </div>
  <ol class="cc-steps" id="cc-steps" style="list-style:none;margin:0;padding:0"></ol>
  <div class="cc-body">
    <div class="cc-sec" id="cc-inputs">
      <h3>1 · Inputs <small>Requested creator list + Vendor A, B, C files (.xlsx or .csv, any file names)</small></h3>
      <div class="cc-row">
        <label class="cc-month">Month<input type="month" id="cc-month"></label>
        <label class="cc-drop" id="cc-drop"><input type="file" id="cc-file" multiple accept=".xlsx,.csv">
          <span><strong>Upload files</strong> or drop them here · each is recognised by its content</span></label>
        <button class="btn secondary" id="cc-demo" type="button">Generate Demo Data</button>
        <button class="btn tertiary" id="cc-reset" type="button">Reset Demo</button>
      </div>
      <div class="tablebox" style="margin-top:10px"><table class="cc-slots"><thead><tr><th>Input slot</th><th>File</th><th>Recognised</th><th class="num">Rows</th></tr></thead><tbody id="cc-slots"></tbody></table></div>
      <div id="cc-scen"></div>
      <div class="cc-row" style="margin-top:12px"><button class="btn primary" id="cc-start" type="button" disabled>Start QA &amp; Processing</button><span class="note" id="cc-start-note" style="margin:0"></span></div>
    </div>
    <div id="cc-msg" role="status" aria-live="polite"></div>
    <div class="cc-sec" id="cc-qa" hidden></div>
    <div class="cc-sec" id="cc-review" hidden></div>
    <div class="cc-sec" id="cc-final" hidden></div>
  </div>
</section>
"""

UI_JS = r"""
(() => {
  const CC = JSON.parse(document.getElementById("cc-data").textContent);
  const ORIGINAL = D;
  const VN = v => v.replace("vendor_", "Vendor ").replace(/ (.)$/, (m, x) => " " + x.toUpperCase());
  const PN = {instagram: "Instagram", tiktok: "TikTok", youtube: "YouTube"};
  const STEPS = ["Inputs", "QA & Processing", "Human Review", "Finalize", "Leaderboard / Reports"];
  const fromCols = t => t.rows.map(r => Object.fromEntries(t.cols.map((c, i) => [c, r[i]])));
  const REAL_MEMORY = {vendor_history: fromCols(CC.memory.vendor_history), review_audit: fromCols(CC.memory.review_audit), creator_history: fromCols(CC.memory.creator_history)};
  const S = {inputs: [], demo: null, run: null, step: 0, result: null};
  const el = id => document.getElementById(id);
  let downloads = null;
  if (window.claude && claude.use) claude.use("downloads").then(d => { downloads = d; drawFinal(); }).catch(() => {});

  const nextMonth = m => { const [y, mo] = m.split("-").map(Number); const d = new Date(Date.UTC(y, mo, 1)); return d.toISOString().slice(0, 7); };
  el("cc-month").value = nextMonth(ORIGINAL.month);

  function msg(text, err) { el("cc-msg").innerHTML = text ? `<div class="cc-msg${err ? " err" : ""}">${text}</div>` : ""; }
  function drawSteps() {
    el("cc-steps").innerHTML = STEPS.map((s, i) => `<li class="cc-step ${i < S.step ? "done" : i === S.step ? "now" : ""}"><b>${i < S.step ? "✓" : i + 1}</b><span>${s}</span></li>`).join("");
  }
  function memory() { return S.demo ? S.demo.memory : REAL_MEMORY; }
  function registry() { return ENG.makeRegistry(CC.config, CC.registry); }

  // ---------- inputs ----------
  function slotOf(inp) {
    const reg = registry(), first = inp.data.sheets[inp.data.order[0]] || [];
    if (ENG.isRequest(inp.data.sheets.Request || first, inp.data.order, CC.config, reg)) return {slot: "request", conf: 1};
    const id = ENG.identify(reg, first, inp.name);
    return {slot: id.vendor || "unknown", conf: id.confidence, best: id.best};
  }
  function drawSlots() {
    const rows = S.inputs.map(inp => ({inp, ...slotOf(inp)}));
    const order = ["request", ...Object.keys(CC.config.vendors)];
    const label = s => s === "request" ? "Requested creator list" : VN(s);
    let html = order.map(s => {
      const r = rows.filter(x => x.slot === s).pop();
      if (!r) return `<tr><td>${label(s)}</td><td class="empty-slot" colspan="3">empty</td></tr>`;
      const sheet = r.inp.data.sheets[r.inp.data.sheets.Request && s === "request" ? "Request" : r.inp.data.order[0]] || [];
      return `<tr><td>${label(s)}</td><td>${esc(r.inp.name)} ${r.inp.source === "demo" ? '<span class="cc-tag demo">Synthetic Demo Data</span>' : '<span class="cc-tag">uploaded</span>'}</td>
        <td>${s === "request" ? "creator list" : `${Math.round(r.conf * 100)}% match`}</td><td class="num">${fmt(sheet.length)}</td></tr>`;
    }).join("");
    html += rows.filter(x => x.slot === "unknown").map(r => `<tr><td>Not recognised</td><td>${esc(r.inp.name)}</td><td colspan="2">closest ${VN(r.best)} ${Math.round(r.conf * 100)}% — skipped</td></tr>`).join("");
    el("cc-slots").innerHTML = html;
    const hasReq = rows.some(x => x.slot === "request"), nV = new Set(rows.filter(x => order.slice(1).includes(x.slot)).map(x => x.slot)).size;
    el("cc-start").disabled = !(hasReq && nV);
    el("cc-start-note").textContent = !S.inputs.length ? "Add the month's files or generate demo data to begin." : !hasReq ? "Missing the requested creator list." : !nV ? "No vendor file recognised yet." : `${nV} of ${order.length - 1} vendor files ready.`;
    el("cc-scen").innerHTML = S.demo ? `<details class="cc-more" style="margin-top:8px"><summary>Seeded QA scenarios in this demo (seed ${S.demo.seed})</summary>
      <p class="note">${esc(S.demo.label)}. Plus ${S.demo.history_months.length} months of synthetic history (${S.demo.history_months.join(", ")}) so Vendor Reliability has a rolling 3-month record.</p>
      <div class="cc-scen">${Object.entries(S.demo.scenarios).sort().map(([k, list]) => `<div><b>${esc(k.replace(/^\d+b? /, ""))} · ${list.length}</b><span>${list.map(x => `${esc(x.creator)} ${PN[x.platform]}`).join("; ")}<br><span class="id" style="white-space:normal">${esc(list[0].what)}</span></span></div>`).join("")}</div></details>` : "";
  }
  function clearRun() { S.run = null; S.result = null; ["cc-qa", "cc-review", "cc-final"].forEach(i => { el(i).hidden = true; el(i).innerHTML = ""; }); S.step = 0; drawSteps(); }
  async function addFiles(files) {
    msg("Reading files…");
    try {
      const read = [];
      for (const f of files) { if (!/\.(xlsx|csv)$/i.test(f.name)) { msg(`${esc(f.name)} isn't an .xlsx or .csv file.`, true); return; } read.push({name: f.name, source: "upload", data: await ENG.readFile(f)}); }
      if (S.demo) { S.demo = null; S.inputs = []; }          // uploads replace demo inputs
      const newSlots = read.map(slotOf);
      S.inputs = S.inputs.filter(old => !newSlots.some(n => n.slot !== "unknown" && n.slot === slotOf(old).slot)).concat(read);
      clearRun(); drawSlots(); msg(`${read.length} file${read.length > 1 ? "s" : ""} added.`);
    } catch (e) { msg("Couldn't read that file: " + esc(e.message), true); }
  }
  el("cc-file").addEventListener("change", e => { if (e.target.files.length) addFiles([...e.target.files]); e.target.value = ""; });
  const drop = el("cc-drop");
  drop.addEventListener("dragover", e => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", e => { e.preventDefault(); drop.classList.remove("over"); if (e.dataTransfer.files.length) addFiles([...e.dataTransfer.files]); });
  el("cc-demo").addEventListener("click", () => {
    const m = el("cc-month").value || nextMonth(ORIGINAL.month);
    S.demo = ENG.generateDemo(CC.config, m); S.inputs = S.demo.inputs;
    clearRun(); drawSlots();
    msg(`Synthetic demo data generated for ${m} (seed ${S.demo.seed}): a request list and Vendor A, B and C files, placed in the input slots. Next: Start QA &amp; Processing.`);
  });
  el("cc-reset").addEventListener("click", () => {
    S.inputs = []; S.demo = null; clearRun(); drawSlots(); msg("");
    el("cc-month").value = nextMonth(ORIGINAL.month);
    if (D !== ORIGINAL) { D = ORIGINAL; boot(); }
  });
  el("cc-fold").addEventListener("click", e => { const c = el("cc"), f = c.dataset.folded === "1"; c.dataset.folded = f ? "0" : "1"; e.target.textContent = f ? "Hide" : "Show"; e.target.setAttribute("aria-expanded", String(f)); });

  // ---------- QA & processing ----------
  el("cc-start").addEventListener("click", () => {
    const m = el("cc-month").value;
    if (!/^\d{4}-\d{2}$/.test(m)) { msg("Pick the month this data is for.", true); return; }
    msg("Running QA…");
    setTimeout(() => {
      try {
        S.run = ENG.newRun(CC.config, S.inputs, m, memory(), registry());
        ENG.process(S.run);
        S.step = ENG.openRed(S.run).length ? 2 : 3; drawSteps(); drawQA(); drawReview(); drawFinal();
        msg(ENG.openRed(S.run).length ? `QA finished. ${ENG.openRed(S.run).length} item(s) are blocked and need a decision before the leaderboard can be built; everything else was processed.` : "QA finished with nothing blocked. Finalize to build the leaderboard.");
        el("cc-qa").scrollIntoView({behavior: "smooth", block: "start"});
      } catch (e) { console.error(e); msg(esc(e.message), true); }
    }, 20);
  });
  function drawQA() {
    const R = S.run, st = ENG.creatorStatus(R), counts = {GREEN: 0, YELLOW: 0, RED: 0};
    R.reqCreators.forEach(c => counts[st[c] || "GREEN"]++);
    const warn = R.flags.filter(f => f.severity === "YELLOW"), byCode = {};
    warn.forEach(f => byCode[f.code] = (byCode[f.code] || 0) + 1);
    const pctS = x => x == null ? "–" : (x * 100).toFixed(0) + "%";
    const tiers = Object.values(R.profiles).sort((a, b) => b.score - a.score);
    el("cc-qa").hidden = false;
    el("cc-qa").innerHTML = `<h3>2 · QA results <small>${esc(R.month)} · ${fmt(R.reqCreators.length)} creators, ${fmt(R.reqPairs.length)} channels requested</small></h3>
      <div class="cc-tiles">
        <div class="cc-tile g"><b>${counts.GREEN}</b><span>Creators GREEN · passed</span></div>
        <div class="cc-tile y"><b>${counts.YELLOW}</b><span>Creators YELLOW · warnings, processed</span></div>
        <div class="cc-tile r"><b>${counts.RED}</b><span>Creators with a RED item${R.flags.some(f => f.severity === "RED" && f.status === "resolved") ? " (incl. reviewed)" : " · blocked"}</span></div>
        <div class="cc-tile"><b>${(R.final.channels_complete * 100).toFixed(1)}%</b><span>Requested channels filled</span></div>
      </div>
      <div class="tablebox" style="margin-top:10px"><table class="cc-table"><thead><tr><th>Vendor</th><th>File</th><th class="num">This month</th><th class="num">3-month reliability</th><th class="num">Blended</th><th>Tier</th><th class="num">Fresh coverage</th></tr></thead><tbody>
        ${tiers.map(P => `<tr><td><b>${VN(P.name)}</b></td><td class="expl">${esc(R.vendorInputs[P.name].inp.name)}</td><td class="num">${P.current_score.toFixed(2)}</td>
          <td class="num">${P.history_score == null ? "no history" : P.history_score.toFixed(2)}<span class="id">${P.history_months ? `${P.history_months} mo · QA ${P.qa_avg_3m.toFixed(2)} · review ${pctS(P.review_accuracy)}` : ""}</span></td>
          <td class="num"><b>${P.score.toFixed(2)}</b></td><td>${P.tier ? "Tier " + P.tier : esc(P.excluded_reason)}</td><td class="num">${pctS(P.usable_coverage)}</td></tr>`).join("")}
      </tbody></table></div>
      <p class="note">Tier = 85% this month's QA score + 15% 3-month reliability (70% average QA score + 30% review accuracy). Waterfall: ${R.tierResults.map(t => `${VN(t.vendor)} → ${(t.after.creators_complete * 100).toFixed(0)}% creators complete`).join(" · ")}.</p>
      ${warn.length ? `<details class="cc-more"><summary>Warnings (${warn.length}) · ${Object.entries(byCode).map(([k, n]) => `${k} ${n}`).join(" · ")}</summary>
        <div class="tablebox"><table class="cc-table"><thead><tr><th>ID</th><th>Creator · channel</th><th>Code</th><th>What happened</th></tr></thead><tbody>
        ${warn.map(f => `<tr><td class="cc-vals">${f.id}</td><td>${esc(name(f.creator_id))}<span class="id">${esc(f.creator_id)} · ${PN[f.platform] || ""}</span></td><td class="cc-vals">${f.code}</td><td class="expl">${esc(f.explanation)}</td></tr>`).join("")}
        </tbody></table></div></details>` : ""}`;
  }
  const name = c => { const R = S.run, n = (R.out.cr.get(c) || {}).display_name; if (n) return n;
    for (const rows of Object.values(R.vendorRows)) { const r = rows.find(x => x[R.key] === c && x.display_name); if (r) return r.display_name; } return c; };
  const showVal = (field, v) => typeof v === "number" ? (field === "follower_count" ? fmt(Math.round(v)) : v.toFixed(3)) : "@" + v;

  // ---------- human review ----------
  const DLABEL = {CONFIRM_MATCH: "Confirm match", REJECT_MATCH: "Reject match", MANUAL_VALUE: "Enter manual value", EXCLUDE: "Exclude"};
  function drawReview() {
    const R = S.run, open = ENG.openRed(R), done = R.flags.filter(f => f.severity === "RED" && f.status === "resolved");
    if (!open.length && !done.length) { el("cc-review").hidden = true; return; }
    el("cc-review").hidden = false;
    el("cc-review").innerHTML = `<h3>3 · Human review <small>${open.length ? `${open.length} blocked item(s). Only these records are held back; nothing else waits on them.` : "All blocked items reviewed."}</small></h3>
      ${open.length ? `<div class="tablebox"><table class="cc-table"><thead><tr><th>ID</th><th>Creator · channel</th><th>Issue</th><th>Vendor values</th><th>Decision</th></tr></thead><tbody>
      ${open.map(f => `<tr data-f="${f.id}"><td class="cc-vals">${f.id}</td><td><b>${esc(name(f.creator_id))}</b><span class="id">${esc(f.creator_id)} · ${PN[f.platform]}</span></td>
        <td><span class="sev RED">${f.code === "IDENTITY_MATCH_UNCERTAIN" ? "Identity" : "Discrepancy"}</span> <span class="cc-vals">${esc(f.field)}</span><div class="expl">${esc(f.explanation)}</div></td>
        <td class="cc-vals">${Object.entries(f.values).map(([v, x]) => `${VN(v)}: ${esc(showVal(f.field, x))}`).join("<br>")}</td>
        <td><select aria-label="Decision for ${f.id}"><option value="">Choose…</option>${(CC.config.review.decisions[f.code] || []).filter(d => !d.startsWith("SELECT_") || ("vendor_" + d.slice(-1).toLowerCase()) in f.values)
          .map(d => `<option value="${d}">${d.startsWith("SELECT_") ? `Use ${VN("vendor_" + d.slice(-1).toLowerCase())} (${esc(showVal(f.field, f.values["vendor_" + d.slice(-1).toLowerCase()]))})` : DLABEL[d]}</option>`).join("")}</select>
          <input type="number" step="any" placeholder="value" aria-label="Manual value for ${f.id}" hidden></td></tr>`).join("")}
      </tbody></table></div>
      <div class="cc-row" style="margin-top:10px"><label class="cc-month" style="flex-direction:row;align-items:center;gap:6px">Reviewer <input id="cc-reviewer" placeholder="your name" style="width:150px"></label>
        <button class="btn primary small" id="cc-apply" type="button">Apply decisions</button><span class="note" style="margin:0">Partial reviews are fine; anything without a decision stays blocked.</span></div>` : ""}
      ${done.length ? `<details class="cc-more"${open.length ? "" : " open"}><summary>Audit trail (${done.length})</summary><div class="tablebox"><table class="cc-table"><thead><tr><th>ID</th><th>Creator · channel</th><th>Decision</th><th>Final value · source</th><th>Reviewer</th></tr></thead><tbody>
        ${done.map(f => `<tr><td class="cc-vals">${f.id}</td><td>${esc(name(f.creator_id))}<span class="id">${PN[f.platform]} · ${esc(f.code)}</span></td><td class="cc-vals">${f.decision}</td><td class="cc-vals">${f.final_value == null ? "–" : esc(showVal(f.field, f.final_value))} · ${esc(f.final_source)}</td><td>${esc(f.reviewer || "–")}<span class="id">${esc(f.reviewed_at)}</span></td></tr>`).join("")}
      </tbody></table></div></details>` : ""}`;
    el("cc-review").querySelectorAll("tr[data-f] select").forEach(s => s.addEventListener("change", () => { s.nextElementSibling.hidden = s.value !== "MANUAL_VALUE"; }));
    const ap = el("cc-apply");
    if (ap) ap.addEventListener("click", () => {
      const decisions = [...el("cc-review").querySelectorAll("tr[data-f]")].map(tr => ({id: tr.dataset.f, decision: tr.querySelector("select").value, manual: tr.querySelector("input").value}));
      if (!decisions.some(d => d.decision)) { msg("Choose a decision for at least one blocked item.", true); return; }
      const problems = ENG.applyDecisions(S.run, decisions, el("cc-reviewer").value.trim());
      const left = ENG.openRed(S.run).length;
      S.step = left ? 2 : 3; drawSteps(); drawQA(); drawReview(); drawFinal();
      msg((problems.length ? "Some decisions weren't applied: " + problems.map(esc).join("; ") + ". " : "") +
        (left ? `${left} item(s) still blocked.` : "All blocked items resolved; only the affected records were reprocessed. Finalize to build the leaderboard."), problems.length > 0);
    });
  }

  // ---------- finalize + reports ----------
  function drawFinal() {
    if (!S.run) return;
    const R = S.run, left = ENG.openRed(R).length;
    el("cc-final").hidden = false;
    if (S.step < 4) {
      el("cc-final").innerHTML = `<h3>4 · Finalize</h3><div class="cc-done"><span class="note" style="margin:0">${left ? `The leaderboard stays locked until the ${left} blocked item(s) above have a decision, so unresolved values never enter the percentiles.` : "Nothing is blocked. Finalizing computes percentiles, scores and roles and rebuilds the leaderboard below."}</span>
        <button class="btn primary" id="cc-fin" type="button" ${left ? "disabled" : ""}>Finalize &amp; build leaderboard</button></div>`;
      const b = el("cc-fin"); if (b) b.addEventListener("click", finalize);
      return;
    }
    const dl = downloads ? `<div class="cc-dl"><button class="btn secondary small" data-dl="leaderboard">Leaderboard .csv</button><button class="btn secondary small" data-dl="channels">Filled channel data .csv</button><button class="btn secondary small" data-dl="flags">QA flags &amp; audit .csv</button></div>` : "";
    el("cc-final").innerHTML = `<h3>5 · Leaderboard / Reports</h3><div class="cc-done"><span class="note" style="margin:0">The leaderboard below now shows this run: ${fmt(S.result.summary.ranked)} of ${fmt(S.result.summary.creators)} creators ranked${S.demo ? " (Synthetic Demo Data)" : ""}. Reset Demo returns to the published ${esc(ORIGINAL.month_label)} board.</span>
      <a class="btn secondary small" href="#board" style="text-decoration:none">View leaderboard ↓</a></div>${dl}`;
    el("cc-final").querySelectorAll("[data-dl]").forEach(b => b.addEventListener("click", () => save(b.dataset.dl)));
  }
  function finalize() {
    try {
      S.result = ENG.finalize(S.run, ORIGINAL.metrics);
      // remember this month for the next run in the session (vendor quality + creator scores)
      const mem = memory();
      mem.vendor_history = mem.vendor_history.filter(r => r.month !== S.run.month).concat(Object.values(S.run.profiles).map(P => ({month: S.run.month, vendor: P.name, current_score: P.current_score, tier: P.tier})));
      mem.review_audit = mem.review_audit.filter(r => r.month !== S.run.month).concat(S.run.audit || []);
      const add = [];
      for (const [k, r] of S.run.out.ch) { const [c, p] = k.split("|"); add.push({month: S.run.month, creator_id: c, platform: p, follower_count: r.follower_count, reach_rate: r.reach_rate,
        reach_rate__pct: r.reach_rate__pct ?? null, growth_rate__pct: r.growth_rate__pct ?? null, meaningful_eng_rate__pct: r.meaningful_eng_rate__pct ?? null}); }
      mem.creator_history = mem.creator_history.filter(r => r.month !== S.run.month).concat(add);
      D = {...S.result, board_note: `<b>${S.demo ? "Synthetic Demo Data · " : ""}${esc(S.result.month_label)} run from the Control Center.</b> Not saved: reload the page or press Reset Demo to return to the published ${esc(ORIGINAL.month_label)} board.`};
      boot(); S.step = 4; drawSteps(); drawFinal();
      msg("Leaderboard built from this run.");
      el("board").scrollIntoView({behavior: "smooth", block: "start"});
    } catch (e) { console.error(e); msg(esc(e.message), true); }
  }
  const csv = rows => { const cols = [...new Set(rows.flatMap(Object.keys))]; const q = v => v == null ? "" : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v);
    return [cols.join(","), ...rows.map(r => cols.map(c => q(r[c])).join(","))].join("\n"); };
  async function save(kind) {
    const R = S.run, M = ORIGINAL.metrics.map(m => m.key); let rows;
    if (kind === "leaderboard") rows = D.rows.map((r, i) => ({rank: i + 1, creator_id: r.id, name: r.name, country: r.country, followers: r.followers, ...Object.fromEntries(M.map(m => [m, r.scores[m]])), primary_role: r.role, confidence: r.confidence, sources: r.sources}));
    else if (kind === "channels") rows = [...R.out.ch].map(([k, r]) => { const [c, p] = k.split("|"); return {creator_id: c, platform: p, name: name(c), handle: r.handle, follower_count: r.follower_count, follower_count_source: r.follower_count__source,
      ...Object.fromEntries(M.flatMap(m => [[m, r[m]], [m + "_source", r[m + "__source"]], [m + "_pct", r[m + "__pct"]]]))}; });
    else rows = R.flags.map(f => ({id: f.id, severity: f.severity, code: f.code, creator_id: f.creator_id, platform: f.platform, field: f.field, values: JSON.stringify(f.values), discrepancy: f.discrepancy, source_used: f.source_used, explanation: f.explanation, status: f.status, decision: f.decision, final_value: f.final_value, final_source: f.final_source, reviewer: f.reviewer, reviewed_at: f.reviewed_at}));
    try { await downloads.save({filename: `${kind}_${R.month}${S.demo ? "_SYNTHETIC_DEMO" : ""}.csv`, data: csv(rows)}); }
    catch (e) { if (!["declined", "rate_limited"].includes(e && e.code)) msg("Download isn't available here.", true); }
  }
  drawSteps(); drawSlots();
  window.__CC = S;                                   // for tests
})();
"""


def _table(df: pd.DataFrame, cols=None) -> dict:
    df = df[[c for c in (cols or df.columns) if c in df.columns]].copy()
    df = df.astype(object).where(pd.notna(df), None)
    return {"cols": list(df.columns), "rows": df.values.tolist()}


def cc_payload(p) -> dict:
    mem = Path(getattr(p, "memory_dir", None) or Path(p.vendor_history.path).parent)
    read = lambda n: pd.read_csv(mem / n, keep_default_na=False, na_values=[""]) if (mem / n).exists() else pd.DataFrame()
    ch = read("creator_history.csv")
    if not ch.empty:
        ch["month"] = ch["month"].astype(str)
        ch = ch[ch["month"].isin(sorted(ch["month"].unique())[-3:])]
        for c in [c for c in HISTORY_COLS if c not in ("month", "creator_id", "platform")]:
            ch[c] = pd.to_numeric(ch[c], errors="coerce").round(4)
    vh, ra = read("vendor_history.csv"), read("review_audit.csv")
    reg = json.loads((mem / "vendor_registry.json").read_text()) if (mem / "vendor_registry.json").exists() else {}
    return {"config": p.cfg, "registry": reg,
            "memory": {"vendor_history": _table(vh, ["month", "vendor", "current_score", "tier"]),
                       "review_audit": _table(ra, ["month", "review_id", "creator_id", "platform", "code", "original_values",
                                                   "decision", "manual_value", "final_source"]),
                       "creator_history": _table(ch, HISTORY_COLS)}}


def cc_html() -> str:
    return CSS + HTML


def cc_script(p) -> str:
    data = json.dumps(cc_payload(p), default=str, separators=(",", ":")).replace("</", "<\\/")
    engine = (HERE / "web" / "engine.js").read_text(encoding="utf-8")
    return (f'<script type="application/json" id="cc-data">{data}</script>\n'
            f"<script>\n{engine}\n</script>\n<script>\n{UI_JS}\n</script>")
