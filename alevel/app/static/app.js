"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const app = $("#app");
const S = { me: null, content: null, byId: {}, chapters: {}, sections: {}, progress: null };
const PAPERS = { 1: "H446/01 Computer systems", 2: "H446/02 Algorithms and programming" };

// ------------------------------------------------------------------ helpers
async function api(path, opts = {}) {
  const o = { credentials: "same-origin", ...opts };
  if (o.json !== undefined) {
    o.method = o.method || "POST";
    o.headers = { "Content-Type": "application/json" };
    o.body = JSON.stringify(o.json);
    delete o.json;
  }
  let r;
  try { r = await fetch(path, o); } catch { throw new Error("Can't reach the server. Check your connection."); }
  const d = await r.json().catch(() => ({}));
  if (r.status === 401 && !path.includes("login")) { S.me = null; if (!location.hash.startsWith("#/teacher")) go("#/login"); }
  if (!r.ok) throw new Error(d.error || `Something went wrong (${r.status}).`);
  return d;
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function rich(s) { // textbook markup: **bold**, `code`, newlines
  return esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`(.+?)`/g, "<code>$1</code>").replace(/\n/g, "<br>");
}
function h(html) { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; }
function go(hash) { if (location.hash !== hash) location.hash = hash; else route(); }
function band(pct) { return pct == null ? "" : pct >= 70 ? "good" : pct >= 40 ? "mid" : "bad"; }
function scoreChip(s, m) { if (s == null) return `<span class="chip">New</span>`; const p = m ? Math.round(100 * s / m) : 0; return `<span class="chip ${band(p)} num">${s}/${m}</span>`; }
function when(iso) {
  if (!iso) return "never";
  const d = new Date(iso), days = Math.floor((Date.now() - d) / 864e5);
  return days <= 0 ? "today" : days === 1 ? "yesterday" : days < 7 ? `${days} days ago` : d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}
function store(k, v) { try { if (v === undefined) return JSON.parse(localStorage.getItem(k) || "null"); if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, JSON.stringify(v)); } catch { return null; } }
function qLabel(q) { return `${q.kind === "q" ? "In-chapter" : "Exercise"} Q${q.n}`; }
function snippet(q) {
  const t = q.text || q.ctx || (q.parts && q.parts.map(p => p.text).join(" ")) || "";
  return t.replace(/\*\*|`/g, "").replace(/\s+/g, " ").slice(0, 160);
}
function busy(btn, on, label) { if (!btn) return; btn.disabled = on; if (label) { if (on) { btn.dataset.l = btn.textContent; btn.textContent = label; } else if (btn.dataset.l) btn.textContent = btn.dataset.l; } }

async function loadContent() {
  if (S.content) return;
  S.content = await api("/api/content");
  for (const s of S.content.sections) { S.sections[s.n] = s; for (const c of s.chapters) S.chapters[c.n] = { ...c, section: s.n }; }
  for (const q of S.content.questions) S.byId[q.id] = q;
}
function questionsIn(ch, kind) { return S.content.questions.filter(q => q.ch === ch && (!kind || q.kind === kind)); }

function topbar() {
  const el = $("#topbar-right");
  if (S.me && S.me.avatar) {
    el.innerHTML = `<span class="pill" title="AI marking, hints and practice questions left today"><span class="num">${S.me.ai_left}</span> AI requests left</span>
      <span class="pill">${esc(S.me.avatar)}</span><button class="btn btn-ghost btn-sm" id="logout">Sign out</button>`;
  } else if (S.me && S.me.teacher) {
    el.innerHTML = `<a class="btn btn-ghost btn-sm" href="#/teacher">Dashboard</a><button class="btn btn-ghost btn-sm" id="logout">Sign out</button>`;
  } else el.innerHTML = "";
  const lo = $("#logout");
  if (lo) lo.onclick = async () => { await api("/api/logout", { json: {} }).catch(() => {}); S.me = null; S.progress = null; go("#/login"); };
}
async function refreshMe() { S.me = await api("/api/me"); topbar(); }

// ------------------------------------------------------------------ router
window.addEventListener("hashchange", route);
async function route() {
  const hash = location.hash || "#/";
  window.scrollTo(0, 0);
  try {
    if (!S.me) await refreshMe();
    if (hash.startsWith("#/teacher")) return S.me.teacher ? teacherView() : teacherLogin();
    if (!S.me.avatar) return S.me.teacher ? go("#/teacher") : loginView();
    if (hash === "#/login") return go("#/");
    await loadContent();
    let m;
    if ((m = hash.match(/^#\/s\/(\d+)/))) return sectionView(+m[1]);
    if ((m = hash.match(/^#\/c\/(\d+)/))) return chapterView(+m[1]);
    if ((m = hash.match(/^#\/q\/([\w-]+)/))) return questionView(m[1]);
    return homeView();
  } catch (e) {
    app.innerHTML = `<div class="error">${esc(e.message)}</div>`;
  }
}

// ------------------------------------------------------------------ login
function loginView() {
  topbar();
  app.innerHTML = `<div class="login stack">
    <div class="stack" style="gap:8px"><span class="eyebrow">OCR A Level Computer Science</span>
    <h1>Sign in with your avatar</h1><p class="muted">Use the avatar name and PIN on the card your teacher gave you.</p></div>
    <form class="card" id="f">
      <label class="field">Avatar name<input type="text" id="avatar" autocomplete="username" placeholder="e.g. SwiftOtter" required></label>
      <label class="field">PIN<input type="password" id="pin" inputmode="numeric" autocomplete="current-password" maxlength="8" required></label>
      <div id="err" class="error" hidden></div>
      <button class="btn btn-primary" id="go">Sign in</button>
    </form>
    <p class="small muted">Teacher? <a href="#/teacher">Open the dashboard</a></p></div>`;
  $("#f").onsubmit = async e => {
    e.preventDefault();
    const b = $("#go"); busy(b, true, "Signing in…");
    try {
      await api("/api/login", { json: { avatar: $("#avatar").value, pin: $("#pin").value } });
      await refreshMe(); go("#/");
    } catch (err) { $("#err").hidden = false; $("#err").textContent = err.message; }
    busy(b, false);
  };
}

// ------------------------------------------------------------------ home
async function homeView() {
  S.progress = await api("/api/progress");
  const P = S.progress, best = P.best;
  const answered = Object.keys(best).length, total = S.content.questions.length;
  let got = 0, max = 0; for (const b of Object.values(best)) { got += b.best; max += b.max; }
  const avg = max ? Math.round(100 * got / max) : null;
  const chs = Object.entries(P.chapters).map(([c, s]) => ({ c: +c, ...s }));
  const weak = chs.filter(x => x.done && x.pct < 70).sort((a, b) => a.pct - b.pct).slice(0, 3);
  const fresh = chs.filter(x => !x.done).slice(0, Math.max(0, 3 - weak.length));
  const focus = [...weak.map(x => ({ ...x, why: `${x.pct}% so far - redo the questions you lost marks on` })),
                 ...fresh.map(x => ({ ...x, why: "Not started yet" }))];
  app.innerHTML = `<div class="stack" style="gap:22px">
    <div class="stack" style="gap:6px"><span class="eyebrow">Your revision</span><h1>Hi, ${esc(S.me.avatar)}</h1></div>
    <div class="stats">
      <div class="stat"><b>${answered}<span class="muted small"> / ${total}</span></b><span class="muted small">questions answered</span></div>
      <div class="stat"><b>${avg == null ? "–" : avg + "%"}</b><span class="muted small">average score</span></div>
      <div class="stat"><b>${P.streak}</b><span class="muted small">day${P.streak === 1 ? "" : "s"} in a row</span></div>
      <div class="stat"><b>${S.me.ai_left}</b><span class="muted small">AI requests left today</span></div>
    </div>
    <div class="grid-2">
      <section class="card plan stack" id="plan"></section>
      <section class="card stack"><h2>Focus next</h2>
        ${focus.length ? `<div class="list">${focus.map(f => `<a class="qrow" style="grid-template-columns:3.4rem 1fr" href="#/c/${f.c}">
            <span class="qn">Ch ${f.c}</span><span><b>${esc(S.chapters[f.c].title)}</b><br><span class="small muted">${esc(f.why)}</span></span></a>`).join("")}</div>`
          : `<p class="muted">Everything you've tried is at 70% or above. Pick a new section below.</p>`}
      </section>
    </div>
    ${P.recent.length ? `<section class="stack"><h2>Recent answers</h2><div class="qlist">${P.recent.map(r => {
      const q = S.byId[r.qid]; return q ? `<a class="qrow" href="#/q/${q.id}"><span class="qn">Ch ${q.ch}</span><span class="qt">${esc(qLabel(q))} · ${esc(snippet(q))}</span>${scoreChip(r.score, r.max)}</a>` : "";
    }).join("")}</div></section>` : ""}
    ${[1, 2].map(paper => `<section class="stack">
      <div class="paper-head"><h2>Paper ${paper}</h2><span class="eyebrow">${PAPERS[paper]}</span></div>
      <div class="grid">${S.content.sections.filter(s => s.paper === paper).map(s => sectionCard(s)).join("")}</div></section>`).join("")}
  </div>`;
  renderPlan(P.plan);
}
function sectionStats(sn) {
  let done = 0, tot = 0, got = 0, max = 0;
  for (const c of S.sections[sn].chapters) { const x = S.progress.chapters[c.n]; done += x.done; tot += x.total; got += x.score; max += x.max; }
  return { done, tot, pct: max ? Math.round(100 * got / max) : null };
}
function sectionCard(s) {
  const st = sectionStats(s.n), cov = st.tot ? Math.round(100 * st.done / st.tot) : 0;
  return `<a class="card-plain sec" href="#/s/${s.n}">
    <div class="sec-top"><span class="sec-n">§${s.n}</span><h3>${esc(s.title)}</h3></div>
    <div class="bar ${band(st.pct)}"><span style="width:${cov}%"></span></div>
    <div class="sec-meta num"><span>${st.done} of ${st.tot} answered</span><span>${st.pct == null ? "" : st.pct + "% scored"}</span></div></a>`;
}
function renderPlan(plan) {
  const el = $("#plan");
  el.innerHTML = `<div class="row" style="justify-content:space-between"><h2>Your study plan</h2>
      <button class="btn btn-sm" id="mkplan">${plan ? "Refresh plan" : "Make my plan"}</button></div>
    ${plan ? `<p>${esc(plan.summary)}</p><ol>${plan.actions.map(a => `<li><b>${esc(a.title)}</b>
        ${S.chapters[a.chapter] ? ` · <a href="#/c/${a.chapter}">Ch ${a.chapter}</a>` : ""}<br><span class="muted small">${esc(a.detail)}</span></li>`).join("")}</ol>
        <p class="small muted">Made ${when(plan.created)}.</p>`
      : `<p class="muted">Answer a few questions, then the AI coach looks at your scores and mistakes and suggests three things to work on this week.</p>`}
    <div id="planerr" class="error" hidden></div>`;
  $("#mkplan").onclick = async e => {
    busy(e.target, true, "Thinking…");
    try { const p = await api("/api/plan", { json: {} }); await refreshMe(); renderPlan(p); }
    catch (err) { $("#planerr").hidden = false; $("#planerr").textContent = err.message; busy(e.target, false); }
  };
}

// ------------------------------------------------------------------ section & chapter
async function ensureProgress() { if (!S.progress) S.progress = await api("/api/progress"); }
async function sectionView(sn) {
  await ensureProgress();
  const s = S.sections[sn]; if (!s) return go("#/");
  app.innerHTML = `<div class="stack" style="gap:20px">
    <nav class="crumbs"><a href="#/">Home</a><span>›</span><span>Section ${sn}</span></nav>
    <div class="stack" style="gap:6px"><span class="eyebrow">Paper ${s.paper} · ${PAPERS[s.paper]}</span><h1>${esc(s.title)}</h1></div>
    <div class="grid">${s.chapters.map(c => {
      const x = S.progress.chapters[c.n], cov = x.total ? Math.round(100 * x.done / x.total) : 0;
      return `<a class="card-plain sec" href="#/c/${c.n}"><div class="sec-top"><span class="sec-n">Ch ${c.n}</span><h3>${esc(c.title)}</h3></div>
        <div class="bar ${band(x.pct)}"><span style="width:${cov}%"></span></div>
        <div class="sec-meta num"><span>${x.done} of ${x.total} answered</span><span>${x.pct == null ? "" : x.pct + "% scored"}</span></div></a>`;
    }).join("")}</div></div>`;
}
async function chapterView(cn) {
  await ensureProgress();
  const c = S.chapters[cn]; if (!c) return go("#/");
  const best = S.progress.best;
  const list = (kind, title, note) => {
    const qs = questionsIn(cn, kind);
    return `<section class="stack"><div><h2>${title}</h2><p class="small muted">${note}</p></div>
      ${qs.length ? `<div class="qlist">${qs.map(q => `<a class="qrow" href="#/q/${q.id}"><span class="qn">Q${q.n}${q.total ? ` [${maxMarks(q)}]` : ""}</span>
        <span class="qt">${esc(snippet(q))}</span>${best[q.id] ? scoreChip(best[q.id].best, best[q.id].max) : `<span class="chip">New</span>`}</a>`).join("")}</div>`
        : `<p class="muted">There are no ${kind === "q" ? "in-chapter questions" : "exercises"} in this chapter.</p>`}</section>`;
  };
  app.innerHTML = `<div class="stack" style="gap:22px">
    <nav class="crumbs"><a href="#/">Home</a><span>›</span><a href="#/s/${c.section}">Section ${c.section}</a><span>›</span><span>Chapter ${cn}</span></nav>
    <div class="stack" style="gap:6px"><span class="eyebrow">Chapter ${cn}</span><h1>${esc(c.title)}</h1></div>
    ${list("q", "In-chapter questions", "Quick checks from the yellow boxes. Each part is marked out of 3.")}
    ${list("e", "End of chapter exercises", "Exam-style questions with OCR mark allocations.")}</div>`;
}

// ------------------------------------------------------------------ question rendering
function tableHtml(t, key, cells) {
  const hdr = t.header ? `<tr>${t.header.map(x => `<th>${rich(x) || "&nbsp;"}</th>`).join("")}</tr>` : "";
  const rows = t.rows.map((r, ri) => `<tr>${r.map((v, ci) => v === "" && key != null
      ? `<td class="in"><input type="text" data-part="${key}" data-cell="${ri},${ci}" aria-label="Row ${ri + 1}, column ${ci + 1}" value="${esc((cells || {})[`${ri},${ci}`] || "")}"></td>`
      : `<td>${rich(v) || "&nbsp;"}</td>`).join("")}</tr>`).join("");
  return `${t.caption ? `<p class="small muted"><i>${rich(t.caption)}</i></p>` : ""}<div class="tbl-wrap"><table class="qt ${t.align === "left" ? "left" : ""}">${hdr}${rows}</table></div>`;
}
function blockHtml(b, key, draft, answerable) {
  const out = [];
  if (b.ctx) out.push(`<p class="ctx">${rich(b.ctx)}</p>`);
  if (b.img) out.push(`<div><div class="fig"><img src="/img/${esc(b.img[0])}" width="${b.img[1]}" height="${b.img[2]}" alt="Textbook diagram for this question"></div></div>`);
  if (b.code) out.push(`<pre class="code">${esc(b.code)}</pre>`);
  if (b.table) out.push(tableHtml(b.table, answerable || key === "stem" ? key : null, draft && draft.cells));
  if (b.pre) out.push(`<p>${rich(b.pre)}</p>`);
  if (answerable) {
    const needsBox = b.draw || b.box !== false;
    if (needsBox) out.push(`<textarea data-part="${key}" aria-label="Your answer" placeholder="${b.draw ? "Describe your diagram in words, or upload a photo of it below" : "Type your answer"}">${esc(draft && draft.text || "")}</textarea>`);
    out.push(`<div class="photo">${b.draw ? "<b>Upload a photo of your diagram:</b>" : "Or add a photo of handwritten working:"}
      <input type="file" accept="image/*" data-photo="${key}"></div>`);
  }
  if (b.after) out.push(`<p class="src">${esc(b.after)}</p>`);
  return out.join("");
}
function answerable(b) { return !!(b.marks || b.draw || b.box !== false || (b.table && b.table.rows.some(r => r.includes("")))); }
// every part, flagged `ans` when the student answers it (display-only parts just show data)
function partsOf(q) { return q.parts ? q.parts.map((p, i) => ({ key: String(i), label: p.label || String(i + 1), b: p, ans: answerable(p) })) : [{ key: "0", label: "", b: q, ans: true }]; }
function maxMarks(q) { return partsOf(q).filter(p => p.ans).reduce((t, p) => t + (p.b.marks || 3), 0); }
function questionHtml(q, draft) {
  const parts = partsOf(q);
  let body = `<p class="q-text">${rich(q.text || "")}${q.marks ? ` <span class="marks">[${q.marks}]</span>` : ""}</p>`;
  if (q.parts) {
    body += blockHtml(q, "stem", draft.stem, false);
    body += parts.map(p => p.ans ? `<div class="part"><p class="q-text"><span class="part-label">(${esc(p.label.replace(/[()]/g, ""))})</span>${rich(p.b.text || "")}${p.b.marks ? ` <span class="marks">[${p.b.marks}]</span>` : ""}</p>
      ${blockHtml(p.b, p.key, draft[p.key], true)}</div>`
      : `<div class="stack" style="gap:10px">${p.b.text ? `<p class="q-text">${rich(p.b.text)}</p>` : ""}${blockHtml(p.b, p.key, null, false)}</div>`).join("");
  } else body += blockHtml(q, "0", draft["0"], true);
  return body;
}
function collect(root) {
  const answers = {};
  for (const t of $$("textarea[data-part]", root)) (answers[t.dataset.part] ||= {}).text = t.value;
  for (const i of $$("input[data-cell]", root)) if (i.value.trim()) ((answers[i.dataset.part] ||= {}).cells ||= {})[i.dataset.cell] = i.value.trim();
  return answers;
}

// ------------------------------------------------------------------ question page
async function questionView(id) {
  const q = S.byId[id]; if (!q) return go("#/");
  await ensureProgress();
  const st = await api(`/api/question/${id}`);
  const c = S.chapters[q.ch];
  const draftKey = `draft:${S.me.avatar}:${id}`;
  const last = st.attempts[st.attempts.length - 1];
  const draft = store(draftKey) || (last ? last.answer : {}) || {};
  const sib = questionsIn(q.ch), idx = sib.findIndex(x => x.id === id);
  const prev = sib[idx - 1], next = sib[idx + 1];
  app.innerHTML = `<div class="stack" style="gap:18px">
    <nav class="crumbs"><a href="#/">Home</a><span>›</span><a href="#/s/${c.section}">Section ${c.section}</a><span>›</span><a href="#/c/${q.ch}">Ch ${q.ch} ${esc(c.title)}</a></nav>
    <div class="q-layout">
      <div class="stack">
        <article class="card stack" id="qcard">
          <div class="q-head"><span class="eyebrow">${esc(qLabel(q))}${q.page ? ` · textbook p.${q.page}` : ""}</span>
            <span class="chip accent num">${maxMarks(q)} marks${q.total ? "" : " · 3 per part"}</span></div>
          <div class="stack" id="qbody">${questionHtml(q, draft)}</div>
          <p class="small muted">Don't include your name or any personal details in answers.</p>
          <div class="actions"><button class="btn btn-primary" id="submit">Mark my answer</button><span id="status" class="small muted"></span></div>
          <div id="err" class="error" hidden></div>
        </article>
        <section class="card result" id="result" hidden></section>
        ${st.attempts.length > 1 ? `<details class="card-plain"><summary>Previous attempts (${st.attempts.length})</summary><div class="history" style="margin-top:10px">
          ${st.attempts.map((a, i) => `<div class="row"><span class="small muted">Attempt ${i + 1} · ${when(a.created)}${a.after_reveal ? " · after model answer" : ""}</span>${scoreChip(a.teacher_score ?? a.score, a.max)}</div>`).join("")}</div></details>` : ""}
        <div class="row" style="justify-content:space-between">
          ${prev ? `<a class="btn" href="#/q/${prev.id}">← ${esc(qLabel(prev))}</a>` : "<span></span>"}
          ${next ? `<a class="btn" href="#/q/${next.id}">${esc(qLabel(next))} →</a>` : `<a class="btn" href="#/c/${q.ch}">Back to chapter</a>`}
        </div>
      </div>
      <aside class="side">
        <section class="card stack" id="tutor"></section>
        <section class="card stack" id="practice"></section>
      </aside>
    </div></div>`;
  const qcard = $("#qcard");
  qcard.addEventListener("input", () => store(draftKey, collect(qcard)));
  if (last) showResult(q, last.result, st, last);
  $("#submit").onclick = async () => {
    const answers = collect(qcard);
    const fd = new FormData();
    fd.append("answers", JSON.stringify(answers));
    for (const f of $$("input[data-photo]", qcard)) if (f.files[0]) fd.append(`photo_${f.dataset.photo}`, f.files[0]);
    const b = $("#submit"); busy(b, true, "Marking…");
    $("#status").innerHTML = `<span class="thinking"><span class="dot"></span>The AI examiner is marking your answer. This usually takes 10-40 seconds.</span>`;
    $("#err").hidden = true;
    try {
      const r = await api(`/api/question/${id}/submit`, { method: "POST", body: fd });
      store(draftKey, answers);
      S.progress = null; refreshMe();
      const fresh = await api(`/api/question/${id}`);
      showResult(q, r.result, fresh, fresh.attempts[fresh.attempts.length - 1]);
      $("#result").scrollIntoView({ behavior: "smooth", block: "start" });
      for (const f of $$("input[data-photo]", qcard)) f.value = "";
      renderTutor(q, fresh);
    } catch (e) { $("#err").hidden = false; $("#err").textContent = e.message; }
    $("#status").textContent = ""; busy(b, false);
  };
  renderTutor(q, st);
  renderPractice(q, st);
}
const VERDICT = { correct: ["good", "Correct"], partial: ["mid", "Partly right"], incorrect: ["bad", "Not yet"], not_attempted: ["", "Not attempted"] };
function showResult(q, res, st, attempt) {
  const el = $("#result"); el.hidden = false;
  const score = attempt && attempt.teacher_score != null ? attempt.teacher_score : res.score;
  const pct = res.max ? Math.round(100 * score / res.max) : 0;
  el.innerHTML = `<div class="row" style="justify-content:space-between;align-items:flex-end">
      <div class="score-big"><b>${score}</b><span class="muted num">/ ${res.max} marks</span></div>
      <span class="chip ${band(pct)} num">${pct}%</span></div>
    <div class="bar ${band(pct)}"><span style="width:${pct}%"></span></div>
    ${attempt && attempt.teacher_comment ? `<div class="teacher-note"><b>Your teacher says:</b> ${esc(attempt.teacher_comment)}</div>` : ""}
    ${attempt && attempt.teacher_score != null ? `<p class="small muted">Your teacher has reviewed this mark.</p>` : ""}
    <p><b>${esc(res.overall || "")}</b></p>
    ${res.parts.map(p => { const [cls, txt] = VERDICT[p.verdict] || ["", p.verdict]; return `<div class="fb-part ${cls}">
      <div class="row" style="justify-content:space-between"><span>${p.label ? `<span class="part-label">(${esc(p.label.replace(/[()]/g, ""))})</span>` : ""}<b>${txt}</b></span><span class="chip ${cls} num">${p.awarded}/${p.max}</span></div>
      <p>${esc(p.feedback)}</p>
      ${p.model_answer ? `<div class="model"><span class="eyebrow">Model answer</span><p>${rich(p.model_answer)}</p></div>` : ""}</div>`; }).join("")}
    ${res.key_terms && res.key_terms.length ? `<div class="stack" style="gap:6px"><span class="eyebrow">Key terms for full marks</span><div class="terms">${res.key_terms.map(t => `<span class="chip accent">${esc(t)}</span>`).join("")}</div></div>` : ""}
    <div class="actions">${st.revealed ? `<span class="small muted">Model answers shown. Later attempts count as practice after seeing them.</span>`
      : `<button class="btn" id="reveal">Show model answers</button><span class="small muted">Try improving your answer first - resubmit as often as you like.</span>`}</div>
    <div id="revealconfirm" class="notice" hidden>Once you see the model answers, any later attempts at this question are marked "after model answer" for your teacher. Show them now?
      <div class="actions" style="margin-top:8px"><button class="btn btn-primary btn-sm" id="revealyes">Show model answers</button><button class="btn btn-sm" id="revealno">Not yet</button></div></div>`;
  const rv = $("#reveal");
  if (rv) {
    rv.onclick = () => { $("#revealconfirm").hidden = false; };
    $("#revealno").onclick = () => { $("#revealconfirm").hidden = true; };
    $("#revealyes").onclick = async () => {
      const fresh = await api(`/api/question/${q.id}/reveal`, { json: {} });
      const a = fresh.attempts[fresh.attempts.length - 1];
      showResult(q, a.result, fresh, a);
    };
  }
}

function renderTutor(q, st) {
  const el = $("#tutor");
  const marked = st.attempts.length > 0;
  const sugg = marked ? ["Why did I lose marks?", "Explain the key idea simply", "Give me an exam tip for this"]
                      : ["Give me a hint", "What is this question really asking?", "Explain the key idea simply"];
  el.innerHTML = `<div><h2>Ask the tutor</h2><p class="small muted">${marked ? "Ask about your feedback or anything you're unsure of." : "Get hints without being given the answer."}</p></div>
    <div class="chat" id="chat">${st.chat.map(m => `<div class="msg ${m.role === "user" ? "user" : "assistant"}">${esc(m.content)}</div>`).join("")}</div>
    <div class="suggest">${sugg.map(s => `<button class="btn btn-sm" data-s="${esc(s)}">${esc(s)}</button>`).join("")}</div>
    <form id="chatf" class="stack" style="gap:8px"><textarea id="chatin" style="min-height:70px" placeholder="Ask a question about this…" maxlength="1500"></textarea>
      <button class="btn btn-primary btn-sm">Send</button></form><div id="chaterr" class="error" hidden></div>`;
  const chat = $("#chat"); chat.scrollTop = chat.scrollHeight;
  const send = async text => {
    if (!text.trim()) return;
    chat.append(h(`<div class="msg user">${esc(text)}</div>`));
    const wait = h(`<div class="msg assistant"><span class="thinking"><span class="dot"></span>Thinking…</span></div>`);
    chat.append(wait); chat.scrollTop = chat.scrollHeight; $("#chaterr").hidden = true;
    try {
      const r = await api(`/api/question/${q.id}/chat`, { json: { message: text } });
      wait.textContent = r.reply; refreshMe();
    } catch (e) { wait.remove(); $("#chaterr").hidden = false; $("#chaterr").textContent = e.message; }
    chat.scrollTop = chat.scrollHeight;
  };
  for (const b of $$("[data-s]", el)) b.onclick = () => send(b.dataset.s);
  $("#chatf").onsubmit = e => { e.preventDefault(); const t = $("#chatin").value; $("#chatin").value = ""; send(t); };
}

function renderPractice(q, st) {
  const el = $("#practice");
  const items = st.practice;
  el.innerHTML = `<div><h2>Practise more</h2><p class="small muted">A fresh exam-style question on the same skill, written and marked by the AI.</p></div>
    <div class="stack" id="plist">${items.map(practiceHtml).join("")}</div>
    <button class="btn" id="newp">${items.length ? "Another question" : "Give me a similar question"}</button><div id="perr" class="error" hidden></div>`;
  const wire = () => {
    for (const f of $$("form[data-pid]", el)) f.onsubmit = async e => {
      e.preventDefault();
      const b = $("button", f); busy(b, true, "Marking…"); $("#perr").hidden = true;
      try {
        const r = await api(`/api/practice/${f.dataset.pid}/submit`, { json: { answer: $("textarea", f).value } });
        const item = items.find(x => x.id == f.dataset.pid); item.answer = $("textarea", f).value; item.result = r.result;
        f.closest(".pitem").replaceWith(h(practiceHtml(item))); wire(); refreshMe();
      } catch (err) { $("#perr").hidden = false; $("#perr").textContent = err.message; busy(b, false); }
    };
  };
  wire();
  $("#newp").onclick = async e => {
    busy(e.target, true, "Writing a question…"); $("#perr").hidden = true;
    try { const p = await api(`/api/question/${q.id}/practice`, { json: {} }); items.push(p); $("#plist").append(h(practiceHtml(p))); wire(); refreshMe(); }
    catch (err) { $("#perr").hidden = false; $("#perr").textContent = err.message; }
    busy(e.target, false);
  };
}
function practiceHtml(p) {
  const r = p.result;
  return `<div class="pitem stack" style="gap:8px;border-top:1px dashed var(--line);padding-top:10px">
    <p>${rich(p.question)} <span class="marks">[${p.marks}]</span></p>
    ${r ? `<div class="model small">${esc(p.answer)}</div>
      ${r.parts.map(x => `<div class="fb-part ${(VERDICT[x.verdict] || [""])[0]}"><div class="row" style="justify-content:space-between"><b>${(VERDICT[x.verdict] || ["", ""])[1]}</b><span class="chip num">${x.awarded}/${x.max}</span></div>
        <p class="small">${esc(x.feedback)}</p><details><summary class="small">Model answer</summary><p class="small">${rich(x.model_answer)}</p></details></div>`).join("")}`
      : `<form data-pid="${p.id}" class="stack" style="gap:8px"><textarea placeholder="Your answer" style="min-height:90px"></textarea><button class="btn btn-primary btn-sm">Mark it</button></form>`}</div>`;
}

// ------------------------------------------------------------------ teacher
function teacherLogin() {
  topbar();
  app.innerHTML = `<div class="login stack"><div class="stack" style="gap:8px"><span class="eyebrow">Teacher</span><h1>Class dashboard</h1></div>
    <form class="card" id="f"><label class="field">Teacher password<input type="password" id="pw" autocomplete="current-password" required></label>
    <div id="err" class="error" hidden></div><button class="btn btn-primary">Sign in</button></form>
    <p class="small muted"><a href="#/login">Student sign-in</a></p></div>`;
  $("#f").onsubmit = async e => {
    e.preventDefault();
    try { await api("/api/teacher/login", { json: { password: $("#pw").value } }); await refreshMe(); go("#/teacher"); }
    catch (err) { $("#err").hidden = false; $("#err").textContent = err.message; }
  };
}
let TAB = "class";
async function teacherView() {
  topbar();
  await loadContent();
  const ov = await api("/api/teacher/overview");
  app.innerHTML = `<div class="stack" style="gap:18px">
    <div class="row" style="justify-content:space-between"><div class="stack" style="gap:6px"><span class="eyebrow">Teacher dashboard</span><h1>Class progress</h1></div>
      <a class="btn btn-sm no-print" href="/api/teacher/export.csv">Download all marks (CSV)</a></div>
    <div class="stats no-print">
      <div class="stat"><b>${ov.avatars.filter(a => a.answered).length}<span class="muted small"> / ${ov.avatars.length}</span></b><span class="muted small">avatars active</span></div>
      <div class="stat"><b>${ov.usage.today_requests}</b><span class="muted small">AI requests today (~$${ov.usage.today_cost})</span></div>
      <div class="stat"><b>${ov.usage.total_requests}</b><span class="muted small">AI requests in total (~$${ov.usage.total_cost})</span></div>
      <div class="stat"><b style="${ov.flags ? "color:var(--bad)" : ""}">${ov.flags}</b><span class="muted small">safeguarding flags to review</span></div>
    </div>
    <div class="tabs no-print" role="tablist">${[["class", "Class"], ["answers", "Answers"], ["flags", `Flags (${ov.flags})`], ["avatars", "Avatars"]]
      .map(([k, l]) => `<button class="tab" role="tab" data-tab="${k}" aria-selected="${TAB === k}">${l}</button>`).join("")}</div>
    <div id="tabbody"></div>
    <p class="small muted no-print">Model: ${esc(ov.model)} · limit ${ov.daily_limit} AI requests per student per day.</p></div>`;
  for (const b of $$("[data-tab]")) b.onclick = () => { TAB = b.dataset.tab; teacherView(); };
  const body = $("#tabbody");
  if (TAB === "class") tClass(body, ov);
  else if (TAB === "answers") tAnswers(body, ov);
  else if (TAB === "flags") tFlags(body);
  else tAvatars(body);
}
function heatCell(v) {
  if (!v || v[0] == null) return `<td class="hn">–</td>`;
  const cls = v[0] >= 70 ? "h2" : v[0] >= 40 ? "h1" : "h0";
  return `<td class="h ${cls}" title="${v[1]} answered">${v[0]}%</td>`;
}
function tClass(body, ov) {
  const secs = S.content.sections.map(s => s.n);
  const weak = ov.chapters.filter(c => c.answered).sort((a, b) => a.pct - b.pct).slice(0, 8);
  body.innerHTML = `<div class="stack" style="gap:18px"><div class="card-plain tbl-wrap"><table class="heat"><tr><th>Avatar</th>${secs.map(s => `<th title="${esc(S.sections[s].title)}">§${s}</th>`).join("")}<th>Answered</th><th>Last seen</th></tr>
    ${ov.avatars.map(a => `<tr><td><a href="#/teacher" data-av="${a.id}">${esc(a.name)}</a>${a.disabled ? ' <span class="chip">off</span>' : ""}</td>${secs.map(s => heatCell(a.sections[s])).join("")}
      <td class="num">${a.answered}</td><td class="small muted">${when(a.last_seen)}</td></tr>`).join("")}</table></div>
    <section class="card-plain stack"><h2>Weakest chapters across the class</h2>${weak.length ? `<div class="qlist">${weak.map(c => `<div class="qrow"><span class="qn">Ch ${c.ch}</span><span>${esc(c.title)} <span class="small muted">· ${c.answered} answers</span></span><span class="chip ${band(c.pct)} num">${c.pct}%</span></div>`).join("")}</div>`
      : `<p class="muted">No answers yet.</p>`}</section></div>`;
  for (const a of $$("[data-av]", body)) a.onclick = e => { e.preventDefault(); TAB = "answers"; ANS_FILTER.avatar = a.dataset.av; teacherView(); };
}
const ANS_FILTER = { avatar: "", ch: "", flagged: false };
async function tAnswers(body, ov) {
  const qs = new URLSearchParams(Object.entries(ANS_FILTER).filter(([, v]) => v).map(([k, v]) => [k, v === true ? "1" : v]));
  const d = await api(`/api/teacher/attempts?${qs}`);
  body.innerHTML = `<div class="stack"><div class="row">
      <select id="fav" style="width:auto"><option value="">All avatars</option>${ov.avatars.map(a => `<option value="${a.id}" ${ANS_FILTER.avatar == a.id ? "selected" : ""}>${esc(a.name)}</option>`).join("")}</select>
      <select id="fch" style="width:auto"><option value="">All chapters</option>${Object.values(S.chapters).map(c => `<option value="${c.n}" ${ANS_FILTER.ch == c.n ? "selected" : ""}>Ch ${c.n} ${esc(c.title)}</option>`).join("")}</select>
      <label class="row small" style="gap:6px"><input type="checkbox" id="ffl" ${ANS_FILTER.flagged ? "checked" : ""}> Flagged only</label></div>
    <div class="list">${d.attempts.length ? d.attempts.map(attemptCard).join("") : `<p class="muted">No answers match.</p>`}</div></div>`;
  $("#fav").onchange = e => { ANS_FILTER.avatar = e.target.value; tAnswers(body, ov); };
  $("#fch").onchange = e => { ANS_FILTER.ch = e.target.value; tAnswers(body, ov); };
  $("#ffl").onchange = e => { ANS_FILTER.flagged = e.target.checked; tAnswers(body, ov); };
  for (const f of $$("form[data-aid]", body)) f.onsubmit = async e => {
    e.preventDefault();
    const b = $("button", f); busy(b, true, "Saving…");
    try { await api(`/api/teacher/attempts/${f.dataset.aid}`, { json: { teacher_score: $("[name=ts]", f).value, teacher_comment: $("[name=tc]", f).value } }); b.textContent = "Saved"; }
    catch (err) { b.textContent = err.message; }
    b.disabled = false;
  };
}
function attemptCard(a) {
  const q = S.byId[a.qid] || {}, parts = q.id ? partsOf(q).filter(p => p.ans) : [];
  return `<details class="card-plain"><summary><span class="row" style="display:inline-flex;gap:10px">
      <b>${esc(a.avatar)}</b><span class="small muted">Ch ${q.ch} · ${esc(q.id ? qLabel(q) : a.qid)} · ${when(a.created)}</span>
      ${scoreChip(a.teacher_score ?? a.score, a.max)}${a.after_reveal ? '<span class="chip">after model answer</span>' : ""}${a.flagged && !a.flag_resolved ? '<span class="chip bad">flagged</span>' : ""}</span></summary>
    <div class="stack" style="margin-top:12px">
      <p class="small">${esc(snippet(q))}</p>
      ${a.result.parts.map((p, i) => { const ans = a.answer[parts[i] ? parts[i].key : String(i)] || {};
        return `<div class="fb-part ${(VERDICT[p.verdict] || [""])[0]}"><div class="row" style="justify-content:space-between"><b>${p.label ? "(" + esc(p.label.replace(/[()]/g, "")) + ") " : ""}Answer</b><span class="chip num">${p.awarded}/${p.max}</span></div>
          <p style="white-space:pre-wrap">${esc(ans.text || "")}${ans.cells ? "<br><span class=\"small muted\">Table: " + esc(Object.entries(ans.cells).map(([k, v]) => `[${k}] ${v}`).join(", ")) + "</span>" : ""}</p>
          ${ans.photo ? `<a href="/uploads/${esc(ans.photo)}" target="_blank" rel="noopener">View uploaded photo</a>` : ""}
          <p class="small muted"><b>AI feedback:</b> ${esc(p.feedback)}</p></div>`; }).join("")}
      ${a.answer.stem && a.answer.stem.cells ? `<p class="small muted">Stem table: ${esc(Object.entries(a.answer.stem.cells).map(([k, v]) => `[${k}] ${v}`).join(", "))}</p>` : ""}
      ${a.flagged ? `<div class="error"><b>Safeguarding flag:</b> ${esc(a.flag_note)}</div>` : ""}
      <form data-aid="${a.id}" class="row" style="align-items:flex-end">
        <label class="field" style="width:130px">Your mark /${a.max}<input type="number" name="ts" min="0" max="${a.max}" value="${a.teacher_score ?? ""}" placeholder="${a.score}"></label>
        <label class="field" style="flex:1;min-width:220px">Comment to student<input type="text" name="tc" value="${esc(a.teacher_comment || "")}" maxlength="2000"></label>
        <button class="btn btn-sm">Save</button></form></div></details>`;
}
async function tFlags(body) {
  const d = await api("/api/teacher/flags");
  body.innerHTML = `<div class="list">${d.flags.length ? d.flags.map(f => `<div class="card-plain stack" style="gap:8px">
      <div class="row" style="justify-content:space-between"><b>${esc(f.avatar)}</b><span class="small muted">${f.kind === "chat" ? "Tutor chat" : "Answer"} · ${esc(f.qid)} · ${when(f.created)}</span></div>
      <p class="error">${esc(f.note)}</p><p style="white-space:pre-wrap">${esc(f.text)}</p>
      <div><button class="btn btn-sm" data-res="${f.kind}/${f.id}">Mark as reviewed</button></div></div>`).join("")
    : `<p class="muted">Nothing to review. The AI flags answers or chat messages that suggest a student may be at risk, distressed or being bullied.</p>`}</div>`;
  for (const b of $$("[data-res]", body)) b.onclick = async () => { await api(`/api/teacher/flags/${b.dataset.res}/resolve`, { json: {} }); teacherView(); };
}
async function tAvatars(body) {
  const d = await api("/api/teacher/avatars");
  body.innerHTML = `<div class="stack">
    <div class="row no-print"><label class="row small" style="gap:8px">Add <input type="number" id="addn" value="5" min="1" max="100" style="width:80px"> avatars</label>
      <button class="btn btn-sm" id="add">Add</button><button class="btn btn-sm" id="print">Print sign-in cards</button></div>
    <p class="small muted no-print">Keep your own private list of which student has which avatar. The app never stores names.</p>
    <div class="card-plain tbl-wrap no-print"><table class="heat"><tr><th>Avatar</th><th>PIN</th><th>Last seen</th><th></th></tr>
      ${d.avatars.map(a => `<tr><td>${esc(a.name)}${a.disabled ? ' <span class="chip">off</span>' : ""}</td><td class="mono">${esc(a.pin)}</td><td class="small muted">${when(a.last_seen)}</td>
        <td><button class="btn btn-ghost btn-sm" data-pin="${a.id}">New PIN</button><button class="btn btn-ghost btn-sm" data-off="${a.id}" data-v="${a.disabled ? 0 : 1}">${a.disabled ? "Enable" : "Disable"}</button></td></tr>`).join("")}</table></div>
    <div class="avatar-cards" id="cards" hidden>${d.avatars.filter(a => !a.disabled).map(a => `<div class="avatar-card"><span class="eyebrow">H446 Revision Coach</span><b>${esc(a.name)}</b>
      <span class="mono">PIN ${esc(a.pin)}</span><p class="small muted">${esc(location.origin)}</p></div>`).join("")}</div></div>`;
  $("#add").onclick = async () => { await api("/api/teacher/avatars", { json: { count: +$("#addn").value } }); tAvatars(body); };
  $("#print").onclick = () => { $("#cards").hidden = false; window.print(); $("#cards").hidden = true; };
  for (const b of $$("[data-pin]", body)) b.onclick = async () => { await api(`/api/teacher/avatars/${b.dataset.pin}`, { json: { new_pin: true } }); tAvatars(body); };
  for (const b of $$("[data-off]", body)) b.onclick = async () => { await api(`/api/teacher/avatars/${b.dataset.off}`, { json: { disabled: b.dataset.v === "1" } }); tAvatars(body); };
}

route();
