const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
let token = localStorage.getItem("token"), docId = null;

async function api(path, opts = {}) {
  const headers = { Authorization: "Bearer " + token, ...(opts.body && !(opts.body instanceof FormData) ? { "Content-Type": "application/json" } : {}) };
  const r = await fetch(path, { ...opts, headers, body: opts.body instanceof FormData ? opts.body : opts.body && JSON.stringify(opts.body) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || "Request failed");
  return d;
}
async function busy(btn, fn) { btn.disabled = true; const t = btn.textContent; btn.textContent = "Working…"; try { await fn(); } catch (e) { alert(e.message); } btn.disabled = false; btn.textContent = t; }

// ---- auth ----
async function auth(kind) {
  const r = await fetch("/api/auth/" + kind, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: $("u").value, password: $("p").value }) });
  const d = await r.json();
  if (!r.ok) { $("autherr").textContent = typeof d.detail === "string" ? d.detail : "Check username (3+) and password (6+)"; return; }
  token = d.token; localStorage.setItem("token", token); localStorage.setItem("user", d.username); start();
}
$("login").onclick = () => auth("login"); $("register").onclick = () => auth("register");
$("logout").onclick = () => { localStorage.clear(); location.reload(); };
function start() {
  $("auth").classList.add("hidden"); $("app").classList.remove("hidden"); $("logout").classList.remove("hidden");
  $("who").textContent = localStorage.getItem("user"); loadDocs();
}

// ---- documents ----
async function loadDocs() {
  const docs = await api("/api/documents").catch(() => { localStorage.clear(); location.reload(); return []; });
  $("docs").innerHTML = docs.map(d => `<li><span>${esc(d.name)} <span class="muted">(${d.chars} chars)</span></span>
    <span><button class="ghost" data-open="${d.id}" data-name="${esc(d.name)}">Open</button> <button class="ghost" data-del="${d.id}">Delete</button></span></li>`).join("") || '<li class="muted">No documents yet.</li>';
}
$("docs").onclick = async e => {
  if (e.target.dataset.open) openDoc(+e.target.dataset.open, e.target.dataset.name);
  if (e.target.dataset.del && confirm("Delete this document and all learning data derived from it?")) { await api("/api/documents/" + e.target.dataset.del, { method: "DELETE" }); if (docId == e.target.dataset.del) $("workspace").classList.add("hidden"); loadDocs(); }
};
$("upload").onclick = () => busy($("upload"), async () => {
  const f = $("file").files[0]; if (!f) throw new Error("Choose a file first");
  const fd = new FormData(); fd.append("file", f); await api("/api/documents", { method: "POST", body: fd }); await loadDocs();
});
function openDoc(id, name) {
  docId = id; $("docname").textContent = name; $("workspace").classList.remove("hidden");
  $("answer").innerHTML = $("quizbox").innerHTML = $("conceptlist").innerHTML = $("dash").innerHTML = ""; loadConcepts();
}

// ---- tabs ----
document.querySelectorAll(".tabs button").forEach(b => b.onclick = () => {
  document.querySelectorAll(".tabs button").forEach(x => x.classList.toggle("on", x === b));
  ["ask", "learn", "dash"].forEach(t => $("tab-" + t).classList.toggle("hidden", t !== b.dataset.tab));
  if (b.dataset.tab === "dash") loadDash();
});

// ---- feature 5: document-restricted Q&A ----
$("askbtn").onclick = () => busy($("askbtn"), async () => {
  const d = await api(`/api/documents/${docId}/ask`, { method: "POST", body: { question: $("q").value } });
  $("answer").innerHTML = `<div class="item"><p>${esc(d.answer)}</p>${d.evidence ? `<div class="quote">Evidence: “${esc(d.evidence)}”</div>` : ""}</div>`;
});

// ---- concepts, quiz, re-teach ----
async function loadConcepts() {
  const d = await api(`/api/documents/${docId}/dashboard`);
  $("conceptlist").innerHTML = d.concepts.map(c => `<div class="item"><b>${esc(c.name)}</b> <span class="pill ${c.score.status}">${c.score.status}</span>
    <div class="muted">${esc(c.description)}${c.prereq_names.length ? " · needs: " + esc(c.prereq_names.join(", ")) : ""}</div>
    <div class="row"><button data-quiz="${c.id}">Quiz me</button>
    <button class="ghost" data-teach="${c.id}">Re-teach (beginner)</button><button class="ghost" data-teach="${c.id}" data-mode="example_first">Example-first</button></div></div>`).join("");
}
$("extract").onclick = () => busy($("extract"), async () => { await api(`/api/documents/${docId}/concepts/extract`, { method: "POST" }); await loadConcepts(); });
$("conceptlist").onclick = async e => {
  const t = e.target;
  if (t.dataset.quiz) busy(t, async () => showQuiz(await api(`/api/concepts/${t.dataset.quiz}/quiz`, { method: "POST", body: { n: 3 } })));
  if (t.dataset.teach) busy(t, async () => { const d = await api(`/api/concepts/${t.dataset.teach}/reteach`, { method: "POST", body: { mode: t.dataset.mode || "beginner" } }); $("quizbox").innerHTML = `<div class="item"><pre style="white-space:pre-wrap;font:inherit">${esc(d.explanation)}</pre></div>`; });
};
function showQuiz(d) {
  const note = d.targeted_misconceptions.length ? `<p class="muted">Targeting your recurring misconception: ${esc(d.targeted_misconceptions.join("; "))}</p>` : "";
  $("quizbox").innerHTML = `<h3>Quiz (${esc(d.difficulty)})</h3>${note}` + d.questions.map(q => `<div class="item" data-q="${q.id}"><b>${esc(q.question)}</b>
    <div class="muted">How sure are you? <select class="conf"><option value="1">Guessing</option><option value="2" selected>Fairly</option><option value="3">Very sure</option></select></div>
    ${q.options.map((o, i) => `<button class="opt" data-i="${i}">${esc(o)}</button>`).join("")}<div class="fb"></div></div>`).join("");
  $("quizbox").querySelectorAll(".item").forEach(box => box.onclick = async e => {
    if (!e.target.classList.contains("opt") || box.dataset.done) return; box.dataset.done = 1;
    const i = +e.target.dataset.i, conf = +box.querySelector(".conf").value;
    const r = await api(`/api/questions/${box.dataset.q}/answer`, { method: "POST", body: { chosen: i, confidence: conf, hints: 0 } });
    box.querySelectorAll(".opt")[r.correct_index].classList.add("right"); if (!r.correct) e.target.classList.add("wrong");
    box.querySelector(".fb").innerHTML = `<p>${r.correct ? "Correct." : "Not quite."} ${esc(r.explanation)}</p><div class="quote">Source: “${esc(r.evidence)}”</div>
      ${r.misconception ? `<p class="err">Misconception noted (seen ${r.misconception.count}×): ${esc(r.misconception.description)}</p>` : ""}
      <p class="muted">Concept mastery now: ${r.concept_score.mastery} (${r.concept_score.status})</p>`;
  });
}

// ---- dashboard ----
$("refresh").onclick = loadDash;
async function loadDash() {
  const d = await api(`/api/documents/${docId}/dashboard`);
  $("dash").innerHTML = `<h3>Next best actions</h3>` + (d.recommendations.map(r => `<div class="item"><b>${esc(r.action.replace("_", " "))}: ${esc(r.concept)}</b><div class="muted">${esc(r.reason)}</div></div>`).join("") || '<p class="muted">Take a quiz to get recommendations.</p>')
    + `<h3>Concept mastery</h3>` + d.concepts.map(c => `<div class="item"><b>${esc(c.name)}</b> <span class="pill ${c.score.status}">${c.score.status}</span>
      <div class="bar"><i style="width:${c.score.mastery ?? 0}%"></i></div>
      <span class="muted">${c.score.mastery ?? "no data"} mastery · evidence confidence ${c.score.confidence} · ${c.score.correct}/${c.score.attempts} correct</span></div>`).join("")
    + (d.recurring_misconceptions.length ? `<h3>Recurring misconceptions</h3>` + d.recurring_misconceptions.map(m => `<div class="item"><b>${esc(m.concept)}</b> (${m.count}×): ${esc(m.description)}</div>`).join("") : "");
}
if (token) start();
