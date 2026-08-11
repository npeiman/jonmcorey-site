# Deploying to your Ubuntu 24 VPS

This moves the Professional Advisory Group site to your VPS, running as a managed
`systemd` service behind nginx, with HTTPS. Because the app is pure Python 3
(standard library only), **there is nothing to compile and no packages to install**
beyond nginx.

Layout we'll create on the server:

```
/opt/pag/website     <- application code (this folder's contents)
/opt/pag/data        <- pag.db lives here (survives code updates)
```

Optionally, a separate development instance on port 8010:

```
/opt/pag-dev/website
/opt/pag-dev/data
```

---

## 0. What I need from you (and what NOT to send)

Please share:
- The VPS **IP address or hostname**
- The **SSH username** you use (e.g. `root` or `ubuntu`)
- Your **domain name(s)** for the site, if you have one yet (optional — we can start with the IP)
- Whether you want a **dev + production** split, or just production for now

**Do NOT paste passwords or private SSH keys into the chat.** For me to run the deploy
commands from your Mac, key-based SSH must already work — i.e. this succeeds without
prompting for a password:

```bash
ssh YOUR_USER@YOUR_VPS_IP "echo connected"
```

If that asks for a password, either (a) set up an SSH key first (`ssh-copy-id
YOUR_USER@YOUR_VPS_IP`), or (b) you run the commands yourself and I'll hand you each one.

---

## 1. Upload the app to the server

From this Mac, in `/Users/nathanielpeiman/CLAUDE/JMCOREY`:

```bash
rsync -avz --exclude 'pag.db' website/ YOUR_USER@YOUR_VPS_IP:/opt/pag/website/
```

(We exclude `pag.db` so your local test database doesn't overwrite the server's.
The server keeps its own database in `/opt/pag/data`.)

If `/opt/pag` doesn't exist yet or you get a permissions error, create it first:

```bash
ssh YOUR_USER@YOUR_VPS_IP "sudo mkdir -p /opt/pag && sudo chown \$USER /opt/pag"
```

---

## 2. Run the one-time setup script

```bash
ssh YOUR_USER@YOUR_VPS_IP "sudo bash /opt/pag/website/deploy/setup.sh"
# ...or, to also create the dev instance:
ssh YOUR_USER@YOUR_VPS_IP "sudo bash /opt/pag/website/deploy/setup.sh --with-dev"
```

This installs nginx, creates the `pag` service user and directories, installs and starts
the `pag` systemd service, and wires up the nginx reverse proxy. On first start the app
creates the database and prints the default admin login (`admin` / `changeme`).

Check it's running:

```bash
ssh YOUR_USER@YOUR_VPS_IP "systemctl status pag --no-pager"
```

At this point the site is reachable at **http://YOUR_VPS_IP/** (via nginx on port 80).

---

## 3. Point your domain at the server

In your DNS provider, create an **A record** for your domain (and `www`) pointing to the
VPS IP. Then set the domain in nginx:

```bash
ssh YOUR_USER@YOUR_VPS_IP "sudo sed -i 's/__DOMAIN__/yourdomain.com www.yourdomain.com/' /etc/nginx/sites-available/pag && sudo nginx -t && sudo systemctl reload nginx"
```

---

## 4. Enable HTTPS (Let's Encrypt)

Once DNS is pointing at the server:

```bash
ssh YOUR_USER@YOUR_VPS_IP "sudo apt-get install -y certbot python3-certbot-nginx && sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com"
```

Certbot edits the nginx config to add HTTPS and sets up auto-renewal.

---

## 5. Final app configuration

1. Visit **https://yourdomain.com/admin**, sign in (`admin` / `changeme`).
2. **Change the admin password** under Settings immediately.
3. Set **Site Base URL** to `https://yourdomain.com` (used later for Stripe return links).
4. Add your availability. (Stripe and email can be configured later.)

---

## Updating the site later (redeploy)

When we change the code, push the update and restart:

```bash
rsync -avz --exclude 'pag.db' website/ YOUR_USER@YOUR_VPS_IP:/opt/pag/website/
ssh YOUR_USER@YOUR_VPS_IP "sudo systemctl restart pag"
```

The database in `/opt/pag/data` is untouched by updates.

## Development workflow (if using --with-dev)

- Push to dev:  `rsync -avz --exclude 'pag.db' website/ YOUR_USER@YOUR_VPS_IP:/opt/pag-dev/website/ && ssh YOUR_USER@YOUR_VPS_IP "sudo systemctl restart pag-dev"`
- Dev runs on port 8010 (expose via a `dev.` subdomain in the nginx config if you want it public).
- When dev looks good, promote the same files to `/opt/pag/website` and restart `pag`.

## Useful commands

```bash
sudo systemctl status pag          # is it running?
sudo journalctl -u pag -f          # live logs
sudo systemctl restart pag         # restart after a code change
```
