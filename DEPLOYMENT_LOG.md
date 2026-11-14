# DEPLOYMENT LOG — jonmcorey.com (Professional Advisory Group site)

Plain-text record of every time this site was deployed, restored, or published,
and *by what* (Hermes / Claude / Copilot / manual). Source of truth for
"who touched the live site and when."

---

## How deployment works (tl;dr)

- **Production host:** srv002 (`100.92.154.76`), path `/opt/pag/website`, run by
  `pag.service` (systemd, plain `/usr/bin/python3 server.py`), behind Apache/nginx.
- **Database:** `/opt/pag/data/pag.db` — lives OUTSIDE the code dir; never
  overwritten by a code deploy.
- **`/opt/pag/website` is a plain file copy, NOT a git checkout.** It is updated
  by rsync (see `deploy/publish.sh`), then `systemctl restart pag`.
- **Git** (`github.com/npeiman/jonmcorey-site`) is the development/shared repo;
  it and the live tree only match when a deploy actually runs.
- **Admin login:** username `admin`. Password stored as PBKDF2-HMAC-SHA256
  (120 000 iterations) + per-user salt in `admin_users`/`settings` in `pag.db`.

---

## Timeline

| Date (UTC) | Actor | Action | Result |
|------------|-------|--------|--------|
| 2026-08-06 | manual / initial | Coolify WordPress for jonmcorey.com created on srv001 | used only as a skeleton; later renamed to `dev.moch10plantarfasciitis.com` |
| 2026-08-09 | manual | PAG site first deployed to srv002 `/opt/pag/website` via rsync + `pag.service` | first live Python version |
| 2026-08-11 | — | git `d947f4d` "initial deployable version" | dev repo baseline on GitHub |
| 2026-10-18 | manual | site removed into dated backup `/root/jonmcorey-removal-20261018T16…` | pre-outage snapshot taken |
| **2026-10-31 15:17** | **Hermes** | **restore from the 10-18 backup** to `/opt/pag/website` (per user "let's restore from the backup") | **jonmcorey.com up, HTTP 200**, title "Professional Advisory Group — Rev. Jon M. Corey, PhD" |
| 2026-10-31 15:20 | user | verified live in browser | looks fine |
| 2026-11-02 | Hermes | git `b6359db` (admin client/invoice mgmt, booking actions, client notes, email) committed + pushed | GitHub only — **not yet deployed to srv002** |
| 2026-11-07/10 | Claude/Hermes | content edits (`4bb53be`, `8a0763a`) + `8c91b2c`/merge add `deploy/publish.sh` + `.gitignore server.log` | GitHub only |

---

## Live site status (verified 2026-11-14)

**The live site matches current git**, confirmed two ways:

- **Over HTTPS:** SHA-256 of live-served files (`about.html`, `invoice.html`,
  `index.html`, `admin.js`, `checkout.html`, `calendar.html`, `contact.html`,
  `styles.css`, `layout.js`, `payment.html`) all MATCH the repo at `HEAD`.
- **Direct SSH file-level diff (srv002):** recursive tree + content-hash comparison
  of `/opt/pag/website` against the repo — **25/26 committed site files byte-identical**.
  Two paths differ, both **expected** (they're local/uncommitted edits, not deployed):
  - `.gitignore` — local adds `server.log`; live still lacks it.
  - `README.md` — local has the new "Deployment history" section; live is the
    committed version.
  Paths in git but not on the site: `DEPLOYMENT_LOG.md` (this doc) and
  `deploy/publish.sh` (deploy script). Against the **remotely-pushed/committed**
  tree the site is current; these two deltas are pre-commit housekeeping.

The Oct 31 restore used the Aug-9-era backup, but the site was **redeployed since**
(up to or including `b6359db` and the Nov-07 content edits), so the live tree is
current with git. An earlier note of mine ("live is behind git") proved inaccurate
by hash comparison and was corrected in place.

> Note: `DEPLOYMENT_LOG.md` lives in git but is **not** part of the deployed site
> tree (publish.sh excludes it), which is fine — it's project documentation, not
> runtime content. If you ever want it on the server too, add it to `publish.sh`.

**To redeploy after future git changes** (run from the Mac, after confirming SSH):

```bash
cd ~/CLAUDE/JMCOREY/website
./deploy/publish.sh --dry-run      # confirm what will change
./deploy/publish.sh                # rsync to srv002 + restart pag + verify HTTP 200
```

---

## Admin password reset (2026-11-14)

- Reason: lost admin password for jonmcorey.com.
- Done: reset `admin` password to a known value, stored as PBKDF2-HMAC-SHA256
  (120 000 iter) + fresh 32-char salt, in `admin_users` AND legacy `settings`.
- Verified: live `POST /api/admin/login` returned HTTP 200 + `admin_token` cookie;
  wrong password returned HTTP 401.
- Backup taken first: `/opt/pag/data/pag.db.bak-before-adminpw-reset-20261102-152111`.
- Recommended: change it again from the Admin → Settings page once logged in.
