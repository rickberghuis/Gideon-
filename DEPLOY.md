# Hosting Gideon always-on (private, reachable from your phone)

Goal: Gideon runs 24/7 on a machine that never sleeps, and you reach it from your phone or
laptop **privately over Tailscale** — nothing exposed to the public internet.

The setup is the same whether the host is a **cloud VPS** (recommended — always-on, nothing
to maintain, ~$4–6/month) or a **Raspberry Pi / mini-PC** at home. It's just Docker +
Tailscale either way, so you can move hosts later without changing anything.

> Recommended host: a small cloud VPS (e.g. Hetzner CX22, DigitalOcean, or Fly.io), Ubuntu
> 24.04. A Pi 4/5 at home works identically and costs nothing to run.

---

## 1. Get the host
Create the VPS (or power on the Pi). You want SSH access and a plain Ubuntu/Debian.

## 2. Install Docker + Tailscale on the host
```bash
# Docker
curl -fsSL https://get.docker.com | sh

# Tailscale (private network)
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```
`tailscale up` prints a link — open it, sign in. This host now joins your private tailnet.
Note its name (e.g. `gideon`) — see it with `tailscale status`.

## 3. Get Gideon onto the host
Easiest is a private GitHub repo:
```bash
# on the host
git clone <your-private-repo-url> gideon && cd gideon
```
No remote yet? Copy the folder from your Mac instead (run on your Mac):
```bash
rsync -av --exclude .venv --exclude state --exclude .git \
  "/Users/rickberghuis/Documents/Claude assistent/" user@HOST:~/gideon/
```

## 4. Create the `.env` on the host
```bash
cp .env.example .env
nano .env
```
Fill in:
- `ANTHROPIC_API_KEY` — the brain (required)
- `DEEPGRAM_API_KEY`, `ELEVENLABS_API_KEY` — voice (optional)
- `GIDEON_WEB_PASSWORD` — **required here.** Pick something long/random; you'll type it once
  per device. (The server refuses to expose itself without it.)

## 5. Start it
```bash
docker compose up -d --build
docker compose logs -f        # watch it boot; Ctrl-C to stop watching
```
`restart: unless-stopped` means it comes back after crashes and host reboots. One container
runs both the chat face and the background heartbeat, so proactivity is always-on too.

## 6. Serve it privately over Tailscale (with HTTPS)
```bash
sudo tailscale serve --bg 8000
sudo tailscale serve status     # shows your private https URL
```
This proxies the local app to your tailnet at `https://<host>.<your-tailnet>.ts.net` — only
your own devices can reach it, and it's real HTTPS (so the browser mic works on your phone).

## 7. Use it from your phone / anywhere
1. Install the **Tailscale** app on your phone, sign in with the same account.
2. Open the `https://<host>.<tailnet>.ts.net` URL in your browser.
3. Enter your `GIDEON_WEB_PASSWORD`. Done — type or tap 🎤 to talk, from anywhere.

---

## Day-to-day
```bash
docker compose pull && docker compose up -d --build   # update after code changes
docker compose restart                                 # restart
docker compose down                                    # stop
docker compose logs -f                                 # logs
```
- **Data** (memory, reminders, inbox, audit log) lives in `./state` on the host — back this up.
- **Kill switch / cost** are in the web UI header, same as local.
- **Change a setting** (model, quiet hours, voice id): edit `config.toml` on the host, then
  `docker compose restart`.

## No-terminal option: Railway (deploys from GitHub in the browser)

Once the code is on GitHub, this is the most point-and-click way — no CLI at all.

1. Go to [railway.app](https://railway.app) → sign in **with GitHub**.
2. **New Project → Deploy from GitHub repo →** pick your `Gideon-` repo. Railway detects the
   `Dockerfile` and builds it.
3. Open the service → **Variables** → add: `ANTHROPIC_API_KEY`, `DEEPGRAM_API_KEY`,
   `ELEVENLABS_API_KEY`, `GIDEON_WEB_PASSWORD` (long/random).
4. **Volumes** → add a volume mounted at `/app/state` (keeps memory/reminders/inbox).
5. **Settings → Networking → Generate Domain** → gives you a public HTTPS URL.
6. Open the URL, enter your password. Done. (The app reads Railway's `$PORT` automatically.)

Always-on by default; ~$5/month usage-based (starts with trial credit). Public URL guarded by
your password + HTTPS. Render works the same way, but its free tier sleeps (bad for the
heartbeat), so use a paid Render plan or Railway.

## Cheapest + easiest option: Fly.io (public URL + password)

If you'd rather not manage a VPS, Fly.io runs the included `Dockerfile` directly and is the
lowest-effort always-on host (~$2–4/month for a tiny machine). It gives a public HTTPS URL
protected by your `GIDEON_WEB_PASSWORD` (no Tailscale needed, though the URL is public — the
password and HTTPS are what protect it, so make the password long).

```bash
# one-time: install flyctl, then from the project folder
fly launch --copy-config --no-deploy            # uses the included fly.toml
fly volumes create gideon_data --size 1         # durable state
fly secrets set ANTHROPIC_API_KEY=... DEEPGRAM_API_KEY=... \
                ELEVENLABS_API_KEY=... GIDEON_WEB_PASSWORD=<long-random>
fly deploy
fly open                                          # opens your https URL
```

`fly.toml` pins `min_machines_running = 1` and disables auto-stop so the heartbeat keeps
beating. Update later with `fly deploy`. Truly free alternative: an Oracle Cloud "Always Free"
VM, then follow the VPS + Tailscale steps above (more setup, $0 forever).

## Security notes
- Bound to `127.0.0.1` on the host and served only over your tailnet — not on the public
  internet. The password is a second layer on top of that.
- If you ever *must* expose it publicly instead of Tailscale, put it behind a reverse proxy
  with HTTPS (Caddy is one line) and keep the password — but Tailscale is safer; prefer it.
- The confirmation gate still applies remotely: send/spend/delete/change always ask first.
