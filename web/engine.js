/* Workflow Control Center — browser engine.
 * A JavaScript port of the Python pipeline (pipeline.py, qa_checks.py, review.py, vendor_registry.py, memory.py,
 * demo_data.py) so the published page can run Inputs → QA & Processing → Human Review → Finalize → Leaderboard
 * on its own. Settings come from config.yaml (embedded as CC.config). Parity with the Python pipeline is checked
 * by tests/test_parity.py, which feeds both the same files.
 */
const ENG = (() => {
  "use strict";
  // ------------------------------------------------------------------ small helpers
  const isNum = v => typeof v === "number" && Number.isFinite(v);
  const num = v => (v === null || v === undefined || v === "") ? NaN : (typeof v === "number" ? v : Number(String(v).replace(/,/g, "")));
  const blank = v => v === null || v === undefined || (typeof v === "number" && Number.isNaN(v)) || (typeof v === "string" && v.trim() === "");
  const norm = s => String(s).toLowerCase().replace(/[^a-z0-9]/g, "");
  const pairKey = (c, p) => c + "|" + p;
  const DAY = 86400000;
  const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
  const COUNTRY = {"united states": "US", "united kingdom": "GB", "canada": "CA", "brazil": "BR", "india": "IN",
    "germany": "DE", "france": "FR", "japan": "JP", "mexico": "MX", "south korea": "KR"};
  const NO = new Set(["", "n", "no", "0", "false", "-", "—"]);
  const round = (x, d = 4) => Math.round(x * 10 ** d) / 10 ** d;

  function isValid(v, rule) {
    if (blank(v)) return false;
    if (rule === "non_empty") return String(v).trim() !== "";
    if (rule === "iso2") return /^[A-Z]{2}$/.test(String(v));
    if (rule === "email") return EMAIL.test(String(v));
    if (rule === "non_negative_int" || rule === "int") {
      const f = num(v);
      return isNum(f) && Number.isInteger(f) && (rule === "int" || f >= 0);
    }
    if (rule && rule.one_of) return rule.one_of.includes(v);
    return false;
  }
  const IDENT = /[A-Za-z_][A-Za-z0-9_]*/g;
  const formulaCache = {};
  function compile(expr) {                       // arithmetic over field names, from config.yaml (trusted)
    if (formulaCache[expr]) return formulaCache[expr];
    const names = [...new Set(expr.match(IDENT))];
    const body = expr.replace(IDENT, m => `v(${JSON.stringify(m)})`);
    const fn = new Function("v", `return (${body});`);
    return (formulaCache[expr] = {names, fn});
  }
  function ratio(a, b) {                         // similarity in [0,1] (like difflib's ratio, via edit distance)
    if (!a.length && !b.length) return 1;
    const d = Array.from({length: a.length + 1}, (_, i) => [i]);
    for (let j = 1; j <= b.length; j++) d[0][j] = j;
    for (let i = 1; i <= a.length; i++) for (let j = 1; j <= b.length; j++)
      d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    return 1 - d[a.length][b.length] / Math.max(a.length, b.length);
  }
  function valueType(vals) {
    const s = vals.filter(v => !blank(v)).slice(0, 200).map(String);
    if (!s.length) return "empty";
    if (s.filter(x => isNum(num(x))).length / s.length > 0.8) return "number";
    if (s.filter(x => !Number.isNaN(Date.parse(x))).length / s.length > 0.8) return "date";
    return "text";
  }
  function combos(arr, k) {
    const out = [];
    const rec = (start, cur) => { if (cur.length === k) { out.push(cur.slice()); return; }
      for (let i = start; i < arr.length; i++) { cur.push(arr[i]); rec(i + 1, cur); cur.pop(); } };
    rec(0, []); return out;
  }
  function rankPct(values) {                     // pandas rank(pct=True), average ties
    const idx = values.map((v, i) => [v, i]).sort((a, b) => a[0] - b[0]);
    const r = new Array(values.length);
    for (let i = 0; i < idx.length;) {
      let j = i; while (j + 1 < idx.length && idx[j + 1][0] === idx[i][0]) j++;
      const avg = (i + j) / 2 + 1;
      for (let k = i; k <= j; k++) r[idx[k][1]] = avg / values.length * 100;
      i = j + 1;
    }
    return r;
  }
  const monthEnd = m => { const [y, mo] = m.split("-").map(Number); return new Date(Date.UTC(y, mo, 0)); };
  const prevMonths = (m, n) => { const [y, mo] = m.split("-").map(Number); const out = [];
    for (let k = n; k >= 1; k--) { const d = new Date(Date.UTC(y, mo - 1 - k, 1)); out.push(d.toISOString().slice(0, 7)); } return out; };
  function parseDate(v) {
    if (blank(v)) return null;
    if (isNum(v) && v > 20000 && v < 80000) return new Date(Date.UTC(1899, 11, 30) + v * DAY);   // Excel serial
    const t = Date.parse(String(v)); return Number.isNaN(t) ? null : new Date(t);
  }

  // ------------------------------------------------------------------ file reading (xlsx without libraries)
  async function inflate(bytes) {
    const ds = new DecompressionStream("deflate-raw");
    const stream = new Blob([bytes]).stream().pipeThrough(ds);
    return new Uint8Array(await new Response(stream).arrayBuffer());
  }
  async function unzip(buf) {
    const dv = new DataView(buf), u8 = new Uint8Array(buf), files = {};
    let eocd = -1;
    for (let i = buf.byteLength - 22; i >= Math.max(0, buf.byteLength - 70000); i--) if (dv.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
    if (eocd < 0) throw new Error("Not a valid .xlsx file");
    let off = dv.getUint32(eocd + 16, true);
    const n = dv.getUint16(eocd + 10, true), dec = new TextDecoder();
    for (let k = 0; k < n; k++) {
      const method = dv.getUint16(off + 10, true), csize = dv.getUint32(off + 20, true);
      const nlen = dv.getUint16(off + 28, true), xlen = dv.getUint16(off + 30, true), clen = dv.getUint16(off + 32, true);
      const lho = dv.getUint32(off + 42, true), name = dec.decode(u8.subarray(off + 46, off + 46 + nlen));
      const start = lho + 30 + dv.getUint16(lho + 26, true) + dv.getUint16(lho + 28, true);
      const data = u8.subarray(start, start + csize);
      files[name] = {method, data};
      off += 46 + nlen + xlen + clen;
    }
    return {async text(name) { const f = files[name]; if (!f) return null;
      return dec.decode(f.method === 8 ? await inflate(f.data) : f.data); }, names: Object.keys(files)};
  }
  const colIndex = ref => { const m = ref.match(/^[A-Z]+/)[0]; let n = 0; for (const ch of m) n = n * 26 + ch.charCodeAt(0) - 64; return n - 1; };
  async function readXlsx(buf) {
    const z = await unzip(buf), P = new DOMParser();
    const xml = s => P.parseFromString(s, "application/xml");
    const wb = xml(await z.text("xl/workbook.xml"));
    const rels = xml(await z.text("xl/_rels/workbook.xml.rels"));
    const target = {};
    for (const r of rels.getElementsByTagName("Relationship")) target[r.getAttribute("Id")] = r.getAttribute("Target");
    const ssText = await z.text("xl/sharedStrings.xml"), shared = [];
    if (ssText) for (const si of xml(ssText).getElementsByTagName("si"))
      shared.push([...si.getElementsByTagName("t")].map(t => t.textContent).join(""));
    const sheets = {}, order = [];
    for (const sh of wb.getElementsByTagName("sheet")) {
      const name = sh.getAttribute("name");
      const rid = sh.getAttribute("r:id") || sh.getAttributeNS("http://schemas.openxmlformats.org/officeDocument/2006/relationships", "id");
      let path = target[rid] || ""; path = path.startsWith("/") ? path.slice(1) : "xl/" + path.replace(/^\.?\//, "");
      const doc = xml(await z.text(path) || "<x/>"), grid = [];
      for (const row of doc.getElementsByTagName("row")) {
        const cells = [];
        for (const c of row.getElementsByTagName("c")) {
          const t = c.getAttribute("t"), vEl = c.getElementsByTagName("v")[0];
          let v = vEl ? vEl.textContent : null;
          if (t === "s") v = shared[+v];
          else if (t === "inlineStr") v = [...c.getElementsByTagName("t")].map(x => x.textContent).join("");
          else if (t === "b") v = v === "1";
          else if (t !== "str" && v !== null && v !== "") v = Number(v);
          cells[colIndex(c.getAttribute("r"))] = v;
        }
        grid.push(cells);
      }
      sheets[name] = gridToRows(grid); order.push(name);
    }
    return {sheets, order};
  }
  function gridToRows(grid) {
    if (!grid.length) return [];
    const head = (grid[0] || []).map(h => h === undefined || h === null ? "" : String(h).trim());
    return grid.slice(1).filter(r => r && r.some(v => !blank(v))).map(r => {
      const o = {}; head.forEach((h, i) => { if (h) o[h] = r[i] === undefined ? null : r[i]; }); return o; });
  }
  function readCsv(text) {
    const rows = []; let cur = [""], q = false;
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      if (q) { if (ch === '"' && text[i + 1] === '"') { cur[cur.length - 1] += '"'; i++; } else if (ch === '"') q = false; else cur[cur.length - 1] += ch; }
      else if (ch === '"') q = true; else if (ch === ",") cur.push(""); else if (ch === "\n") { rows.push(cur); cur = [""]; }
      else if (ch !== "\r") cur[cur.length - 1] += ch;
    }
    if (cur.length > 1 || cur[0] !== "") rows.push(cur);
    const grid = rows.map(r => r.map(v => v === "" ? null : (isNum(Number(v)) ? Number(v) : v)));
    return {sheets: {Sheet1: gridToRows(grid)}, order: ["Sheet1"]};
  }
  async function readFile(file) {
    const buf = await file.arrayBuffer();
    return file.name.toLowerCase().endsWith(".csv") ? readCsv(new TextDecoder().decode(buf)) : readXlsx(buf);
  }

  // ------------------------------------------------------------------ vendor recognition (vendor_registry.py)
  function makeRegistry(cfg, snapshot) {
    const seed = {};
    for (const [v, spec] of Object.entries(cfg.vendors)) {
      const cols = {};
      for (const [src, f] of Object.entries(spec.column_map)) (cols[f] = cols[f] || []).push(src);
      seed[v] = {columns: cols, updated_col: [spec.last_updated_col], platform_values: [], filename_tokens: [], months_seen: [], learned: []};
    }
    const data = JSON.parse(JSON.stringify(snapshot && Object.keys(snapshot).length ? snapshot : seed));
    for (const [v, s] of Object.entries(seed)) { data[v] = data[v] || s; for (const [f, n] of Object.entries(s.columns)) data[v].columns[f] = data[v].columns[f] || n; }
    return data;
  }
  const MONTHW = new Set(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec", "xlsx", "csv", "xls", "export", "data", "file", "copy", "final"]);
  const tokens = name => new Set(name.replace(/\.[^.]+$/, "").toLowerCase().split(/[^a-z]+/).filter(t => t.length > 2 && !MONTHW.has(t)));
  function isRequest(rows, sheetNames, cfg, reg) {
    const cols = new Set(Object.keys(rows[0] || {}).map(norm));
    if (!cols.has(norm(cfg.key))) return false;
    if (Object.values(reg).some(v => cols.has(norm(v.updated_col[0])))) return false;
    const plat = new Set([...cfg.platforms, ...Object.keys(cfg.platform_aliases || {})].map(norm));
    return sheetNames.includes("Request") || cols.has("platform") || [...cols].some(c => plat.has(c));
  }
  function scoreVendor(reg, v, rows, filename) {
    const r = reg[v], heads = new Set(Object.keys(rows[0] || {}).map(norm));
    const known = new Set([...Object.values(r.columns).flat(), ...r.updated_col].map(norm));
    const hit = [...known].filter(k => heads.has(k)).length;
    const parts = [0.5 * hit / Math.max(known.size, 1) + 0.5 * hit / Math.max(heads.size, 1)], w = [0.75];
    const platCol = Object.keys(rows[0] || {}).find(c => (r.columns.platform || []).map(norm).includes(norm(c)));
    if (r.platform_values.length && platCol) {
      const seen = new Set(rows.map(x => x[platCol]).filter(x => !blank(x)).map(String)), kv = new Set(r.platform_values);
      const inter = [...seen].filter(x => kv.has(x)).length, uni = new Set([...seen, ...kv]).size;
      parts.push(inter / Math.max(uni, 1)); w.push(0.15);
    }
    if (r.filename_tokens.length) { const t = tokens(filename); parts.push(r.filename_tokens.some(x => t.has(x)) ? 1 : 0); w.push(0.10); }
    return round(parts.reduce((a, p, i) => a + p * w[i], 0) / w.reduce((a, b) => a + b, 0), 3);
  }
  function identify(reg, rows, filename) {
    const scores = Object.fromEntries(Object.keys(reg).map(v => [v, scoreVendor(reg, v, rows, filename)]));
    const ranked = Object.entries(scores).sort((a, b) => b[1] - a[1]);
    const [best, second] = [ranked[0], ranked[1] || [null, 0]];
    const ok = best[1] >= 0.55 && best[1] - second[1] >= 0.15;
    return {vendor: ok ? best[0] : null, best: best[0], confidence: best[1], runner: second[0], runnerScore: second[1], scores};
  }
  function resolveColumns(reg, v, rows, cfg) {
    const r = reg[v], heads = Object.keys(rows[0] || {}), byNorm = Object.fromEntries(heads.map(h => [norm(h), h]));
    const wanted = {...r.columns, _last_updated: r.updated_col}, mapping = {}, claimed = new Set(), learned = [];
    for (const [f, names] of Object.entries(wanted)) { const col = names.map(n => byNorm[norm(n)]).find(Boolean); if (col) { mapping[col] = f; claimed.add(col); } }
    const rules = {...cfg.fields.creator, ...cfg.fields.channel, ...cfg.metric_inputs};
    const expected = f => f === "_last_updated" ? "date" : (["non_negative_int", "int"].includes((rules[f] || {}).rule) || f === "followers_prev") ? "number" : "text";
    const cands = [];
    for (const f of Object.keys(wanted).filter(f => !Object.values(mapping).includes(f))) {
      const refs = [...wanted[f].map(norm), norm(f)];
      for (const h of heads.filter(h => !claimed.has(h))) {
        const t = valueType(rows.map(x => x[h])), ns = Math.max(...refs.map(rf => ratio(norm(h), rf)));
        cands.push([0.65 * ns + 0.35 * (t === expected(f) ? 1 : t === "empty" ? 0.5 : 0), f, h]);
      }
    }
    for (const [sc, f, h] of cands.sort((a, b) => b[0] - a[0])) {
      if (Object.values(mapping).includes(f) || claimed.has(h) || sc < 0.6) continue;
      mapping[h] = f; claimed.add(h); learned.push({field: f, column: h, score: round(sc, 2), was: wanted[f]});
    }
    return {mapping, learned, missing: Object.keys(wanted).filter(f => !Object.values(mapping).includes(f))};
  }

  // ------------------------------------------------------------------ the run (pipeline.py + qa_checks.py)
  function newRun(cfg, inputs, month, memory, registry) {
    const R = {cfg, month, memory, registry, log: [], flags: [], nflag: 0, status: "new",
      runDate: monthEnd(month), sla: cfg.qa.freshness_sla_days, key: cfg.key, platforms: cfg.platforms,
      aliases: Object.fromEntries([...cfg.platforms.map(p => [p, p]), ...Object.entries(cfg.platform_aliases || {}).map(([k, v]) => [String(k).toLowerCase(), v])]),
      crF: cfg.fields.creator, chF: cfg.fields.channel, inputs: cfg.metric_inputs, metrics: cfg.metrics};
    R.fields = {...R.crF, ...R.chF};
    R.crReq = Object.keys(R.crF).filter(f => R.crF[f].required);
    R.chReq = [...Object.keys(R.chF).filter(f => R.chF[f].required), ...Object.keys(R.metrics).filter(m => R.metrics[m].required)];
    R.required = [...R.crReq, ...R.chReq];
    R.chValues = [...Object.keys(R.chF), ...Object.keys(R.metrics)];
    R.decide = (step, decision, reason) => R.log.push({step, decision, reason});
    R.normPlat = v => blank(v) ? null : (R.aliases[String(v).trim().toLowerCase()] || String(v).trim().toLowerCase());
    R.fresh = row => row._ts && (R.runDate - row._ts) / DAY <= R.sla;
    R.recognition = []; R.vendorInputs = {};
    // recognise inputs
    const reqs = [];
    for (const inp of inputs) {
      const first = inp.data.sheets[inp.data.order[0]] || [];
      const reqRows = inp.data.sheets.Request || first;
      if (isRequest(reqRows, inp.data.order, cfg, registry)) { reqs.push({inp, rows: reqRows}); R.recognition.push({file: inp.name, kind: "request", vendor: "", confidence: 1}); continue; }
      const id = identify(registry, first, inp.name), vendor = (inp.assign) || id.vendor;
      if (!vendor) { R.recognition.push({file: inp.name, kind: "unrecognised", vendor: "", confidence: id.confidence});
        R.decide("recognise", "flag", `couldn't tell which vendor sent ${inp.name} (closest ${id.best} ${Math.round(id.confidence * 100)}%); skipped`); continue; }
      const res = resolveColumns(registry, vendor, first, cfg);
      R.vendorInputs[vendor] = {inp, rows: first, res, confidence: id.confidence};
      R.recognition.push({file: inp.name, kind: "vendor", vendor, confidence: id.confidence, learned: res.learned, missing: res.missing});
      R.decide("recognise", vendor, `${inp.name} → ${vendor} (matched ${Math.round(id.confidence * 100)}%)`);
      for (const l of res.learned) R.decide("learn", "new column name", `${vendor} now calls ${l.field} '${l.column}'`);
    }
    if (!reqs.length) throw new Error("No requested creator list found among the inputs.");
    if (!Object.keys(R.vendorInputs).length) throw new Error("None of the files could be matched to a vendor.");
    loadRequest(R, reqs[0].rows);
    ingest(R);
    return R;
  }
  function loadRequest(R, rows) {
    const key = R.key, pairs = new Map();
    const cols = Object.keys(rows[0] || {});
    const platCol = cols.find(c => c.toLowerCase() === "platform");
    for (const r of rows) {
      const cid = blank(r[key]) ? null : String(r[key]).trim(); if (!cid) continue;
      if (platCol) { const p = R.normPlat(r[platCol]); if (R.platforms.includes(p)) pairs.set(pairKey(cid, p), [cid, p]); }
      else for (const c of cols) { const p = R.normPlat(c); if (R.platforms.includes(p) && !blank(r[c]) && !NO.has(String(r[c]).trim().toLowerCase())) pairs.set(pairKey(cid, p), [cid, p]); }
    }
    if (!pairs.size) throw new Error("The request list has no channels marked. Put Y under the channels you need.");
    R.reqPairs = [...pairs.values()].sort((a, b) => (a[0] + a[1]).localeCompare(b[0] + b[1]));
    R.reqSet = new Set(R.reqPairs.map(([c, p]) => pairKey(c, p)));
    R.reqCreators = [...new Set(R.reqPairs.map(x => x[0]))];
    R.reqMix = Object.fromEntries(R.platforms.map(p => [p, R.reqPairs.filter(x => x[1] === p).length]));
    const per = {}; for (const [c] of R.reqPairs) per[c] = (per[c] || 0) + 1;
    R.shape = {}; for (const n of Object.values(per)) R.shape[n] = (R.shape[n] || 0) + 1;
    R.decide("request", "accept", `${R.reqCreators.length} creators, ${R.reqPairs.length} channels requested`);
  }
  function ingest(R) {
    R.vendorRows = {};
    for (const [v, {rows, res}] of Object.entries(R.vendorInputs)) {
      const spec = R.cfg.vendors[v], tr = (R.cfg.transforms || {})[v] || {}, prec = {...(spec.precision || {})};
      const out = [];
      for (const raw of rows) {
        const r = {};
        for (const [col, f] of Object.entries(res.mapping)) r[f] = raw[col] === undefined ? null : raw[col];
        r._ts = parseDate(r._last_updated);
        r[R.key] = blank(r[R.key]) ? null : String(r[R.key]).trim();
        if (!r[R.key]) continue;
        r.platform = R.normPlat(r.platform);
        for (const [col, t] of Object.entries(tr)) {
          if (t === "uppercase" && typeof r[col] === "string") r[col] = r[col].toUpperCase();
          else if (t === "lowercase" && typeof r[col] === "string") r[col] = r[col].toLowerCase();
          else if (t === "country_name_to_iso2" && typeof r[col] === "string") r[col] = COUNTRY[r[col].trim().toLowerCase()] || r[col];
          else if (t && t.multiply) { const x = num(r[col]); r[col] = isNum(x) ? Math.round(x * t.multiply) : null; }
        }
        for (const [col, expr] of Object.entries(spec.derive || {})) {
          const {fn} = compile(expr); const x = fn(n => num(r[n])); r[col] = isNum(x) ? x : null;
        }
        const lk = r.likes_90d;
        r.likes_hidden = typeof lk === "string" && lk.trim().toLowerCase() === "hidden";
        if (r.likes_hidden) r.likes_90d = null;
        for (const f of [...Object.keys(R.fields), ...Object.keys(R.inputs)]) if (r[f] === undefined) r[f] = null;
        r._err = {};
        for (const [col, e] of Object.entries(prec)) r._err[col] = e;
        for (const [col, expr] of Object.entries(spec.derive || {})) {
          const names = compile(expr).names; if (names.some(n => prec[n])) r._err[col] = names.reduce((a, n) => a + (prec[n] || 0), 0);
        }
        r._vendor = v;
        out.push(r);
      }
      R.vendorRows[v] = out;
      R.missingInputs = R.missingInputs || {};
      R.missingInputs[v] = Object.keys(R.inputs).filter(f => !Object.values(res.mapping).includes(f) && !(spec.derive || {})[f]);
    }
  }
  function clean(R, row) {
    const r = {...row};
    for (const [f, s] of Object.entries({...R.fields, ...R.inputs})) if (!isValid(r[f], s.rule)) r[f] = null;
    return r;
  }
  function addMetrics(R, r) {
    for (const [m, spec] of Object.entries(R.metrics)) {
      const expr = (spec.by_platform || {})[r.platform] || spec.formula, {names, fn} = compile(expr);
      let v = fn(n => num(r[n])); if (!isNum(v)) v = NaN;
      const miss = names.filter(n => blank(r[n]) || !isNum(num(r[n])));
      let d = miss.length ? "missing " + miss.join(", ") : "ok";
      if (spec.needs_visible_likes && r.likes_hidden) d = "likes hidden";
      const [lo, hi] = spec.bounds || [-Infinity, Infinity];
      if (d === "ok" && isNum(v) && (v < lo || v > hi)) d = "implausible value";
      if (d === "ok" && isNum(v)) {
        let rel = 0; for (const n of names) if (r._err && r._err[n]) rel += r._err[n] / Math.abs(num(r[n]) || NaN);
        if (!(rel <= (R.cfg.qa.max_rounding_error ?? 0.05))) d = "imprecise (rounded counts)";
      }
      r[m] = d === "ok" ? v : null; r["_diag_" + m] = d;
    }
    return r;
  }
  function prepare(R, v, respect = true) {
    let rows = R.vendorRows[v].slice().sort((a, b) => (a._ts || 0) - (b._ts || 0));
    if (respect) rows = rows.filter(r => !R.excluded.has(v + "|" + pairKey(r[R.key], r.platform)));
    if (!R.cfg.waterfall.allow_stale_values) rows = rows.filter(R.fresh);
    rows = rows.map(r => addMetrics(R, clean(R, r)));
    const ch = new Map(), cr = new Map();
    for (const r of rows) {
      ch.set(pairKey(r[R.key], r.platform), r);
      const c = cr.get(r[R.key]) || {}; for (const f of Object.keys(R.crF)) if (!blank(r[f])) c[f] = r[f]; cr.set(r[R.key], c);
    }
    return {ch, cr};
  }
  function addFlag(R, cid, plat, field, code, extra = {}) {
    const sev = R.cfg.qa_rules.severity[code] || "YELLOW";
    const f = {id: "Q" + String(++R.nflag).padStart(5, "0"), creator_id: cid, platform: plat, field, code, severity: sev,
      values: {}, discrepancy: null, source_used: "", explanation: "", dependents: [], status: sev === "RED" ? "open" : "auto",
      decision: "", ...extra};
    R.flags.push(f); return f;
  }
  const normHandle = v => { if (blank(v)) return null; let s = String(v).trim().toLowerCase(); if (s.includes("/")) s = s.split(/[/?#]/).filter(Boolean).pop(); return s.replace(/^@/, ""); };

  function identityCheck(R) {
    R.excluded = new Set(); R.blockedPairs = new Set();
    const seen = new Map();
    for (const [v, rows] of Object.entries(R.vendorRows)) for (const r of rows) {
      const k = pairKey(r[R.key], r.platform); if (!R.reqSet.has(k)) continue;
      const h = normHandle(r.handle); if (!h) continue;
      (seen.get(k) || seen.set(k, {}).get(k))[v] = h;
    }
    for (const [k, hs] of seen) {
      const vals = Object.values(hs); if (new Set(vals).size <= 1) continue;
      const counts = {}; vals.forEach(h => counts[h] = (counts[h] || 0) + 1);
      const [top, nTop] = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
      const [cid, plat] = k.split("|");
      if (R.cfg.qa_rules.identity.majority_resolves && nTop >= 2 && nTop > vals.length / 2) {
        const odd = Object.keys(hs).filter(v => hs[v] !== top); odd.forEach(v => R.excluded.add(v + "|" + k));
        addFlag(R, cid, plat, "identity", "IDENTITY_CONFLICT_RESOLVED", {values: {...hs}, source_used: Object.keys(hs).filter(v => hs[v] === top).join(", "),
          explanation: `${nTop} vendors agree the account is @${top}; ${odd.join(", ")} reported ${odd.map(v => "@" + hs[v]).join(", ")} and was not used for this channel.`});
      } else {
        R.blockedPairs.add(k); Object.keys(hs).forEach(v => R.excluded.add(v + "|" + k));
        addFlag(R, cid, plat, "identity", "IDENTITY_MATCH_UNCERTAIN", {values: {...hs},
          explanation: "Vendors report different accounts for this creator-channel (" + Object.entries(hs).map(([v, h]) => `${v}: @${h}`).join("; ") + "), with no majority. None of their data is used until reviewed."});
      }
    }
  }
  function differs(a, b, rule) { if (rule.mode === "absolute") return Math.abs(a - b); const big = Math.max(Math.abs(a), Math.abs(b)); return big === 0 ? 0 : Math.abs(a - b) / big; }
  function dependentsOf(R, fld) {
    const re = new RegExp("\\b" + fld + "\\b");
    return Object.entries(R.metrics).filter(([m, s]) => [s.formula, ...Object.values(s.by_platform || {})].some(f => re.test(f))).map(([m]) => m);
  }
  function consensus(vals, rule) {
    const names = Object.keys(vals);
    let spread = 0; for (const [a, b] of combos(names, 2)) spread = Math.max(spread, differs(vals[a], vals[b], rule));
    for (let k = names.length; k > 1; k--) for (const c of combos(names, k))
      if (combos(c, 2).every(([a, b]) => differs(vals[a], vals[b], rule) <= rule.threshold)) return {group: c, spread};
    return {group: [], spread};
  }
  function discrepancyCheck(R, apply = true, onlyPairs = null) {
    const rules = R.cfg.qa_rules.discrepancy, tierOf = Object.fromEntries((R.tiers || []).map((v, i) => [v, i + 1]));
    R.outlierExcl = R.outlierExcl || {};
    const cons = Object.fromEntries(Object.keys(R.vendorRows).map(v => [v, [0, 0]]));
    const vendors = Object.keys(R.prepared);
    for (const [fld, rule] of Object.entries(rules.fields)) {
      const keys = new Set(); vendors.forEach(v => R.prepared[v].ch.forEach((_, k) => keys.add(k)));
      for (const k of keys) {
        if (onlyPairs && !onlyPairs.has(k)) continue;
        const dropped = apply ? ((R.outlierExcl[k] || {})[fld] || new Set()) : new Set();
        const vals = {};
        for (const v of vendors) { const r = R.prepared[v].ch.get(k); if (r && isNum(num(r[fld])) && !blank(r[fld]) && !dropped.has(v)) vals[v] = num(r[fld]); }
        const out = apply && R.out.ch.get(k);
        if (apply && dropped.size && out && dropped.has(out[fld + "__source"])) {
          const alt = Object.keys(vals).sort((a, b) => (tierOf[a] || 9) - (tierOf[b] || 9));
          out[fld] = alt.length ? vals[alt[0]] : null; out[fld + "__source"] = alt.length ? alt[0] : `EXCLUDED: computed from an outlier`;
        }
        const names = Object.keys(vals); if (names.length < 2) continue;
        const {group, spread} = consensus(vals, rule);
        for (const v of names) { cons[v][1]++; if (names.some(o => o !== v && differs(vals[v], vals[o], rule) <= rule.threshold)) cons[v][0]++; }
        if (!apply || group.length === names.length || !out) continue;
        if (R.blockedPairs.has(k) || ((R.blockedFields[k] || {})[fld])) continue;
        const [cid, plat] = k.split("|"), abs = rule.mode === "absolute";
        const fmt = x => fld === "follower_count" ? Math.round(x).toLocaleString("en-US") : x.toFixed(3);
        const shown = Object.entries(vals).sort((a, b) => (tierOf[a[0]] || 9) - (tierOf[b[0]] || 9)).map(([v, x]) => `${v} ${fmt(x)}`).join("; ");
        const thr = abs ? `${Math.round(rule.threshold * 100)} pts` : `${Math.round(rule.threshold * 100)}%`;
        const spreadTxt = abs ? `${(spread * 100).toFixed(1)} pts` : `${Math.round(spread * 100)}%`;
        if (rules.majority_resolves && group.length >= 2 && group.length > names.length / 2) {
          const use = group.slice().sort((a, b) => (tierOf[a] || 9) - (tierOf[b] || 9))[0], outliers = names.filter(v => !group.includes(v));
          if (outliers.includes(out[fld + "__source"]) || blank(out[fld])) { out[fld] = R.prepared[use].ch.get(k)[fld]; out[fld + "__source"] = use; }
          for (const dep of dependentsOf(R, fld)) { R.outlierExcl[k] = R.outlierExcl[k] || {}; R.outlierExcl[k][dep] = new Set([...(R.outlierExcl[k][dep] || []), ...outliers]); }
          addFlag(R, cid, plat, fld, "OUTLIER_SOURCE_EXCLUDED", {values: vals, discrepancy: round(spread), source_used: use,
            explanation: `${group.join(", ")} agree within ${thr}; ${outliers.join(", ")} differ (${shown}). Used ${use} (highest tier among the agreeing vendors)` +
              ((R.tiers || [])[0] && outliers.includes(R.tiers[0]) ? `, not Tier 1 ${R.tiers[0]}, because it's the outlier.` : ", not the outlier.")});
        } else {
          const deps = rules.block_dependents ? dependentsOf(R, fld) : [];
          const f = addFlag(R, cid, plat, fld, "CROSS_VENDOR_DISCREPANCY", {values: vals, discrepancy: round(spread), source_used: String(out[fld + "__source"]), dependents: deps,
            explanation: `Vendors disagree by ${spreadTxt} (threshold ${thr}): ${shown}. No credible majority, so the value is held back rather than defaulting to the highest tier` + (deps.length ? `; ${deps.join(", ")} (computed from it) held back too.` : ".")});
          for (const col of [fld, ...deps]) { out[col] = null; out[col + "__source"] = "BLOCKED: " + f.id; R.blockedFields[k] = R.blockedFields[k] || {}; R.blockedFields[k][col] = f.id; }
        }
      }
    }
    return Object.fromEntries(Object.entries(cons).map(([v, [a, n]]) => [v, n ? round(a / n) : 1]));
  }
  function vendorQA(R) {
    const w = R.cfg.qa.weights, prof = {};
    const byP = {}; R.reqPairs.forEach(([, p]) => byP[p] = (byP[p] || 0) + 1);
    const reqCr = new Set(R.reqCreators);
    for (const [v, rows] of Object.entries(R.vendorRows)) {
      const inScope = rows.filter(r => R.reqSet.has(pairKey(r[R.key], r.platform)));
      const relCr = rows.filter(r => reqCr.has(r[R.key]));
      const have = new Set(inScope.map(r => pairKey(r[R.key], r.platform)));
      const freshRows = inScope.filter(R.fresh);
      const haveFresh = new Set(freshRows.map(r => pairKey(r[R.key], r.platform)));
      const scored = inScope.map(r => addMetrics(R, clean(R, r)));
      const nn = (arr, f) => arr.filter(r => !blank(r[f])).length;
      const fc = {};
      for (const f of Object.keys(R.crF)) fc[f] = relCr.length ? round(nn(relCr, f) / relCr.length) : 0;
      for (const f of Object.keys(R.chF)) fc[f] = inScope.length ? round(nn(inScope, f) / inScope.length) : 0;
      for (const m of Object.keys(R.metrics)) fc[m] = scored.length ? round(scored.filter(r => isNum(r[m])).length / scored.length) : 0;
      let vh = 0, nTot = 0;
      for (const [f, s] of Object.entries({...R.chF, ...R.inputs})) { vh += inScope.filter(r => isValid(r[f], s.rule)).length; nTot += nn(inScope, f); }
      for (const [f, s] of Object.entries(R.crF)) { vh += relCr.filter(r => isValid(r[f], s.rule)).length; nTot += nn(relCr, f); }
      const impl = scored.reduce((a, r) => a + Object.keys(R.metrics).filter(m => r["_diag_" + m] === "implausible value").length, 0);
      const pc = {}; for (const p of Object.keys(byP)) pc[p] = round([...haveFresh].filter(k => k.endsWith("|" + p)).length / byP[p]);
      const P = {name: v, rows: rows.length, rows_not_needed: rows.length - inScope.length,
        coverage: round(have.size / R.reqPairs.length), usable_coverage: round(haveFresh.size / R.reqPairs.length),
        completeness: round(R.required.reduce((a, f) => a + fc[f], 0) / R.required.length),
        freshness: inScope.length ? round(freshRows.length / inScope.length) : 0, validity: nTot ? round((vh - impl) / nTot) : 0,
        consistency: R.consistency[v] ?? 1, field_completeness: fc, platform_coverage: pc, implausible_values: impl};
      P.current_score = round(Object.entries(w).reduce((a, [k, wt]) => a + (P[k] || 0) * wt, 0));
      const rel = reliability(R, v);
      Object.assign(P, {history_score: rel.score, history_months: rel.months, qa_avg_3m: rel.qa_avg, review_accuracy: rel.acc, disputes_reviewed: rel.disputes});
      const hw = R.cfg.qa.history_weight ?? 0.15;
      P.score = rel.score === null ? P.current_score : round((1 - hw) * P.current_score + hw * rel.score);
      prof[v] = P;
      R.decide("history", rel.score === null ? "no history" : "blend", rel.score === null ? `${v}: first month on record (${P.current_score.toFixed(2)})`
        : `${v}: this month ${P.current_score.toFixed(2)}; ${rel.months}-month reliability ${rel.score.toFixed(2)} → blended ${P.score.toFixed(2)}`);
    }
    R.profiles = prof;
    const floor = R.cfg.qa.min_score_to_use;
    let t = 1;
    for (const P of Object.values(prof).sort((a, b) => b.score - a.score)) {
      if (P.score < floor) { P.tier = null; P.excluded_reason = `score ${P.score.toFixed(2)} below floor ${floor}`; continue; }
      P.tier = t++; R.decide("tiering", `tier ${P.tier}`, `${P.name}: blended score ${P.score.toFixed(2)}`);
    }
    R.tiers = Object.values(prof).filter(P => P.tier).sort((a, b) => a.tier - b.tier).map(P => P.name);
  }
  function reliability(R, v) {
    const rc = R.cfg.qa.reliability || {}, n = rc.window_months || 3;
    const h = R.memory.vendor_history.filter(r => r.vendor === v && r.month < R.month).sort((a, b) => a.month < b.month ? -1 : 1).slice(-n);
    if (!h.length) return {score: null, months: 0, qa_avg: null, acc: null, disputes: 0};
    const qa = h.reduce((a, r) => a + Number(r.current_score), 0) / h.length, ms = new Set(h.map(r => r.month));
    let kept = 0, inv = 0;
    for (const r of R.memory.review_audit.filter(a => ms.has(String(a.month)))) {
      let vals; try { vals = typeof r.original_values === "string" ? JSON.parse(r.original_values) : r.original_values; } catch { continue; }
      if (!vals || !(v in vals) || ["EXCLUDE", "REJECT_MATCH", "EXCLUDED_UNRESOLVED"].includes(r.decision)) continue;
      inv++;
      const src = String(r.final_source || "");
      if (r.decision === "CONFIRM_MATCH" || src.split(", ").includes(v)) kept++;
      else if (r.decision === "MANUAL_VALUE" && Math.abs(num(r.manual_value) - num(vals[v])) / Math.max(Math.abs(num(r.manual_value)), 1e-9) <= 0.05) kept++;
    }
    const acc = inv ? kept / inv : null;
    const score = acc === null ? qa : (rc.qa_score_weight ?? 0.7) * qa + (rc.review_accuracy_weight ?? 0.3) * acc;
    return {score: round(score), months: h.length, qa_avg: round(qa), acc: acc === null ? null : round(acc), disputes: inv};
  }
  const filled = (row, f) => !blank(row[f]) || String(row[f + "__source"] || "").startsWith("n/a");
  function assess(R) {
    const cr = R.out.cr, ch = R.out.ch, fill = {};
    for (const f of Object.keys(R.crF)) fill[f] = round([...cr.values()].filter(r => !blank(r[f])).length / Math.max(cr.size, 1));
    for (const f of R.chValues) fill[f] = round([...ch.values()].filter(r => filled(r, f)).length / Math.max(ch.size, 1));
    const chOk = new Map([...ch].map(([k, r]) => [k, R.chReq.every(f => filled(r, f))]));
    const byP = {}; for (const p of R.platforms) { const ks = [...chOk].filter(([k]) => k.endsWith("|" + p)); if (ks.length) byP[p] = round(ks.filter(x => x[1]).length / ks.length); }
    const okCr = c => R.crReq.every(f => !blank(cr.get(c)[f])) && R.reqPairs.filter(x => x[0] === c).every(([, p]) => chOk.get(pairKey(c, p)));
    const n = R.reqCreators.filter(okCr).length;
    const perN = {}; const counts = {}; R.reqPairs.forEach(([c]) => counts[c] = (counts[c] || 0) + 1);
    for (const c of R.reqCreators) { const k = counts[c]; perN[k] = perN[k] || [0, 0]; perN[k][1]++; if (okCr(c)) perN[k][0]++; }
    return {fill, channels_complete: round([...chOk.values()].filter(Boolean).length / Math.max(chOk.size, 1)), by_platform: byP,
      creators_complete: round(n / R.reqCreators.length), by_n: Object.fromEntries(Object.entries(perN).map(([k, [a, b]]) => [k, round(a / b)])),
      open: [...cr.values()].reduce((a, r) => a + Object.keys(R.crF).filter(f => blank(r[f])).length, 0) + [...ch.values()].reduce((a, r) => a + R.chValues.filter(f => !filled(r, f)).length, 0)};
  }
  function waterfall(R) {
    const wf = R.cfg.waterfall;
    R.out = {cr: new Map(R.reqCreators.map(c => [c, {}])), ch: new Map(R.reqPairs.map(([c, p]) => [pairKey(c, p), {}]))};
    R.tierResults = [];
    let st = assess(R);
    R.tiers.forEach((v, i) => {
      const short = R.required.filter(f => st.fill[f] < wf.required_field_target);
      if (i > 0 && !short.length) return;
      const {cr, ch} = R.prepared[v];
      let gain = 0;
      for (const [c, row] of R.out.cr) { const s = cr.get(c); if (s) for (const f of Object.keys(R.crF)) if (blank(row[f]) && !blank(s[f])) gain++; }
      for (const [k, row] of R.out.ch) { const s = ch.get(k); if (s) for (const f of R.chValues) if (!filled(row, f) && !blank(s[f])) gain++; }
      if (i > 0 && gain / Math.max(st.open, 1) < wf.min_expected_gain) return;
      for (const [c, row] of R.out.cr) { const s = cr.get(c); if (s) for (const f of Object.keys(R.crF)) if (blank(row[f]) && !blank(s[f])) { row[f] = s[f]; row[f + "__source"] = v; } }
      for (const [k, row] of R.out.ch) { const s = ch.get(k); if (!s) continue;
        for (const f of R.chValues) if (!filled(row, f) && !blank(s[f])) { row[f] = s[f]; row[f + "__source"] = v; }
        for (const m of Object.keys(R.metrics)) if (!filled(row, m) && s["_diag_" + m] === "likes hidden") row[m + "__source"] = `n/a (likes hidden, ${v})`; }
      const before = st; st = assess(R);
      R.tierResults.push({tier: i + 1, vendor: v, before, after: st});
      R.decide(`tier ${i + 1}`, `use ${v}`, `${Math.round(st.creators_complete * 100)}% of creators complete after ${v}`);
    });
  }
  function fallbackCheck(R) {
    const t1 = R.tiers[0]; if (!t1) return;
    const raw = R.vendorRows[t1], has = new Set(raw.map(r => pairKey(r[R.key], r.platform))), fresh = new Set(raw.filter(R.fresh).map(r => pairKey(r[R.key], r.platform)));
    for (const [k, r] of R.out.ch) {
      const used = {};
      for (const f of R.cfg.qa_rules.fallback.warn_fields) { const s = r[f + "__source"]; if (typeof s === "string" && s !== t1 && !/^(n\/a|BLOCKED|EXCLUDED)/.test(s)) used[f] = s; }
      if (!Object.keys(used).length) continue;
      const t1row = R.prepared[t1].ch.get(k);
      const why = R.excluded.has(t1 + "|" + k) ? `${t1}'s record was excluded by the identity check` : !has.has(k) ? `${t1} has no record for this channel`
        : !fresh.has(k) ? `${t1}'s record is stale` : `${t1}'s record lacks a valid value for ` + Object.keys(used).filter(f => !t1row || blank(t1row[f])).join(", ");
      const srcs = [...new Set(Object.values(used))].sort().join(", "), [cid, plat] = k.split("|");
      addFlag(R, cid, plat, Object.keys(used).join(", "), "PRIMARY_SOURCE_MISSING", {values: used, source_used: srcs, explanation: `${why}; filled from ${srcs} (fallback).`});
    }
  }
  function historyCheck(R) {
    R.flags = R.flags.filter(f => f.code !== "HISTORICAL_ANOMALY");
    const prev = {};
    for (const r of R.memory.creator_history) if (r.platform !== "all" && String(r.month) < R.month) { const k = pairKey(r.creator_id, r.platform); if (!prev[k] || prev[k].month < r.month) prev[k] = r; }
    for (const [k, r] of R.out.ch) {
      const last = prev[k]; if (!last) continue;
      for (const [fld, rule] of Object.entries(R.cfg.qa_rules.history.fields)) {
        const cur = num(r[fld]), before = num(last[fld]);
        if (!isNum(cur) || !isNum(before) || before <= 0) continue;
        const change = cur / before - 1;
        if (change > rule.max_increase || change < -rule.max_decrease) {
          const [cid, plat] = k.split("|"), f = x => fld === "follower_count" ? Math.round(x).toLocaleString("en-US") : x.toFixed(2);
          addFlag(R, cid, plat, fld, "HISTORICAL_ANOMALY", {values: {previous_month: last.month, previous: before, current: cur}, discrepancy: round(change), source_used: String(r[fld + "__source"]),
            explanation: `${fld} moved ${change >= 0 ? "+" : ""}${Math.round(change * 100)}% vs ${last.month} (${f(before)} → ${f(cur)}). Kept: big swings can be genuine (viral content, events).`});
        }
      }
    }
  }
  function process(R) {                          // stage 1: everything automated, up to the review gate
    identityCheck(R);
    R.prepared = Object.fromEntries(Object.keys(R.vendorRows).map(v => [v, prepare(R, v)]));
    R.blockedFields = {};
    R.consistency = discrepancyCheck(R, false);
    vendorQA(R);
    waterfall(R);
    for (const k of R.blockedPairs) { const f = R.flags.find(x => x.code === "IDENTITY_MATCH_UNCERTAIN" && pairKey(x.creator_id, x.platform) === k);
      const row = R.out.ch.get(k); for (const col of R.chValues) { row[col] = null; row[col + "__source"] = "BLOCKED: " + (f ? f.id : ""); (R.blockedFields[k] = R.blockedFields[k] || {})[col] = f && f.id; } }
    discrepancyCheck(R, true);
    fallbackCheck(R);
    historyCheck(R);
    R.final = assess(R);
    R.status = openRed(R).length && R.cfg.review.leaderboard_gate === "strict" ? "awaiting_review" : "ready";
    return R;
  }
  const openRed = R => R.flags.filter(f => f.severity === "RED" && f.status === "open");
  function creatorStatus(R) {
    const rank = {GREEN: 0, YELLOW: 1, RED: 2}, out = {};
    for (const f of R.flags) { const s = f.severity === "RED" && f.status === "resolved" ? "YELLOW" : f.severity; if (rank[s] > rank[out[f.creator_id] || "GREEN"]) out[f.creator_id] = s; }
    return out;
  }

  // ------------------------------------------------------------------ human review (review.py)
  function refillPair(R, k, vendors) {
    const row = R.out.ch.get(k); for (const c of R.chValues) { row[c] = null; delete row[c + "__source"]; }
    for (const v of vendors) { const s = R.prepared[v].ch.get(k); if (!s) continue;
      for (const c of R.chValues) if (blank(row[c]) && !blank(s[c])) { row[c] = s[c]; row[c + "__source"] = v; }
      for (const m of Object.keys(R.metrics)) if (!row[m + "__source"] && s["_diag_" + m] === "likes hidden") row[m + "__source"] = `n/a (likes hidden, ${v})`; }
  }
  function applyDecisions(R, decisions, reviewer) {
    const allowed = R.cfg.review.decisions, problems = [], vendors = Object.keys(R.cfg.vendors), now = new Date().toISOString().replace("T", " ").slice(0, 19);
    R.audit = R.audit || [];
    for (const d of decisions) {
      const f = R.flags.find(x => x.id === d.id); if (!f || f.status !== "open" || !d.decision) continue;
      const dec = d.decision; if (!(allowed[f.code] || []).includes(dec)) { problems.push(`${f.id}: ${dec} isn't allowed for ${f.code}`); continue; }
      const k = pairKey(f.creator_id, f.platform), vSel = vendors.find(v => dec === "SELECT_" + v.toUpperCase());
      const cols = [f.field, ...f.dependents]; let finalSrc, finalVal;
      if (f.code === "IDENTITY_MATCH_UNCERTAIN") {
        if (vSel && !(vSel in f.values)) { problems.push(`${f.id}: ${vSel} has no record for this channel`); continue; }
        if (dec === "CONFIRM_MATCH" || vSel) {
          const keep = R.tiers.filter(v => v in f.values && (dec === "CONFIRM_MATCH" || v === vSel));
          for (const v of Object.keys(f.values)) { R.excluded.delete(v + "|" + k); if (!keep.includes(v)) R.excluded.add(v + "|" + k); }
          R.blockedPairs.delete(k); delete R.blockedFields[k];
          for (const v of Object.keys(f.values)) R.prepared[v] = prepare(R, v);
          refillPair(R, k, keep);
          if (dec === "CONFIRM_MATCH") discrepancyCheck(R, true, new Set([k]));
          finalSrc = keep.join(", "); finalVal = keep.length ? "@" + f.values[keep[0]] : null;
        } else { const row = R.out.ch.get(k); for (const c of R.chValues) row[c + "__source"] = "EXCLUDED: " + f.id; finalSrc = "excluded"; finalVal = null; }
      } else {
        const rule = R.cfg.qa_rules.discrepancy.fields[f.field], row = R.out.ch.get(k);
        if (dec === "MANUAL_VALUE" && !isNum(num(d.manual))) { problems.push(`${f.id}: MANUAL_VALUE needs a number`); continue; }
        if (vSel && !(vSel in f.values)) { problems.push(`${f.id}: ${vSel} didn't report ${f.field}`); continue; }
        if (dec === "EXCLUDE") { for (const c of cols) { row[c] = null; row[c + "__source"] = "EXCLUDED: " + f.id; } finalSrc = "excluded"; finalVal = null; }
        else {
          const target = dec === "MANUAL_VALUE" ? num(d.manual) : f.values[vSel];
          row[f.field] = f.field === "follower_count" ? Math.round(target) : target; row[f.field + "__source"] = dec === "MANUAL_VALUE" ? "manual (review)" : vSel;
          const donors = [...(vSel ? [vSel] : []), ...Object.keys(f.values).filter(v => differs(f.values[v], target, rule) <= rule.threshold).sort((a, b) => Math.abs(f.values[a] - target) - Math.abs(f.values[b] - target))];
          for (const c of f.dependents) { row[c] = null; row[c + "__source"] = `EXCLUDED: ${f.id} (no consistent source)`;
            for (const v of donors) { const s = R.prepared[v].ch.get(k); if (s && !blank(s[c])) { row[c] = s[c]; row[c + "__source"] = v; break; } } }
          finalSrc = row[f.field + "__source"]; finalVal = target;
        }
        if (R.blockedFields[k]) cols.forEach(c => delete R.blockedFields[k][c]);
      }
      Object.assign(f, {status: "resolved", decision: dec, manual_value: dec === "MANUAL_VALUE" ? num(d.manual) : null, final_value: finalVal, final_source: String(finalSrc), reviewer: reviewer || "", reviewed_at: now, note: d.note || ""});
      R.audit.push({month: R.month, reviewed_at: now, review_id: f.id, creator_id: f.creator_id, platform: f.platform, fields: cols.join(", "), code: f.code,
        original_values: JSON.stringify(f.values), decision: dec, manual_value: f.manual_value, final_value: finalVal, final_source: String(finalSrc), reviewer: reviewer || "", note: d.note || ""});
    }
    R.final = assess(R);
    R.status = openRed(R).length && R.cfg.review.leaderboard_gate === "strict" ? "awaiting_review" : "ready";
    R.decide("review", `${decisions.filter(x => x.decision).length} decision(s)`, `${openRed(R).length} blocked item(s) still open`);
    return problems;
  }

  // ------------------------------------------------------------------ finalize → leaderboard data (same shape the page renders)
  function sizeBand(R, f) { if (!isNum(num(f))) return null; const b = Object.entries(R.cfg.size_bands).sort((a, b) => a[1] - b[1]); return b.filter(([, lo]) => num(f) >= lo).pop()[0]; }
  function finalize(R, metricsMeta) {
    if (openRed(R).length && R.cfg.review.leaderboard_gate === "strict") throw new Error("Blocked items are still open.");
    historyCheck(R);
    const minPeers = R.cfg.min_peers_for_band || 8, M = Object.keys(R.metrics);
    for (const [k, r] of R.out.ch) r.size_band = sizeBand(R, r.follower_count);
    for (const m of M) {
      for (const p of R.platforms) {
        const ks = [...R.out.ch].filter(([k, r]) => k.endsWith("|" + p) && isNum(num(r[m])));
        const setPct = (list, label) => { const pc = rankPct(list.map(([, r]) => num(r[m]))); list.forEach(([, r], i) => { r[m + "__pct"] = Math.round(pc[i] * 10) / 10; r[m + "__peers"] = label; }); };
        if (R.metrics[m].compare_within_size_band) {
          const bands = {}; ks.forEach(x => { const b = x[1].size_band; if (b) (bands[b] = bands[b] || []).push(x); });
          const done = new Set();
          for (const [b, list] of Object.entries(bands)) if (list.length >= minPeers) { setPct(list, `${p} · ${b}`); list.forEach(([k]) => done.add(k)); }
          const left = ks.filter(([k]) => !done.has(k));
          if (left.length) { const all = rankPct(ks.map(([, r]) => num(r[m]))); ks.forEach(([k, r], i) => { if (!done.has(k)) { r[m + "__pct"] = Math.round(all[i] * 10) / 10; r[m + "__peers"] = `${p} (band too small)`; } }); }
        } else if (ks.length) setPct(ks, p);
      }
    }
    const tierOf = Object.fromEntries(R.tiers.map((v, i) => [v, i + 1])), conf = {1: "High", 2: "Medium", 3: "Low"};
    const pillar = Object.fromEntries(M.map(m => [m, R.metrics[m].pillar]));
    const reqBy = {}; R.reqPairs.forEach(([c, p]) => (reqBy[c] = reqBy[c] || []).push(p));
    const scores = {};
    for (const c of R.reqCreators) {
      const s = {}; for (const m of M) { const v = reqBy[c].map(p => R.out.ch.get(pairKey(c, p))[m + "__pct"]).filter(isNum); s[m] = v.length ? Math.round(v.reduce((a, b) => a + b, 0) / v.length * 10) / 10 : null; }
      const best = M.reduce((a, m) => (s[m] ?? -1) > (s[a] ?? -1) ? m : a, M[0]);
      s.role = M.some(m => s[m] !== null) ? pillar[best] : null; scores[c] = s;
    }
    const chOk = k => R.chReq.every(f => filled(R.out.ch.get(k), f));
    const realSrc = r => ["follower_count", ...M].map(f => r[f + "__source"]).filter(s => s && !String(s).startsWith("n/a"));
    const worst = r => Math.max(...realSrc(r).map(s => tierOf[s] || 3), 1);
    const complete = R.reqCreators.filter(c => R.crReq.every(f => !blank(R.out.cr.get(c)[f])) && reqBy[c].every(p => chOk(pairKey(c, p))));
    const completeSet = new Set(complete);
    const detail = (c, p) => { const r = R.out.ch.get(pairKey(c, p)); return {handle: r.handle, followers: Math.round(num(r.follower_count)), band: r.size_band,
      ...Object.fromEntries(M.map(m => [m, isNum(num(r[m])) ? num(r[m]) : null])), ...Object.fromEntries(M.map(m => [m + "__pct", r[m + "__pct"] ?? null]))}; };
    const rows = complete.map(c => {
      const ch = Object.fromEntries(R.platforms.filter(p => reqBy[c].includes(p)).map(p => [p, detail(c, p)]));
      const rs = reqBy[c].map(p => R.out.ch.get(pairKey(c, p)));
      return {id: c, name: R.out.cr.get(c).display_name, country: R.out.cr.get(c).country, followers: Object.values(ch).reduce((a, d) => a + d.followers, 0),
        ch, scores: Object.fromEntries(M.map(m => [m, scores[c][m]])), role: scores[c].role, confidence: conf[Math.max(...rs.map(worst))] || "Low",
        sources: [...new Set(rs.flatMap(realSrc))].sort().join(", ")};
    }).sort((a, b) => (b.scores[M[0]] ?? -1) - (a.scores[M[0]] ?? -1));
    const channels = {};
    for (const [c, p] of R.reqPairs) { const k = pairKey(c, p); if (!chOk(k)) continue; const r = R.out.ch.get(k), d = detail(c, p);
      const pcs = Object.fromEntries(M.map(m => [m, r[m + "__pct"] ?? null])); const best = M.reduce((a, m) => (pcs[m] ?? -1) > (pcs[a] ?? -1) ? m : a, M[0]);
      (channels[p] = channels[p] || []).push({id: c, name: R.out.cr.get(c).display_name, country: R.out.cr.get(c).country, handle: d.handle, followers: d.followers, band: d.band,
        val: Object.fromEntries(M.map(m => [m, d[m]])), pct: pcs, role: M.some(m => pcs[m] !== null) ? pillar[best] : null,
        confidence: conf[worst(r)] || "Low", sources: realSrc(r).filter((v, i, a) => a.indexOf(v) === i).sort().join(", "), complete: completeSet.has(c)}); }
    for (const p in channels) channels[p].sort((a, b) => (b.pct[M[0]] ?? -1) - (a.pct[M[0]] ?? -1));
    // creator history for profiles: memory + this month
    const hist = R.memory.creator_history.filter(h => String(h.month) < R.month);
    const months = [...new Set([...hist.map(h => String(h.month)), R.month])].sort().slice(-12);
    const H = {};
    const put = (c, p, mo, vals) => { if (!reqBy[c]) return; const e = ((H[c] = H[c] || {})[p] = H[c][p] || Object.fromEntries(M.map(m => [m, months.map(() => null)])));
      const i = months.indexOf(mo); if (i >= 0) M.forEach(m => e[m][i] = vals[m] ?? null); };
    for (const h of hist) put(h.creator_id, h.platform, String(h.month), Object.fromEntries(M.map(m => [m, h[m + "__pct"] === "" || h[m + "__pct"] === null ? null : num(h[m + "__pct"])])).valueOf());
    for (const [c, p] of R.reqPairs) put(c, p, R.month, Object.fromEntries(M.map(m => [m, R.out.ch.get(pairKey(c, p))[m + "__pct"] ?? null])));
    for (const c of R.reqCreators) put(c, "all", R.month, Object.fromEntries(M.map(m => [m, scores[c][m]])));
    const anySrc = {}, freshSrc = {};
    for (const [v, rs] of Object.entries(R.vendorRows)) for (const r of rs) { const k = pairKey(r[R.key], r.platform); (anySrc[k] = anySrc[k] || new Set()).add(v); if (R.fresh(r)) (freshSrc[k] = freshSrc[k] || new Set()).add(v); }
    const reason = (k, r) => { const held = R.chReq.map(f => String(r[f + "__source"] || "")).find(s => /^(BLOCKED|EXCLUDED)/.test(s));
      if (held) { const id = held.split(": ")[1].split(" ")[0], fl = R.flags.find(x => x.id === id); return `${held.startsWith("EXCLUDED") ? "Excluded at review" : "Held back for review"}: ${fl ? fl.code : ""}`; }
      if (!anySrc[k]) return "No vendor has this channel"; if (!freshSrc[k]) return "Only stale data"; return "Field empty or invalid in fresh data"; };
    const qaBy = {}; R.flags.filter(f => f.code !== "PRIMARY_SOURCE_MISSING").forEach(f => (qaBy[f.creator_id] = qaBy[f.creator_id] || []).push({code: f.code, severity: f.severity, platform: f.platform, explanation: f.explanation, status: f.status, decision: f.decision}));
    const profiles = {};
    for (const c of R.reqCreators) {
      const cur = {};
      for (const p of R.platforms.filter(p => reqBy[c].includes(p))) { const k = pairKey(c, p), r = R.out.ch.get(k), ok = chOk(k);
        cur[p] = {handle: r.handle || null, followers: isNum(num(r.follower_count)) ? Math.round(num(r.follower_count)) : null, band: r.size_band, filled: ok,
          ...(ok ? {val: Object.fromEntries(M.map(m => [m, isNum(num(r[m])) ? num(r[m]) : null])), pct: Object.fromEntries(M.map(m => [m, r[m + "__pct"] ?? null])),
            confidence: conf[worst(r)] || "Low", sources: realSrc(r).filter((v, i, a) => a.indexOf(v) === i).sort().join(", ")} : {reason: reason(k, r)})}; }
      const cr = R.out.cr.get(c);
      profiles[c] = {id: c, name: cr.display_name || null, country: cr.country || null, category: cr.category || null, channels: Object.keys(cur), current: cur,
        filled: Object.values(cur).filter(x => x.filled).length, complete: completeSet.has(c), scores: Object.fromEntries(M.map(m => [m, scores[c][m]])),
        role: scores[c].role, history: H[c] || {}, qa: qaBy[c] || []};
    }
    const fin = assess(R);
    R.status = "finalized";
    return {run_date: R.runDate.toISOString().slice(0, 10), sla_days: R.sla, month: R.month,
      month_label: new Date(R.month + "-15").toLocaleString("en-US", {month: "long", year: "numeric"}), months, profiles,
      platforms: R.platforms, bands: Object.keys(R.cfg.size_bands), metrics: metricsMeta,
      summary: {creators: R.reqCreators.length, channels: R.reqPairs.length, ranked: rows.length, channels_complete: fin.channels_complete, gap_creators: R.reqCreators.length - complete.length},
      request: R.platforms.filter(p => R.reqMix[p]).map(p => ({platform: p, requested: R.reqMix[p], complete: fin.by_platform[p] || 0})),
      shape: Object.keys(R.shape).sort((a, b) => b - a).map(n => ({n: +n, creators: R.shape[n], complete: fin.by_n[n] || 0})),
      tiers: Object.values(R.profiles).sort((a, b) => b.score - a.score).map(P => ({tier: P.tier, vendor: P.name, score: P.score, usable_coverage: P.usable_coverage,
        best: Object.entries(P.platform_coverage).sort((a, b) => b[1] - a[1])[0]?.[0] || "-", excluded: P.excluded_reason || null})),
      rows, channels, qa: {warnings: R.flags.filter(f => f.severity === "YELLOW").length, reviewed: R.flags.filter(f => f.severity === "RED" && f.status === "resolved").length}};
  }

  // ------------------------------------------------------------------ Generate Demo Data (demo_data.py)
  function mulberry(seed) { return () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
  function generateDemo(cfg, month, seed) {
    seed = seed ?? Math.floor(Math.random() * 1e6);
    const rnd = mulberry(seed), U = (a, b) => a + (b - a) * rnd(), pick = a => a[Math.floor(rnd() * a.length)];
    const gauss = () => { let u = 0, v = 0; while (!u) u = rnd(); while (!v) v = rnd(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); };
    const logn = (mu, s) => Math.exp(mu + s * gauss());
    const shuffle = a => { for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };
    const sample = (a, n) => shuffle(a.slice()).slice(0, n);
    const ADJ = ["amber", "velvet", "lunar", "copper", "misty", "neon", "quiet", "solar", "crimson", "frosty", "golden", "hollow", "ivory", "jade", "kinetic", "lucky", "mellow", "nimble", "opal", "pixel", "rustic", "silver", "tidal", "urban", "vivid", "wild", "zesty", "brisk", "cosmic", "dusky"];
    const NOUN = ["otter", "comet", "fern", "harbor", "lantern", "maple", "nova", "orchid", "pebble", "quartz", "raven", "sparrow", "thistle", "willow", "yarrow", "badger", "cinder", "delta", "ember", "falcon", "glacier", "heron", "iris", "juniper", "kestrel", "lotus", "meadow", "nectar", "onyx", "prairie"];
    const COUNTRIES = {US: "United States", GB: "United Kingdom", CA: "Canada", BR: "Brazil", IN: "India", DE: "Germany", FR: "France", JP: "Japan", MX: "Mexico", KR: "South Korea"};
    const CATS = ["gaming", "beauty", "fitness", "food", "tech", "travel", "music", "education", "comedy", "finance"];
    const REACH = {tiktok: 3.0, youtube: 1.2, instagram: 0.6}, P = cfg.platforms;
    const end = monthEnd(month), N = 160;
    const ids = sample([...Array(9999).keys()].map(i => i + 1), N).map(i => "DEMO-" + String(i).padStart(4, "0"));
    const names = sample(ADJ.flatMap(a => NOUN.map(n => [a, n])), N);
    const truth = new Map(), creators = {}, have = {};
    ids.forEach((id, i) => {
      const [a, n] = names[i]; creators[id] = {name: `${a[0].toUpperCase() + a.slice(1)} ${n[0].toUpperCase() + n.slice(1)} (demo)`, slug: `demo_${a}${n}`, country: pick(Object.keys(COUNTRIES)), email: `${a}.${n}@example.invalid`, category: pick(CATS)};
      const k = [1, 2, 3][(() => { const x = rnd() * 10; return x < 2 ? 0 : x < 5 ? 1 : 2; })()];
      have[id] = sample(P, k);
      for (const p of have[id]) {
        const f = Math.round(logn(10.8, 1.3)), g = Math.min(1.5, Math.max(-0.2, 0.06 + 0.05 * gauss() + 0.5 / Math.log10(Math.max(f, 100)) ** 2));
        const views = Math.round(f * logn(Math.log(REACH[p]), 0.6)), eng = Math.round(views * U(0.02, 0.08));
        const w = [16, 1.2, 0.8, p !== "youtube" ? 1 : 0.0001].map(x => -Math.log(rnd()) * x), sw = w.reduce((a, b) => a + b, 0);
        const [likes, comments, shares, saves] = w.map(x => Math.round(eng * x / sw));
        truth.set(pairKey(id, p), {creator_id: id, platform: p, handle: `@${creators[id].slug}_${p}`, follower_count: f, net_new_followers_90d: f - Math.round(f / (1 + g)),
          views_90d: views, likes_90d: likes, comments_90d: comments, shares_90d: shares, saves_90d: p !== "youtube" ? saves : null, likes_hidden: p === "instagram" && rnd() < 0.08,
          display_name: creators[id].name, country: creators[id].country, contact_email: creators[id].email, category: creators[id].category});
      }
    });
    const three = ids.filter(c => have[c].length === 3), full = sample(three, 60), rest = ids.filter(c => !full.includes(c));
    const two = sample(rest.filter(c => have[c].length >= 2), 20), one = sample(rest.filter(c => !two.includes(c)), 20);
    const req = {}; full.forEach(c => req[c] = P.slice()); two.forEach(c => req[c] = sample(have[c], 2)); one.forEach(c => req[c] = sample(have[c], 1));
    const reqPairs = Object.entries(req).flatMap(([c, ps]) => ps.map(p => pairKey(c, p)));
    const used = new Set(), pool = shuffle(reqPairs.filter(k => !truth.get(k).likes_hidden));
    const take = (n, need = () => true) => { const out = []; for (const k of pool) { if (out.length >= n) break; const c = k.split("|")[0]; if (used.has(c) || !need(k)) continue; out.push(k); used.add(c); } return out; };
    const clean = []; for (const c of shuffle(full.slice())) { if (clean.length >= 8) break; if (!req[c].some(p => truth.get(pairKey(c, p)).likes_hidden)) { clean.push(c); used.add(c); } }
    const S = {clean: clean.flatMap(c => req[c].map(p => pairKey(c, p))), fallback: take(6), discrepancy: take(4), t1_outlier: take(2), identity: take(3), identity_majority: take(2),
      anomaly: take(4, k => truth.get(k).follower_count > 5000)};
    const seeded = new Set(Object.values(S).flat());
    const cover = {vendor_a: .85, vendor_b: .75, vendor_c: .65}, stale = {vendor_a: .04, vendor_b: .15, vendor_c: .35}, nulls = {vendor_a: .01, vendor_b: .04, vendor_c: .10};
    const presence = {}, must = {vendor_a: new Set(), vendor_b: new Set(), vendor_c: new Set()};
    const extra = [...truth.keys()].filter(k => !reqPairs.includes(k));
    for (const v in cover) { presence[v] = new Set(reqPairs.filter(k => !seeded.has(k) && rnd() < cover[v])); sample(extra, {vendor_a: 45, vendor_b: 70, vendor_c: 85}[v]).forEach(k => presence[v].add(k)); }
    [...S.clean, ...S.t1_outlier, ...S.identity_majority].forEach(k => Object.values(must).forEach(s => s.add(k)));
    [...S.fallback, ...S.discrepancy, ...S.anomaly].forEach(k => { must.vendor_a.add(k); must.vendor_b.add(k); });
    S.identity.forEach(k => { must.vendor_a.add(k); must.vendor_c.add(k); });
    for (const v in presence) { must[v].forEach(k => presence[v].add(k)); seeded.forEach(k => { if (!must[v].has(k)) presence[v].delete(k); }); }
    const stamp = fresh => new Date(end - (fresh ? 3 + Math.floor(rnd() * 73) : 120 + Math.floor(rnd() * 260)) * DAY).toISOString().slice(0, 10);
    const frames = {};
    for (const v in presence) {
      frames[v] = new Map();
      for (const k of [...presence[v]].sort()) {
        const r = {...truth.get(k)};
        for (const c of ["follower_count", "views_90d", "likes_90d", "comments_90d", "shares_90d", "saves_90d"]) if (r[c] !== null) r[c] = Math.round(r[c] * (1 + 0.012 * gauss()));
        const seededRow = must[v].has(k);
        if (!seededRow) for (const c of ["follower_count", "views_90d", "likes_90d", "comments_90d", "contact_email", "category"]) if (rnd() < nulls[v]) r[c] = null;
        if (r.likes_hidden) r.likes_90d = "hidden";
        r.ts = stamp(seededRow || rnd() > stale[v]);
        frames[v].set(k, r);
      }
    }
    const A = frames.vendor_a, B = frames.vendor_b, C = frames.vendor_c, scen = {};
    const note = (key, k, what) => (scen[key] = scen[key] || []).push({creator_id: k.split("|")[0], platform: k.split("|")[1], creator: truth.get(k).display_name, what});
    S.clean.forEach(k => note("1 Clean agreement · GREEN", k, "A, B and C all report this channel within ~2% of each other"));
    S.fallback.forEach(k => { A.get(k).likes_90d = null; note("2 Primary source missing · YELLOW", k, "Vendor A (Tier 1) has no likes count; Vendor B fills the engagement metric"); });
    S.discrepancy.forEach(k => { const m = rnd() < .5 ? U(.45, .62) : U(1.55, 1.9); B.get(k).follower_count = Math.round(A.get(k).follower_count * m);
      note("3 Material discrepancy · RED", k, `A ${A.get(k).follower_count.toLocaleString("en-US")} vs B ${B.get(k).follower_count.toLocaleString("en-US")} followers; no third source`); });
    S.t1_outlier.forEach(k => { A.get(k).follower_count = Math.round(A.get(k).follower_count * U(.5, .6)); note("3b Tier 1 outlier overruled · YELLOW", k, "Vendor A (Tier 1) is the outlier; B and C agree, so their value is used"); });
    const others = [...truth.keys()].filter(k => !seeded.has(k));
    S.identity.forEach(k => { const o = truth.get(pick(others.filter(x => x.endsWith("|" + k.split("|")[1])))), r = C.get(k);
      for (const c of ["handle", "follower_count", "net_new_followers_90d", "views_90d", "likes_90d", "comments_90d", "shares_90d", "saves_90d"]) r[c] = o[c];
      note("4 Identity can't be matched · RED", k, `A says ${A.get(k).handle}, C says ${r.handle}; no majority`); });
    S.identity_majority.forEach(k => { const o = truth.get(pick(others.filter(x => x.endsWith("|" + k.split("|")[1])))); C.get(k).handle = o.handle;
      note("4b Identity resolved by majority · YELLOW", k, `A and B agree on ${A.get(k).handle}; C reports ${o.handle}`); });
    S.anomaly.forEach(k => note("5 Historical anomaly · YELLOW", k, "follower count ~5–8x last month's (seeded history); vendors agree, so it's kept"));
    const fmtVendor = (v, frame) => {
      const cmap = cfg.vendors[v].column_map, rows = [];
      for (const r0 of frame.values()) {
        const r = {...r0};
        if (v === "vendor_a") r.platform = {youtube: "YouTube", instagram: "Instagram", tiktok: "TikTok"}[r.platform];
        if (v === "vendor_b") { r.platform = {instagram: "IG", tiktok: "TT", youtube: "YT"}[r.platform]; r.country = COUNTRIES[r.country];
          const prev = (r.follower_count === null || r.net_new_followers_90d === null) ? null : r.follower_count - r.net_new_followers_90d;
          r.followers_prev = prev === null ? null : Math.round(prev / 10) / 100; r.follower_count = r.follower_count === null ? null : Math.round(r.follower_count / 10) / 100; }
        if (v === "vendor_c") { r.platform = pick([r.platform, r.platform.toUpperCase(), r.platform[0].toUpperCase() + r.platform.slice(1)]); r.country = r.country.toLowerCase();
          if (rnd() < .3) r.display_name = r.display_name.toLowerCase(); }
        const o = {}; for (const [col, f] of Object.entries(cmap)) o[col] = r[f] ?? null; o[cfg.vendors[v].last_updated_col] = r.ts; rows.push(o);
      }
      return shuffle(rows);
    };
    const label = `SYNTHETIC DEMO DATA · generated ${new Date().toISOString().slice(0, 16).replace("T", " ")} · seed ${seed}`;
    const inputs = [{name: `SYNTHETIC_DEMO_creator_request_${month}.xlsx`, source: "demo", data: {order: ["Request", "About"], sheets: {Request: shuffle(Object.entries(req).map(([c, ps]) =>
      ({creator_id: c, "creator_name (optional)": creators[c].name, ...Object.fromEntries(P.map(p => [p, ps.includes(p) ? "Y" : null]))}))), About: [{note: label}]}}},
      ...[["vendor_a", A], ["vendor_b", B], ["vendor_c", C]].map(([v, fr]) => ({name: `SYNTHETIC_DEMO_${v.replace("vendor_", "vendor_").replace(/_(.)$/, (m, x) => "_" + x.toUpperCase())}_${month}.xlsx`,
        source: "demo", data: {order: ["data", "About"], sheets: {data: fmtVendor(v, fr), About: [{note: label}]}}}))];
    // 3 months of synthetic history
    const hm = prevMonths(month, 3), quality = {vendor_a: [.86, .9], vendor_b: [.73, .6], vendor_c: [.57, .25]}, vh = [], audit = [], ch = [];
    hm.forEach((m, k) => {
      Object.entries(quality).forEach(([v, [q]], t) => vh.push({month: m, vendor: v, current_score: round(q + 0.012 * gauss()), tier: t + 1}));
      for (let j = 0; j < 4; j++) { const kk = pick(reqPairs), f = truth.get(kk).follower_count, vals = Object.fromEntries(Object.keys(quality).map(v => [v, Math.round(f * (1 + 0.02 * gauss()))]));
        const win = Object.keys(quality).reduce((a, v) => quality[v][1] * rnd() ** 0.35 > quality[a][1] * rnd() ** 0.35 ? v : a, "vendor_a");
        audit.push({month: m, review_id: `H${k}${j}`, creator_id: kk.split("|")[0], platform: kk.split("|")[1], code: "CROSS_VENDOR_DISCREPANCY", original_values: JSON.stringify(vals),
          decision: "SELECT_" + win.toUpperCase(), final_source: win, manual_value: null, reviewer: "Synthetic history"}); }
    });
    const base = {}; for (const k of truth.keys()) base[k] = Object.fromEntries(Object.keys(cfg.metrics).map(m => [m, U(10, 95)]));
    hm.forEach((m, k) => { const back = hm.length - k;
      for (const [c, ps] of Object.entries(req)) {
        const rowsC = [];
        for (const p of have[c]) { const key = pairKey(c, p), t = truth.get(key);
          const f = S.anomaly.includes(key) ? t.follower_count / (U(5, 8) * (1 + 0.02 * (back - 1))) : t.follower_count / 1.015 ** back;
          const r = {month: m, creator_id: c, platform: p, follower_count: Math.round(f), reach_rate: t.views_90d / t.follower_count * (1 + 0.1 * gauss())};
          for (const mm of Object.keys(cfg.metrics)) r[mm + "__pct"] = Math.round(Math.min(100, Math.max(1, base[key][mm] + 8 * gauss())) * 10) / 10;
          ch.push(r); if (ps.includes(p)) rowsC.push(r); }
        const all = {month: m, creator_id: c, platform: "all"};
        for (const mm of Object.keys(cfg.metrics)) all[mm + "__pct"] = Math.round(rowsC.reduce((a, r) => a + r[mm + "__pct"], 0) / rowsC.length * 10) / 10;
        ch.push(all);
      } });
    return {inputs, memory: {vendor_history: vh, review_audit: audit, creator_history: ch}, scenarios: scen, seed, label, history_months: hm, month};
  }

  return {readFile, newRun, process, applyDecisions, finalize, generateDemo, openRed, creatorStatus, makeRegistry, isRequest, identify};
})();
