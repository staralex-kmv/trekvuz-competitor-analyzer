// Состояние интерфейса и вызовы бэкенда
const state = { busy: false, competitors: {} };
const $ = (id) => document.getElementById(id);

const LABELS = {
  strengths: "Сильные стороны", weaknesses: "Слабые стороны", unique_offers: "Уникальные предложения",
  recommendations: "Рекомендации для Трек ВУЗ", marketing_insights: "Маркетинговые инсайты", trust_signals: "Сигналы доверия",
};
const SCORES = {
  data_trust_score: "доверие к данным", threat_level: "угроза для нас",
  visual_style_score: "визуальный стиль", design_score: "дизайн/UX", trust_score: "доверие (визуально)",
};

function esc(s) { return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

function setBusy(on, text = "Анализ…") {
  state.busy = on;
  $("progress").hidden = !on;
  $("progress-text").textContent = text;
  document.querySelectorAll("button.primary").forEach((b) => (b.disabled = on));
}

function showError(msg) { $("error").hidden = !msg; $("error").textContent = msg || ""; }

async function api(path, options = {}) {
  const r = await fetch(path, options);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || `HTTP ${r.status}`);
  return body;
}

function renderAnalysis(a, title, meta = "") {
  if (!a) return "";
  const scores = Object.keys(SCORES).filter((k) => k in a)
    .map((k) => `<span class="score"><b>${a[k]}</b>/10 ${SCORES[k]}</span>`).join("");
  const lists = Object.keys(LABELS).filter((k) => a[k]?.length)
    .map((k) => `<div><h4>${LABELS[k]}</h4><ul>${a[k].map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>`).join("");
  const text = [a.summary, a.description, a.visual_style_analysis, a.data_trust_reason && `Доверие к данным: ${a.data_trust_reason}`]
    .filter(Boolean).map((t) => `<p>${esc(t)}</p>`).join("");
  return `<div class="card"><h3>${esc(title)}</h3>${meta ? `<div class="meta">${meta}</div>` : ""}
    <div class="scores">${scores}</div>${text}<div class="grid">${lists}</div></div>`;
}

function renderParse(p) {
  if (p.error && !p.text_analysis && !p.image_analysis)
    return `<div class="card"><h3>${esc(p.competitor)}</h3><div class="meta">${esc(p.url)}</div><p style="color:var(--bad)">${esc(p.error)}</p></div>`;
  const meta = `<a href="${esc(p.url)}" target="_blank">${esc(p.url)}</a> · ${p.text_chars} символов текста` +
    (p.pdf ? ` · <a href="/${esc(p.pdf)}" target="_blank">PDF страницы</a>` : "") + (p.error ? ` · ⚠️ ${esc(p.error)}` : "");
  const shot = p.screenshot ? `<img class="shot" src="/${esc(p.screenshot)}" alt="скриншот">` : "";
  return `<div class="card"><h3>${esc(p.competitor)} — ${esc(p.title)}</h3><div class="meta">${meta}</div>${shot}</div>` +
    renderAnalysis(p.text_analysis, `${p.competitor}: анализ текста сайта`) +
    renderAnalysis(p.image_analysis, `${p.competitor}: анализ скриншота`);
}

async function run(label, fn) {
  if (state.busy) return;
  showError(""); $("result").innerHTML = "";
  setBusy(true, label);
  const t0 = performance.now();
  try { await fn(); } catch (e) { showError(e.message); } finally { setBusy(false); }
  console.log(`${label}: ${((performance.now() - t0) / 1000).toFixed(1)} с`);
}

function upload(path, fileInput, competitorInput) {
  const f = $(fileInput).files[0];
  if (!f) throw new Error("Выберите файл");
  const fd = new FormData();
  fd.append("file", f);
  fd.append("competitor", $(competitorInput).value);
  return api(path, { method: "POST", body: fd });
}

$("text-go").onclick = () => run("Анализ текста…", async () => {
  const r = await api("/analyze/text", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: $("text-input").value, competitor: $("text-competitor").value }) });
  $("result").innerHTML = renderAnalysis(r.result, $("text-competitor").value || "Анализ текста", `${r.tokens} токенов`);
});

$("image-go").onclick = () => run("Загрузка и анализ изображения…", async () => {
  const r = await upload("/analyze/image", "image-file", "image-competitor");
  $("result").innerHTML = renderAnalysis(r.result, $("image-competitor").value || "Анализ изображения", `${r.tokens} токенов`);
});

$("pdf-go").onclick = () => run("Извлечение текста из PDF и анализ…", async () => {
  const r = await upload("/analyze/pdf", "pdf-file", "pdf-competitor");
  $("result").innerHTML = renderAnalysis(r.result, $("pdf-competitor").value || "Анализ PDF", `${r.chars} символов · ${r.tokens} токенов`);
});

$("parse-go").onclick = () => run("Chrome открывает сайт(ы), затем GigaChat анализирует текст и скриншот… (до минуты на сайт)", async () => {
  const url = $("parse-url").value.trim();
  const r = await api("/parse/demo", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url: url || null, competitor: $("parse-competitor").value }) });
  $("result").innerHTML = r.map(renderParse).join("");
});

async function loadHistory() {
  const items = await api("/history");
  $("history-list").innerHTML = items.length ? items.map((h) => `<div class="hist" data-id="${h.id}">
      <span class="tag">${h.kind}</span><b>${esc(h.competitor || "—")}</b> · ${new Date(h.created_at).toLocaleString("ru")}
      · ${h.tokens} ток. <div class="meta">${esc(h.input_preview)}</div></div>`).join("") : "<p>История пуста</p>";
  document.querySelectorAll(".hist").forEach((el) => (el.onclick = () => {
    const h = items.find((x) => x.id == el.dataset.id);
    $("result").innerHTML = h.kind === "parse" ? renderParse(h.result) : renderAnalysis(h.result, h.competitor || h.kind);
  }));
}
$("history-refresh").onclick = () => loadHistory().catch((e) => showError(e.message));
$("history-clear").onclick = async () => { if (confirm("Очистить историю?")) { await api("/history", { method: "DELETE" }); loadHistory(); } };

document.querySelectorAll("#tabs button").forEach((b) => (b.onclick = () => {
  document.querySelectorAll("#tabs button, .tab").forEach((x) => x.classList.remove("active"));
  b.classList.add("active");
  $(`tab-${b.dataset.tab}`).classList.add("active");
  $("result").innerHTML = ""; showError("");
  if (b.dataset.tab === "history") loadHistory().catch((e) => showError(e.message));
}));

api("/competitors").then((c) => {
  state.competitors = c;
  $("competitor-list").innerHTML = Object.entries(c).map(([n, u]) => `<button data-url="${esc(u)}">${esc(n)}</button>`).join("");
  document.querySelectorAll("#competitor-list button").forEach((b) => (b.onclick = () => {
    $("parse-url").value = b.dataset.url; $("parse-competitor").value = b.textContent;
  }));
});
