const emailSelect = document.getElementById("customer-email");
const messageInput = document.getElementById("message");
const chatForm = document.getElementById("chat-form");
const sendButton = document.getElementById("send-button");
const conversation = document.getElementById("conversation");
const failureToggle = document.getElementById("simulate-failure");
const storedSessions = JSON.parse(localStorage.getItem("supportops_sessions") || "{}");
let busy = false;

function currentSession() {
  return storedSessions[emailSelect.value] || null;
}

function updateSessionIndicator() {
  const sessionId = currentSession();
  document.getElementById("session-state").textContent = sessionId ? "Session active" : "New session";
  document.getElementById("session-id").textContent = sessionId
    ? `ID ${sessionId.slice(0, 8)}…`
    : "Not started";
}

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text != null) element.textContent = text;
  return element;
}

function scrollToNewest() {
  conversation.lastElementChild?.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function appendUserMessage(message) {
  const wrapper = node("div", "message user");
  wrapper.append(node("div", "bubble", message));
  conversation.append(wrapper);
  scrollToNewest();
}

async function apiRequest(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${response.status}).`);
  }
  return body;
}

async function renderTrace(details, traceId, sessionId) {
  const content = details.querySelector(".trace-list");
  content.replaceChildren(node("div", "trace-loading", "Loading trace events…"));
  try {
    const trace = await apiRequest(`/api/traces/${encodeURIComponent(traceId)}?session_id=${encodeURIComponent(sessionId)}`);
    content.replaceChildren();
    trace.events.forEach((event) => {
      const row = node("div", `trace-row ${event.status || ""}`);
      row.append(node("span", "trace-dot"));
      const description = node("span", "trace-description", event.message);
      if (event.tool_name) description.append(node("small", "", event.tool_name));
      row.append(description);
      row.append(node("span", "trace-time", event.duration_ms == null ? "" : `${event.duration_ms} ms`));
      content.append(row);
    });
  } catch (error) {
    content.replaceChildren(node("div", "trace-loading", error.message));
  }
}

function renderResponse(payload) {
  const { response, trace_id: traceId, session_id: sessionId } = payload;
  const wrapper = node("article", "message assistant");
  const card = node("div", "answer-card");
  const main = node("div", "answer-main");
  const heading = node("div", "answer-heading");
  heading.append(node("strong", "", response.category ? `${response.category.replaceAll("_", " ")} response` : "Agent response"));
  heading.append(node("span", `status-tag ${response.status}`, response.status.replaceAll("_", " ")));
  main.append(heading, node("p", "answer-message", response.message));

  const meta = node("div", "answer-meta");
  meta.append(node("span", "meta-label", "TOOLS USED"));
  if (response.tools_used.length) {
    response.tools_used.forEach((toolName) => meta.append(node("span", "tool-pill", toolName.replaceAll("_", " "))));
  } else {
    meta.append(node("span", "no-tools", "None"));
  }
  if (response.ticket_id) meta.append(node("span", "ticket-reference", response.ticket_id));
  main.append(meta);

  if (response.confirmation_required && response.action) {
    const actions = node("div", "confirmation-actions");
    const approve = node("button", "confirm-button", `Confirm ${response.action.replaceAll("_", " ")}`);
    const decline = node("button", "decline-button", "Keep things as they are");
    approve.type = decline.type = "button";
    approve.addEventListener("click", () => submitConfirmation(traceId, true, actions));
    decline.addEventListener("click", () => submitConfirmation(traceId, false, actions));
    actions.append(approve, decline);
    main.append(actions);
  }
  card.append(main);

  const details = node("details", "trace-panel");
  const summary = node("summary");
  summary.append(node("span", "", "VIEW AGENT TRACE"), node("span", "", "⌄"));
  details.append(summary, node("div", "trace-list"));
  details.addEventListener("toggle", () => {
    if (details.open) renderTrace(details, traceId, sessionId);
  });
  card.append(details);
  wrapper.append(card);
  conversation.append(wrapper);
  scrollToNewest();
}

async function submitConfirmation(traceId, confirmed, actions) {
  if (busy) return;
  busy = true;
  actions.querySelectorAll("button").forEach((button) => { button.disabled = true; });
  try {
    const payload = await apiRequest("/api/confirm", {
      method: "POST",
      body: JSON.stringify({ session_id: currentSession(), trace_id: traceId, confirm: confirmed }),
    });
    actions.remove();
    renderResponse(payload);
  } catch (error) {
    renderResponse({
      session_id: currentSession(),
      trace_id: traceId,
      response: { status: "error", category: "system", message: error.message, tools_used: [] },
    });
    actions.querySelectorAll("button").forEach((button) => { button.disabled = false; });
  } finally {
    busy = false;
  }
}

async function sendMessage(event) {
  event.preventDefault();
  const message = messageInput.value.trim();
  if (!message || busy) return;
  busy = true;
  sendButton.disabled = true;
  sendButton.textContent = "Working…";
  appendUserMessage(message);
  messageInput.value = "";
  try {
    const payload = await apiRequest("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        session_id: currentSession(),
        customer_email: emailSelect.value,
        message,
        simulate_invoice_timeout: failureToggle.checked,
      }),
    });
    storedSessions[emailSelect.value] = payload.session_id;
    localStorage.setItem("supportops_sessions", JSON.stringify(storedSessions));
    updateSessionIndicator();
    renderResponse(payload);
  } catch (error) {
    const wrapper = node("div", "message assistant");
    const card = node("div", "answer-card");
    const main = node("div", "answer-main");
    main.append(node("strong", "", "Request could not complete"), node("p", "answer-message", error.message));
    card.append(main);
    wrapper.append(card);
    conversation.append(wrapper);
  } finally {
    busy = false;
    sendButton.disabled = false;
    sendButton.textContent = "Send message ↗";
    scrollToNewest();
    messageInput.focus();
  }
}

async function loadHealth() {
  try {
    const health = await apiRequest("/api/health");
    document.getElementById("service-state").textContent = "System ready";
    document.getElementById("provider-name").textContent = health.provider;
    failureToggle.disabled = health.provider !== "mock";
    if (health.provider !== "mock") failureToggle.checked = false;
  } catch {
    document.getElementById("service-state").textContent = "Service unavailable";
  }
}

chatForm.addEventListener("submit", sendMessage);
messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    chatForm.requestSubmit();
  }
});
emailSelect.addEventListener("change", updateSessionIndicator);
document.querySelectorAll("[data-prompt]").forEach((button) => {
  button.addEventListener("click", () => {
    messageInput.value = button.dataset.prompt;
    messageInput.focus();
  });
});
updateSessionIndicator();
loadHealth();