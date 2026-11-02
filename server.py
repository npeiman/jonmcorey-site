#!/usr/bin/env python3
"""
Professional Advisory Group — Rev. Jon M. Corey, PhD
Self-contained website + booking backend.

Pure Python standard library (no pip installs required).
Run:  python3 server.py           (defaults to http://localhost:8000)
      PORT=9000 python3 server.py  (custom port)

Bookings are fixed 1-hour sessions. Availability is defined per hour, per day,
within a 7 AM - 9 PM window. Data is stored in a local SQLite file (pag.db).
"""

import http.server
import socketserver
import json
import os
import re
import calendar as _calendar
import sqlite3
import hashlib
import hmac
import secrets
import smtplib
import urllib.request
import urllib.parse
import mimetypes
from datetime import datetime, date, timedelta
from email.message import EmailMessage
from http import cookies

# ---------------------------------------------------------------------------
# Configuration & paths
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR = os.path.join(BASE_DIR, "public")
DB_PATH = os.environ.get("PAG_DB", os.path.join(BASE_DIR, "pag.db"))
PORT = int(os.environ.get("PORT", "8000"))
# Bind address. Default "" = all interfaces (handy for local dev). In production
# behind nginx, set HOST=127.0.0.1 so the app is only reachable via the proxy.
HOST = os.environ.get("HOST", "")

# Bookable window (start hours). 7 => 7 AM ... 20 => 8 PM-9 PM block.
DAY_START_HOUR = 7
DAY_END_HOUR = 21  # exclusive: last bookable start hour is 20 (8-9 PM)

DEFAULT_THANKYOU = (
    "Dear {name},\n\n"
    "Thank you for booking a session with Rev. Jon M. Corey of the "
    "Professional Advisory Group.\n\n"
    "Your session is confirmed:\n"
    "  Date: {date}\n"
    "  Time: {start_time} - {end_time}\n"
    "  Service: {service}\n"
    "  Amount: {amount}\n\n"
    "If you need to make any changes, please reply to this email or call "
    "480.388.6606.\n\n"
    "With warm regards,\n"
    "Rev. Jon M. Corey, PhD\n"
    "Professional Advisory Group"
)

# In-memory admin sessions: token -> created timestamp
SESSIONS = {}

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS hours (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,          -- YYYY-MM-DD
            hour INTEGER NOT NULL,       -- start hour 0-23 (block = hour:00 to hour+1:00)
            price_cents INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'open',  -- open | booked
            created_at TEXT NOT NULL,
            UNIQUE(date, hour)
        );

        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            address TEXT,
            phone TEXT,
            email TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER,
            date TEXT NOT NULL,
            hour INTEGER NOT NULL,
            service TEXT,
            notes TEXT,
            amount_cents INTEGER NOT NULL DEFAULT 0,
            payment_status TEXT NOT NULL DEFAULT 'pending', -- pending | paid | unpaid_request
            stripe_session_id TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(customer_id) REFERENCES customers(id)
        );

        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT NOT NULL,
            service TEXT,
            message TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    conn.commit()

    defaults = {
        "admin_password_hash": "",
        "admin_salt": "",
        "notify_email": "jonmichaelcorey@gmail.com",
        "smtp_host": "",
        "smtp_port": "587",
        "smtp_user": "",
        "smtp_pass": "",
        "smtp_from": "",
        "stripe_secret_key": "",
        "stripe_publishable_key": "",
        "currency": "usd",
        "site_base_url": "http://localhost:%d" % PORT,
        "thankyou_template": DEFAULT_THANKYOU,
        "next_invoice_number": "1005",
    }
    for k, v in defaults.items():
        c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))

    # Ensure an admin user exists in the database. If a legacy settings-based
    # password is present, migrate it; otherwise create the default admin user.
    au = c.execute("SELECT COUNT(*) AS n FROM admin_users").fetchone()
    if au["n"] == 0:
        legacy_hash = c.execute("SELECT value FROM settings WHERE key='admin_password_hash'").fetchone()
        legacy_salt = c.execute("SELECT value FROM settings WHERE key='admin_salt'").fetchone()
        now = datetime.utcnow().isoformat()
        if legacy_hash and legacy_hash["value"] and legacy_salt and legacy_salt["value"]:
            c.execute("INSERT INTO admin_users(username, password_hash, salt, created_at) "
                      "VALUES ('admin', ?, ?, ?)",
                      (legacy_hash["value"], legacy_salt["value"], now))
            print("=" * 64)
            print(" ADMIN USER READY  (username: admin)")
            print("   Existing password preserved. Change it on the Admin page.")
            print("=" * 64)
        else:
            salt = secrets.token_hex(16)
            c.execute("INSERT INTO admin_users(username, password_hash, salt, created_at) "
                      "VALUES ('admin', ?, ?, ?)",
                      (hash_password("changeme", salt), salt, now))
            print("=" * 64)
            print(" ADMIN USER CREATED")
            print("   Username: admin   Password: changeme")
            print("   Change the password on the Admin page (Settings) after logging in.")
            print("=" * 64)

    # Lightweight migrations: add columns if missing.
    def ensure_col(table, col, decl):
        cols = [r[1] for r in c.execute("PRAGMA table_info(%s)" % table).fetchall()]
        if col not in cols:
            c.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, col, decl))

    # Booking lifecycle + payment method
    ensure_col("bookings", "status", "TEXT NOT NULL DEFAULT 'active'")   # active | cancelled
    ensure_col("bookings", "archived", "INTEGER NOT NULL DEFAULT 0")
    ensure_col("bookings", "payment_method", "TEXT NOT NULL DEFAULT ''")  # card | in_person
    ensure_col("bookings", "invoice_number", "INTEGER")
    ensure_col("bookings", "invoice_created_at", "TEXT")
    # Structured (Stripe-conformant) billing address + Dr. Corey's private notes
    ensure_col("customers", "address2", "TEXT")
    ensure_col("customers", "city", "TEXT")
    ensure_col("customers", "state", "TEXT")
    ensure_col("customers", "zip", "TEXT")
    ensure_col("customers", "country", "TEXT")
    ensure_col("customers", "corey_notes", "TEXT")
    # Admin identity
    ensure_col("admin_users", "display_name", "TEXT")
    c.execute("UPDATE admin_users SET display_name='Dr. Jon M. Corey' "
              "WHERE username='admin' AND (display_name IS NULL OR display_name='')")

    conn.commit()
    conn.close()


def get_setting(key, default=""):
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row and row["value"] is not None else default


def set_setting(key, value):
    conn = get_db()
    conn.execute(
        "INSERT INTO settings(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def hash_password(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120000).hex()


def verify_password(password, username="admin"):
    conn = get_db()
    row = conn.execute("SELECT password_hash, salt FROM admin_users WHERE username=?",
                       (username,)).fetchone()
    conn.close()
    if not row:
        return False
    return hmac.compare_digest(hash_password(password, row["salt"]), row["password_hash"])


def make_session():
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = datetime.utcnow().isoformat()
    return token


def is_authed(handler):
    cookie_header = handler.headers.get("Cookie", "")
    if not cookie_header:
        return False
    ck = cookies.SimpleCookie()
    ck.load(cookie_header)
    if "admin_token" in ck:
        return ck["admin_token"].value in SESSIONS
    return False


# ---------------------------------------------------------------------------
# Validation / formatting helpers
# ---------------------------------------------------------------------------
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def valid_email(e):
    return bool(e and EMAIL_RE.match(e.strip()))


def money_str(cents):
    return "${:,.2f}".format((cents or 0) / 100.0)


def hour_label(h):
    ampm = "AM" if h < 12 else "PM"
    h12 = h % 12
    if h12 == 0:
        h12 = 12
    return "%d:00 %s" % (h12, ampm)


def hour_range_label(h):
    return "%s - %s" % (hour_label(h), hour_label(h + 1))


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------
def send_email(subject, body, to_addr=None, reply_to=None):
    host = get_setting("smtp_host")
    if not host:
        return False, "SMTP not configured"
    port = int(get_setting("smtp_port", "587") or "587")
    user = get_setting("smtp_user")
    pw = get_setting("smtp_pass")
    from_addr = get_setting("smtp_from") or user
    to_addr = to_addr or get_setting("notify_email")
    if not to_addr:
        return False, "No recipient configured"
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    if reply_to:
        msg["Reply-To"] = reply_to   # so "Reply" goes to the client, not himself
    msg.set_content(body)
    try:
        with smtplib.SMTP(host, port, timeout=15) as s:
            s.starttls()
            if user:
                s.login(user, pw)
            s.send_message(msg)
        return True, "sent"
    except Exception as e:  # noqa
        return False, str(e)


def render_thankyou(template, ctx):
    out = template or DEFAULT_THANKYOU
    for k, v in ctx.items():
        out = out.replace("{%s}" % k, str(v))
    return out


# ---------------------------------------------------------------------------
# Stripe (via REST API, no library required)
# ---------------------------------------------------------------------------
def stripe_create_checkout_session(amount_cents, description, success_url, cancel_url,
                                    customer_email=None, metadata=None):
    secret = get_setting("stripe_secret_key")
    if not secret:
        raise RuntimeError("Stripe not configured")
    currency = get_setting("currency", "usd") or "usd"
    fields = {
        "mode": "payment",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "line_items[0][price_data][currency]": currency,
        "line_items[0][price_data][product_data][name]": description,
        "line_items[0][price_data][unit_amount]": str(int(amount_cents)),
        "line_items[0][quantity]": "1",
    }
    if customer_email:
        fields["customer_email"] = customer_email
    if metadata:
        for k, v in metadata.items():
            fields["metadata[%s]" % k] = str(v)
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(
        "https://api.stripe.com/v1/checkout/sessions",
        data=data,
        headers={
            "Authorization": "Bearer %s" % secret,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode())
    return payload["url"], payload["id"]


def stripe_create_payment_intent(amount_cents, metadata=None, description=None):
    """Create a Stripe PaymentIntent (for the custom on-site Elements checkout)."""
    secret = get_setting("stripe_secret_key")
    if not secret:
        raise RuntimeError("Stripe not configured")
    currency = get_setting("currency", "usd") or "usd"
    fields = {
        "amount": str(int(amount_cents)),
        "currency": currency,
        "payment_method_types[0]": "card",
    }
    if description:
        fields["description"] = description
    if metadata:
        for k, v in metadata.items():
            fields["metadata[%s]" % k] = str(v)
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(
        "https://api.stripe.com/v1/payment_intents",
        data=data,
        headers={
            "Authorization": "Bearer %s" % secret,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def stripe_retrieve_payment_intent(pi_id):
    """Fetch a PaymentIntent so the server can verify payment status itself."""
    secret = get_setting("stripe_secret_key")
    if not secret:
        raise RuntimeError("Stripe not configured")
    req = urllib.request.Request(
        "https://api.stripe.com/v1/payment_intents/%s" % urllib.parse.quote(pi_id),
        headers={"Authorization": "Bearer %s" % secret},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


# ---------------------------------------------------------------------------
# Shared booking finalization
# ---------------------------------------------------------------------------
def finalize_booking(conn, booking, paid=True):
    """Mark hour booked, set payment status, and send confirmation emails."""
    cust = conn.execute("SELECT * FROM customers WHERE id=?", (booking["customer_id"],)).fetchone()
    conn.execute("UPDATE hours SET status='booked' WHERE date=? AND hour=?",
                 (booking["date"], booking["hour"]))
    conn.execute("UPDATE bookings SET payment_status=? WHERE id=?",
                 ("paid" if paid else "unpaid_request", booking["id"]))
    conn.commit()

    when_date = _pretty_date(booking["date"])
    start_t = hour_label(booking["hour"])
    end_t = hour_label(booking["hour"] + 1)
    amount = money_str(booking["amount_cents"])
    service = booking["service"] or "Session"

    # Notify Jon
    jon_body = (
        "%s booking via website\n\n"
        "Name: %s\nEmail: %s\nPhone: %s\nAddress: %s\n\n"
        "Date: %s\nTime: %s - %s\nService: %s\nAmount: %s\nNotes: %s\n"
        % ("PAID" if paid else "RESERVED (unpaid)",
           cust["name"], cust["email"], cust["phone"] or "", cust["address"] or "",
           when_date, start_t, end_t, service, amount, booking["notes"] or "(none)")
    )
    send_email("%s booking - %s" % ("PAID" if paid else "New", cust["name"]), jon_body,
               reply_to=cust["email"])

    # Confirm to customer using the admin-defined template
    tmpl = get_setting("thankyou_template", DEFAULT_THANKYOU)
    cust_body = render_thankyou(tmpl, {
        "name": cust["name"], "date": when_date, "start_time": start_t,
        "end_time": end_t, "time": "%s - %s" % (start_t, end_t),
        "service": service, "amount": amount,
    })
    send_email("Your session with Rev. Jon M. Corey is confirmed", cust_body,
               to_addr=cust["email"], reply_to=get_setting("notify_email"))


def _pretty_date(iso):
    try:
        d = datetime.strptime(iso, "%Y-%m-%d")
        return d.strftime("%A, %B %-d, %Y")
    except Exception:
        return iso


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------
class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "PAG/2.0"

    # --- utility responders -------------------------------------------------
    def send_json(self, obj, status=200, extra_headers=None):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, message, status=400):
        self.send_json({"ok": False, "error": message}, status=status)

    def read_json_body(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode())
        except Exception:
            return {}

    def redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    # --- static files -------------------------------------------------------
    def serve_static(self, url_path):
        if url_path in ("/", ""):
            rel = "index.html"
        else:
            rel = url_path.lstrip("/")
        candidate = os.path.join(PUBLIC_DIR, rel)
        if not os.path.splitext(candidate)[1] and not os.path.isfile(candidate):
            if os.path.isfile(candidate + ".html"):
                candidate = candidate + ".html"
        candidate = os.path.abspath(candidate)
        if not candidate.startswith(PUBLIC_DIR):
            self.send_error(403)
            return
        if not os.path.isfile(candidate):
            self.send_error(404, "Not found")
            return
        ctype, _ = mimetypes.guess_type(candidate)
        ctype = ctype or "application/octet-stream"
        with open(candidate, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # --- GET ----------------------------------------------------------------
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if path == "/api/config":
            return self.send_json({
                "ok": True,
                "stripe_configured": bool(get_setting("stripe_secret_key")),
                "stripe_publishable_key": get_setting("stripe_publishable_key"),
                "notify_email": get_setting("notify_email"),
                "phone": "480.388.6606",
                "day_start": DAY_START_HOUR, "day_end": DAY_END_HOUR,
            })

        if path == "/api/availability/month":
            return self.api_month(qs)
        if path == "/api/availability/day":
            return self.api_day(qs)
        if path == "/api/availability/quote":
            return self.api_quote(qs)

        if path == "/api/admin/session":
            authed = is_authed(self)
            name = ""
            if authed:
                conn = get_db()
                row = conn.execute("SELECT display_name FROM admin_users WHERE username='admin'").fetchone()
                conn.close()
                name = (row["display_name"] if row and row["display_name"] else "Administrator")
            return self.send_json({"ok": True, "authed": authed, "display_name": name})
        if path == "/api/admin/hours":
            if not is_authed(self):
                return self.send_error_json("unauthorized", 401)
            return self.api_admin_get_hours(qs)
        if path == "/api/admin/bookings":
            if not is_authed(self):
                return self.send_error_json("unauthorized", 401)
            return self.api_admin_bookings(qs)
        if path == "/api/admin/customers":
            if not is_authed(self):
                return self.send_error_json("unauthorized", 401)
            return self.api_admin_customers()
        if path == "/api/admin/client":
            if not is_authed(self):
                return self.send_error_json("unauthorized", 401)
            return self.api_admin_client_detail(qs)
        if path == "/api/admin/invoice":
            if not is_authed(self):
                return self.send_error_json("unauthorized", 401)
            return self.api_admin_invoice(qs)
        if path == "/api/admin/contacts":
            if not is_authed(self):
                return self.send_error_json("unauthorized", 401)
            return self.api_admin_contacts()
        if path == "/api/admin/settings":
            if not is_authed(self):
                return self.send_error_json("unauthorized", 401)
            return self.api_admin_get_settings()

        if path == "/booking/success":
            return self.handle_booking_success(qs)
        if path == "/booking/cancel":
            return self.handle_booking_cancel(qs)

        return self.serve_static(path)

    # --- POST ---------------------------------------------------------------
    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/contact":
            return self.api_contact()
        if path == "/api/bookings":
            return self.api_create_booking()
        if path == "/api/payment/create-intent":
            return self.api_payment_create_intent()
        if path == "/api/payment/confirm":
            return self.api_payment_confirm()

        if path == "/api/admin/login":
            return self.api_admin_login()
        if path == "/api/admin/logout":
            return self.api_admin_logout()

        if path == "/api/admin/hours":
            if not is_authed(self):
                return self.send_error_json("unauthorized", 401)
            return self.api_admin_save_hours()
        if path == "/api/admin/bookings/delete":
            if not is_authed(self):
                return self.send_error_json("unauthorized", 401)
            return self.api_admin_booking_delete()
        if path == "/api/admin/bookings/cancel":
            if not is_authed(self):
                return self.send_error_json("unauthorized", 401)
            return self.api_admin_booking_cancel()
        if path == "/api/admin/bookings/archive":
            if not is_authed(self):
                return self.send_error_json("unauthorized", 401)
            return self.api_admin_booking_archive()
        if path == "/api/admin/bookings/update":
            if not is_authed(self):
                return self.send_error_json("unauthorized", 401)
            return self.api_admin_booking_update()
        if path == "/api/admin/client/notes":
            if not is_authed(self):
                return self.send_error_json("unauthorized", 401)
            return self.api_admin_client_notes()
        if path == "/api/admin/settings":
            if not is_authed(self):
                return self.send_error_json("unauthorized", 401)
            return self.api_admin_save_settings()
        if path == "/api/admin/password":
            if not is_authed(self):
                return self.send_error_json("unauthorized", 401)
            return self.api_admin_change_password()

        return self.send_error_json("not found", 404)

    # =======================================================================
    # Public availability API
    # =======================================================================
    def api_month(self, qs):
        try:
            year = int((qs.get("year") or [""])[0])
            month = int((qs.get("month") or [""])[0])
        except ValueError:
            return self.send_error_json("Invalid year/month.")
        if not (1 <= month <= 12):
            return self.send_error_json("Invalid month.")
        first = "%04d-%02d-01" % (year, month)
        last_day = _calendar.monthrange(year, month)[1]
        last = "%04d-%02d-%02d" % (year, month, last_day)
        conn = get_db()
        rows = conn.execute(
            "SELECT date, COUNT(*) AS c FROM hours "
            "WHERE status='open' AND date >= ? AND date <= ? GROUP BY date",
            (first, last),
        ).fetchall()
        conn.close()
        days = {r["date"]: r["c"] for r in rows}
        return self.send_json({"ok": True, "year": year, "month": month, "days": days,
                               "today": date.today().isoformat()})

    def api_day(self, qs):
        the_date = (qs.get("date") or [""])[0]
        if not DATE_RE.match(the_date):
            return self.send_error_json("Invalid date.")
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM hours WHERE date=? ORDER BY hour", (the_date,)
        ).fetchall()
        conn.close()
        hours = [{
            "hour": r["hour"], "label": hour_label(r["hour"]),
            "end_label": hour_label(r["hour"] + 1),
            "range_label": hour_range_label(r["hour"]),
            "price_cents": r["price_cents"], "price_display": money_str(r["price_cents"]),
            "status": r["status"],
        } for r in rows]
        return self.send_json({"ok": True, "date": the_date, "hours": hours,
                               "day_start": DAY_START_HOUR, "day_end": DAY_END_HOUR})

    def api_quote(self, qs):
        the_date = (qs.get("date") or [""])[0]
        hour_s = (qs.get("hour") or [""])[0]
        if not DATE_RE.match(the_date) or not hour_s.isdigit():
            return self.send_error_json("Invalid selection.")
        hour = int(hour_s)
        conn = get_db()
        row = conn.execute("SELECT * FROM hours WHERE date=? AND hour=?", (the_date, hour)).fetchone()
        conn.close()
        if not row:
            return self.send_error_json("That time is not available.", 404)
        if row["status"] != "open":
            return self.send_error_json("That time has already been booked.", 409)
        return self.send_json({"ok": True, "quote": {
            "date": the_date, "date_pretty": _pretty_date(the_date), "hour": hour,
            "start_label": hour_label(hour), "end_label": hour_label(hour + 1),
            "range_label": hour_range_label(hour),
            "price_cents": row["price_cents"], "price_display": money_str(row["price_cents"]),
        }})

    # =======================================================================
    # Contact
    # =======================================================================
    def api_contact(self):
        d = self.read_json_body()
        name = (d.get("name") or "").strip()
        email = (d.get("email") or "").strip()
        phone = (d.get("phone") or "").strip()
        service = (d.get("service") or "").strip()
        message = (d.get("message") or "").strip()
        if not name:
            return self.send_error_json("Please enter your name.")
        if not valid_email(email):
            return self.send_error_json("Please enter a valid email address.")
        if not phone:
            return self.send_error_json("Please enter a phone number.")
        conn = get_db()
        conn.execute(
            "INSERT INTO contacts(name, email, phone, service, message, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (name, email, phone, service, message, datetime.utcnow().isoformat()),
        )
        conn.commit()
        conn.close()
        body = ("New inquiry via Professional Advisory Group website\n\n"
                "Name: %s\nEmail: %s\nPhone: %s\nService: %s\n\nMessage:\n%s\n"
                % (name, email, phone, service or "(not specified)", message or "(none)"))
        sent, _ = send_email("New inquiry from %s" % name, body, reply_to=email)
        return self.send_json({"ok": True, "notified": sent,
                               "message": "Thank you. Your inquiry has been received."})

    # =======================================================================
    # Booking
    # =======================================================================
    def api_create_booking(self):
        d = self.read_json_body()
        the_date = (d.get("date") or "").strip()
        hour = d.get("hour")
        name = (d.get("name") or "").strip()
        email = (d.get("email") or "").strip()
        phone = (d.get("phone") or "").strip()
        address = (d.get("address") or "").strip()      # line 1
        address2 = (d.get("address2") or "").strip()
        city = (d.get("city") or "").strip()
        state = (d.get("state") or "").strip()
        zip_code = (d.get("zip") or "").strip()
        country = (d.get("country") or "").strip() or "US"
        service = (d.get("service") or "").strip()
        notes = (d.get("notes") or "").strip()
        payment_method = (d.get("payment_method") or "card").strip()
        if payment_method not in ("card", "in_person"):
            payment_method = "card"

        if not DATE_RE.match(the_date):
            return self.send_error_json("Please choose a valid date.")
        if not (isinstance(hour, int) or (isinstance(hour, str) and str(hour).isdigit())):
            return self.send_error_json("Please choose a time.")
        hour = int(hour)
        if not name:
            return self.send_error_json("Please enter your name.")
        if not valid_email(email):
            return self.send_error_json("Please enter a valid email address.")
        if not phone:
            return self.send_error_json("Please enter a phone number.")

        conn = get_db()
        slot = conn.execute("SELECT * FROM hours WHERE date=? AND hour=?", (the_date, hour)).fetchone()
        if not slot:
            conn.close()
            return self.send_error_json("That time is not available.", 404)
        if slot["status"] != "open":
            conn.close()
            return self.send_error_json("Sorry, that time has just been booked.", 409)

        # Upsert client record by email (structured billing address)
        conn.execute(
            "INSERT INTO customers(name, address, address2, city, state, zip, country, phone, email, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(email) DO UPDATE SET name=excluded.name, address=excluded.address, "
            "address2=excluded.address2, city=excluded.city, state=excluded.state, "
            "zip=excluded.zip, country=excluded.country, phone=excluded.phone",
            (name, address, address2, city, state, zip_code, country, phone, email,
             datetime.utcnow().isoformat()),
        )
        cust = conn.execute("SELECT id FROM customers WHERE email=?", (email,)).fetchone()
        customer_id = cust["id"]

        amount = slot["price_cents"]
        cur = conn.execute(
            "INSERT INTO bookings(customer_id, date, hour, service, notes, amount_cents, "
            "payment_status, payment_method, created_at) VALUES (?,?,?,?,?,?, 'pending', ?, ?)",
            (customer_id, the_date, hour, service, notes, amount, payment_method,
             datetime.utcnow().isoformat()),
        )
        booking_id = cur.lastrowid
        conn.commit()

        # Card path: send the customer to our custom on-site payment page (Stripe Elements).
        if payment_method == "card" and get_setting("stripe_secret_key") and amount > 0:
            conn.close()
            return self.send_json({"ok": True, "booking_id": booking_id,
                                   "payment_url": "/payment?booking_id=%d" % booking_id})

        # Check/cash in person, complimentary, or Stripe not yet enabled: reserve now.
        booking = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
        finalize_booking(conn, booking, paid=(amount == 0))
        conn.close()
        if payment_method == "in_person":
            msg = "Your session is reserved. Payment by check or cash will be collected in person."
        else:
            msg = "Your session is reserved. Rev. Corey's office will contact you about payment."
        return self.send_json({
            "ok": True, "booking_id": booking_id, "payment_url": None, "message": msg,
        })

    def handle_booking_success(self, qs):
        booking_id = (qs.get("booking_id") or [""])[0]
        if booking_id.isdigit():
            conn = get_db()
            b = conn.execute("SELECT * FROM bookings WHERE id=?", (int(booking_id),)).fetchone()
            if b and b["payment_status"] != "paid":
                finalize_booking(conn, b, paid=True)
            conn.close()
        self.redirect("/thank-you.html?status=paid")

    def handle_booking_cancel(self, qs):
        self.redirect("/thank-you.html?status=cancelled")

    # =======================================================================
    # Custom on-site payment (Stripe Elements)
    # =======================================================================
    def _booking_summary(self, conn, b):
        cust = conn.execute("SELECT * FROM customers WHERE id=?", (b["customer_id"],)).fetchone()
        return {
            "booking_id": b["id"],
            "date_pretty": _pretty_date(b["date"]),
            "range_label": hour_range_label(b["hour"]),
            "amount_cents": b["amount_cents"],
            "amount_display": money_str(b["amount_cents"]),
            "service": b["service"] or "",
            "name": cust["name"] if cust else "",
            "email": cust["email"] if cust else "",
            "phone": cust["phone"] if cust else "",
            "address": (cust["address"] if cust else "") or "",
            "address2": (cust["address2"] if cust else "") or "",
            "city": (cust["city"] if cust else "") or "",
            "state": (cust["state"] if cust else "") or "",
            "zip": (cust["zip"] if cust else "") or "",
            "country": (cust["country"] if cust else "") or "US",
        }

    def api_payment_create_intent(self):
        d = self.read_json_body()
        bid = d.get("booking_id")
        if not (isinstance(bid, int) or (isinstance(bid, str) and str(bid).isdigit())):
            return self.send_error_json("Invalid booking.")
        bid = int(bid)
        conn = get_db()
        b = conn.execute("SELECT * FROM bookings WHERE id=?", (bid,)).fetchone()
        if not b:
            conn.close()
            return self.send_error_json("Booking not found.", 404)
        summary = self._booking_summary(conn, b)
        if not get_setting("stripe_secret_key"):
            # Return the summary so the payment page can still render a preview.
            conn.close()
            return self.send_json({"ok": False, "error": "Online payment is not enabled.",
                                   "summary": summary})
        if b["payment_status"] == "paid":
            conn.close()
            return self.send_json({"ok": True, "already_paid": True, "summary": summary})
        if b["amount_cents"] <= 0:
            conn.close()
            return self.send_error_json("No payment is required for this booking.")

        desc = "Session with Rev. Jon M. Corey - %s, %s" % (summary["date_pretty"], summary["range_label"])
        try:
            pi_id = b["stripe_session_id"]
            if pi_id and str(pi_id).startswith("pi_"):
                pi = stripe_retrieve_payment_intent(pi_id)
                if pi.get("status") == "succeeded":
                    if b["payment_status"] != "paid":
                        finalize_booking(conn, b, paid=True)
                    conn.close()
                    return self.send_json({"ok": True, "already_paid": True, "summary": summary})
            else:
                pi = stripe_create_payment_intent(
                    b["amount_cents"], metadata={"booking_id": bid, "date": b["date"], "hour": b["hour"]},
                    description=desc)
                conn.execute("UPDATE bookings SET stripe_session_id=? WHERE id=?", (pi["id"], bid))
                conn.commit()
        except Exception as e:  # noqa
            conn.close()
            return self.send_error_json("Could not initialize payment: %s" % e, 502)
        conn.close()
        return self.send_json({
            "ok": True,
            "client_secret": pi["client_secret"],
            "publishable_key": get_setting("stripe_publishable_key"),
            "summary": summary,
        })

    def api_payment_confirm(self):
        d = self.read_json_body()
        bid = d.get("booking_id")
        if not (isinstance(bid, int) or (isinstance(bid, str) and str(bid).isdigit())):
            return self.send_error_json("Invalid booking.")
        bid = int(bid)
        conn = get_db()
        b = conn.execute("SELECT * FROM bookings WHERE id=?", (bid,)).fetchone()
        if not b:
            conn.close()
            return self.send_error_json("Booking not found.", 404)
        if b["payment_status"] == "paid":
            conn.close()
            return self.send_json({"ok": True, "status": "paid"})
        pi_id = b["stripe_session_id"]
        if not pi_id:
            conn.close()
            return self.send_error_json("No payment found for this booking.")
        # The server verifies payment status with Stripe directly — never trusts the client.
        try:
            pi = stripe_retrieve_payment_intent(pi_id)
        except Exception as e:  # noqa
            conn.close()
            return self.send_error_json("Could not verify payment: %s" % e, 502)
        if pi.get("status") == "succeeded":
            finalize_booking(conn, b, paid=True)
            conn.close()
            return self.send_json({"ok": True, "status": "paid"})
        conn.close()
        return self.send_error_json("Payment has not been completed.", 402)

    # =======================================================================
    # Admin
    # =======================================================================
    def api_admin_login(self):
        d = self.read_json_body()
        if verify_password(d.get("password") or ""):
            token = make_session()
            ck = cookies.SimpleCookie()
            ck["admin_token"] = token
            ck["admin_token"]["path"] = "/"
            ck["admin_token"]["httponly"] = True
            ck["admin_token"]["samesite"] = "Lax"
            self.send_json({"ok": True}, extra_headers={"Set-Cookie": ck["admin_token"].OutputString()})
        else:
            self.send_error_json("Incorrect password.", 401)

    def api_admin_logout(self):
        cookie_header = self.headers.get("Cookie", "")
        if cookie_header:
            ck = cookies.SimpleCookie()
            ck.load(cookie_header)
            if "admin_token" in ck:
                SESSIONS.pop(ck["admin_token"].value, None)
        self.send_json({"ok": True}, extra_headers={"Set-Cookie": "admin_token=; Path=/; Max-Age=0"})

    def api_admin_change_password(self):
        d = self.read_json_body()
        new_pw = d.get("new_password") or ""
        if len(new_pw) < 6:
            return self.send_error_json("Password must be at least 6 characters.")
        salt = secrets.token_hex(16)
        conn = get_db()
        conn.execute("UPDATE admin_users SET password_hash=?, salt=? WHERE username='admin'",
                     (hash_password(new_pw, salt), salt))
        conn.commit()
        conn.close()
        return self.send_json({"ok": True, "message": "Password updated."})

    def api_admin_get_hours(self, qs):
        the_date = (qs.get("date") or [""])[0]
        if not DATE_RE.match(the_date):
            return self.send_error_json("Invalid date.")
        conn = get_db()
        rows = conn.execute("SELECT * FROM hours WHERE date=? ORDER BY hour", (the_date,)).fetchall()
        conn.close()
        state = {}
        for r in rows:
            state[r["hour"]] = {"status": r["status"], "price_cents": r["price_cents"]}
        return self.send_json({"ok": True, "date": the_date, "state": state,
                               "day_start": DAY_START_HOUR, "day_end": DAY_END_HOUR})

    def _apply_day_hours(self, conn, the_date, hours, price_cents, now):
        """Set the open hours for a single date: add selected, remove unselected
        open hours, leave booked hours untouched. `hours` is a set of ints."""
        existing = conn.execute("SELECT * FROM hours WHERE date=?", (the_date,)).fetchall()
        existing_map = {r["hour"]: r for r in existing}
        for r in existing:
            if r["status"] == "open" and r["hour"] not in hours:
                conn.execute("DELETE FROM hours WHERE id=?", (r["id"],))
        for h in hours:
            r = existing_map.get(h)
            if r is None:
                conn.execute(
                    "INSERT INTO hours(date, hour, price_cents, status, created_at) "
                    "VALUES (?,?,?, 'open', ?)", (the_date, h, price_cents, now))
            elif r["status"] == "open":
                conn.execute("UPDATE hours SET price_cents=? WHERE id=?", (price_cents, r["id"]))

    def api_admin_save_hours(self):
        d = self.read_json_body()
        the_date = (d.get("date") or "").strip()
        end_date = (d.get("end_date") or "").strip()
        weekdays = d.get("weekdays")  # optional list of ints, JS convention (Sun=0..Sat=6)
        hours = d.get("hours") or []
        try:
            price_cents = int(round(float(d.get("price") or 0) * 100))
        except ValueError:
            return self.send_error_json("Invalid price.")
        if not DATE_RE.match(the_date):
            return self.send_error_json("Invalid start date.")
        try:
            hours = sorted({int(h) for h in hours if DAY_START_HOUR <= int(h) < DAY_END_HOUR})
        except (ValueError, TypeError):
            return self.send_error_json("Invalid hours.")

        try:
            start = datetime.strptime(the_date, "%Y-%m-%d").date()
        except ValueError:
            return self.send_error_json("Invalid start date.")
        if end_date and DATE_RE.match(end_date):
            try:
                end = datetime.strptime(end_date, "%Y-%m-%d").date()
            except ValueError:
                return self.send_error_json("Invalid end date.")
        else:
            end = start
        if end < start:
            return self.send_error_json("End date must be on or after the start date.")
        if (end - start).days > 366:
            return self.send_error_json("Please choose a range of one year or less.")

        wd_filter = None
        if isinstance(weekdays, list) and len(weekdays) > 0:
            try:
                wd_filter = {int(w) % 7 for w in weekdays}
            except (ValueError, TypeError):
                return self.send_error_json("Invalid weekday selection.")

        conn = get_db()
        now = datetime.utcnow().isoformat()
        applied = 0
        cur = start
        while cur <= end:
            js_wd = (cur.weekday() + 1) % 7   # Python Mon=0..Sun=6 -> JS Sun=0..Sat=6
            if wd_filter is None or js_wd in wd_filter:
                self._apply_day_hours(conn, cur.isoformat(), hours, price_cents, now)
                applied += 1
            cur += timedelta(days=1)
        conn.commit()
        conn.close()
        if applied == 0:
            return self.send_json({"ok": True,
                "message": "No days matched the selected weekdays in that range."})
        if applied == 1:
            return self.send_json({"ok": True, "message": "Availability saved for %s." % start.isoformat()})
        return self.send_json({"ok": True, "message": "Availability saved for %d days." % applied})

    def api_admin_bookings(self, qs=None):
        include_archived = bool(qs and (qs.get("include_archived") or [""])[0] in ("1", "true"))
        where = "" if include_archived else "WHERE b.archived = 0"
        conn = get_db()
        rows = conn.execute(
            "SELECT b.*, c.name AS c_name, c.email AS c_email, c.phone AS c_phone, "
            "c.address AS c_address FROM bookings b "
            "LEFT JOIN customers c ON b.customer_id = c.id " + where + " "
            "ORDER BY b.archived ASC, b.date DESC, b.hour DESC, b.created_at DESC"
        ).fetchall()
        conn.close()
        out = [{
            "id": r["id"], "name": r["c_name"], "email": r["c_email"], "phone": r["c_phone"],
            "address": r["c_address"], "service": r["service"], "notes": r["notes"],
            "amount_cents": r["amount_cents"], "amount_display": money_str(r["amount_cents"]),
            "payment_status": r["payment_status"],
            "status": r["status"], "archived": bool(r["archived"]),
            "paid": r["payment_status"] == "paid",
            "when": "%s, %s" % (_pretty_date(r["date"]), hour_range_label(r["hour"])),
            "created_at": r["created_at"],
        } for r in rows]
        return self.send_json({"ok": True, "bookings": out})

    def _get_booking_or_error(self, conn, bid_raw):
        """Return (booking_row, None) or (None, error_response_sent)."""
        if not (isinstance(bid_raw, int) or (isinstance(bid_raw, str) and str(bid_raw).isdigit())):
            self.send_error_json("Invalid booking id.")
            return None, True
        b = conn.execute("SELECT * FROM bookings WHERE id=?", (int(bid_raw),)).fetchone()
        if not b:
            self.send_error_json("Booking not found.", 404)
            return None, True
        return b, False

    def _free_slot(self, conn, the_date, hour):
        conn.execute("UPDATE hours SET status='open' WHERE date=? AND hour=?", (the_date, hour))

    def api_admin_booking_delete(self):
        d = self.read_json_body()
        conn = get_db()
        b, err = self._get_booking_or_error(conn, d.get("id"))
        if err:
            conn.close(); return
        if b["payment_status"] == "paid":
            conn.close()
            return self.send_error_json("Paid bookings can't be deleted. Archive it instead.", 409)
        self._free_slot(conn, b["date"], b["hour"])
        conn.execute("DELETE FROM bookings WHERE id=?", (b["id"],))
        conn.commit()
        conn.close()
        return self.send_json({"ok": True, "message": "Booking deleted and the time slot reopened."})

    def api_admin_booking_cancel(self):
        d = self.read_json_body()
        conn = get_db()
        b, err = self._get_booking_or_error(conn, d.get("id"))
        if err:
            conn.close(); return
        if b["payment_status"] == "paid":
            conn.close()
            return self.send_error_json("Paid bookings can't be cancelled here (that would need a refund). Archive it instead.", 409)
        self._free_slot(conn, b["date"], b["hour"])
        conn.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (b["id"],))
        conn.commit()
        conn.close()
        return self.send_json({"ok": True, "message": "Booking cancelled and the time slot reopened."})

    def api_admin_booking_archive(self):
        d = self.read_json_body()
        archived = 0 if d.get("archived") in (False, 0, "0", "false") else 1
        conn = get_db()
        b, err = self._get_booking_or_error(conn, d.get("id"))
        if err:
            conn.close(); return
        conn.execute("UPDATE bookings SET archived=? WHERE id=?", (archived, b["id"]))
        conn.commit()
        conn.close()
        return self.send_json({"ok": True,
            "message": "Booking archived." if archived else "Booking restored to the active list."})

    def api_admin_booking_update(self):
        d = self.read_json_body()
        conn = get_db()
        b, err = self._get_booking_or_error(conn, d.get("id"))
        if err:
            conn.close(); return
        name = (d.get("name") or "").strip()
        email = (d.get("email") or "").strip()
        phone = (d.get("phone") or "").strip()
        service = (d.get("service") or "").strip()
        notes = (d.get("notes") or "").strip()
        payment_status = (d.get("payment_status") or b["payment_status"]).strip()
        if payment_status not in ("pending", "paid", "unpaid_request"):
            conn.close()
            return self.send_error_json("Invalid payment status.")
        if not name:
            conn.close()
            return self.send_error_json("Name is required.")
        if not valid_email(email):
            conn.close()
            return self.send_error_json("A valid email is required.")
        try:
            amount_cents = int(round(float(d.get("amount") if d.get("amount") not in (None, "") else b["amount_cents"] / 100.0) * 100))
        except (ValueError, TypeError):
            conn.close()
            return self.send_error_json("Invalid amount.")
        # Update the linked customer record (or create one if somehow missing)
        if b["customer_id"]:
            conn.execute("UPDATE customers SET name=?, email=?, phone=? WHERE id=?",
                         (name, email, phone, b["customer_id"]))
        conn.execute("UPDATE bookings SET service=?, notes=?, amount_cents=?, payment_status=? WHERE id=?",
                     (service, notes, amount_cents, payment_status, b["id"]))
        conn.commit()
        conn.close()
        return self.send_json({"ok": True, "message": "Booking updated."})

    def _full_address(self, r):
        parts = []
        line1 = (r["address"] or "").strip()
        line2 = (r["address2"] or "").strip() if "address2" in r.keys() else ""
        if line1:
            parts.append(line1)
        if line2:
            parts.append(line2)
        city = (r["city"] or "").strip() if "city" in r.keys() else ""
        state = (r["state"] or "").strip() if "state" in r.keys() else ""
        zip_c = (r["zip"] or "").strip() if "zip" in r.keys() else ""
        csz = " ".join([p for p in [", ".join([p for p in [city, state] if p]), zip_c] if p]).strip()
        if csz:
            parts.append(csz)
        return "\n".join(parts)

    def api_admin_customers(self):
        conn = get_db()
        rows = conn.execute(
            "SELECT c.*, COUNT(b.id) AS bookings FROM customers c "
            "LEFT JOIN bookings b ON b.customer_id = c.id GROUP BY c.id "
            "ORDER BY c.created_at DESC"
        ).fetchall()
        conn.close()
        out = [{
            "id": r["id"], "name": r["name"], "address": self._full_address(r), "phone": r["phone"],
            "email": r["email"], "bookings": r["bookings"], "created_at": r["created_at"],
            "has_notes": bool((r["corey_notes"] or "").strip() if "corey_notes" in r.keys() else False),
        } for r in rows]
        return self.send_json({"ok": True, "customers": out})

    def api_admin_client_detail(self, qs):
        cid = (qs.get("id") or [""])[0]
        if not cid.isdigit():
            return self.send_error_json("Invalid client id.")
        conn = get_db()
        c = conn.execute("SELECT * FROM customers WHERE id=?", (int(cid),)).fetchone()
        if not c:
            conn.close()
            return self.send_error_json("Client not found.", 404)
        rows = conn.execute(
            "SELECT * FROM bookings WHERE customer_id=? ORDER BY date DESC, hour DESC", (int(cid),)
        ).fetchall()
        conn.close()
        bookings = [{
            "id": b["id"],
            "when": "%s, %s" % (_pretty_date(b["date"]), hour_range_label(b["hour"])),
            "service": b["service"] or "", "amount_display": money_str(b["amount_cents"]),
            "payment_status": b["payment_status"], "payment_method": b["payment_method"],
            "status": b["status"], "archived": bool(b["archived"]),
            "client_notes": b["notes"] or "",
        } for b in rows]
        # Aggregate the client's own notes to Rev. Corey (from their bookings)
        client_notes = [{"when": bk["when"], "text": bk["client_notes"]} for bk in bookings if bk["client_notes"]]
        client = {
            "id": c["id"], "name": c["name"], "email": c["email"], "phone": c["phone"],
            "address": self._full_address(c),
            "address_line1": c["address"] or "", "address2": c["address2"] or "",
            "city": c["city"] or "", "state": c["state"] or "", "zip": c["zip"] or "",
            "country": c["country"] or "", "corey_notes": c["corey_notes"] or "",
            "created_at": c["created_at"],
        }
        return self.send_json({"ok": True, "client": client, "bookings": bookings,
                               "client_notes": client_notes})

    def _ensure_invoice_number(self, conn, b):
        """Assign (and persist) an invoice number for a booking if it lacks one."""
        if b["invoice_number"]:
            return b["invoice_number"]
        row = conn.execute("SELECT value FROM settings WHERE key='next_invoice_number'").fetchone()
        try:
            num = int(row["value"]) if row and row["value"] else 1005
        except (TypeError, ValueError):
            num = 1005
        now = datetime.utcnow().isoformat()
        conn.execute("UPDATE bookings SET invoice_number=?, invoice_created_at=? WHERE id=?",
                     (num, now, b["id"]))
        conn.execute("INSERT INTO settings(key, value) VALUES('next_invoice_number', ?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(num + 1),))
        conn.commit()
        return num

    def api_admin_invoice(self, qs):
        bid = (qs.get("booking_id") or [""])[0]
        if not bid.isdigit():
            return self.send_error_json("Invalid booking id.")
        conn = get_db()
        b = conn.execute("SELECT * FROM bookings WHERE id=?", (int(bid),)).fetchone()
        if not b:
            conn.close()
            return self.send_error_json("Booking not found.", 404)
        number = self._ensure_invoice_number(conn, b)
        b = conn.execute("SELECT * FROM bookings WHERE id=?", (int(bid),)).fetchone()
        cust = conn.execute("SELECT * FROM customers WHERE id=?", (b["customer_id"],)).fetchone()
        conn.close()

        paid = b["payment_status"] == "paid"
        amount = b["amount_cents"]
        inv_date = b["invoice_created_at"] or datetime.utcnow().isoformat()
        try:
            inv_date_pretty = datetime.strptime(inv_date[:10], "%Y-%m-%d").strftime("%B %-d, %Y")
        except Exception:
            inv_date_pretty = inv_date[:10]
        method = {"card": "Credit/Debit Card", "in_person": "Check or Cash (in person)"}.get(
            b["payment_method"], "")

        invoice = {
            "number": number,
            "date": inv_date_pretty,
            "business": {
                "name": "Professional Advisory Group",
                "person": "Rev. Jon M. Corey, PhD",
                "phone": "480.388.6606",
                "email": get_setting("notify_email", "jonmichaelcorey@gmail.com"),
            },
            "client": {
                "name": cust["name"] if cust else "",
                "email": cust["email"] if cust else "",
                "phone": cust["phone"] if cust else "",
                "address": self._full_address(cust) if cust else "",
            },
            "session_when": "%s, %s" % (_pretty_date(b["date"]), hour_range_label(b["hour"])),
            "service": b["service"] or "Pastoral Session (1 hour)",
            "amount_display": money_str(amount),
            "subtotal_display": money_str(amount),
            "total_display": money_str(amount),
            "paid": paid,
            "payment_method": method,
            "payment_status": b["payment_status"],
            "amount_paid_display": money_str(amount if paid else 0),
            "balance_display": money_str(0 if paid else amount),
        }
        return self.send_json({"ok": True, "invoice": invoice})

    def api_admin_client_notes(self):
        d = self.read_json_body()
        cid = d.get("id")
        if not (isinstance(cid, int) or (isinstance(cid, str) and str(cid).isdigit())):
            return self.send_error_json("Invalid client id.")
        notes = d.get("corey_notes") or ""
        conn = get_db()
        c = conn.execute("SELECT id FROM customers WHERE id=?", (int(cid),)).fetchone()
        if not c:
            conn.close()
            return self.send_error_json("Client not found.", 404)
        conn.execute("UPDATE customers SET corey_notes=? WHERE id=?", (notes, int(cid)))
        conn.commit()
        conn.close()
        return self.send_json({"ok": True, "message": "Client notes saved."})

    def api_admin_contacts(self):
        conn = get_db()
        rows = conn.execute("SELECT * FROM contacts ORDER BY created_at DESC").fetchall()
        conn.close()
        out = [{
            "id": r["id"], "name": r["name"], "email": r["email"], "phone": r["phone"],
            "service": r["service"], "message": r["message"], "created_at": r["created_at"],
        } for r in rows]
        return self.send_json({"ok": True, "contacts": out})

    def api_admin_get_settings(self):
        keys = ["notify_email", "smtp_host", "smtp_port", "smtp_user", "smtp_from",
                "stripe_publishable_key", "currency", "site_base_url", "thankyou_template"]
        data = {k: get_setting(k) for k in keys}
        data["smtp_pass_set"] = bool(get_setting("smtp_pass"))
        data["stripe_secret_set"] = bool(get_setting("stripe_secret_key"))
        return self.send_json({"ok": True, "settings": data})

    def api_admin_save_settings(self):
        d = self.read_json_body()
        allowed = ["notify_email", "smtp_host", "smtp_port", "smtp_user", "smtp_from",
                   "stripe_publishable_key", "currency", "site_base_url", "thankyou_template"]
        for k in allowed:
            if k in d:
                set_setting(k, (d.get(k) or "").strip() if k != "thankyou_template" else (d.get(k) or ""))
        if d.get("smtp_pass"):
            set_setting("smtp_pass", d["smtp_pass"])
        if d.get("stripe_secret_key"):
            set_setting("stripe_secret_key", d["stripe_secret_key"].strip())
        return self.send_json({"ok": True, "message": "Settings saved."})

    def log_message(self, fmt, *args):
        pass


def main():
    init_db()
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer((HOST, PORT), Handler) as httpd:
        print("Professional Advisory Group site running at http://localhost:%d" % PORT)
        print("  Home:    http://localhost:%d/" % PORT)
        print("  Admin:   http://localhost:%d/admin  (default password: changeme)" % PORT)
        print("Press Ctrl+C to stop.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down.")


if __name__ == "__main__":
    main()
