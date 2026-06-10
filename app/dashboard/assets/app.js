(function () {
  const state = {
    token: new URLSearchParams(window.location.search).get("token") || "",
    context: null,
    lastLookup: {},
    snapshot: null,
    selectedPartnerId: null,
    themeChoice: localStorage.getItem("odoo-panel-theme") || "auto",
    fieldLabels: {},
    loadedSections: new Set(),
    loadingSections: new Set(),
  };

  const els = {
    searchForm: document.getElementById("searchForm"),
    searchInput: document.getElementById("searchInput"),
    refreshButton: document.getElementById("refreshButton"),
    contextLine: document.getElementById("contextLine"),
    statusPanel: document.getElementById("statusPanel"),
    statusText: document.getElementById("statusText"),
    noteButton: document.getElementById("noteButton"),
    diagnosticsPanel: document.getElementById("diagnosticsPanel"),
    diagnosticsCount: document.getElementById("diagnosticsCount"),
    diagnosticsList: document.getElementById("diagnosticsList"),
    metricQuotations: document.getElementById("metricQuotations"),
    metricSalesOrders: document.getElementById("metricSalesOrders"),
    metricLeads: document.getElementById("metricLeads"),
    metricInvoices: document.getElementById("metricInvoices"),
    metricInvoicedItems: document.getElementById("metricInvoicedItems"),
    metricCourses: document.getElementById("metricCourses"),
    matchesPanel: document.getElementById("matchesPanel"),
    matchesCount: document.getElementById("matchesCount"),
    matchesList: document.getElementById("matchesList"),
    contactDetails: document.getElementById("contactDetails"),
    relatedContactsCount: document.getElementById("relatedContactsCount"),
    relatedContactsList: document.getElementById("relatedContactsList"),
    leadsList: document.getElementById("leadsList"),
    quotationsList: document.getElementById("quotationsList"),
    salesOrdersList: document.getElementById("salesOrdersList"),
    invoicedItemsList: document.getElementById("invoicedItemsList"),
    invoicesList: document.getElementById("invoicesList"),
    journalEntriesList: document.getElementById("journalEntriesList"),
    coursesList: document.getElementById("coursesList"),
    emptyTemplate: document.getElementById("emptyTemplate"),
  };

  function valueOrDash(value) {
    if (value === false || value === null || value === undefined || value === "") return "-";
    if (value === true) return "Yes";
    if (Array.isArray(value)) {
      if (value.length === 2 && typeof value[1] === "string") return String(value[1]);
      return value.map((item) => valueOrDash(item)).join(", ");
    }
    if (typeof value === "object") return JSON.stringify(value);
    if (typeof value === "string" && /<\/?[a-z][\s\S]*>/i.test(value)) {
      const parsed = new DOMParser().parseFromString(value, "text/html");
      return parsed.body.textContent.trim() || "-";
    }
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

  function detail(label, value) {
    const wrap = document.createElement("div");
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = label;
    dd.textContent = valueOrDash(value);
    wrap.append(dt, dd);
    return wrap;
  }

  function humanizeField(field) {
    return String(field || "")
      .replace(/^x_/, "")
      .replace(/_id$/, "")
      .replace(/_/g, " ")
      .replace(/\b\w/g, (letter) => letter.toUpperCase());
  }

  function fieldLabel(group, field) {
    return state.fieldLabels?.[group]?.[field] || humanizeField(field);
  }

  function visibleFieldKeys(record, excluded, preferred) {
    const excludedSet = new Set(excluded || []);
    const preferredKeys = (preferred || []).filter(
      (key) => Object.prototype.hasOwnProperty.call(record || {}, key) && !excludedSet.has(key)
    );
    const remaining = Object.keys(record || {})
      .filter((key) => !excludedSet.has(key) && !preferredKeys.includes(key))
      .sort((left, right) => fieldLabel("", left).localeCompare(fieldLabel("", right)));
    return [...preferredKeys, ...remaining];
  }

  function appendRecordFields(target, record, group, options) {
    const fields = document.createElement("dl");
    fields.className = options?.className || "record-fields";
    const keys = visibleFieldKeys(record, options?.exclude, options?.preferred);
    keys.forEach((key) => fields.appendChild(detail(fieldLabel(group, key), record[key])));
    if (keys.length > 0) target.appendChild(fields);
  }

  function appendLines(target, lines, group, currency) {
    if (!Array.isArray(lines) || lines.length === 0) return;
    const section = document.createElement("section");
    section.className = "line-section";
    const heading = document.createElement("h3");
    heading.textContent = `Lines (${lines.length})`;
    section.appendChild(heading);

    lines.forEach((line) => {
      const row = document.createElement("article");
      row.className = "line-row";
      const title = document.createElement("p");
      const total = line.price_total ?? line.price_subtotal;
      title.className = "line-title";
      title.textContent = [
        valueOrDash(line.product_id || line.name),
        line.quantity !== undefined
          ? `Qty ${valueOrDash(line.quantity)}`
          : `Qty ${valueOrDash(line.product_uom_qty)}`,
        total !== undefined ? money(total, line.currency_id || currency) : "",
      ]
        .filter(Boolean)
        .join(" | ");
      row.appendChild(title);
      appendRecordFields(row, line, group, {
        className: "record-fields is-compact",
        exclude: ["order_id", "move_id"],
        preferred: [
          "id",
          "name",
          "product_id",
          "product_uom_qty",
          "quantity",
          "product_uom",
          "product_uom_id",
          "qty_delivered",
          "qty_invoiced",
          "qty_to_invoice",
          "invoice_status",
          "price_unit",
          "discount",
          "tax_id",
          "tax_ids",
          "price_subtotal",
          "price_tax",
          "price_total",
          "account_id",
        ],
      });
      section.appendChild(row);
    });
    target.appendChild(section);
  }

  function renderContact(partner) {
    clearNode(els.contactDetails);
    if (!partner) {
      els.contactDetails.appendChild(emptyNode());
      return;
    }

    visibleFieldKeys(
      partner,
      [],
      [
        "name",
        "id",
        "email",
        "phone",
        "mobile",
        "user_id",
        "team_id",
        "company_name",
        "commercial_partner_id",
        "parent_id",
        "vat",
        "ref",
        "function",
        "street",
        "street2",
        "city",
        "state_id",
        "zip",
        "country_id",
        "website",
        "property_payment_term_id",
        "property_product_pricelist",
        "credit",
        "credit_limit",
        "create_date",
        "write_date",
      ]
    ).forEach((key) =>
      els.contactDetails.appendChild(detail(fieldLabel("partner", key), partner[key]))
    );
  }

  function renderRelatedContacts(contacts) {
    const relatedContacts = Array.isArray(contacts) ? contacts : [];
    els.relatedContactsCount.textContent = String(relatedContacts.length);
    clearNode(els.relatedContactsList);
    if (relatedContacts.length === 0) {
      els.relatedContactsList.appendChild(emptyNode());
      return;
    }

    relatedContacts.forEach((contact) => {
      const item = document.createElement("article");
      item.className = "record-item";
      item.innerHTML = `
        <p class="record-title"></p>
        <p class="record-meta"></p>
      `;
      item.querySelector(".record-title").textContent = valueOrDash(contact.name);
      item.querySelector(".record-meta").textContent = [
        valueOrDash(contact.email),
        valueOrDash(contact.phone || contact.mobile),
        valueOrDash(contact.company_name || contact.parent_id),
      ]
        .filter((value) => value !== "-")
        .join(" | ");
      appendRecordFields(item, contact, "partner", {
        exclude: ["name"],
        preferred: ["id", "type", "email", "phone", "mobile", "parent_id", "user_id"],
      });
      els.relatedContactsList.appendChild(item);
    });
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
        `Type: ${valueOrDash(lead.type)}`,
        `Stage: ${valueOrDash(lead.stage_id)}`,
        `Revenue: ${money(lead.expected_revenue)}`,
        `Probability: ${valueOrDash(lead.probability)}%`,
        `Owner: ${valueOrDash(lead.user_id)}`,
      ].join(" | ");
      appendRecordFields(item, lead, "crm_lead", {
        exclude: ["name"],
        preferred: [
          "id",
          "type",
          "stage_id",
          "partner_id",
          "expected_revenue",
          "probability",
          "priority",
          "user_id",
          "team_id",
          "email_from",
          "phone",
          "mobile",
          "date_deadline",
          "create_date",
          "date_open",
          "date_closed",
        ],
      });
      els.leadsList.appendChild(item);
    });
  }

  function renderOrders(target, orders) {
    clearNode(target);
    if (!orders || orders.length === 0) {
      target.appendChild(emptyNode());
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
        `Date: ${valueOrDash(order.date_order)}`,
        `Total: ${money(order.amount_total, order.currency_id)}`,
        `Invoice: ${valueOrDash(order.invoice_status)}`,
        `Salesperson: ${valueOrDash(order.user_id)}`,
      ].join(" | ");

      appendRecordFields(item, order, "sale_order", {
        exclude: ["name", "lines"],
        preferred: [
          "id",
          "state",
          "date_order",
          "validity_date",
          "commitment_date",
          "client_order_ref",
          "origin",
          "partner_id",
          "partner_invoice_id",
          "partner_shipping_id",
          "user_id",
          "team_id",
          "company_id",
          "warehouse_id",
          "pricelist_id",
          "payment_term_id",
          "amount_untaxed",
          "amount_tax",
          "amount_total",
          "amount_invoiced",
          "amount_to_invoice",
          "amount_paid",
          "invoice_status",
          "invoice_count",
          "invoice_ids",
          "signed_by",
          "signed_on",
        ],
      });
      appendLines(item, order.lines || [], "sale_order_line", order.currency_id);

      target.appendChild(item);
    });
  }

  function renderInvoices(invoices) {
    clearNode(els.invoicesList);
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
        `Type: ${valueOrDash(invoice.move_type)}`,
        `State: ${valueOrDash(invoice.state)}`,
        `Payment: ${valueOrDash(invoice.payment_state)}`,
        `Total: ${money(invoice.amount_total, invoice.currency_id)}`,
        `Due: ${money(invoice.amount_residual, invoice.currency_id)}`,
        `Salesperson: ${valueOrDash(invoice.invoice_user_id)}`,
      ].join(" | ");

      appendRecordFields(item, invoice, "invoice", {
        exclude: ["name", "lines"],
        preferred: [
          "id",
          "move_type",
          "state",
          "invoice_date",
          "invoice_date_due",
          "invoice_origin",
          "ref",
          "payment_reference",
          "partner_id",
          "invoice_user_id",
          "company_id",
          "journal_id",
          "invoice_payment_term_id",
          "amount_untaxed",
          "amount_tax",
          "amount_total",
          "amount_residual",
          "payment_state",
          "reversed_entry_id",
        ],
      });
      appendLines(item, invoice.lines || [], "invoice_line", invoice.currency_id);

      els.invoicesList.appendChild(item);
    });
  }

  function renderInvoicedItems(items) {
    clearNode(els.invoicedItemsList);
    if (!items || items.length === 0) {
      els.invoicedItemsList.appendChild(emptyNode());
      return;
    }

    items.forEach((line) => {
      const item = document.createElement("article");
      item.className = "record-item";
      item.innerHTML = `
        <p class="record-title"></p>
        <p class="record-meta"></p>
      `;
      item.querySelector(".record-title").textContent = valueOrDash(line.product_id || line.name);
      item.querySelector(".record-meta").textContent = [
        `Invoice: ${valueOrDash(line.invoice_name)}`,
        `Date: ${valueOrDash(line.invoice_date)}`,
        `Qty: ${valueOrDash(line.quantity)}`,
        `Subtotal: ${money(line.price_subtotal, line.currency_id || line.invoice_currency_id)}`,
        `Payment: ${valueOrDash(line.payment_state)}`,
      ].join(" | ");
      appendRecordFields(item, line, "invoice_line", {
        exclude: ["move_id"],
        preferred: [
          "id",
          "invoice_name",
          "invoice_type",
          "invoice_state",
          "invoice_date",
          "invoice_date_due",
          "invoice_origin",
          "payment_state",
          "invoice_user_id",
          "product_id",
          "name",
          "quantity",
          "product_uom_id",
          "price_unit",
          "discount",
          "tax_ids",
          "price_subtotal",
          "price_total",
          "account_id",
          "sale_line_ids",
        ],
      });
      els.invoicedItemsList.appendChild(item);
    });
  }

  function renderJournalEntries(entries) {
    clearNode(els.journalEntriesList);
    if (!entries || entries.length === 0) {
      els.journalEntriesList.appendChild(emptyNode());
      return;
    }

    entries.forEach((entry) => {
      const item = document.createElement("article");
      item.className = "record-item";
      item.innerHTML = `
        <p class="record-title"></p>
        <p class="record-meta"></p>
      `;
      item.querySelector(".record-title").textContent = valueOrDash(entry.name);
      item.querySelector(".record-meta").textContent = [
        `Date: ${valueOrDash(entry.date)}`,
        `Journal: ${valueOrDash(entry.journal_id)}`,
        `State: ${valueOrDash(entry.state)}`,
        `Reference: ${valueOrDash(entry.ref)}`,
        `Debit: ${money(entry.partner_debit, entry.currency_id)}`,
        `Credit: ${money(entry.partner_credit, entry.currency_id)}`,
      ].join(" | ");

      appendRecordFields(item, entry, "invoice", {
        exclude: ["name", "lines"],
        preferred: [
          "id",
          "date",
          "journal_id",
          "state",
          "ref",
          "company_id",
          "partner_id",
          "partner_debit",
          "partner_credit",
          "partner_balance",
        ],
      });

      (entry.lines || []).forEach((line) => {
        const lineItem = document.createElement("p");
        lineItem.className = "line-item";
        lineItem.textContent = [
          valueOrDash(line.account_id),
          valueOrDash(line.name || line.ref),
          `Debit ${money(line.debit, line.currency_id || entry.currency_id)}`,
          `Credit ${money(line.credit, line.currency_id || entry.currency_id)}`,
        ].join(" | ");
        item.appendChild(lineItem);
      });

      els.journalEntriesList.appendChild(item);
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
      const hasProgress =
        course.completion !== false && course.completion !== null && course.completion !== undefined;
      const completion = hasProgress ? Number(course.completion || 0) : null;

      item.innerHTML = `
        <p class="record-title"></p>
        <p class="record-meta"></p>
      `;
      item.querySelector(".record-title").textContent = valueOrDash(course.channel_id);
      const meta = [
        `Source: ${valueOrDash(course.source_label || course.source)}`,
        `Status: ${valueOrDash(course.member_status)}`,
      ];
      if (hasProgress) {
        meta.push(`Progress: ${completion.toFixed(0)}%`);
        meta.push(`Completed slides: ${valueOrDash(course.completed_slides_count)}`);
        meta.push(`Next: ${valueOrDash(course.next_slide_id)}`);
      }
      if (course.order_name || course.order_id) {
        meta.push(`Order: ${valueOrDash(course.order_name || course.order_id)}`);
      }
      if (course.invoice_name || course.invoice_id) {
        meta.push(`Invoice: ${valueOrDash(course.invoice_name || course.invoice_id)}`);
      }
      if (course.salesperson) {
        meta.push(`Salesperson: ${valueOrDash(course.salesperson)}`);
      }
      if (course.quantity) {
        meta.push(`Qty: ${valueOrDash(course.quantity)}`);
      }
      item.querySelector(".record-meta").textContent = meta.join(" | ");

      if (course.description && course.description !== valueOrDash(course.channel_id)) {
        const description = document.createElement("p");
        description.className = "line-item";
        description.textContent = valueOrDash(course.description);
        item.appendChild(description);
      }

      appendRecordFields(item, course, "", {
        exclude: ["channel_id", "description"],
        preferred: [
          "id",
          "source_label",
          "member_status",
          "completion",
          "completed_slides_count",
          "next_slide_id",
          "order_name",
          "invoice_name",
          "salesperson",
          "quantity",
        ],
      });

      if (hasProgress) {
        const progressTrack = document.createElement("div");
        const progressBar = document.createElement("span");
        progressTrack.className = "progress-track";
        progressBar.className = "progress-bar";
        progressBar.style.width = `${Math.max(0, Math.min(100, completion))}%`;
        progressTrack.appendChild(progressBar);
        item.appendChild(progressTrack);
      }

      els.coursesList.appendChild(item);
    });
  }

  function diagnosticEntry(title, meta, kind) {
    const item = document.createElement("article");
    item.className = `record-item${kind ? ` is-${kind}` : ""}`;
    item.innerHTML = `
      <p class="record-title"></p>
      <p class="record-meta"></p>
    `;
    item.querySelector(".record-title").textContent = title;
    const metaNode = item.querySelector(".record-meta");
    if (meta) {
      metaNode.textContent = meta;
    } else {
      metaNode.remove();
    }
    return item;
  }

  function renderDiagnostics(snapshot) {
    clearNode(els.diagnosticsList);
    const entries = [];
    const partner = snapshot.partner || null;
    const warnings = snapshot.warnings || [];
    const debug = snapshot.debug || {};

    if (partner && debug.scope_partner_ids) {
      const scope = Array.isArray(debug.scope_partner_ids)
        ? debug.scope_partner_ids.join(", ")
        : "";
      const commercial =
        debug.commercial_partner_id && debug.commercial_partner_id !== debug.partner_id
          ? ` (commercial partner ${debug.commercial_partner_id} included)`
          : "";
      entries.push(
        diagnosticEntry(
          `Matched Odoo partner ${debug.partner_id ?? valueOrDash(partner.id)}`,
          `Searched contacts, CRM, orders, invoices, journal entries, and courses against partner ids: ${scope}${commercial}.`,
          "muted"
        )
      );
    }

    warnings.forEach((warning) => {
      entries.push(diagnosticEntry("Optional Odoo data unavailable", String(warning), "warning"));
    });

    els.diagnosticsCount.textContent = String(entries.length);
    els.diagnosticsPanel.classList.toggle("is-hidden", entries.length === 0);
    entries.forEach((entry) => els.diagnosticsList.appendChild(entry));
  }

  function renderSnapshot(snapshot) {
    state.snapshot = snapshot;
    state.fieldLabels = snapshot.field_labels || {};
    const partner = snapshot.partner || null;
    const relatedContacts = snapshot.related_contacts || [];
    const leads = snapshot.leads || [];
    const orders = snapshot.orders || [];
    const quotations =
      snapshot.quotations || orders.filter((order) => ["draft", "sent"].includes(order.state));
    const salesOrders =
      snapshot.sales_orders || orders.filter((order) => !["draft", "sent"].includes(order.state));
    const invoices = snapshot.invoices || [];
    const invoicedItems =
      snapshot.invoiced_items ||
      invoices.flatMap((invoice) =>
        (invoice.lines || []).map((line) => ({
          ...line,
          invoice_id: invoice.id,
          invoice_name: invoice.name,
          invoice_date: invoice.invoice_date,
          payment_state: invoice.payment_state,
          invoice_user_id: invoice.invoice_user_id,
          invoice_currency_id: invoice.currency_id,
        }))
      );
    const journalEntries = snapshot.journal_entries || [];
    const courses = snapshot.courses || [];
    const warnings = snapshot.warnings || [];

    const countOrPending = (section, count) =>
      state.loadedSections.has(section) ? String(count) : "...";
    els.metricQuotations.textContent = countOrPending("orders", quotations.length);
    els.metricSalesOrders.textContent = countOrPending("orders", salesOrders.length);
    els.metricLeads.textContent = countOrPending("crm", leads.length);
    els.metricInvoices.textContent = countOrPending("invoices", invoices.length);
    els.metricInvoicedItems.textContent = countOrPending("invoices", invoicedItems.length);
    els.metricCourses.textContent = countOrPending("courses", courses.length);
    els.noteButton.disabled = !state.lastLookup.conversationId;

    renderMatches(snapshot.matches || []);
    renderContact(partner);
    renderRelatedContacts(relatedContacts);
    renderLeads(leads);
    renderOrders(els.quotationsList, quotations);
    renderOrders(els.salesOrdersList, salesOrders);
    renderInvoicedItems(invoicedItems);
    renderInvoices(invoices);
    renderJournalEntries(journalEntries);
    renderCourses(courses);
    renderDiagnostics(snapshot);

    if (partner && warnings.length > 0) {
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
      sections: "profile",
    };
    state.selectedPartnerId = params.partner_id || null;
    state.lastLookup = { ...state.lastLookup, ...params };
    state.loadedSections = new Set(["profile"]);
    state.loadingSections = new Set();
    setStatus("muted", "Loading Odoo data...");
    try {
      const snapshot = await apiFetch("/api/dashboard/search", params);
      renderSnapshot(snapshot);
    } catch (error) {
      setStatus("error", "Could not load Odoo data.");
      console.error(error);
    }
  }

  function mergeSectionSnapshot(current, incoming, section) {
    const merged = { ...(current || {}), partner: incoming.partner || current?.partner || null };
    if (!current?.matches?.length && incoming.matches?.length) merged.matches = incoming.matches;
    if (section === "contacts") merged.related_contacts = incoming.related_contacts || [];
    if (section === "crm") merged.leads = incoming.leads || [];
    if (section === "orders") {
      merged.orders = incoming.orders || [];
      merged.quotations = incoming.quotations || [];
      merged.sales_orders = incoming.sales_orders || [];
    }
    if (section === "invoices") {
      merged.invoices = incoming.invoices || [];
      merged.invoiced_items = incoming.invoiced_items || [];
    }
    if (section === "journal") merged.journal_entries = incoming.journal_entries || [];
    if (section === "courses") merged.courses = incoming.courses || [];

    const labels = { ...(current?.field_labels || {}) };
    Object.entries(incoming.field_labels || {}).forEach(([group, values]) => {
      labels[group] = { ...(labels[group] || {}), ...(values || {}) };
    });
    merged.field_labels = labels;
    merged.warnings = [...new Set([...(current?.warnings || []), ...(incoming.warnings || [])])];
    merged.debug = { ...(current?.debug || {}), ...(incoming.debug || {}) };
    return merged;
  }

  async function loadDashboardSection(section) {
    if (
      !section ||
      section === "profile" ||
      state.loadedSections.has(section) ||
      state.loadingSections.has(section) ||
      !state.snapshot?.partner
    ) {
      return;
    }

    state.loadingSections.add(section);
    setStatus("muted", `Loading ${humanizeField(section)}...`);
    const params = {
      q: state.lastLookup.q || "",
      email: state.lastLookup.email || "",
      phone: state.lastLookup.phone || "",
      partner_id: state.selectedPartnerId || state.snapshot.partner.id || "",
      agent_email: state.lastLookup.agentEmail || "",
      agent_id: state.lastLookup.agentId || "",
      agent_name: state.lastLookup.agentName || "",
      sections: section,
    };

    try {
      const incoming = await apiFetch("/api/dashboard/search", params);
      state.loadedSections.add(section);
      renderSnapshot(mergeSectionSnapshot(state.snapshot, incoming, section));
    } catch (error) {
      setStatus("error", `Could not load ${humanizeField(section)}.`);
      console.error(error);
    } finally {
      state.loadingSections.delete(section);
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

    if (lookup.contactName || lookup.email || lookup.phone) {
      loadSnapshot({
        query: lookup.contactName,
        email: lookup.email,
        phone: lookup.phone,
      });
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
      const sectionMap = {
        contacts: "contacts",
        crm: "crm",
        quotations: "orders",
        "sales-orders": "orders",
        "invoiced-items": "invoices",
        invoices: "invoices",
        courses: "courses",
        journal: "journal",
      };
      loadDashboardSection(sectionMap[button.dataset.tab]);
    });
  });

  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (state.themeChoice === "auto") setTheme("auto");
  });

  setTheme(state.themeChoice);
  window.parent.postMessage("chatwoot-dashboard-app:fetch-info", "*");
})();
