const API_BASE = "/api/v1";

let state = {
  tickets: [],
  jobs: [],
  customers: [],
  drafts: [],
  currentView: "dashboard",
  simulator: {
    customerId: "",
    threadId: "",
    ticketId: "",
    messages: [],
    draft: null,
    conversations: {},
  },
};

function $(selector) {
  return document.querySelector(selector);
}

function $$ (selector) {
  return document.querySelectorAll(selector);
}

async function get(path) {
  const res = await fetch(API_BASE + path);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

async function post(path, body) {
  const res = await fetch(API_BASE + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

function formatDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

function badge(text) {
  const cls = `badge-${String(text).toLowerCase()}`;
  return `<span class="badge ${cls}">${text}</span>`;
}

function truncate(text, len = 40) {
  if (!text) return "";
  return text.length > len ? text.slice(0, len) + "..." : text;
}

function showToast(message, type = "info") {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 3000);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderSimulatorMessages() {
  const messages = state.simulator.messages;
  const customerChat = $("#sim-customer-chat");
  const threadChat = $("#sim-thread-messages");
  if (!messages.length) {
    customerChat.innerHTML = '<div class="chat-placeholder">No messages yet. Type a message below to start the conversation.</div>';
    threadChat.innerHTML = '<div class="chat-placeholder">Thread history will appear here.</div>';
    return;
  }
  const messageHtml = messages.map((message) => `
    <div class="chat-bubble ${message.sender === "customer" ? "customer" : message.sender === "system" ? "system" : "agent"}">
      <div class="chat-bubble-meta">${message.sender === "customer" ? "Customer" : message.sender === "system" ? "Status" : "Support desk"}</div>
      <div>${escapeHtml(message.body).replaceAll("\\n", "<br>")}</div>
    </div>`).join("");
  customerChat.innerHTML = messageHtml;
  threadChat.innerHTML = messageHtml;
  customerChat.scrollTop = customerChat.scrollHeight;
  threadChat.scrollTop = threadChat.scrollHeight;
}

function renderSimulatorCustomer() {
  const customer = state.customers.find((item) => item.id === state.simulator.customerId);
  $("#sim-customer-info").textContent = customer
    ? `${customer.name} · ${customer.email} · Conversation thread ${state.simulator.threadId || "will be created on first message"}`
    : "Select a customer above to start multi-turn conversation testing.";
  renderSimulatorMessages();
}

function loadSimulatorCustomers() {
  const select = $("#sim-customer-select");
  if (!select) return;
  if (!state.customers.length) {
    get("/customers").then((data) => {
      state.customers = data.customers;
      loadSimulatorCustomers();
    }).catch((err) => showToast(err.message, "error"));
    return;
  }
  select.innerHTML = '<option value="">Choose one of the five test customers...</option>' +
    state.customers.slice(0, 5).map((customer) => `<option value="${escapeHtml(customer.id)}">${escapeHtml(customer.name)} (${escapeHtml(customer.id)})</option>`).join("");
  select.value = state.simulator.customerId;
  renderSimulatorCustomer();
}

async function resetSimulatorThread(customerId) {
  state.simulator = { customerId, threadId: "", ticketId: "", messages: [], draft: null, conversations: state.simulator.conversations || {} };
  renderSimulatorCustomer();
  if (!customerId) return;
  try {
    const data = await get(`/simulator/conversations?customer_id=${encodeURIComponent(customerId)}`);
    const previous = data.conversations?.[0];
    if (previous) {
      state.simulator.threadId = previous.thread_id;
      state.simulator.ticketId = previous.ticket_id || "";
      state.simulator.messages = previous.messages.map((message) => ({
        sender: message.sender_type === "customer" ? "customer" : "agent",
        body: message.content,
      }));
      renderSimulatorCustomer();
    }
  } catch (err) { showToast(err.message, "error"); }
}

function newSimulatorConversation() {
  const customerId = state.simulator.customerId;
  if (!customerId) return showToast("Select a customer first", "error");
  resetSimulatorThread(customerId);
}

async function sendSimulatorMessage() {
  const input = $("#sim-msg-input");
  const message = input.value.trim();
  if (!state.simulator.customerId) return showToast("Select a customer first", "error");
  if (!message) return showToast("Type a message first", "error");
  const customer = state.customers.find((item) => item.id === state.simulator.customerId);
  try {
    $("#sim-send-btn").disabled = true;
    const result = await post("/customer-inquiries/draft-reply", {
      customer_id: state.simulator.customerId,
      message,
      title: "Simulator conversation",
      ticket_id: state.simulator.ticketId || null,
      email_thread_id: state.simulator.threadId || null,
    });
    state.simulator.ticketId = result.draft.ticket_id;
    state.simulator.threadId = state.simulator.threadId || `thread-${state.simulator.ticketId}`;
    state.simulator.messages.push({ sender: "customer", body: message });
    state.simulator.draft = result.draft;
    input.value = "";
    renderSimulatorCustomer();
    state.simulator.messages.push({
      sender: "system",
      body: "Your message was received and is waiting for support approval.",
    });
    state.simulator.conversations[state.simulator.threadId] = [...state.simulator.messages];
    renderSimulatorCustomer();
    showToast("Message sent to support for approval");
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    $("#sim-send-btn").disabled = false;
  }
}

function renderSimulatorDraft(draft, response, customer) {
  $("#sim-draft-box").innerHTML = `
    <div class="draft-card">
      <div class="draft-card-header"><strong>Draft reply for ${escapeHtml(customer?.name || draft.customer_id)}</strong>${badge("human_review")}</div>
      <p class="draft-inquiry-text">${escapeHtml(response)}</p>
      <div class="actions">
        <button class="btn btn-success" onclick="approveSimulatorDraft('${draft.id}')">Approve &amp; Send to Customer</button>
        <button class="btn btn-danger" onclick="rejectSimulatorDraft('${draft.id}')">Reject</button>
      </div>
    </div>`;
}

async function approveSimulatorDraft(draftId) {
  try {
    const result = await post(`/support/email-drafts/${draftId}/approve`, { reviewer: "support-desk" });
    const body = result.final_sent_message || result.body || "";
    state.simulator.messages.push({ sender: "agent", body });
    state.simulator.draft = null;
    $("#sim-draft-box").innerHTML = '<div class="empty-state success-text">Approved and sent. The customer can now see this reply.</div>';
    renderSimulatorCustomer();
    showToast("Reply approved and sent to the customer");
    loadDashboard();
  } catch (err) { showToast(err.message, "error"); }
}

async function rejectSimulatorDraft(draftId) {
  try {
    await post(`/support/email-drafts/${draftId}/reject`, { reviewer: "support-desk", reason: "Rejected from simulator" });
    state.simulator.draft = null;
    $("#sim-draft-box").innerHTML = '<div class="empty-state">Draft rejected. Send another customer message to try again.</div>';
    showToast("Draft rejected");
  } catch (err) { showToast(err.message, "error"); }
}

async function pollSimulatorApproval() {
  if (state.currentView !== "simulator" || !state.simulator.draft) return;
  try {
    const data = await get("/support/email-drafts");
    if (!data.drafts.some((draft) => draft.id === state.simulator.draft.id)) {
      const sentData = await get(`/support/sent-emails?customer_id=${encodeURIComponent(state.simulator.customerId)}`);
      const sent = sentData.sent_emails?.find((email) => email.ticket_id === state.simulator.ticketId);
      if (sent) {
        state.simulator.messages = state.simulator.messages.filter((message) => message.sender !== "system");
        state.simulator.messages.push({ sender: "agent", body: sent.body });
        state.simulator.draft = null;
        renderSimulatorCustomer();
        showToast("Support approved and sent a reply");
      }
    }
  } catch (err) { console.warn("Simulator approval polling failed", err); }
}

function setLoading(view, loading) {
  const el = $(`#view-${view}`);
  if (loading) {
    el.innerHTML = `<div class="empty-state">Loading...</div>`;
  }
}

async function loadDashboard() {
  try {
    const [tickets, jobs, customers, drafts] = await Promise.all([
      get("/tickets"),
      get("/jobs"),
      get("/customers"),
      get("/support/email-drafts?status=human_review"),
    ]);
    state = { ...state, tickets: tickets.tickets, jobs: jobs.jobs, customers: customers.customers, drafts: drafts.drafts };
    renderDashboard();
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function loadTickets() {
  try {
    const data = await get("/tickets");
    state.tickets = data.tickets;
    renderTickets();
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function loadJobs() {
  try {
    const data = await get("/jobs");
    state.jobs = data.jobs;
    renderJobs();
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function loadCustomers() {
  try {
    const data = await get("/customers");
    state.customers = data.customers;
    renderCustomers();
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function loadDrafts() {
  try {
    const data = await get("/support/email-drafts");
    state.drafts = data.drafts;
    renderDrafts();
  } catch (err) {
    showToast(err.message, "error");
  }
}

function renderDashboard() {
  const { tickets, jobs, customers, drafts } = state;
  const pendingDrafts = drafts.filter((d) => d.status === "human_review").length;
  const openTickets = tickets.filter((t) => t.status !== "resolved" && t.status !== "closed").length;
  $("#dashboard-cards").innerHTML = `
    <div class="card"><h3>Open Tickets</h3><div class="value">${openTickets}</div></div>
    <div class="card"><h3>Jobs</h3><div class="value">${jobs.length}</div></div>
    <div class="card"><h3>Customers</h3><div class="value">${customers.length}</div></div>
    <div class="card"><h3>Drafts Awaiting Approval</h3><div class="value">${pendingDrafts}</div></div>
  `;

  const tbody = $("#dashboard-drafts-table tbody");
  if (!drafts.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="empty-state">No drafts awaiting approval</td></tr>`;
    return;
  }
  tbody.innerHTML = drafts
    .map(
      (d) => `
    <tr>
      <td>${d.id}</td>
      <td>${d.customer_id}</td>
      <td>${badge(d.status)}</td>
      <td>${formatDate(d.created_at)}</td>
      <td>
        <button class="btn btn-secondary btn-small" onclick="showDraftDetail('${d.id}')">Review</button>
        <button class="btn btn-warning btn-small" onclick="showDraftDetail('${d.id}', true)">Edit</button>
        <button class="btn btn-success btn-small" onclick="approveDraft('${d.id}')">Approve</button>
        <button class="btn btn-danger btn-small" onclick="rejectDraft('${d.id}')">Reject</button>
      </td>
    </tr>
  `
    )
    .join("");
}

function renderTickets() {
  const tbody = $("#tickets-table tbody");
  const filter = $("#ticket-filter").value.toLowerCase();
  const filtered = state.tickets.filter(
    (t) =>
      !filter ||
      t.title.toLowerCase().includes(filter) ||
      t.id.toLowerCase().includes(filter) ||
      t.customer_id.toLowerCase().includes(filter)
  );

  if (!filtered.length) {
    tbody.innerHTML = `<tr><td colspan="8" class="empty-state">No tickets found</td></tr>`;
    return;
  }
  tbody.innerHTML = filtered
    .map(
      (t) => `
    <tr>
      <td>${t.id}</td>
      <td>${truncate(t.title)}</td>
      <td>${t.customer_id}</td>
      <td>${badge(t.status)}</td>
      <td>${badge(t.intent || "GENERAL_INQUIRY")}</td>
      <td>${badge(t.priority)}</td>
      <td>${formatDate(t.created_at)}</td>
      <td>
        <button class="btn btn-secondary btn-small" onclick="showTicketDetail('${t.id}')">View</button>
      </td>
    </tr>
  `
    )
    .join("");
}

function renderJobs() {
  const tbody = $("#jobs-table tbody");
  const filter = $("#job-filter").value.toLowerCase();
  const filtered = state.jobs.filter(
    (j) =>
      !filter ||
      j.title.toLowerCase().includes(filter) ||
      j.id.toLowerCase().includes(filter) ||
      j.customer_id.toLowerCase().includes(filter)
  );

  if (!filtered.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="empty-state">No jobs found</td></tr>`;
    return;
  }
  tbody.innerHTML = filtered
    .map(
      (j) => `
    <tr>
      <td>${j.id}</td>
      <td>${truncate(j.title)}</td>
      <td>${j.customer_id}</td>
      <td>${badge(j.status)}</td>
      <td>${j.required_skill || "—"}</td>
      <td>${formatDate(j.scheduled_at)}</td>
      <td>
        <button class="btn btn-secondary btn-small" onclick="showJobDetail('${j.id}')">View</button>
      </td>
    </tr>
  `
    )
    .join("");
}

function renderCustomers() {
  const tbody = $("#customers-table tbody");
  if (!state.customers.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="empty-state">No customers found</td></tr>`;
    return;
  }
  tbody.innerHTML = state.customers
    .map(
      (c) => `
    <tr>
      <td>${c.id}</td>
      <td>${c.name}</td>
      <td>${c.email}</td>
      <td>${c.phone}</td>
      <td>${c.company}</td>
    </tr>
  `
    )
    .join("");
}

function renderDrafts() {
  const tbody = $("#drafts-table tbody");
  if (!state.drafts.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty-state">No drafts found</td></tr>`;
    return;
  }
  tbody.innerHTML = state.drafts
    .map(
      (d) => `
    <tr>
      <td>${d.id}</td>
      <td>${d.ticket_id}</td>
      <td>${d.customer_id}</td>
      <td>${badge(d.status)}</td>
      <td>${formatDate(d.created_at)}</td>
      <td>
        <button class="btn btn-secondary btn-small" onclick="showDraftDetail('${d.id}')">Review</button>
        <button class="btn btn-warning btn-small" onclick="showDraftDetail('${d.id}', true)">Edit</button>
        <button class="btn btn-success btn-small" onclick="approveDraft('${d.id}')">Approve</button>
        <button class="btn btn-danger btn-small" onclick="rejectDraft('${d.id}')">Reject</button>
      </td>
    </tr>
  `
    )
    .join("");
}

async function showTicketDetail(ticketId) {
  try {
    const context = await get(`/tickets/${ticketId}/context`);
    const t = context.ticket || {};
    openModal(
      `Ticket ${t.id}`,
      `
      <dl>
        <dt>Title</dt><dd>${t.title}</dd>
        <dt>Description</dt><dd>${t.description}</dd>
        <dt>Customer</dt><dd>${t.customer_id}</dd>
        <dt>Status</dt><dd>${badge(t.status)}</dd>
        <dt>Intent</dt><dd>${badge(t.intent || "GENERAL_INQUIRY")}</dd>
        <dt>Priority</dt><dd>${badge(t.priority)}</dd>
        <dt>Handled By</dt><dd>${t.handled_by}</dd>
        <dt>Created</dt><dd>${formatDate(t.created_at)}</dd>
      </dl>
      <div class="actions">
        <button class="btn btn-primary" onclick="openCreateJobForTicket('${t.id}', '${t.customer_id}')">Create Job</button>
      </div>
    `
    );
  } catch (err) {
    showToast(err.message, "error");
  }
}

function showJobDetail(jobId) {
  const job = state.jobs.find((j) => j.id === jobId);
  if (!job) return;
  openModal(
    `Job ${job.id}`,
    `
    <dl>
      <dt>Title</dt><dd>${job.title}</dd>
      <dt>Description</dt><dd>${job.description}</dd>
      <dt>Customer</dt><dd>${job.customer_id}</dd>
      <dt>Status</dt><dd>${badge(job.status)}</dd>
      <dt>Skill</dt><dd>${job.required_skill || "—"}</dd>
      <dt>Area</dt><dd>${job.service_area || "—"}</dd>
      <dt>Priority</dt><dd>${badge(job.priority)}</dd>
      <dt>Scheduled</dt><dd>${formatDate(job.scheduled_at)}</dd>
      <dt>Created</dt><dd>${formatDate(job.created_at)}</dd>
    </dl>
  `
  );
}

async function showDraftDetail(draftId, startInEditMode = false) {
  const draft = state.drafts.find((d) => d.id === draftId);
  if (!draft) return;

  let ticket = state.tickets.find((t) => t.id === draft.ticket_id);
  if (!ticket && draft.ticket_id) {
    try {
      const context = await get(`/tickets/${draft.ticket_id}/context`);
      ticket = context.ticket || {};
    } catch (e) {
      console.warn("Could not fetch ticket context", e);
    }
  }

  const inquiryTitle = ticket?.title || "Customer Inquiry";
  const inquiryMessage = ticket?.description || "No inquiry text available for this ticket.";
  const agentResponse = draft.human_edited_version || draft.original_ai_draft || "";

  openModal(
    `Review Draft ${draft.id}`,
    `
    <dl>
      <dt>Ticket</dt><dd>${draft.ticket_id} ${ticket?.category ? `(${ticket.category})` : ""}</dd>
      <dt>Customer</dt><dd>${draft.customer_id}</dd>
      <dt>Status</dt><dd>${badge(draft.status)}</dd>
      <dt>Created</dt><dd>${formatDate(draft.created_at)}</dd>
    </dl>

    <div class="draft-detail-block">
      <h4 style="color: var(--primary-2);">Customer Inquiry</h4>
      <div style="font-weight: 600; margin-bottom: 6px;">${inquiryTitle}</div>
      <div class="draft-inquiry-text">${inquiryMessage}</div>
    </div>

    <div class="draft-detail-block">
      <h4 style="color: var(--success);">LLM Generated Output (Agent Message)</h4>
      <div class="draft-llm-text" id="draft-output-preview-${draft.id}">${agentResponse}</div>
    </div>

    <div class="draft-detail-block" id="draft-edit-box-${draft.id}" style="display: ${startInEditMode ? "block" : "none"}; border-color: var(--warning);">
      <h4 style="color: var(--warning);">Edit Response Box</h4>
      <p style="font-size: 0.85rem; color: var(--muted); margin: 0 0 6px;">Type below to edit the agent response if the output is wrong:</p>
      <textarea id="draft-edit-text-${draft.id}" class="draft-edit-area">${agentResponse}</textarea>
    </div>

    <div class="actions" style="margin-top: 16px;">
      <button id="btn-approve-${draft.id}" class="btn btn-success" onclick="handleApproveDraft('${draft.id}')">Approve &amp; Send</button>
      <button class="btn btn-warning" onclick="toggleEditDraftBox('${draft.id}')">
        <span id="btn-edit-text-${draft.id}">${startInEditMode ? "Close Edit Box" : "Edit Message"}</span>
      </button>
      <button class="btn btn-danger" onclick="rejectDraft('${draft.id}')">Reject</button>
    </div>
  `
  );
}

function toggleEditDraftBox(draftId) {
  const editBox = $(`#draft-edit-box-${draftId}`);
  const btnText = $(`#btn-edit-text-${draftId}`);
  if (!editBox) return;
  if (editBox.style.display === "none") {
    editBox.style.display = "block";
    if (btnText) btnText.textContent = "Close Edit Box";
    const textarea = $(`#draft-edit-text-${draftId}`);
    if (textarea) textarea.focus();
  } else {
    editBox.style.display = "none";
    if (btnText) btnText.textContent = "Edit Message";
  }
}

async function handleApproveDraft(draftId) {
  const editBox = $(`#draft-edit-box-${draftId}`);
  const textarea = $(`#draft-edit-text-${draftId}`);
  let editedBody = null;
  if (editBox && editBox.style.display !== "none" && textarea) {
    editedBody = textarea.value;
  }
  await approveDraft(draftId, editedBody);
}

function openCreateTicketForm() {
  openModal(
    "Create Ticket / Inquiry",
    `
    <form onsubmit="event.preventDefault(); submitCreateTicket(this);">
      <div class="form-group">
        <label>Customer ID</label>
        <input name="customer_id" required placeholder="e.g. customer-1" />
      </div>
      <div class="form-group">
        <label>Title</label>
        <input name="title" required />
      </div>
      <div class="form-group">
        <label>Message / Description</label>
        <textarea name="message" required></textarea>
      </div>
      <button class="btn btn-primary" type="submit">Create Draft Reply</button>
    </form>
  `
  );
}

async function submitCreateTicket(form) {
  const data = Object.fromEntries(new FormData(form));
  try {
    await post("/customer-inquiries/draft-reply", data);
    showToast("Ticket and draft created");
    closeModal();
    loadTickets();
    loadDrafts();
  } catch (err) {
    showToast(err.message, "error");
  }
}

function openCreateJobForm() {
  openModal(
    "Create Job",
    `
    <form onsubmit="event.preventDefault(); submitCreateJob(this);">
      <div class="form-group">
        <label>Customer ID</label>
        <input name="customer_id" required placeholder="e.g. customer-1" />
      </div>
      <div class="form-group">
        <label>Title</label>
        <input name="title" required />
      </div>
      <div class="form-group">
        <label>Description</label>
        <textarea name="description" required></textarea>
      </div>
      <div class="form-group">
        <label>Required Skill</label>
        <select name="required_skill" required>
          <option value="technician">technician</option>
          <option value="plumber">plumber</option>
          <option value="HVAC">HVAC</option>
          <option value="electrical">electrical</option>
          <option value="sanitary">sanitary</option>
        </select>
      </div>
      <div class="form-group">
        <label>Service Area</label>
        <input name="service_area" required value="London" />
      </div>
      <div class="form-group">
        <label>Priority</label>
        <select name="priority">
          <option value="low">low</option>
          <option value="medium" selected>medium</option>
          <option value="high">high</option>
          <option value="urgent">urgent</option>
        </select>
      </div>
      <button class="btn btn-primary" type="submit">Create Job</button>
    </form>
  `
  );
}

async function submitCreateJob(form) {
  const data = Object.fromEntries(new FormData(form));
  try {
    await post("/jobs", data);
    showToast("Job created");
    closeModal();
    loadJobs();
  } catch (err) {
    showToast(err.message, "error");
  }
}

function openCreateJobForTicket(ticketId, customerId) {
  openModal(
    "Create Job for Ticket",
    `
    <form onsubmit="event.preventDefault(); submitCreateJobForTicket(this, '${ticketId}');">
      <div class="form-group">
        <label>Title</label>
        <input name="title" required />
      </div>
      <div class="form-group">
        <label>Description</label>
        <textarea name="description" required></textarea>
      </div>
      <div class="form-group">
        <label>Required Skill</label>
        <select name="required_skill" required>
          <option value="technician">technician</option>
          <option value="plumber">plumber</option>
          <option value="HVAC">HVAC</option>
          <option value="electrical">electrical</option>
          <option value="sanitary">sanitary</option>
        </select>
      </div>
      <div class="form-group">
        <label>Service Area</label>
        <input name="service_area" required value="London" />
      </div>
      <div class="form-group">
        <label>Priority</label>
        <select name="priority">
          <option value="low">low</option>
          <option value="medium" selected>medium</option>
          <option value="high">high</option>
          <option value="urgent">urgent</option>
        </select>
      </div>
      <input type="hidden" name="customer_id" value="${customerId}" />
      <button class="btn btn-primary" type="submit">Create Job</button>
    </form>
  `
  );
}

async function submitCreateJobForTicket(form, ticketId) {
  const data = Object.fromEntries(new FormData(form));
  try {
    await post(`/tickets/${ticketId}/create-job`, data);
    showToast("Job created for ticket");
    closeModal();
    loadJobs();
    loadTickets();
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function approveDraft(draftId, editedBody = null) {
  try {
    const payload = { reviewer: "support-desk" };
    if (editedBody !== null) {
      payload.edited_body = editedBody;
    }
    await post(`/support/email-drafts/${draftId}/approve`, payload);
    showToast(editedBody !== null ? "Draft edited, approved & sent!" : "Draft approved & sent!");
    closeModal();
    loadDashboard();
    loadDrafts();
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function rejectDraft(draftId) {
  try {
    await post(`/support/email-drafts/${draftId}/reject`, {
      reviewer: "support-desk",
      reason: "Rejected from support desk",
    });
    showToast("Draft rejected");
    closeModal();
    loadDashboard();
    loadDrafts();
  } catch (err) {
    showToast(err.message, "error");
  }
}

function openModal(title, bodyHtml) {
  $("#modal-title").textContent = title;
  $("#modal-body").innerHTML = bodyHtml;
  $("#modal-overlay").classList.add("active");
}

function closeModal() {
  $("#modal-overlay").classList.remove("active");
}

function navigate(view) {
  state.currentView = view;
  $$(".nav-link").forEach((link) => link.classList.remove("active"));
  $$(".view").forEach((v) => v.classList.remove("active"));
  $(`.nav-link[data-view="${view}"]`)?.classList.add("active");
  $(`#view-${view}`)?.classList.add("active");
  $("#page-title").textContent =
    view.charAt(0).toUpperCase() + view.slice(1);

  const topActions = $("#top-actions");
  topActions.innerHTML = "";

  if (view === "tickets") {
    topActions.innerHTML = `<button class="btn btn-primary" onclick="openCreateTicketForm()">Create Ticket</button>`;
    loadTickets();
  } else if (view === "jobs") {
    topActions.innerHTML = `<button class="btn btn-primary" onclick="openCreateJobForm()">Create Job</button>`;
    loadJobs();
  } else if (view === "customers") {
    loadCustomers();
  } else if (view === "drafts") {
    loadDrafts();
  } else if (view === "simulator") {
    loadSimulatorCustomers();
  } else {
    loadDashboard();
  }
}

function init() {
  $$(".nav-link").forEach((link) => {
    link.addEventListener("click", (e) => {
      e.preventDefault();
      const view = link.dataset.view;
      history.pushState(null, "", `#${view}`);
      navigate(view);
    });
  });

  $("#modal-close").addEventListener("click", closeModal);
  $("#modal-overlay").addEventListener("click", (e) => {
    if (e.target === $("#modal-overlay")) closeModal();
  });

  $("#ticket-filter").addEventListener("input", renderTickets);
  $("#job-filter").addEventListener("input", renderJobs);
  $("#sim-customer-select").addEventListener("change", (event) => resetSimulatorThread(event.target.value));
  $("#sim-send-btn").addEventListener("click", sendSimulatorMessage);
  $("#sim-new-conversation-btn").addEventListener("click", newSimulatorConversation);
  $("#sim-msg-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendSimulatorMessage();
    }
  });
  setInterval(pollSimulatorApproval, 2000);

  const hash = window.location.hash.replace("#", "") || "dashboard";
  navigate(hash);
}

init();
