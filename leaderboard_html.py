"""Self-contained HTML creator leaderboard with The Pulse / The Lens / The Hub tabs (data embedded)."""
from __future__ import annotations

import json
import math

import pandas as pd
from pathlib import Path

TEMPLATE = r"""<title>Creator Leaderboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,700&family=Instrument+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap">
<style>
/* Layout: summary strip -> three pillar tabs -> ranked table beside a rail explaining the active pillar and the run */
:root{
  --bg:#ffffff; --panel:#ffffff; --ink:#0a0a0a; --muted:#5c5c5c; --line:#e4e4e4; --accent:#ea580c; --accent-ink:#c2410c; --accent-soft:#fff1e6;
  --hi:#ffffff; --hi-bg:#ea580c; --md:#c2410c; --md-bg:#ffedd5; --lo:#404040; --lo-bg:#ededed; --gold:#ea580c; --bar:#fdba74;
  --c-instagram:#ea580c; --c-tiktok:#0a0a0a; --c-youtube:#8c8c8c; --grid:#ececec; --overlay:rgba(0,0,0,.45);
  --display:"Bricolage Grotesque",ui-sans-serif,system-ui,sans-serif;
  --body:"Instrument Sans",ui-sans-serif,system-ui,sans-serif;
  --mono:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --bg:#0a0a0a; --panel:#141414; --ink:#fafafa; --muted:#a3a3a3; --line:#2a2a2a; --accent:#fb923c; --accent-ink:#fb923c; --accent-soft:#2a1608;
  --hi:#0a0a0a; --hi-bg:#fb923c; --md:#fdba74; --md-bg:#3a1d0a; --lo:#d4d4d4; --lo-bg:#262626; --gold:#fb923c; --bar:#9a3412; --c-instagram:#fb923c; --c-tiktok:#fafafa; --c-youtube:#8f8f8f; --grid:#262626; --overlay:rgba(0,0,0,.6); color-scheme:dark}}
:root[data-theme="dark"]{
  --bg:#0a0a0a; --panel:#141414; --ink:#fafafa; --muted:#a3a3a3; --line:#2a2a2a; --accent:#fb923c; --accent-ink:#fb923c; --accent-soft:#2a1608;
  --hi:#0a0a0a; --hi-bg:#fb923c; --md:#fdba74; --md-bg:#3a1d0a; --lo:#d4d4d4; --lo-bg:#262626; --gold:#fb923c; --bar:#9a3412; --c-instagram:#fb923c; --c-tiktok:#fafafa; --c-youtube:#8f8f8f; --grid:#262626; --overlay:rgba(0,0,0,.6); color-scheme:dark}
*{box-sizing:border-box}
[hidden]{display:none!important}
.boardnote{margin:0 0 12px;padding:8px 12px;border-left:3px solid var(--accent,#f60);background:var(--accent-soft);font-size:13px}
body{background:var(--bg);color:var(--ink);font:15px/1.5 var(--body);margin:0}
.wrap{max-width:1220px;margin:0 auto;padding-inline:clamp(16px,3vw,32px);padding-block:28px 48px}
header{margin-bottom:18px}
h1{font:700 clamp(28px,4vw,40px)/1.05 var(--display);border-left:6px solid var(--accent);padding-left:12px;letter-spacing:-.02em;margin:0;text-wrap:balance}
.sub{color:var(--muted);margin:6px 0 0;max-width:70ch}
.stamp{font:12px var(--mono);color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:18px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.stat b{display:block;font:600 24px/1.2 var(--display);font-variant-numeric:tabular-nums}
.stat span{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.tabs{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-bottom:18px}
@media (max-width:640px){.tabs{grid-template-columns:minmax(0,1fr)}}
.tab{font:inherit;text-align:left;color:var(--ink);background:var(--panel);border:1.5px solid var(--line);border-radius:12px;padding:12px 14px;cursor:pointer;display:grid;gap:2px}
.tab .th{font:600 12px var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.tab .tn{font:700 20px/1.2 var(--display)}
.tab .tm{font-size:13px;color:var(--muted)}
.tab[aria-selected="true"]{border-color:var(--ink);background:var(--ink);color:var(--bg)}
.tab[aria-selected="true"] .tm{color:var(--bg);opacity:.75}
.tab[aria-selected="true"] .th{color:var(--accent)}
.grid{display:grid;grid-template-columns:minmax(0,1fr) 270px;gap:20px;align-items:start}
@media (max-width:940px){.grid{grid-template-columns:minmax(0,1fr)}}
.filters{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;margin-bottom:12px}
.filters input{grid-column:1/-1}
.filters input,.filters select{font:inherit;font-size:14px;color:var(--ink);background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:8px 10px;min-width:0}
input:focus-visible,select:focus-visible,button:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
.tablebox{background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:14px;min-width:680px}
th{font:500 11px var(--mono);text-transform:uppercase;letter-spacing:.07em;color:var(--muted);text-align:left;padding:10px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:middle}
tr:last-child td{border-bottom:0}
.num{text-align:right;font-variant-numeric:tabular-nums;font-family:var(--mono);font-size:13px}
.rank{font:600 15px var(--display);color:var(--muted);width:44px}
tr.top .rank{color:var(--gold)}
.name{font-weight:600;white-space:nowrap}
.id{display:block;font:12px var(--mono);color:var(--muted);white-space:nowrap}
.chans{display:flex;flex-wrap:wrap;gap:4px}
.chip{display:inline-flex;gap:5px;align-items:baseline;font:12px var(--mono);background:var(--accent-soft);color:var(--accent-ink);padding:2px 7px;border-radius:5px;white-space:nowrap}
.chip b{font-weight:500;color:var(--ink)}
.chip.on{outline:1.5px solid var(--accent)}
.chip.na b{color:var(--muted);font-style:italic}
.score{position:relative;min-width:76px}
.score strong{font:600 16px var(--display)}
.score i{position:absolute;right:10px;bottom:6px;height:5px;background:var(--bar);border-radius:3px}
.others{font:12px var(--mono);color:var(--muted);white-space:nowrap}
.others span{display:block}
.role{font-size:12px;font-weight:600;color:var(--accent-ink);white-space:nowrap}
.pill{font-size:12px;font-weight:600;padding:2px 8px;border-radius:999px;white-space:nowrap}
.High{color:var(--hi);background:var(--hi-bg)} .Medium{color:var(--md);background:var(--md-bg)} .Low{color:var(--lo);background:var(--lo-bg)}
.more{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:12px;color:var(--muted);font-size:13px;flex-wrap:wrap}
button.load{font:inherit;font-size:14px;font-weight:600;color:var(--accent-ink);background:var(--accent-soft);border:0;border-radius:8px;padding:8px 14px;cursor:pointer}
button[disabled]{opacity:.4;cursor:default}
aside{display:grid;gap:16px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px}
.card h2{font:600 16px var(--display);margin:0 0 4px}
.card p{margin:0 0 10px;color:var(--muted);font-size:13px}
.formula{font:12px/1.5 var(--mono);background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin:0 0 10px;overflow-x:auto;white-space:pre-wrap}
.caveat{font-size:13px;margin:0}
.caveat b{font-weight:600}
.tier{display:grid;grid-template-columns:28px 1fr auto;gap:8px;align-items:center;padding:7px 0;border-top:1px solid var(--line);font-size:14px}
.tier:first-of-type{border-top:0}
.tier .t{font:600 12px var(--mono);color:var(--accent-ink)}
.tier .s{font:13px var(--mono);font-variant-numeric:tabular-nums}
.tier small{display:block;color:var(--muted);font-size:12px}
.req{display:grid;grid-template-columns:78px 1fr 44px;gap:8px;align-items:center;font-size:13px;margin:7px 0}
.req .n{font:12px var(--mono);color:var(--muted);text-align:right}
.track{height:8px;background:var(--line);border-radius:4px;overflow:hidden}
.track div{height:100%;background:var(--accent);border-radius:4px}
.note{font-size:12px;color:var(--muted);margin-top:8px}
.empty{padding:32px;text-align:center;color:var(--muted)}
tbody tr[data-id]{cursor:pointer}
tbody tr[data-id]:hover td,tbody tr[data-id]:focus-visible td{background:var(--accent-soft)}
tbody tr[data-id]:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
.scrim{position:fixed;inset:0;background:var(--overlay);z-index:20}
.drawer{position:fixed;top:0;right:0;bottom:0;width:min(640px,100vw);background:var(--bg);z-index:21;overflow-y:auto;
  padding:calc(env(safe-area-inset-top,0px) + 20px) clamp(16px,3vw,28px) calc(env(safe-area-inset-bottom,0px) + 28px);
  border-left:1px solid var(--line);box-shadow:-12px 0 32px rgba(0,0,0,.12)}
.dhead{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}
.dhead h2{font:700 26px/1.1 var(--display);margin:0}
.close{font:inherit;font-size:14px;font-weight:600;color:var(--ink);background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:6px 12px;cursor:pointer}
.dsub{color:var(--muted);font-size:13px;margin:4px 0 16px}
.ptiles{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-bottom:16px}
.ptile{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.ptile b{display:block;font:600 24px/1.1 var(--display);font-variant-numeric:tabular-nums}
.ptile span{font-size:12px;color:var(--muted)}
.ptile.lead{border-color:var(--ink);background:var(--ink);color:var(--bg)}
.ptile.lead span{color:var(--accent)}
.dsec{font:600 15px var(--display);margin:18px 0 8px}
.chcards{display:grid;gap:8px}
.chcard{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px;display:grid;gap:6px}
.chcard .top{display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;align-items:baseline}
.chcard .pl{font-weight:600;display:inline-flex;gap:6px;align-items:center}
.sw{width:10px;height:10px;border-radius:2px;display:inline-block;flex:none}
.sw.instagram{border-radius:50%}
.sw.youtube{transform:rotate(45deg) scale(.85)}
.chcard .kv{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;font-size:13px}
.chcard .kv div span{display:block;font-size:11px;color:var(--muted)}
.chcard .kv div b{font:500 13px var(--mono)}
.chcard .miss{font-size:13px;color:var(--accent-ink)}
.legend{display:flex;flex-wrap:wrap;gap:12px;font-size:12px;color:var(--muted);margin-bottom:6px}
.legend span{display:inline-flex;gap:6px;align-items:center}
.lg-dash{width:18px;height:8px;display:inline-block;background:linear-gradient(var(--muted),var(--muted)) center/100% 0 no-repeat;border-top:2px dashed var(--muted);position:relative;top:4px}
.charts{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}
@media (max-width:560px){.charts,.ptiles{grid-template-columns:minmax(0,1fr)}.chcard .kv{grid-template-columns:minmax(0,1fr)}}
.chart{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:8px 8px 4px}
.chart h4{font:600 13px var(--body);margin:0 0 2px}
.chart svg{width:100%;max-width:300px;height:auto;display:block;overflow:visible;margin:0 auto}
.chart text{font:10px var(--mono);fill:var(--muted)}
.chart .vl{fill:var(--ink)}
.tip{position:fixed;z-index:30;pointer-events:none;background:var(--ink);color:var(--bg);font:12px var(--mono);padding:5px 8px;border-radius:6px;white-space:nowrap}
.def{cursor:help;border-bottom:1.5px dotted var(--accent);padding-bottom:1px}
.def:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.deftip{position:fixed;z-index:30;max-width:300px;background:var(--ink);color:var(--bg);font:13px/1.45 var(--body);
  text-transform:none;letter-spacing:0;text-align:left;padding:10px 12px;border-radius:8px;border-top:3px solid var(--accent);
  box-shadow:0 8px 24px rgba(0,0,0,.18)}
.deftip b{color:var(--accent)}
.htable{width:100%;min-width:0;font-size:12px;margin-top:8px}
.htable th,.htable td{padding:5px 6px}
.toggle{font:inherit;font-size:13px;font-weight:600;color:var(--accent-ink);background:none;border:0;padding:4px 0;cursor:pointer}
.note2{font-size:12px;color:var(--muted);margin:6px 0 0}
.qa{display:grid;gap:6px}
.qrow{display:grid;grid-template-columns:auto 1fr;gap:10px;align-items:start;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:8px 10px;font-size:13px}
.qrow .id{white-space:normal;margin-top:2px}
.sev{font-size:11px;font-weight:700;padding:2px 7px;border-radius:999px;white-space:nowrap}
.sev.YELLOW{background:var(--md-bg);color:var(--md)} .sev.RED{background:var(--hi-bg);color:var(--hi)}
.views{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px}
.view{font:inherit;font-size:14px;font-weight:600;color:var(--muted);background:var(--panel);border:1px solid var(--line);border-radius:999px;padding:6px 14px;cursor:pointer;display:inline-flex;gap:6px;align-items:baseline}
.view small{font:12px var(--mono);color:var(--muted)}
.view[aria-selected="true"]{color:var(--accent-ink);border-color:var(--accent);background:var(--accent-soft)}
.metric{font:13px var(--mono);white-space:nowrap}
.band{font:12px var(--mono);color:var(--muted)}
th.wrap{white-space:normal;max-width:90px}
.pending{white-space:nowrap;display:block;font-size:11px;font-weight:600;color:var(--md)}
</style>

<div class="wrap">
  __CC_HTML__
  <header id="board">
    <div id="boardnote"></div>
    <div class="stamp" id="stamp"></div>
    <h1>Creator Leaderboard</h1>
    <p class="sub">Three ways to find the right creators. Each channel is scored 0–100 against requested channels on the same platform. <b>All channels</b> ranks creators on the average of the channels we asked for (only creators with every requested channel filled). The <b>Instagram, TikTok and YouTube</b> boards rank each channel on its own, so a channel appears as soon as it's filled.</p>
  </header>

  <section class="stats" id="stats"></section>
  <nav class="tabs" id="tabs" role="tablist" aria-label="Pillar"></nav>

  <div class="grid">
    <main>
      <nav class="views" id="views" role="tablist" aria-label="Leaderboard"></nav>
      <div class="filters">
        <input id="q" type="search" placeholder="Search creator name, ID or handle" aria-label="Search creators">
        <select id="f-band" aria-label="Size band"></select>
        <select id="f-country" aria-label="Country"></select>
        <select id="f-role" aria-label="Primary role"></select>
        <select id="f-conf" aria-label="Confidence"></select>
      </div>
      <div class="tablebox">
        <table>
          <thead id="thead"></thead>
          <tbody id="rows"></tbody>
        </table>
        <div class="more"><span id="count"></span><button class="load" id="more" type="button">Show 50 more</button></div>
      </div>
    </main>
    <aside>
      <div class="card" id="pillar-card"></div>
      <div class="card">
        <h2>This run's request</h2>
        <p>Channels requested, and the share now complete.</p>
        <div id="req"></div>
        <div class="note">Bar = share complete · number = channels requested</div>
        <div id="shape"></div>
      </div>
      <div class="card">
        <h2>Vendor tiers</h2>
        <p>QA scored on the requested channels only.</p>
        <div id="tiers"></div>
      </div>
    </aside>
  </div>
</div>

<div class="scrim" id="scrim" hidden></div>
<div class="drawer" id="drawer" hidden role="dialog" aria-modal="true" aria-labelledby="pname"></div>
<div class="tip" id="tip" hidden></div>
<div class="deftip" id="deftip" role="tooltip" hidden></div>

<script>
let D = __DATA__;
const $ = s => document.querySelector(s);
const fmt = n => n.toLocaleString("en-US");
const compact = n => n >= 1e6 ? (n/1e6).toFixed(n>=1e7?0:1)+"M" : n >= 1e3 ? (n/1e3).toFixed(n>=1e4?0:1)+"K" : String(n);
const pct = x => (x*100).toFixed(1)+"%";
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const show = (v, d) => v == null ? "n/a" : d === "multiple" ? v.toFixed(1)+"x" : d === "percent_signed" ? (v>=0?"+":"")+(v*100).toFixed(1)+"%" : (v*100).toFixed(1)+"%";

function drawHeader(){
  $("#stamp").textContent = D.month_label + " run · QA: " + D.qa.reviewed + " reviewed, " + D.qa.warnings + " warnings · " + D.months.length + " month" + (D.months.length > 1 ? "s" : "") + " of history · freshness limit " + D.sla_days + " days";
  const s = D.summary;
  $("#stats").innerHTML = [
    [fmt(s.ranked), "Creators ranked"], [pct(s.ranked / s.creators), "Of " + fmt(s.creators) + " requested"],
    [pct(s.channels_complete), "Of " + fmt(s.channels) + " channels filled"], [fmt(s.gap_creators), "Creators still missing data"],
  ].map(([v,l]) => `<div class="stat"><b>${v}</b><span>${l}</span></div>`).join("");
  $("#boardnote").innerHTML = D.board_note ? `<div class="boardnote">${D.board_note}</div>` : "";
}

let active = D.metrics[0].key;
function drawTabs(){
  $("#tabs").innerHTML = D.metrics.map(m => `<button class="tab" role="tab" type="button" data-k="${m.key}" aria-selected="${m.key===active}">
    <span class="th">${esc(m.theme)}</span><span class="tn">${esc(m.pillar)}</span><span class="tm">${esc(m.label)}</span></button>`).join("");
  document.querySelectorAll(".tab").forEach(b => b.addEventListener("click", () => { active = b.dataset.k; shown = 50; drawTabs(); render(); }));
  const m = D.metrics.find(x => x.key === active);
  $("#pillar-card").innerHTML = `<h2>${esc(m.pillar)} · ${esc(m.theme)}</h2><p>${esc(m.blurb)}.</p>
    <div class="formula">${esc(m.label)} =\n${esc(m.formula)}${m.overrides.map(o => `\n${esc(o[0])}: ${esc(o[1])}`).join("")}</div>
    <p class="caveat"><b>Compared within:</b> ${esc(m.within)}. ${esc(m.caveat)}</p>`;
}
function drawSide(){
$("#shape").innerHTML = `<p style="margin:14px 0 4px">Creators by channels needed</p>` + D.shape.map(r => `<div class="req"><span>${r.n} of ${D.platforms.length}</span>
  <div class="track"><div style="width:${r.complete*100}%"></div></div><span class="n">${r.creators}</span></div>`).join("")
  + `<div class="note">Bar = share of those creators complete · number = creators</div>`;
$("#req").innerHTML = D.request.map(r => `<div class="req"><span>${esc(r.platform)}</span>
  <div class="track"><div style="width:${r.complete*100}%"></div></div><span class="n">${r.requested}</span></div>`).join("");
$("#tiers").innerHTML = D.tiers.map(t => `<div class="tier"><span class="t">${t.tier ? "T"+t.tier : "—"}</span>
  <span>${esc(t.vendor)}<small>${t.excluded ? esc(t.excluded) : "fresh coverage " + pct(t.usable_coverage) + " · best on " + esc(t.best)}</small></span>
  <span class="s">${t.score.toFixed(2)}</span></div>`).join("");
}
function opts(sel, vals, label){ sel.innerHTML = `<option value="">${label}</option>` + vals.map(v => `<option>${esc(v)}</option>`).join(""); }
function fillFilters(){
  opts($("#f-band"), D.bands, "Any size");
  opts($("#f-country"), [...new Set([...D.rows.map(r => r.country), ...Object.values(D.channels).flat().map(r => r.country)].filter(Boolean))].sort(), "All countries");
  opts($("#f-role"), D.metrics.map(m => m.pillar), "Any primary role");
  opts($("#f-conf"), ["High","Medium","Low"], "Any confidence");
  $("#q").value = "";
}
let view = "all";
const PNAME = {instagram: "Instagram", tiktok: "TikTok", youtube: "YouTube"};
function drawViews(){
  const req = Object.fromEntries(D.request.map(r => [r.platform, r.requested]));
  const items = [["all", "All creators", `${fmt(D.rows.length)} of ${fmt(D.summary.creators)} ranked`],
    ...D.platforms.filter(p => D.channels[p]).map(p => [p, PNAME[p], `${fmt(D.channels[p].length)} of ${fmt(req[p] || 0)} ranked`])];
  $("#views").innerHTML = items.map(([k, label, n]) => `<button class="view" role="tab" type="button" data-v="${k}" aria-selected="${k===view}">${esc(label)} <small>${esc(n)}</small></button>`).join("");
  document.querySelectorAll(".view").forEach(b => b.addEventListener("click", () => { view = b.dataset.v; shown = 50; drawViews(); render(); }));
}
let shown = 50;
function confDef(plat){
  const order = D.tiers.filter(t => t.tier).map(t => `Tier ${t.tier} = ${t.vendor}`).join(", ");
  const what = plat ? "this channel's follower count and three metrics" : "the follower counts and metrics across all of the creator's requested channels";
  return `Confidence · how reliable the source data is|Based on which vendor tier supplied ${what}. High = all from the Tier 1 vendor; Medium = at least one value had to come from Tier 2; Low = at least one came from Tier 3. This month: ${order}. Vendors are tiered by data quality (coverage, completeness, freshness, validity, plus past months).`;
}
function roleDef(){
  return `Primary role · what this creator is strongest at|The pillar with the highest score: ${D.metrics.map(m => `${m.pillar} (${m.theme.toLowerCase()})`).join(", ")}. Ties go to the pillar listed first.`;
}
function scoreDef(m, plat){
  const within = m.within.includes("size band") ? "on the same platform and in the same follower-size band" : "on the same platform";
  const head = `${m.pillar} score (0–100) · ${m.label}`;
  if (plat) return `${head}|This ${PNAME[plat]} channel's ${m.label.replace("90d ", "").toLowerCase()} ranked against every other requested ${PNAME[plat]} channel ${m.within.includes("size band") ? "in the same follower-size band" : ""} this month. 100 = highest, 50 = middle of the group.`;
  return `${head}|The creator's average across the channels we requested. Each channel's ${m.label.replace("90d ", "").toLowerCase()} is ranked against requested channels ${within} this month, so 100 = top of that group and 50 = the middle.`;
}
const rankBy = (rows, val) => { let prev = null, rank = 0; return rows.map((r, i) => { if (val(r) !== prev) { rank = i + 1; prev = val(r); } return {...r, _rank: rank}; }); };
const others = (scores) => D.metrics.filter(x => x.key !== active).map(x => `<span>${esc(x.pillar.replace("The ",""))} ${scores[x.key]==null?"–":Math.round(scores[x.key])}</span>`).join("");
const scoreCell = v => `<td class="num score"><strong>${Math.round(v)}</strong><i style="width:${Math.max(2, v*0.6)}px"></i></td>`;
function render(){
  const m = D.metrics.find(x => x.key === active);
  const q = $("#q").value.trim().toLowerCase(), band = $("#f-band").value;
  const f = {country:$("#f-country").value, role:$("#f-role").value, confidence:$("#f-conf").value};
  const short = m.label.replace("90d ", "").replace("Meaningful Engagement", "Meaningful Eng");
  let rows, html;
  if (view === "all") {
    $("#thead").innerHTML = `<tr><th>#</th><th>Creator</th><th>Channels · ${esc(short)}</th><th class="num"><span class="def" tabindex="0" data-def="${esc(scoreDef(m, null))}">Score</span></th><th>Other pillars</th><th><span class="def" tabindex="0" data-def="${esc(roleDef())}">Primary role</span></th><th><span class="def" tabindex="0" data-def="${esc(confDef(view === "all" ? null : view))}">Confidence</span></th></tr>`;
    const val = r => r.scores[active];
    rows = rankBy(D.rows.filter(r => (!band || Object.values(r.ch).some(c => c.band === band))
      && Object.entries(f).every(([k,v]) => !v || r[k] === v) && val(r) != null).sort((a,b) => val(b) - val(a)), val);
    if (q) rows = rows.filter(r => (r.name + " " + r.id + " " + Object.values(r.ch).map(c => c.handle).join(" ")).toLowerCase().includes(q));
    html = rows.slice(0, shown).map(r => `<tr class="${r._rank<=3?"top":""}" data-id="${esc(r.id)}" tabindex="0" aria-label="Open ${esc(r.name)}'s profile">
      <td class="rank">${r._rank}</td>
      <td><span class="name">${esc(r.name)}</span><span class="id">${esc(r.id)} · ${esc(r.country)} · ${compact(r.followers)}</span></td>
      <td><div class="chans">${Object.entries(r.ch).map(([p,c]) => `<span class="chip${c[active]==null?" na":""}" title="${esc(c.handle)} · ${fmt(c.followers)} followers · ${esc(c.band)} · percentile ${c[active+"__pct"] ?? "n/a"}">${esc(p)} <b>${c[active]==null ? "likes hidden" : show(c[active], m.display)}</b></span>`).join("")}</div></td>
      ${scoreCell(val(r))}<td class="others">${others(r.scores)}</td>
      <td><span class="role">${esc(r.role ?? "")}</span></td>
      <td><span class="pill ${r.confidence}" title="Sources: ${esc(r.sources)}">${r.confidence}</span></td></tr>`).join("");
  } else {
    $("#thead").innerHTML = `<tr><th>#</th><th>Creator · handle</th><th>Size · country</th><th class="num wrap">${esc(short)}</th><th class="num"><span class="def" tabindex="0" data-def="${esc(scoreDef(m, view))}">Score</span></th><th>Other pillars</th><th><span class="def" tabindex="0" data-def="${esc(roleDef())}">Primary role</span></th><th><span class="def" tabindex="0" data-def="${esc(confDef(view === "all" ? null : view))}">Confidence</span></th></tr>`;
    const val = r => r.pct[active];
    rows = rankBy(D.channels[view].filter(r => (!band || r.band === band)
      && Object.entries(f).every(([k,v]) => !v || r[k] === v) && val(r) != null).sort((a,b) => val(b) - val(a)), val);
    if (q) rows = rows.filter(r => (r.name + " " + r.id + " " + r.handle).toLowerCase().includes(q));
    html = rows.slice(0, shown).map(r => `<tr class="${r._rank<=3?"top":""}" data-id="${esc(r.id)}" tabindex="0" aria-label="Open ${esc(r.name || r.id)}'s profile">
      <td class="rank">${r._rank}</td>
      <td><span class="name">${esc(r.name || r.id)}</span><span class="id">${esc(r.handle)}</span>${r.complete ? "" : `<span class="pending">other channels pending</span>`}</td>
      <td><span class="band">${esc(r.band)} · ${esc(r.country || "")}</span><span class="id">${compact(r.followers)}</span></td>
      <td class="num metric">${show(r.val[active], m.display)}</td>
      ${scoreCell(val(r))}<td class="others">${others(r.pct)}</td>
      <td><span class="role">${esc(r.role ?? "")}</span></td>
      <td><span class="pill ${r.confidence}" title="Sources: ${esc(r.sources)}">${r.confidence}</span></td></tr>`).join("");
  }
  const noun = view === "all" ? "creators" : view + " channels";
  $("#rows").innerHTML = rows.length ? html : `<tr><td colspan="8" class="empty">No ${noun} match these filters.</td></tr>`;
  $("#count").textContent = `Showing ${fmt(Math.min(shown, rows.length))} of ${fmt(rows.length)} ${noun}`;
  $("#more").disabled = shown >= rows.length;
}
["#q","#f-band","#f-country","#f-role","#f-conf"].forEach(id => $(id).addEventListener("input", () => { shown = 50; render(); }));
$("#more").addEventListener("click", () => { shown += 50; render(); });
function boot(){ view = "all"; shown = 50; drawHeader(); drawSide(); fillFilters(); drawTabs(); drawViews(); render(); }
boot();
const deftip = $("#deftip");
function showDef(el){
  const [title, body] = el.dataset.def.split("|");
  deftip.innerHTML = `<b>${esc(title)}</b><br>${esc(body)}`;
  deftip.hidden = false;
  const r = el.getBoundingClientRect(), w = deftip.offsetWidth;
  deftip.style.left = Math.max(8, Math.min(window.innerWidth - w - 8, r.right - w)) + "px";
  deftip.style.top = (r.bottom + 8) + "px";
}
const hideDef = () => { deftip.hidden = true; };
$("#thead").addEventListener("mouseover", e => { const d = e.target.closest(".def"); if (d) showDef(d); });
$("#thead").addEventListener("mouseout", e => { if (e.target.closest(".def")) hideDef(); });
$("#thead").addEventListener("focusin", e => { const d = e.target.closest(".def"); if (d) showDef(d); });
$("#thead").addEventListener("focusout", hideDef);
document.addEventListener("keydown", e => { if (e.key === "Escape") hideDef(); });
window.addEventListener("scroll", () => { if (!document.activeElement?.classList.contains("def")) hideDef(); }, {passive: true});

/* ---------------- creator profile ---------------- */
const MON = m => new Date(m + "-15").toLocaleString("en-US", {month: "short"}) + " " + m.slice(2, 4);
const tip = $("#tip");
function lineChart(metric, series, months){
  const W = 180, H = 120, L = 26, R = 30, T = 8, B = 18;
  const x = i => months.length === 1 ? (L + (W - R)) / 2 : L + i * ((W - R - L) / (months.length - 1));
  const y = v => T + (100 - v) * (H - T - B) / 100;
  let g = [0, 50, 100].map(v => `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="var(--grid)" stroke-width="1"/><text x="${L - 4}" y="${y(v) + 3}" text-anchor="end">${v}</text>`).join("");
  g += months.map((m, i) => `<text x="${x(i)}" y="${H - 4}" text-anchor="middle">${MON(m)}</text>`).join("");
  const ends = [];
  for (const s of series) {
    const pts = s.vals.map((v, i) => v == null ? null : [x(i), y(v), v, months[i]]);
    const segs = []; let cur = [];
    pts.forEach(p => { if (p) cur.push(p); else if (cur.length) { segs.push(cur); cur = []; } });
    if (cur.length) segs.push(cur);
    for (const sg of segs) if (sg.length > 1) g += `<polyline fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" ${s.dash ? 'stroke-dasharray="4 3"' : ""} points="${sg.map(p => p[0] + "," + p[1]).join(" ")}"/>`;
    for (const p of pts.filter(Boolean)) g += s.shape === "square" ? `<rect x="${p[0] - 4}" y="${p[1] - 4}" width="8" height="8" rx="1" fill="${s.color}" stroke="var(--panel)" stroke-width="2"/>`
      : s.shape === "diamond" ? `<path d="M${p[0]} ${p[1] - 5.5}L${p[0] + 5.5} ${p[1]}L${p[0]} ${p[1] + 5.5}L${p[0] - 5.5} ${p[1]}Z" fill="${s.color}" stroke="var(--panel)" stroke-width="2"/>`
      : s.dash ? `<circle cx="${p[0]}" cy="${p[1]}" r="3.5" fill="var(--panel)" stroke="${s.color}" stroke-width="1.5"/>`
      : `<circle cx="${p[0]}" cy="${p[1]}" r="4.5" fill="${s.color}" stroke="var(--panel)" stroke-width="2"/>`;
    const last = pts.filter(Boolean).pop();
    if (last) ends.push({y: last[1], v: last[2], x: last[0]});
  }
  // one hover band per month listing every series (crosshair-style), so overlapping points never hide each other
  const step = months.length === 1 ? (W - R - L) : (W - R - L) / (months.length - 1);
  g += months.map((mo, i) => {
    const vals = series.map(s => s.vals[i] == null ? null : `${s.label} ${Math.round(s.vals[i])}`).filter(Boolean);
    return vals.length ? `<rect x="${x(i) - step / 2}" y="${T}" width="${step}" height="${H - T - B}" fill="transparent" data-tip="${MON(mo)} · ${esc(metric.pillar)} — ${esc(vals.join(" · "))}"/>` : "";
  }).join("");
  ends.sort((a, b) => a.y - b.y);                                     // nudge end labels apart
  for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 11) ends[i].y = ends[i - 1].y + 11;
  g += ends.map(e => `<text class="vl" x="${e.x + 7}" y="${e.y + 3}">${Math.round(e.v)}</text>`).join("");
  return `<div class="chart"><h4>${esc(metric.pillar)}</h4><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(metric.pillar)} score by month">${g}</svg></div>`;
}
function openProfile(id){
  const P = D.profiles[id]; if (!P) return;
  const months = D.months, hist = P.history || {};
  const lead = P.role;
  const tiles = D.metrics.map(m => `<div class="ptile${m.pillar === lead ? " lead" : ""}"><span>${esc(m.pillar)} · ${esc(m.theme)}</span><b>${P.scores[m.key] == null ? "–" : Math.round(P.scores[m.key])}</b></div>`).join("");
  const cards = P.channels.map(pl => {
    const c = P.current[pl] || {};
    const head = `<div class="top"><span class="pl"><i class="sw ${pl}" style="background:var(--c-${pl})"></i>${PNAME[pl]}${c.handle ? ` <span class="id" style="display:inline">${esc(c.handle)}</span>` : ""}</span>
      <span class="id" style="display:inline">${c.followers ? compact(c.followers) + " followers · " + esc(c.band) : ""}</span></div>`;
    if (!c.filled) return `<div class="chcard">${head}<div class="miss">Not filled this month: ${esc(c.reason || "missing data")}</div></div>`;
    return `<div class="chcard">${head}<div class="kv">${D.metrics.map(m => `<div><span>${esc(m.label.replace("90d ", ""))}</span><b>${c.val[m.key] == null ? "likes hidden" : show(c.val[m.key], m.display)} · ${c.pct[m.key] == null ? "–" : Math.round(c.pct[m.key])}</b></div>`).join("")}</div>
      <div class="id">Confidence ${esc(c.confidence)} · from ${esc(c.sources)}</div></div>`;
  }).join("");
  const SHAPE = {instagram: "circle", tiktok: "square", youtube: "diamond"};
  const series = m => [...P.channels.map(pl => ({label: PNAME[pl], color: `var(--c-${pl})`, shape: SHAPE[pl], vals: months.map((_, i) => (hist[pl] || {})[m.key]?.[i] ?? null)})),
                       ...(P.channels.length > 1 ? [{label: "Average", color: "var(--muted)", dash: true, vals: months.map((_, i) => (hist.all || {})[m.key]?.[i] ?? null)}] : [])];
  const legend = `<div class="legend">${P.channels.map(pl => `<span><i class="sw ${pl}" style="background:var(--c-${pl})"></i>${PNAME[pl]}</span>`).join("")}${P.channels.length > 1 ? `<span><i class="lg-dash"></i>Average of requested channels</span>` : ""}</div>`;
  const rowsT = months.map((mo, i) => `<tr><td>${MON(mo)}</td>${[...P.channels, "all"].map(pl => D.metrics.map(m => `<td class="num">${(hist[pl] || {})[m.key]?.[i] == null ? "–" : Math.round(hist[pl][m.key][i])}</td>`).join("")).join("")}</tr>`).join("");
  const table = `<div class="tablebox" style="margin-top:8px"><table class="htable"><thead><tr><th>Month</th>${[...P.channels, "all"].map(pl => D.metrics.map(m => `<th class="num">${pl === "all" ? "Avg" : PNAME[pl]} ${esc(m.pillar.replace("The ", ""))}</th>`).join("")).join("")}</tr></thead><tbody>${rowsT}</tbody></table></div>`;
  $("#drawer").innerHTML = `<div class="dhead"><div><div class="stamp">${esc(P.id)} · ${esc(P.country || "")} · ${esc(P.category || "")}</div><h2 id="pname">${esc(P.name || P.id)}</h2></div><button class="close" id="pclose" type="button">Close</button></div>
    <p class="dsub">${P.complete ? "All requested channels filled" : `${P.filled} of ${P.channels.length} requested channels filled`} · ${lead ? "primary role " + esc(lead) : "no score yet"} · requested: ${P.channels.map(pl => PNAME[pl]).join(", ")}</p>
    <div class="ptiles">${tiles}</div>
    <div class="dsec">Channels this month</div><div class="chcards">${cards}</div>
    ${P.qa.length ? `<div class="dsec">Data checks this month</div><div class="qa">${P.qa.map(q => `<div class="qrow"><span class="sev ${q.severity}">${q.severity === "RED" ? (q.status === "resolved" ? "Reviewed" : "Blocked") : "Warning"}</span><div><b>${esc(q.code)}</b> · ${esc(q.platform ? PNAME[q.platform] || q.platform : "")}${q.decision ? ` · decision ${esc(q.decision)}` : ""}<div class="id">${esc(q.explanation)}</div></div></div>`).join("")}</div>` : ""}
    <div class="dsec">Scores by month</div>${legend}
    <div class="charts">${D.metrics.map(m => lineChart(m, series(m), months)).join("")}</div>
    <p class="note2">0–100 score per channel each month${P.channels.length > 1 ? "; the dashed line is the creator's average over requested channels" : ""}. ${months.length < 2 ? "History builds up as each month is processed." : ""}</p>
    <button class="toggle" id="ptable" type="button" aria-expanded="false">Show as table</button><div id="ptablebox" hidden>${table}</div>`;
  $("#scrim").hidden = false; $("#drawer").hidden = false; $("#pclose").focus();
  $("#pclose").addEventListener("click", closeProfile);
  $("#ptable").addEventListener("click", e => { const b = $("#ptablebox"); b.hidden = !b.hidden; e.target.textContent = b.hidden ? "Show as table" : "Hide table"; e.target.setAttribute("aria-expanded", String(!b.hidden)); });
  $("#drawer").querySelectorAll("[data-tip]").forEach(el => {
    el.addEventListener("mouseenter", ev => { tip.textContent = el.dataset.tip; tip.hidden = false; });
    el.addEventListener("mousemove", ev => { tip.style.left = (ev.clientX + 12) + "px"; tip.style.top = (ev.clientY - 28) + "px"; });
    el.addEventListener("mouseleave", () => { tip.hidden = true; });
  });
}
let lastRow = null;
function closeProfile(){ $("#drawer").hidden = true; $("#scrim").hidden = true; tip.hidden = true; if (lastRow) lastRow.focus(); }
$("#scrim").addEventListener("click", closeProfile);
document.addEventListener("keydown", e => { if (e.key === "Escape" && !$("#drawer").hidden) closeProfile(); });
$("#rows").addEventListener("click", e => { const tr = e.target.closest("tr[data-id]"); if (tr) { lastRow = tr; openProfile(tr.dataset.id); } });
$("#rows").addEventListener("keydown", e => { const tr = e.target.closest("tr[data-id]"); if (tr && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); lastRow = tr; openProfile(tr.dataset.id); } });
</script>
__CC_SCRIPT__
"""

CAVEATS = {
    "reach_rate": "Favours accounts that publish video, so each channel is only compared with the same platform.",
    "growth_rate": "Favours small accounts gaining traction, so growth is compared within follower-size band.",
    "meaningful_eng_rate": "Hidden likes would inflate the rate, so those accounts show n/a and the creator's Hub "
                           "score uses their other channels. YouTube doesn't publish saves.",
}


def _clean(v):
    if v is None or v is pd.NA or (isinstance(v, float) and math.isnan(v)):
        return None
    return v.item() if hasattr(v, "item") else v


def months_kept(p, n: int = 12) -> list:
    h = p.creator_history.df
    return sorted(h["month"].astype(str).unique())[-n:] if not h.empty else [p.month]


def profiles(p) -> dict:
    """Every requested creator: details, this month's channels (filled or why not), and score history."""
    months = months_kept(p)
    h = p.creator_history.df
    h = h[h["creator_id"].isin(set(p.req_creators)) & h["month"].astype(str).isin(months)]
    hist = {}
    for (cid, pl), g in h.groupby(["creator_id", "platform"]):
        g = g.set_index(g["month"].astype(str))
        hist.setdefault(cid, {})[pl] = {m: [_clean(None if mo not in g.index else
                                                   (None if pd.isna(g.at[mo, f"{m}__pct"]) else round(float(g.at[mo, f"{m}__pct"]), 1)))
                                               for mo in months] for m in p.metrics}
    ch = p.scored_ch
    filled = pd.concat([p.filled(ch, f) for f in p.ch_required], axis=1).all(axis=1)
    conf_rows = {(r[p.key], r["platform"]): r for r in p.channel_board.to_dict("records")}
    reasons = {(r[p.key], r["platform"]): r["reason"] for r in p.gaps.to_dict("records") if r["level"] == "channel"}
    creator_reason = {r[p.key]: r["reason"] for r in p.gaps.to_dict("records") if r["level"] == "creator"}
    complete = set(p.leaderboard[p.key])
    qa_by = {}
    for f in p.flags.flags:                                  # skip routine fallback notes in the profile
        if f.code != "PRIMARY_SOURCE_MISSING":
            qa_by.setdefault(f.creator_id, []).append({"code": f.code, "severity": f.severity, "platform": f.platform,
                                                       "explanation": f.explanation, "status": f.status, "decision": f.decision})
    out = {}
    for cid in p.req_creators:
        cr = p.out_cr.loc[cid]
        sc = p.creator_scores.loc[cid] if cid in p.creator_scores.index else None
        chans = [pl for pl in p.platforms if (cid, pl) in ch.index]
        cur = {}
        for pl in chans:
            r = ch.loc[(cid, pl)]
            fol = _clean(r["follower_count"])
            base = {"handle": _clean(r["handle"]), "followers": None if fol is None else int(float(fol)),
                    "band": _clean(r["size_band"]), "filled": bool(filled.loc[(cid, pl)])}
            if base["filled"]:
                cb = conf_rows.get((cid, pl), {})
                base.update({"val": {m: _clean(r[m]) for m in p.metrics}, "pct": {m: _clean(r[f"{m}__pct"]) for m in p.metrics},
                             "confidence": cb.get("confidence", ""), "sources": cb.get("sources", "")})
            else:
                base["reason"] = reasons.get((cid, pl)) or creator_reason.get(cid) or "missing data"
            cur[pl] = base
        out[cid] = {"id": cid, "name": _clean(cr["display_name"]), "country": _clean(cr["country"]),
                    "category": _clean(cr["category"]), "channels": chans, "current": cur,
                    "filled": sum(1 for c in cur.values() if c["filled"]), "complete": cid in complete,
                    "scores": {m: None if sc is None else _clean(sc[m]) for m in p.metrics},
                    "role": None if sc is None else _clean(sc["primary_role"]), "history": hist.get(cid, {}),
                    "qa": qa_by.get(cid, [])}
    return out


def channel_rows(p) -> dict:
    out = {}
    for r in p.channel_board.to_dict("records"):
        out.setdefault(r["platform"], []).append({
            "id": r[p.key], "name": _clean(r.get("display_name")), "country": _clean(r.get("country")),
            "handle": r["handle"], "followers": int(r["follower_count"]), "band": r["size_band"],
            "val": {m: _clean(r[m]) for m in p.metrics}, "pct": {m: _clean(r[f"{m}__pct"]) for m in p.metrics},
            "role": _clean(r["primary_role"]), "confidence": r["confidence"], "sources": r["sources"],
            "complete": bool(r["creator_complete"])})
    return out


def leaderboard_payload(p) -> dict:
    lb = p.leaderboard
    tiers = []
    for n, pr in sorted(p.profiles.items(), key=lambda kv: -kv[1].score):
        best = max(pr.platform_coverage, key=pr.platform_coverage.get) if pr.platform_coverage else "-"
        tiers.append({"tier": pr.tier, "vendor": n, "score": pr.score, "usable_coverage": pr.usable_coverage,
                      "best": best, "excluded": pr.excluded_reason})
    metrics = [{"key": m, "pillar": s["pillar"], "theme": s["theme"], "label": s["label"], "blurb": s["blurb"],
                "formula": s["formula"], "overrides": list((s.get("by_platform") or {}).items()),
                "display": s["display"], "caveat": CAVEATS.get(m, ""),
                "within": "platform + follower-size band" if s.get("compare_within_size_band") else "platform"}
               for m, s in p.metrics.items()]
    rows = []
    for r in lb.to_dict("records"):
        rows.append({"id": r[p.key], "name": r["display_name"], "country": r["country"],
                     "followers": int(r["total_followers"]),
                     "ch": {pl: {k: _clean(v) for k, v in d.items()} for pl, d in r["detail"].items()},
                     "scores": {m: _clean(r[m]) for m in p.metrics},
                     "role": _clean(r["primary_role"]), "confidence": r["confidence"], "sources": r["sources"]})
    fin = p.final
    return {
        "run_date": str(p.run_date.date()), "sla_days": p.cfg["qa"]["freshness_sla_days"],
        "month": p.month, "month_label": pd.Period(p.month, "M").strftime("%B %Y"),
        "months": months_kept(p), "profiles": profiles(p),
        "platforms": p.platforms, "bands": list(p.cfg["size_bands"]), "metrics": metrics,
        "summary": {"creators": len(p.req_creators), "channels": len(p.req_pairs), "ranked": len(lb),
                    "channels_complete": fin["channels_complete"], "gap_creators": p.creators_with_gaps},
        "request": [{"platform": pl, "requested": n, "complete": fin["channels_complete_by_platform"].get(pl, 0)}
                    for pl, n in p.request_mix.items() if n],
        "shape": [{"n": n, "creators": c, "complete": fin["creators_complete_by_n_channels"].get(n, 0)}
                  for n, c in p.request_shape.items()],
        "tiers": tiers, "rows": rows, "channels": channel_rows(p),
        "qa": {"warnings": sum(1 for f in p.flags.flags if f.severity == "YELLOW"),
               "reviewed": sum(1 for f in p.flags.flags if f.severity == "RED" and f.status == "resolved")},
    }


def render(p, standalone: bool = True) -> str:
    body = TEMPLATE.replace("__DATA__", json.dumps(leaderboard_payload(p)).replace("</", "<\\/"))
    try:                                   # in-page Workflow Control Center (optional module)
        from control_center import cc_html, cc_script
        body = body.replace("__CC_HTML__", cc_html()).replace("__CC_SCRIPT__", cc_script(p))
    except ImportError:
        body = body.replace("__CC_HTML__", "").replace("__CC_SCRIPT__", "")
    if not standalone:
        return body
    return ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">\n' + body.replace(
                "<div class=\"wrap\">", "</head><body>\n<div class=\"wrap\">", 1) + "\n</body></html>\n")


def write_leaderboard_html(p, path: Path, standalone: bool = True) -> Path:
    Path(path).write_text(render(p, standalone), encoding="utf-8")
    return Path(path)
