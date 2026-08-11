/* Admin dashboard logic */
(function () {
  var $ = function (id) { return document.getElementById(id); };
  var DAY_START = 7, DAY_END = 21;   // updated from /api/config
  var hourState = {};                // hour -> {status, price_cents} for selected date
  var selectedHours = {};            // hour -> true (pending selection in editor)

  function alertIn(el, msg, kind) {
    el.className = "alert show " + (kind === "ok" ? "alert-ok" : kind === "info" ? "alert-info" : "alert-err");
    el.textContent = msg;
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function hourLabel(h) {
    var ampm = h < 12 ? "AM" : "PM"; var h12 = h % 12; if (h12 === 0) h12 = 12;
    return h12 + ":00 " + ampm;
  }
  function fmtTs(iso) {
    if (!iso) return "";
    var d = new Date(iso + (iso.indexOf("Z") === -1 ? "Z" : ""));
    if (isNaN(d)) return iso;
    return d.toLocaleString();
  }

  // ---- Views ----
  var loginView = $("login-view"), dashView = $("dash-view");
  function setNavLogin(authed) {
    var el = document.getElementById("nav-login");
    if (!el) return;
    el.textContent = authed ? "🔓 Admin" : "🔒 Login";
    el.title = authed ? "You are signed in" : "";
  }
  function showDash() { loginView.style.display = "none"; dashView.style.display = "block"; setNavLogin(true); loadAll(); }
  function showLogin() { loginView.style.display = "block"; dashView.style.display = "none"; setNavLogin(false); }

  async function checkSession() {
    try {
      var cfg = await (await fetch("/api/config")).json();
      DAY_START = cfg.day_start; DAY_END = cfg.day_end;
    } catch (e) {}
    try {
      var r = await (await fetch("/api/admin/session")).json();
      if (r.authed) showDash(); else showLogin();
    } catch (e) { showLogin(); }
  }

  // ---- Login ----
  $("login-form").addEventListener("submit", async function (e) {
    e.preventDefault();
    var btn = $("login-btn"); btn.disabled = true; btn.textContent = "Signing in…";
    try {
      var r = await (await fetch("/api/admin/login", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: $("password").value })
      })).json();
      if (r.ok) { $("password").value = ""; showDash(); }
      else alertIn($("login-alert"), r.error || "Incorrect password.", "err");
    } catch (e) { alertIn($("login-alert"), "Network error.", "err"); }
    finally { btn.disabled = false; btn.textContent = "Sign In"; }
  });
  $("logout-btn").addEventListener("click", async function () {
    await fetch("/api/admin/logout", { method: "POST" }); showLogin();
  });

  // ---- Tabs ----
  document.querySelectorAll(".tab-btn").forEach(function (b) {
    b.addEventListener("click", function () {
      document.querySelectorAll(".tab-btn").forEach(function (x) { x.classList.remove("active"); });
      document.querySelectorAll(".tab-panel").forEach(function (x) { x.classList.remove("active"); });
      b.classList.add("active");
      $("tab-" + b.dataset.tab).classList.add("active");
    });
  });

  // ---- Availability editor ----
  function renderHourEditor() {
    var html = "";
    for (var h = DAY_START; h < DAY_END; h++) {
      var st = hourState[h];
      if (st && st.status === "booked") {
        html += '<div class="hour-cell booked"><div class="h-time">' + hourLabel(h) +
          '</div><div class="h-tag">Booked</div></div>';
      } else {
        var sel = selectedHours[h];
        html += '<div class="hour-cell ' + (sel ? "selected" : "unavailable") + '" data-hour="' + h + '">' +
          '<div class="h-time">' + hourLabel(h) + '</div>' +
          '<div class="h-tag">' + (sel ? "Available" : "Off") + '</div></div>';
      }
    }
    var grid = $("admin-hour-grid");
    grid.innerHTML = html;
    grid.querySelectorAll(".hour-cell[data-hour]").forEach(function (el) {
      el.addEventListener("click", function () {
        var h = parseInt(el.getAttribute("data-hour"), 10);
        if (selectedHours[h]) delete selectedHours[h]; else selectedHours[h] = true;
        renderHourEditor();
      });
    });
  }

  // Weekday picker (JS convention: Sun=0..Sat=6)
  var WD = [["Sun",0],["Mon",1],["Tue",2],["Wed",3],["Thu",4],["Fri",5],["Sat",6]];
  function renderWeekdayPicker() {
    var html = WD.map(function (w) {
      return '<label style="display:inline-flex;align-items:center;gap:6px;font-weight:400;border:1px solid var(--line);' +
        'border-radius:8px;padding:6px 10px;cursor:pointer;">' +
        '<input type="checkbox" class="wd-cb" value="' + w[1] + '" checked style="width:auto;"> ' + w[0] + '</label>';
    }).join("");
    html += '<button type="button" class="btn btn-ghost btn-sm" id="wd-weekdays">Mon–Fri</button>' +
            '<button type="button" class="btn btn-ghost btn-sm" id="wd-all">All 7</button>';
    $("weekday-picker").innerHTML = html;
    $("wd-weekdays").addEventListener("click", function () { setWeekdays([1,2,3,4,5]); });
    $("wd-all").addEventListener("click", function () { setWeekdays([0,1,2,3,4,5,6]); });
  }
  function setWeekdays(list) {
    document.querySelectorAll(".wd-cb").forEach(function (cb) {
      cb.checked = list.indexOf(parseInt(cb.value, 10)) !== -1;
    });
  }
  function checkedWeekdays() {
    var out = [];
    document.querySelectorAll(".wd-cb:checked").forEach(function (cb) { out.push(parseInt(cb.value, 10)); });
    return out;
  }
  function toggleRangeUI() {
    var isRange = !!$("a-end-date").value && $("a-end-date").value !== $("a-date").value;
    $("weekday-row").style.display = isRange ? "block" : "none";
    $("avail-save").textContent = isRange ? "Save Availability for These Days" : "Save Availability for This Day";
  }

  async function loadDayState() {
    toggleRangeUI();
    var ds = $("a-date").value;
    if (!ds) return;
    hourState = {}; selectedHours = {};
    try {
      var r = await (await fetch("/api/admin/hours?date=" + ds)).json();
      if (r.ok) {
        hourState = r.state || {};
        DAY_START = r.day_start; DAY_END = r.day_end;
        // Pre-select currently-open hours; note the existing price
        var anyPrice = null;
        Object.keys(hourState).forEach(function (h) {
          if (hourState[h].status === "open") { selectedHours[h] = true; anyPrice = hourState[h].price_cents; }
        });
        if (anyPrice != null) $("a-price").value = (anyPrice / 100);
      }
    } catch (e) {}
    renderHourEditor();
  }
  $("a-date").addEventListener("change", loadDayState);
  $("a-end-date").addEventListener("change", toggleRangeUI);

  $("avail-selectall").addEventListener("click", function () {
    for (var h = DAY_START; h < DAY_END; h++) {
      if (!(hourState[h] && hourState[h].status === "booked")) selectedHours[h] = true;
    }
    renderHourEditor();
  });
  $("avail-clear").addEventListener("click", function () {
    selectedHours = {}; renderHourEditor();
  });

  $("avail-save").addEventListener("click", async function () {
    var ds = $("a-date").value;
    if (!ds) { alertIn($("avail-alert"), "Please choose a start date first.", "err"); return; }
    var endDs = $("a-end-date").value;
    var isRange = !!endDs && endDs !== ds;
    if (isRange && endDs < ds) {
      alertIn($("avail-alert"), "End date must be on or after the start date.", "err"); return;
    }
    var hours = Object.keys(selectedHours).map(Number);
    var payload = { date: ds, hours: hours, price: $("a-price").value };
    if (isRange) {
      payload.end_date = endDs;
      var wd = checkedWeekdays();
      if (wd.length === 0) { alertIn($("avail-alert"), "Please select at least one weekday.", "err"); return; }
      payload.weekdays = wd;
    }
    var btn = $("avail-save"); var origLabel = btn.textContent; btn.disabled = true; btn.textContent = "Saving…";
    try {
      var r = await (await fetch("/api/admin/hours", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      })).json();
      if (r.ok) { alertIn($("avail-alert"), r.message, "ok"); loadDayState(); }
      else alertIn($("avail-alert"), r.error, "err");
    } catch (e) { alertIn($("avail-alert"), "Network error.", "err"); }
    finally { btn.disabled = false; btn.textContent = origLabel; toggleRangeUI(); }
  });

  // ---- Bookings ----
  async function loadBookings() {
    var r = await (await fetch("/api/admin/bookings")).json();
    var tb = $("bookings-table").querySelector("tbody"); tb.innerHTML = "";
    if (!r.ok || !r.bookings.length) { $("bookings-empty").style.display = "block"; $("bookings-table").style.display = "none"; return; }
    $("bookings-empty").style.display = "none"; $("bookings-table").style.display = "table";
    r.bookings.forEach(function (b) {
      var pillCls = b.payment_status === "paid" ? "paid" : b.payment_status === "unpaid_request" ? "request" : "pending";
      var pillTxt = b.payment_status === "unpaid_request" ? "reserved (unpaid)" : b.payment_status;
      var tr = document.createElement("tr");
      tr.innerHTML =
        "<td>" + esc(b.when) + "</td>" +
        "<td>" + esc(b.name) + "</td>" +
        '<td><a href="mailto:' + esc(b.email) + '">' + esc(b.email) + "</a><br><span class='muted'>" + esc(b.phone || "") + "</span></td>" +
        "<td>" + esc(b.service || "—") + "</td>" +
        "<td>" + esc(b.amount_display) + "</td>" +
        '<td><span class="pill ' + pillCls + '">' + pillTxt + "</span></td>";
      tb.appendChild(tr);
    });
  }
  $("refresh-bookings").addEventListener("click", loadBookings);

  // ---- Customers ----
  async function loadCustomers() {
    var r = await (await fetch("/api/admin/customers")).json();
    var tb = $("customers-table").querySelector("tbody"); tb.innerHTML = "";
    if (!r.ok || !r.customers.length) { $("customers-empty").style.display = "block"; $("customers-table").style.display = "none"; return; }
    $("customers-empty").style.display = "none"; $("customers-table").style.display = "table";
    r.customers.forEach(function (c) {
      var tr = document.createElement("tr");
      tr.innerHTML =
        "<td>" + esc(c.name) + "</td>" +
        '<td><a href="mailto:' + esc(c.email) + '">' + esc(c.email) + "</a></td>" +
        "<td>" + esc(c.phone || "—") + "</td>" +
        "<td>" + esc(c.address || "—") + "</td>" +
        "<td>" + esc(c.bookings) + "</td>";
      tb.appendChild(tr);
    });
  }
  $("refresh-customers").addEventListener("click", loadCustomers);

  // ---- Contacts ----
  async function loadContacts() {
    var r = await (await fetch("/api/admin/contacts")).json();
    var tb = $("contacts-table").querySelector("tbody"); tb.innerHTML = "";
    if (!r.ok || !r.contacts.length) { $("contacts-empty").style.display = "block"; $("contacts-table").style.display = "none"; return; }
    $("contacts-empty").style.display = "none"; $("contacts-table").style.display = "table";
    r.contacts.forEach(function (c) {
      var tr = document.createElement("tr");
      tr.innerHTML =
        "<td>" + fmtTs(c.created_at) + "</td>" +
        "<td>" + esc(c.name) + "</td>" +
        '<td><a href="mailto:' + esc(c.email) + '">' + esc(c.email) + "</a><br><span class='muted'>" + esc(c.phone) + "</span></td>" +
        "<td>" + esc(c.service || "—") + "</td>" +
        "<td>" + esc(c.message || "—") + "</td>";
      tb.appendChild(tr);
    });
  }
  $("refresh-contacts").addEventListener("click", loadContacts);

  // ---- Settings ----
  async function loadSettings() {
    var r = await (await fetch("/api/admin/settings")).json();
    if (!r.ok) return;
    var s = r.settings;
    $("notify_email").value = s.notify_email || "";
    $("smtp_host").value = s.smtp_host || "";
    $("smtp_port").value = s.smtp_port || "";
    $("smtp_user").value = s.smtp_user || "";
    $("smtp_from").value = s.smtp_from || "";
    $("stripe_publishable_key").value = s.stripe_publishable_key || "";
    $("currency").value = s.currency || "usd";
    $("site_base_url").value = s.site_base_url || "";
    $("thankyou_template").value = s.thankyou_template || "";
    $("stripe-status").textContent = s.stripe_secret_set
      ? "✓ A secret key is saved. Card payments are enabled at checkout."
      : "No secret key saved yet — checkout reserves bookings without charging.";
  }

  $("save-email").addEventListener("click", async function () {
    var payload = {
      notify_email: $("notify_email").value, smtp_host: $("smtp_host").value,
      smtp_port: $("smtp_port").value, smtp_user: $("smtp_user").value, smtp_from: $("smtp_from").value
    };
    if ($("smtp_pass").value) payload.smtp_pass = $("smtp_pass").value;
    var r = await (await fetch("/api/admin/settings", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload)
    })).json();
    alertIn($("email-alert"), r.ok ? "Email settings saved." : (r.error || "Error"), r.ok ? "ok" : "err");
    $("smtp_pass").value = "";
  });

  $("save-tmpl").addEventListener("click", async function () {
    var r = await (await fetch("/api/admin/settings", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ thankyou_template: $("thankyou_template").value })
    })).json();
    alertIn($("tmpl-alert"), r.ok ? "Template saved." : (r.error || "Error"), r.ok ? "ok" : "err");
  });

  $("save-stripe").addEventListener("click", async function () {
    var payload = {
      stripe_publishable_key: $("stripe_publishable_key").value,
      currency: $("currency").value, site_base_url: $("site_base_url").value
    };
    if ($("stripe_secret_key").value) payload.stripe_secret_key = $("stripe_secret_key").value;
    var r = await (await fetch("/api/admin/settings", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload)
    })).json();
    alertIn($("stripe-alert"), r.ok ? "Payment settings saved." : (r.error || "Error"), r.ok ? "ok" : "err");
    $("stripe_secret_key").value = ""; loadSettings();
  });

  $("save-pw").addEventListener("click", async function () {
    var r = await (await fetch("/api/admin/password", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ new_password: $("new_password").value })
    })).json();
    alertIn($("pw-alert"), r.ok ? "Password updated." : (r.error || "Error"), r.ok ? "ok" : "err");
    if (r.ok) $("new_password").value = "";
  });

  function loadAll() { loadDayState(); loadBookings(); loadCustomers(); loadContacts(); loadSettings(); }

  // Default availability date = today
  var t = new Date();
  $("a-date").value = t.getFullYear() + "-" + String(t.getMonth() + 1).padStart(2, "0") + "-" + String(t.getDate()).padStart(2, "0");
  renderWeekdayPicker();

  checkSession();
})();
