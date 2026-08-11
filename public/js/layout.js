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
        link("/calendar", "Book a Session", "calendar") +
        link("/contact", "Contact", "contact") +
        link("/calendar", "Schedule Now", "", "cta") +
        '<a href="/admin" class="nav-login" id="nav-login">🔒 Login</a>' +
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

  // Reflect signed-in state on the Login button.
  fetch("/api/admin/session").then(function (r) { return r.json(); }).then(function (d) {
    var el = document.getElementById("nav-login");
    if (el && d && d.authed) { el.textContent = "🔓 Admin"; el.title = "You are signed in"; }
  }).catch(function () {});
})();
