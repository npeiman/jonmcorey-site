/* Monthly calendar + day hour picker */
(function () {
  var $ = function (id) { return document.getElementById(id); };
  var MONTHS = ["January","February","March","April","May","June","July","August",
    "September","October","November","December"];
  var DOWS = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];

  var view = new Date();
  view.setDate(1);
  var todayIso = null;
  var monthDays = {};          // "YYYY-MM-DD" -> open_count
  var selectedDate = null;
  var selectedHour = null;
  var selectedPrice = null;

  function iso(y, m, d) {
    return y + "-" + String(m + 1).padStart(2, "0") + "-" + String(d).padStart(2, "0");
  }
  function showAlert(msg) {
    var a = $("alert"); a.className = "alert show alert-err"; a.textContent = msg;
  }
  function showInfo(msg) {
    var a = $("alert"); a.className = "alert show alert-info"; a.textContent = msg;
  }
  function hideAlert() {
    var a = $("alert"); a.className = "alert";
  }

  // Draw day-of-week header once
  (function () {
    $("cal-dows").innerHTML = DOWS.map(function (d) {
      return '<div class="cal-dow">' + d + "</div>";
    }).join("");
  })();

  async function loadMonth() {
    hideAlert();
    var y = view.getFullYear(), m = view.getMonth();
    $("cal-title").textContent = MONTHS[m] + " " + y;
    try {
      var r = await (await fetch("/api/availability/month?year=" + y + "&month=" + (m + 1))).json();
      if (!r.ok) { showAlert("Could not load the calendar."); return; }
      monthDays = r.days || {};
      todayIso = r.today;
      renderDays();
    } catch (e) { showAlert("Could not load the calendar. Please refresh."); }
    // Disable prev when the viewed month is before the current month
    var now = new Date(); now.setDate(1); now.setHours(0,0,0,0);
    $("prev-month").disabled = (view.getFullYear() === now.getFullYear() && view.getMonth() <= now.getMonth());
  }

  function renderDays() {
    var y = view.getFullYear(), m = view.getMonth();
    var firstDow = new Date(y, m, 1).getDay();
    var daysInMonth = new Date(y, m + 1, 0).getDate();
    var cells = "", availableInMonth = 0;
    for (var i = 0; i < firstDow; i++) cells += '<div class="cal-day empty"></div>';
    for (var d = 1; d <= daysInMonth; d++) {
      var ds = iso(y, m, d);
      var count = monthDays[ds] || 0;
      var isPast = todayIso && ds < todayIso;
      var isToday = (ds === todayIso);
      var cls = "cal-day", extra = "";
      if (isToday) cls += " today";
      if (!isPast && count > 0) {
        cls += " available"; availableInMonth++;
        if (ds === selectedDate) cls += " selected";
        extra = '<span class="dot"></span><span class="count">' + count + " open</span>";
      } else {
        cls += " unavailable";
        if (isToday) extra = '<span class="today-lbl">Today</span>';
      }
      cells += '<div class="' + cls + '" data-date="' + ds + '" data-available="' +
        (!isPast && count > 0 ? "1" : "0") + '" data-past="' + (isPast ? "1" : "0") +
        '"><span>' + d + "</span>" + extra + "</div>";
    }
    $("cal-days").innerHTML = cells;
    $("cal-days").querySelectorAll('.cal-day[data-available="1"]').forEach(function (el) {
      el.addEventListener("click", function () { hideAlert(); openDay(el.getAttribute("data-date")); });
    });
    // Gentle feedback when a day with no openings is clicked
    $("cal-days").querySelectorAll('.cal-day.unavailable[data-past="0"]').forEach(function (el) {
      if (el.classList.contains("empty")) return;
      el.style.cursor = "pointer";
      el.addEventListener("click", function () {
        showInfo("No openings on that day. Please choose a highlighted date, or use the arrows to view another month.");
      });
    });
    // Month-level empty state
    if (availableInMonth === 0) {
      showInfo("No available dates are posted this month. Use the arrows to check another month, or contact us to arrange a time.");
    }
  }

  function fmtDateLong(ds) {
    var p = ds.split("-");
    var dt = new Date(parseInt(p[0]), parseInt(p[1]) - 1, parseInt(p[2]));
    return dt.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric", year: "numeric" });
  }

  async function openDay(ds) {
    selectedDate = ds; selectedHour = null; selectedPrice = null;
    renderDays();
    $("cal-wrap").classList.add("with-day");
    $("day-card").style.display = "block";
    $("day-title").textContent = fmtDateLong(ds);
    $("selection-box").style.display = "none";
    var grid = $("hour-grid"); grid.innerHTML = '<p class="muted">Loading times…</p>';
    try {
      var r = await (await fetch("/api/availability/day?date=" + ds)).json();
      if (!r.ok) { grid.innerHTML = ""; $("day-empty").style.display = "block"; return; }
      renderHours(r);
    } catch (e) { grid.innerHTML = '<p class="muted">Could not load times.</p>'; }
    $("day-card").scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function renderHours(r) {
    // Build a fixed window (day_start..day_end) so unavailable hours are greyed.
    var byHour = {};
    r.hours.forEach(function (h) { byHour[h.hour] = h; });
    var openCount = 0, html = "";
    for (var h = r.day_start; h < r.day_end; h++) {
      var info = byHour[h];
      if (info && info.status === "open") {
        openCount++;
        html += '<div class="hour-cell open" data-hour="' + h + '" data-price="' + info.price_cents + '">' +
          '<div class="h-time">' + info.label + "</div>" +
          '<div class="h-price">' + (info.price_cents > 0 ? info.price_display : "Complimentary") + "</div>" +
          "</div>";
      } else if (info && info.status === "booked") {
        html += '<div class="hour-cell booked"><div class="h-time">' + info.label + "</div>" +
          '<div class="h-tag">Booked</div></div>';
      } else {
        html += '<div class="hour-cell unavailable"><div class="h-time">' + hourLabel(h) + "</div>" +
          '<div class="h-tag">—</div></div>';
      }
    }
    $("hour-grid").innerHTML = html;
    $("day-empty").style.display = openCount ? "none" : "block";
    $("hour-grid").querySelectorAll(".hour-cell.open").forEach(function (el) {
      el.addEventListener("click", function () { selectHour(el); });
    });
  }

  function hourLabel(h) {
    var ampm = h < 12 ? "AM" : "PM"; var h12 = h % 12; if (h12 === 0) h12 = 12;
    return h12 + ":00 " + ampm;
  }

  function selectHour(el) {
    $("hour-grid").querySelectorAll(".hour-cell").forEach(function (c) { c.classList.remove("selected"); });
    el.classList.add("selected");
    selectedHour = parseInt(el.getAttribute("data-hour"), 10);
    selectedPrice = parseInt(el.getAttribute("data-price"), 10);
    var start = hourLabel(selectedHour), end = hourLabel(selectedHour + 1);
    $("sel-summary").textContent = fmtDateLong(selectedDate) + " · " + start + " – " + end + " (1 hour)";
    $("sel-price").textContent = selectedPrice > 0 ? "Total: " + money(selectedPrice) : "Complimentary session";
    $("continue-btn").href = "/checkout?date=" + selectedDate + "&hour=" + selectedHour;
    $("selection-box").style.display = "block";
    $("selection-box").scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function money(cents) { return "$" + (cents / 100).toFixed(2); }

  $("prev-month").addEventListener("click", function () {
    view.setMonth(view.getMonth() - 1); selectedDate = null;
    $("day-card").style.display = "none"; $("cal-wrap").classList.remove("with-day");
    loadMonth();
  });
  $("next-month").addEventListener("click", function () {
    view.setMonth(view.getMonth() + 1); selectedDate = null;
    $("day-card").style.display = "none"; $("cal-wrap").classList.remove("with-day");
    loadMonth();
  });

  loadMonth();
})();
