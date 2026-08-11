# Professional Advisory Group — Website

A complete website and booking system for **Rev. Jon M. Corey, PhD** and the
Professional Advisory Group.

Built with **pure Python 3** (standard library only — no packages to install) and
**SQLite**. Runs on any Mac/Linux/Windows machine that already has Python 3.

---

## Pages

| Page | URL | Purpose |
|------|-----|---------|
| **Home** | `/` | Front-facing landing page — bio, services, calls to action |
| **Schedule a Session** | `/calendar` | Monthly calendar; pick an available day, then an open one-hour time |
| **Checkout** | `/checkout?date=…&hour=…` | Linked from the calendar — collects details and confirms the booking |
| **Secure Payment** | `/payment?booking_id=…` | Custom on-site card checkout (Stripe Elements) |
| **Contact Us** | `/contact` | Inquiry form (name, phone, email, service, message) |
| **Thank You** | `/thank-you` | Shown after a successful booking or payment |
| **Admin** | `/admin` | Back-end for Jon: availability, bookings, customers, inquiries, settings |

---

## Running the site

From this `website/` folder:

```bash
python3 server.py
```

Then open **http://localhost:8000**. Use a different port with `PORT=9000 python3 server.py`.

Data is stored in a local file `pag.db` (created automatically on first run).
Deleting `pag.db` resets everything to a clean state.

---

## How booking works

1. Jon sets availability in **Admin → Availability**: pick a date, click the hours to
   make bookable (7 AM–9 PM window), set a price per session, Save.
2. A visitor opens **Schedule a Session**. The **monthly calendar** highlights days that
   have openings; days with none are greyed out, as are past days.
3. Clicking an available day reveals that day's **hourly grid**. Open hours are selectable;
   booked and unavailable hours are greyed out.
4. The visitor picks a **one-hour** session and clicks **Continue to Checkout**.
5. On checkout they enter their details (name, phone, email, mailing address, service, notes).
   Clicking **Review Booking** shows a confirmation dialog with **Go Back** / **Yes, Confirm & Continue**.
6. On confirm:
   - **Stripe configured** → the customer goes to the site's own **Secure Payment** page
     (`/payment`) — a custom on-site checkout built with **Stripe Elements**. They enter name,
     billing address (Address 1/2, City, State, ZIP), and card number / expiry / CVC. The card
     fields are hosted by Stripe, so **raw card data never touches Jon's server**. On success
     the server verifies the payment with Stripe, marks the hour booked, and sends **confirmation
     emails to both Jon and the customer**, then shows the **Thank You** page.
   - **Stripe not configured** → the session is reserved, the hour is marked booked, and the
     same confirmation emails are sent (so it works before Stripe is set up). The payment page
     shows a preview of the checkout layout with card entry disabled.
7. Booked hours disappear from the public calendar automatically.

> **Card security / PCI:** card number, expiry, and CVC are entered into Stripe-hosted fields
> (Stripe Elements) and tokenized in the browser — they are sent directly to Stripe and are
> never received or stored by this application. The server only ever sees a Stripe token and
> verifies payment status via the Stripe API.

> **Sessions are fixed one-hour bookings.** Additional time (half-hour increments after the
> first hour) is intended for a separate billing interface to be added later.

---

## Admin back-end

Click the **🔒 Login** button in the site header (top right, on every page), or go directly to
**http://localhost:8000/admin**. Once signed in, that button shows **🔓 Admin**.

- **Admin user:** stored in the database (`admin_users` table), username **`admin`**.
- **Default password:** `changeme` (printed to the terminal on first launch). Change it under
  **Settings → Change Admin Password** right away.
- **Availability** — the hour-grid editor described above. Select All / Clear All included.
  Booked hours are locked and can't be removed here.
- **Bookings** — every booking with the customer's contact info, service, amount, and payment status.
- **Customers** — the customer database (name, email, phone, mailing address, number of bookings).
- **Inquiries** — every message from the Contact page.
- **Settings** — email, Stripe, the thank-you email template, and the admin password.

---

## Connecting email (notifications + customer confirmations)

Under **Admin → Settings → Email & Notifications**, enter an SMTP account. Then:
- **Jon** is emailed on every new booking and inquiry (to the "Notify email" address).
- The **customer** receives the thank-you confirmation email after booking.

**Gmail example** (use an App Password, not the account password):
- SMTP Host: `smtp.gmail.com` · Port: `587`
- Username / From: `jonmichaelcorey@gmail.com`
- Password: a Gmail **App Password** (create at https://myaccount.google.com/apppasswords
  with 2-Step Verification enabled)

All bookings, customers, and inquiries are stored in the database and visible in the admin
dashboard even if email is not configured.

### Thank-you email template

Under **Admin → Settings → Thank-You Email Template**, edit the message customers receive.
Available variables (substituted automatically):
`{name}`, `{date}`, `{start_time}`, `{end_time}`, `{service}`, `{amount}`.

---

## Connecting Stripe (accepting payments)

Under **Admin → Settings → Stripe Payments**, paste the keys from
Stripe Dashboard → **Developers → API keys**:
- **Publishable Key** (`pk_live_…` / `pk_test_…`)
- **Secret Key** (`sk_live_…` / `sk_test_…`)
- **Site Base URL** — the site's public address (e.g. `https://professionaladvisorygroup.com`)
  so Stripe can send customers back after payment.

Once keys are saved, the **Secure Payment** page renders live Stripe card fields and can take
payment. Without keys, that page shows a disabled preview of the checkout layout.

> **Testing tip:** Use Stripe **test** keys and card `4242 4242 4242 4242` (any future
> expiry, any CVC, any ZIP) to run the full on-site payment flow without real charges.

---

## Database tables

- **hours** — bookable one-hour slots: `date`, `hour`, `price_cents`, `status` (open/booked)
- **customers** — `name`, `address`, `phone`, `email` (unique) — the customer database
- **bookings** — links a customer to a date/hour, with service, amount, and payment status
- **contacts** — Contact-page inquiries
- **settings** — email, Stripe, thank-you template, admin credentials

---

## Notes & next steps

- **Security:** change the admin password from the default before going live, and serve the
  site over **HTTPS** in production (the admin uses a session cookie).
- **Deployment:** runs as a single process — fine for a small practice. For a public domain,
  host on a small VM or a service like Render/Railway/Fly, put it behind HTTPS, and set the
  **Site Base URL** in Settings.
- **Timezone:** times are stored/displayed as entered (no timezone conversion yet).
- **Planned:** the separate half-hour add-on billing interface; Stripe webhooks for
  bulletproof payment reconciliation; customer self-service reschedule/cancel;
  recurring weekly availability; calendar sync (Google Calendar).

---

## File layout

```
website/
├── server.py             # Backend: routes, DB, admin, Stripe, email
├── pag.db                # SQLite database (auto-created; delete to reset)
├── README.md             # This file
└── public/
    ├── index.html            # Home / landing page
    ├── calendar.html         # Schedule a Session (monthly calendar)
    ├── checkout.html         # Checkout details + confirmation modal
    ├── payment.html          # Secure on-site card payment (Stripe Elements)
    ├── contact.html          # Contact Us
    ├── thank-you.html        # Thank You page
    ├── admin.html            # Admin back-end
    ├── css/styles.css
    ├── js/layout.js          # Shared header/footer
    ├── js/calendar.js        # Monthly calendar + hour picker
    ├── js/admin.js           # Admin dashboard logic
    └── img/corey.jpg         # Rev. Corey's portrait
```
