(function () {
  const state = {
    token: new URLSearchParams(window.location.search).get("token") || "",
    context: null,
    lastLookup: {},
    snapshot: null,
    selectedPartnerId: null,
    themeChoice: localStorage.getItem("odoo-panel-theme") || "auto",
  };

  const els = {
    searchForm: document.getElementById("searchForm"),
    searchInput: document.getElementById("searchInput"),
    refreshButton: document.getElementById("refreshButton"),
    contextLine: document.getElementById("contextLine"),
    statusPanel: document.getElementById("statusPanel"),
    statusText: document.getElementById("statusText"),
    noteButton: document.getElementById("noteButton"),
    metricContact: document.getElementById("metricContact"),
    metricLeads: document.getElementById("metricLeads"),
    metricOrders: document.getElementById("metricOrders"),
    metricInvoices: document.getElementById("metricInvoices"),
    metricCourses: document.getElementById("metricCourses"),
    matchesPanel: document.getElementById("matchesPanel"),
    matchesCount: document.getElementById("matchesCount"),
    matchesList: document.getElementById("matchesList"),
    contactDetails: document.getElementById("contactDetails"),
    leadsList: document.getElementById("leadsList"),
    ordersList: document.getElementById("ordersList"),
    invoicesList: document.getElementById("invoicesList"),
    coursesList: document.getElementById("coursesList"),
    emptyTemplate: document.getElementById("emptyTemplate"),
  };

  function valueOrDash(value) {
    if (value === false || value === null || value === undefined || value === "") return "-";
    if (Array.isArray(value)) return value.length > 1 ? String(value[1]) : String(value[0]);
    return String(value);
  }

  function money(value, currency) {
    const amount = Number(value || 0).toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
    const currencyName = valueOrDash(currency);
    return currencyName === "-" ? amount : `${amount} ${currencyName}`;
  }

  function safeParse(data) {
    if (typeof data === "object" && data !== null) return data;
    if (typeof data !== "string") return null;
    try {
      return JSON.parse(data);
    } catch (_error) {
      return null;
    }
  }

  function findConversation(payload) {
    return (
      payload.conversation ||
      payload.current_conversation ||
      payload.appContext?.conversation ||
      payload.data?.conversation ||
      payload
    );
  }

  function findContact(payload) {
    const conversation = findConversation(payload) || {};
    return (
      payload.contact ||
      payload.sender ||
      payload.appContext?.contact ||
      payload.data?.contact ||
      conversation.meta?.sender ||
      {}
    );
  }

  function findCurrentAgent(payload) {
    return (
      payload.currentAgent ||
      payload.current_agent ||
      payload.appContext?.currentAgent ||
      payload.data?.currentAgent ||
      payload.data?.current_agent ||
      {}
    );
  }

  function contextLookup(payload) {
    const conversation = findConversation(payload) || {};
    const contact = findContact(payload);
    const currentAgent = findCurrentAgent(payload);
    return {
      conversationId: conversation.id || payload.conversation_id || null,
      contactName: contact.name || "",
      email: contact.email || "",
      phone: contact.phone_number || contact.phone || contact.mobile || "",
      agentEmail: currentAgent.email || "",
      agentId: currentAgent.id || "",
      agentName: currentAgent.name || "",
    };
  }

  function setTheme(choice) {
    state.themeChoice = choice;
    localStorage.setItem("odoo-panel-theme", choice);

    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const theme = choice === "auto" ? (prefersDark ? "dark" : "light") : choice;
    document.documentElement.dataset.theme = theme;

    document.querySelectorAll("[data-theme-choice]").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.themeChoice === choice);
    });
  }

  function setStatus(kind, text) {
    els.statusPanel.classList.remove("is-muted", "is-success", "is-warning", "is-error");
    els.statusPanel.classList.add(`is-${kind}`);
    els.statusText.textContent = text;
  }

  function clearNode(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function emptyNode() {
    return els.emptyTemplate.content.firstElementChild.cloneNode(true);
  }

  function restrictedNode(sectionName) {
    const node = emptyNode();
    node.querySelector("p").textContent = `${sectionName} are restricted for the current agent.`;
    return node;
  }

  function detail(label, value) {
    const wrap = document.createElement("div");
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = label;
    dd.textContent = valueOrDash(value);
    wrap.append(dt, dd);
    return wrap;
  }

  function renderContact(partner) {
    clearNode(els.contactDetails);
    if (!partner) {
      els.contactDetails.appendChild(emptyNode());
      return;
    }

    els.contactDetails.append(
      detail("Name", partner.name),
      detail("Odoo ID", partner.id),
      detail("Email", partner.email),
      detail("Phone", partner.phone || partner.mobile),
      detail("Company", partner.company_name || partner.commercial_partner_id),
      detail("VAT", partner.vat),
      detail("City", partner.city),
      detail("Country", partner.country_id)
    );
  }

  function renderMatches(matches) {
    const visibleMatches = Array.isArray(matches) ? matches : [];
    els.matchesCount.textContent = String(visibleMatches.length);
    els.matchesPanel.classList.toggle("is-hidden", visibleMatches.length <= 1);
    clearNode(els.matchesList);

    visibleMatches.forEach((partner) => {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "match-item";
      row.innerHTML = `
        <span>
          <span class="match-title"></span>
          <span class="match-meta"></span>
        </span>
        <span class="badge">Open</span>
      `;
      row.querySelector(".match-title").textContent = valueOrDash(partner.name);
      row.querySelector(".match-meta").textContent = [
        valueOrDash(partner.email),
        valueOrDash(partner.phone || partner.mobile),
      ]
        .filter((item) => item !== "-")
        .join(" | ");
      row.addEventListener("click", () => loadSnapshot({ partnerId: partner.id }));
      els.matchesList.appendChild(row);
    });
  }

  function renderLeads(leads) {
    clearNode(els.leadsList);
    if (!leads || leads.length === 0) {
      els.leadsList.appendChild(emptyNode());
      return;
    }

    leads.forEach((lead) => {
      const item = document.createElement("article");
      item.className = "record-item";
      item.innerHTML = `
        <p class="record-title"></p>
        <p class="record-meta"></p>
      `;
      item.querySelector(".record-title").textContent = `#${lead.id} ${valueOrDash(lead.name)}`;
      item.querySelector(".record-meta").textContent = [
        `Stage: ${valueOrDash(lead.stage_id)}`,
        `Revenue: ${money(lead.expected_revenue)}`,
        `Owner: ${valueOrDash(lead.user_id)}`,
      ].join(" | ");
      els.leadsList.appendChild(item);
    });
  }

  function renderOrders(orders, restricted) {
    clearNode(els.ordersList);
    if (restricted) {
      els.ordersList.appendChild(restrictedNode("Sales orders"));
      return;
    }
    if (!orders || orders.length === 0) {
      els.ordersList.appendChild(emptyNode());
      return;
    }

    orders.forEach((order) => {
      const item = document.createElement("article");
      item.className = "record-item";

      item.innerHTML = `
        <p class="record-title"></p>
        <p class="record-meta"></p>
      `;
      item.querySelector(".record-title").textContent = valueOrDash(order.name);
      item.querySelector(".record-meta").textContent = [
        `State: ${valueOrDash(order.state)}`,
        `Total: ${money(order.amount_total, order.currency_id)}`,
        `Invoice: ${valueOrDash(order.invoice_status)}`,
      ].join(" | ");

      (order.lines || []).slice(0, 4).forEach((line) => {
        const lineItem = document.createElement("p");
        lineItem.className = "line-item";
        lineItem.textContent = `${valueOrDash(line.product_id)} x ${
          line.product_uom_qty || 0
        } - ${money(line.price_subtotal, order.currency_id)}`;
        item.appendChild(lineItem);
      });

      els.ordersList.appendChild(item);
    });
  }

  function renderInvoices(invoices, restricted) {
    clearNode(els.invoicesList);
    if (restricted) {
      els.invoicesList.appendChild(restrictedNode("Invoices"));
      return;
    }
    if (!invoices || invoices.length === 0) {
      els.invoicesList.appendChild(emptyNode());
      return;
    }

    invoices.forEach((invoice) => {
      const item = document.createElement("article");
      item.className = "record-item";

      item.innerHTML = `
        <p class="record-title"></p>
        <p class="record-meta"></p>
      `;
      item.querySelector(".record-title").textContent = valueOrDash(invoice.name);
      item.querySelector(".record-meta").textContent = [
        `State: ${valueOrDash(invoice.state)}`,
        `Payment: ${valueOrDash(invoice.payment_state)}`,
        `Total: ${money(invoice.amount_total, invoice.currency_id)}`,
        `Due: ${money(invoice.amount_residual, invoice.currency_id)}`,
      ].join(" | ");

      (invoice.lines || []).slice(0, 4).forEach((line) => {
        const lineItem = document.createElement("p");
        lineItem.className = "line-item";
        lineItem.textContent = `${valueOrDash(line.product_id || line.name)} x ${
          line.quantity || 0
        } - ${money(line.price_subtotal, invoice.currency_id)}`;
        item.appendChild(lineItem);
      });

      els.invoicesList.appendChild(item);
    });
  }

  function renderCourses(courses) {
    clearNode(els.coursesList);
    if (!courses || courses.length === 0) {
      els.coursesList.appendChild(emptyNode());
      return;
    }

    courses.forEach((course) => {
      const item = document.createElement("article");
      item.className = "record-item";
      const completion = Number(course.completion || 0);

      item.innerHTML = `
        <p class="record-title"></p>
        <p class="record-meta"></p>
        <div class="progress-track"><span class="progress-bar"></span></div>
      `;
      item.querySelector(".record-title").textContent = valueOrDash(course.channel_id);
      item.querySelector(".record-meta").textContent = [
        `Status: ${valueOrDash(course.member_status)}`,
        `Progress: ${completion.toFixed(0)}%`,
        `Completed slides: ${valueOrDash(course.completed_slides_count)}`,
        `Next: ${valueOrDash(course.next_slide_id)}`,
      ].join(" | ");
      item.querySelector(".progress-bar").style.width = `${Math.max(
        0,
        Math.min(100, completion)
      )}%`;

      els.coursesList.appendChild(item);
    });
  }

  function renderSnapshot(snapshot) {
    state.snapshot = snapshot;
    const partner = snapshot.partner || null;
    const leads = snapshot.leads || [];
    const orders = snapshot.orders || [];
    const invoices = snapshot.invoices || [];
    const courses = snapshot.courses || [];
    const warnings = snapshot.warnings || [];
    const restrictedSections = snapshot.restricted_sections || [];

    els.metricContact.textContent = partner ? valueOrDash(partner.name) : "-";
    els.metricLeads.textContent = String(leads.length);
    els.metricOrders.textContent = restrictedSections.includes("orders") ? "Locked" : String(orders.length);
    els.metricInvoices.textContent = restrictedSections.includes("invoices")
      ? "Locked"
      : String(invoices.length);
    els.metricCourses.textContent = String(courses.length);
    els.noteButton.disabled = !state.lastLookup.conversationId;

    renderMatches(snapshot.matches || []);
    renderContact(partner);
    renderLeads(leads);
    renderOrders(orders, restrictedSections.includes("orders"));
    renderInvoices(invoices, restrictedSections.includes("invoices"));
    renderCourses(courses);

    if (partner && restrictedSections.length > 0) {
      setStatus(
        "warning",
        `Matched ${valueOrDash(partner.name)}. Sensitive sections are restricted for this agent.`
      );
    } else if (partner && warnings.length > 0) {
      setStatus("warning", `Matched ${valueOrDash(partner.name)}. Some optional Odoo data is unavailable.`);
    } else if (partner) {
      setStatus("success", `Matched ${valueOrDash(partner.name)} in Odoo.`);
    } else {
      setStatus("warning", "No matching Odoo contact found.");
    }
  }

  async function apiFetch(path, params) {
    const url = new URL(path, window.location.origin);
    Object.entries(params || {}).forEach(([key, value]) => {
      if (value !== null && value !== undefined && value !== "") url.searchParams.set(key, value);
    });
    if (state.token) url.searchParams.set("token", state.token);

    const response = await fetch(url);
    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || `Request failed with ${response.status}`);
    }
    return response.json();
  }

  async function loadSnapshot(options) {
    const params = {
      q: options?.query || "",
      email: options?.email || "",
      phone: options?.phone || "",
      partner_id: options?.partnerId || "",
      agent_email: state.lastLookup.agentEmail || "",
      agent_id: state.lastLookup.agentId || "",
      agent_name: state.lastLookup.agentName || "",
    };
    state.selectedPartnerId = params.partner_id || null;
    state.lastLookup = { ...state.lastLookup, ...params };
    setStatus("muted", "Loading Odoo data...");
    try {
      const snapshot = await apiFetch("/api/dashboard/search", params);
      renderSnapshot(snapshot);
    } catch (error) {
      setStatus("error", "Could not load Odoo data.");
      console.error(error);
    }
  }

  function loadFromContext(payload) {
    state.context = payload;
    const lookup = contextLookup(payload);
    state.lastLookup = lookup;

    const label = [
      lookup.contactName || "Unknown contact",
      lookup.email || "",
      lookup.phone || "",
      lookup.agentEmail ? `agent: ${lookup.agentEmail}` : "",
    ]
      .filter(Boolean)
      .join(" | ");
    els.contextLine.textContent = label || "No contact details found in Chatwoot context.";

    if (lookup.email || lookup.phone) {
      loadSnapshot({ email: lookup.email, phone: lookup.phone });
    }
  }

  async function addPrivateNote() {
    if (!state.lastLookup.conversationId) return;
    els.noteButton.disabled = true;
    els.noteButton.textContent = "Adding...";

    const payload = {
      conversation_id: state.lastLookup.conversationId,
      query: state.lastLookup.q || "",
      email: state.lastLookup.email || "",
      phone: state.lastLookup.phone || "",
      partner_id: state.selectedPartnerId || state.lastLookup.partner_id || null,
      agent_email: state.lastLookup.agentEmail || "",
      agent_id: state.lastLookup.agentId || "",
      agent_name: state.lastLookup.agentName || "",
    };

    try {
      const response = await fetch(
        `/api/dashboard/conversations/${state.lastLookup.conversationId}/note${
          state.token ? `?token=${encodeURIComponent(state.token)}` : ""
        }`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        }
      );
      if (!response.ok) throw new Error(await response.text());
      setStatus("success", "Private note added to this conversation.");
    } catch (error) {
      setStatus("error", "Could not add private note.");
      console.error(error);
    } finally {
      els.noteButton.disabled = false;
      els.noteButton.textContent = "Add private note";
    }
  }

  window.addEventListener("message", (event) => {
    const payload = safeParse(event.data);
    if (!payload) return;
    loadFromContext(payload);
  });

  els.searchForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const query = els.searchInput.value.trim();
    if (!query) return;
    loadSnapshot({ query });
  });

  els.refreshButton.addEventListener("click", () => {
    window.parent.postMessage("chatwoot-dashboard-app:fetch-info", "*");
    if (state.context) loadFromContext(state.context);
  });

  els.noteButton.addEventListener("click", addPrivateNote);

  document.querySelectorAll("[data-theme-choice]").forEach((button) => {
    button.addEventListener("click", () => setTheme(button.dataset.themeChoice));
  });

  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll("[data-tab]").forEach((tab) => tab.classList.remove("is-active"));
      document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.add("is-hidden"));
      button.classList.add("is-active");
      document.getElementById(`tab-${button.dataset.tab}`).classList.remove("is-hidden");
    });
  });

  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (state.themeChoice === "auto") setTheme("auto");
  });

  setTheme(state.themeChoice);
  window.parent.postMessage("chatwoot-dashboard-app:fetch-info", "*");
})();
