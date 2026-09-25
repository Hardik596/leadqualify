// Sales desk front end. Plain JS against the FastAPI endpoints in app/main.py.
// Only POST /leads/{id}/messages reaches Gemini; everything else is free.

const $ = (id) => document.getElementById(id);

const SOURCE_LABEL = { whatsapp: "WhatsApp", indiamart: "IndiaMART", email: "Email", web: "Website" };
const FIELDS = [
  ["name", "Name"],
  ["company", "Company"],
  ["product_interest", "Product"],
  ["quantity", "Quantity"],
  ["budget_inr", "Budget"],
  ["timeline", "Timeline"],
  ["city", "City"],
];

let leads = [];
let currentId = null;
let sending = false;
// Tool names used per assistant turn, for turns sent in this browser session.
// The API stores tool calls per lead, not per turn, so older turns just show the log.
const usedByTurn = {};

// ---------- api ----------

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "content-type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch (_) { /* not json */ }
    throw new Error(detail);
  }
  return res.json();
}

// ---------- sent-today counter (per browser) ----------

function todayKey() {
  return "sent:" + new Date().toISOString().slice(0, 10);
}
function readSent() {
  try { return Number(localStorage.getItem(todayKey())) || 0; } catch (_) { return 0; }
}
function bumpSent() {
  const n = readSent() + 1;
  try { localStorage.setItem(todayKey(), String(n)); } catch (_) { /* storage blocked */ }
  $("sent-today").textContent = n;
}

// ---------- formatting ----------

const inr = new Intl.NumberFormat("en-IN");

function fmtValue(key, value) {
  if (value === null || value === undefined || value === "") return null;
  if (key === "budget_inr") return "₹" + inr.format(value);
  if (key === "quantity") return inr.format(value) + " units";
  return String(value);
}

function fmtTime(iso) {
  const d = new Date(iso);
  return d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
}

function statusLabel(s) {
  return s.replace("_", " ");
}

function latestScore(lead) {
  for (let i = lead.tool_calls.length - 1; i >= 0; i--) {
    const call = lead.tool_calls[i];
    if (call.name !== "score_lead") continue;
    try { return JSON.parse(call.result); } catch (_) { return null; }
  }
  return null;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// ---------- rendering ----------

function renderInbox() {
  const list = $("lead-list");
  list.replaceChildren();
  $("inbox-empty").hidden = leads.length > 0;

  // newest first
  [...leads].reverse().forEach((lead) => {
    const q = lead.qualification;
    const li = el("li");
    if (lead.id === currentId) li.classList.add("active");

    const top = el("div", "lead-top");
    const id = el("span", "lead-id");
    const dot = el("span", "dot");
    dot.dataset.status = q.status;
    id.append(dot, lead.id);
    top.append(id, el("span", "lead-time", fmtTime(lead.created_at)));

    const bits = [SOURCE_LABEL[lead.source] || lead.source];
    if (q.product_interest) bits.push(q.product_interest);
    else if (lead.history.length === 0) bits.push("no messages");
    bits.push(statusLabel(q.status));

    li.append(top, el("div", "lead-sub", bits.join(" · ")));
    li.addEventListener("click", () => selectLead(lead.id));
    list.append(li);
  });
}

function renderThread(lead) {
  $("thread-empty").hidden = true;
  $("thread-live").hidden = false;
  $("thread-id").textContent = lead.id;
  $("thread-source").textContent = SOURCE_LABEL[lead.source] || lead.source;
  $("thread-started").textContent = "opened " + fmtTime(lead.created_at);

  const box = $("messages");
  box.replaceChildren();
  lead.history.forEach((turn, i) => box.append(messageNode(turn.role, turn.content, usedByTurn[lead.id + ":" + i])));
  box.scrollTop = box.scrollHeight;
}

function messageNode(role, content, used) {
  const li = el("li", "msg " + role);
  li.append(el("div", "who", role === "user" ? "Customer" : "Priya"));
  li.append(el("div", "body", content));
  if (used && used.length) li.append(el("div", "used", "checked " + used.join(", ")));
  return li;
}

function renderSheet(lead) {
  const q = lead ? lead.qualification : { status: "new", missing_fields: [] };
  const stamp = $("status-stamp");
  stamp.dataset.status = q.status;
  stamp.textContent = statusLabel(q.status);

  const fields = $("fields");
  fields.replaceChildren();
  FIELDS.forEach(([key, label]) => {
    const row = el("div", "field");
    if (lead && q.missing_fields.includes(key)) row.classList.add("missing");
    const value = lead ? fmtValue(key, q[key]) : null;
    const dd = el("dd", value ? "" : "empty", value || "—");
    if (value && (key === "quantity" || key === "budget_inr")) dd.classList.add("num");
    row.append(el("dt", "", label), dd);
    fields.append(row);
  });

  const score = lead ? latestScore(lead) : null;
  $("score-box").hidden = !score;
  if (score) {
    $("score-num").textContent = score.score;
    $("score-tier").textContent = score.tier;
    $("score-tier").dataset.tier = score.tier;
    $("score-bar").style.width = Math.max(0, Math.min(100, score.score)) + "%";
    $("score-reason").textContent = score.reason;
  }

  const tools = $("tool-list");
  tools.replaceChildren();
  const calls = lead ? lead.tool_calls : [];
  $("tool-empty").hidden = calls.length > 0;
  $("tool-count").textContent = calls.length ? `(${calls.length})` : "";
  calls.forEach((call) => {
    const li = el("li");
    const details = el("details");
    const args = Object.entries(call.args).map(([k, v]) => `${k}: ${JSON.stringify(v)}`).join(", ");
    details.append(el("summary", "", `${call.name}(${args})`));
    let pretty = call.result;
    try { pretty = JSON.stringify(JSON.parse(call.result), null, 2); } catch (_) { /* leave as is */ }
    details.append(el("pre", "", pretty));
    li.append(details);
    tools.append(li);
  });
}

function showError(message) {
  const box = $("error");
  box.hidden = !message;
  box.textContent = message ? message + " — your message was not saved. Press Send when you want to try again." : "";
}

// ---------- actions ----------

async function loadLeads() {
  try {
    leads = await api("/leads");
    setServer(true);
  } catch (_) {
    setServer(false);
    return;
  }
  renderInbox();
  // Restore the lead named in the URL (#<id>) on first load, so a refresh keeps your place.
  if (!currentId && location.hash.length > 1 && leads.some((l) => l.id === location.hash.slice(1))) {
    selectLead(location.hash.slice(1));
    return;
  }
  const current = leads.find((l) => l.id === currentId);
  if (current) {
    renderThread(current);
    renderSheet(current);
  }
}

function selectLead(id) {
  currentId = id;
  history.replaceState(null, "", "#" + id);
  const lead = leads.find((l) => l.id === id);
  showError(null);
  renderInbox();
  renderThread(lead);
  renderSheet(lead);
  $("input").focus();
}

async function createLead(event) {
  event.preventDefault();
  try {
    // No first_message on purpose: creating a lead should not spend a Gemini request.
    const lead = await api("/leads", {
      method: "POST",
      body: JSON.stringify({ source: $("new-source").value }),
    });
    leads.push(lead);
    selectLead(lead.id);
  } catch (err) {
    alert("Could not open a lead: " + err.message);
  }
}

async function sendMessage(event) {
  event.preventDefault();
  if (sending || !currentId) return;
  const input = $("input");
  const content = input.value.trim();
  if (!content) return;

  sending = true;
  $("send").disabled = true;
  $("send").textContent = "Sending…";
  showError(null);

  const box = $("messages");
  const mine = messageNode("user", content);
  const waiting = messageNode("assistant", "Priya is typing…");
  waiting.classList.add("pending");
  box.append(mine, waiting);
  box.scrollTop = box.scrollHeight;
  input.value = "";

  const leadId = currentId;
  try {
    bumpSent();
    const res = await api(`/leads/${leadId}/messages`, {
      method: "POST",
      body: JSON.stringify({ content }),
    });
    const lead = await api(`/leads/${leadId}`);
    usedByTurn[leadId + ":" + (lead.history.length - 1)] = res.tool_calls.map((c) => c.name);
    leads = leads.map((l) => (l.id === leadId ? lead : l));
    renderInbox();
    if (currentId === leadId) {
      renderThread(lead);
      renderSheet(lead);
    }
  } catch (err) {
    mine.remove();
    waiting.remove();
    if (currentId === leadId) input.value = content;
    showError(err.message);
  } finally {
    sending = false;
    $("send").disabled = false;
    $("send").textContent = "Send";
  }
}

function setServer(up) {
  const node = $("server-state");
  node.className = "server-state " + (up ? "up" : "down");
  node.textContent = up ? "server running" : "server not reachable";
}

// ---------- wire up ----------

$("sent-today").textContent = readSent();
$("new-lead").addEventListener("submit", createLead);
$("composer").addEventListener("submit", sendMessage);
$("refresh").addEventListener("click", loadLeads);
$("input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    $("composer").requestSubmit();
  }
});

renderSheet(null);
loadLeads();
