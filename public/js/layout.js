/* Shared header + footer, injected on every page. */
(function () {
  var page = document.body.getAttribute("data-page") || "";

  function link(href, label, key, extraClass) {
    var cls = extraClass || "";
    if (page === key) cls += " active";
    return '<a href="' + href + '" class="' + cls.trim() + '">' + label + "</a>";
  }

  var header =
    '<header class="site-header"><div class="nav">' +
      '<a class="brand" href="/">' +
        '<span class="mark">PAG</span>' +
        '<span class="brand-text">' +
          '<span class="brand-name">Professional Advisory Group</span>' +
          '<span class="brand-sub">Rev. Jon M. Corey, PhD</span>' +
        '</span>' +
      '</a>' +
      '<nav class="nav-links">' +
        link("/", "Home", "home") +
        link("/about", "About", "about") +
        link("/calendar", "Book a Session", "calendar") +
        link("/contact", "Contact", "contact") +
        link("/calendar", "Schedule Now", "", "cta") +
      '</nav>' +
    '</div></header>';

  var year = new Date().getFullYear();
  var footer =
    '<footer class="site-footer"><div class="container"><div class="footer-grid">' +
      '<div>' +
        '<h4>Professional Advisory Group</h4>' +
        '<p style="margin-top:10px;color:#c7d1de;">Compassionate, professional pastoral and ministerial ' +
        'services for individuals and families — available on short or emergency notice. ' +
        'All faiths, convictions, and cultures are welcome.</p>' +
      '</div>' +
      '<div>' +
        '<h4>Navigate</h4>' +
        '<ul class="footer-list">' +
          '<li><a href="/">Home</a></li>' +
          '<li><a href="/about">About</a></li>' +
          '<li><a href="/calendar">Book a Session</a></li>' +
          '<li><a href="/contact">Contact Us</a></li>' +
        '</ul>' +
      '</div>' +
      '<div>' +
        '<h4>Contact</h4>' +
        '<ul class="footer-list">' +
          '<li>Rev. Jon M. Corey, PhD</li>' +
          '<li><a href="tel:+14803886606">480.388.6606</a></li>' +
          '<li><a href="mailto:jonmichaelcorey@gmail.com">jonmichaelcorey@gmail.com</a></li>' +
        '</ul>' +
      '</div>' +
    '</div>' +
    '<div class="footer-bottom">© ' + year + ' Professional Advisory Group · Rev. Jon M. Corey, PhD · ' +
    'Ordained by the National Association of Christian Ministers</div>' +
    '</div></footer>';

  var h = document.getElementById("site-header");
  if (h) h.outerHTML = header;
  var f = document.getElementById("site-footer");
  if (f) f.outerHTML = footer;

  // ---- Hidden admin entrance: double-click the PAG logo ----
  // Single click on the logo still goes Home. A double-click opens the admin
  // login (or, if already signed in, a small Admin / Sign Out dialog).
  var authed = false;
  fetch("/api/admin/session").then(function (r) { return r.json(); })
    .then(function (d) { authed = !!(d && d.authed); }).catch(function () {});

  var backdrop = document.createElement("div");
  backdrop.className = "modal-backdrop";
  backdrop.innerHTML =
    '<div class="modal" style="max-width:360px;text-align:center;">' +
      '<h3 style="margin-top:0;">Admin</h3>' +
      '<p class="muted" id="pag-admin-msg">You are signed in as Dr. Jon M. Corey.</p>' +
      '<div class="modal-actions" style="justify-content:center;">' +
        '<button class="btn btn-ghost" id="pag-admin-dash">Go to Admin</button>' +
        '<button class="btn btn-primary" id="pag-admin-logout">Sign Out</button>' +
      '</div>' +
      '<p style="margin:12px 0 0;"><a href="#" id="pag-admin-cancel" class="muted" style="font-size:.85rem;">Cancel</a></p>' +
    '</div>';
  document.body.appendChild(backdrop);
  function closeModal() { backdrop.classList.remove("show"); }
  backdrop.addEventListener("click", function (e) { if (e.target === backdrop) closeModal(); });
  document.getElementById("pag-admin-cancel").addEventListener("click", function (e) { e.preventDefault(); closeModal(); });
  document.getElementById("pag-admin-dash").addEventListener("click", function () { window.location.href = "/admin"; });
  document.getElementById("pag-admin-logout").addEventListener("click", function () {
    fetch("/api/admin/logout", { method: "POST" }).then(function () {
      authed = false; closeModal(); window.location.href = "/";
    }).catch(function () { closeModal(); });
  });

  function secretAdmin() {
    if (authed) { backdrop.classList.add("show"); }
    else { window.location.href = "/admin"; }
  }

  var brand = document.querySelector(".brand");
  if (brand) {
    var clickTimer = null;
    brand.addEventListener("click", function (e) {
      e.preventDefault();
      if (clickTimer) return;           // second click handled by dblclick
      clickTimer = setTimeout(function () {
        clickTimer = null;
        window.location.href = "/";      // single click → Home
      }, 260);
    });
    brand.addEventListener("dblclick", function (e) {
      e.preventDefault();
      if (clickTimer) { clearTimeout(clickTimer); clickTimer = null; }
      secretAdmin();
    });
  }
})();
