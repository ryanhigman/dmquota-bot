# DMquota Bot

A small Discord bot that audits Dungeon Master activity in the Avalor **Game Log**
forum. It counts each DM's rifts and explorations and reports them against the
server's activity rules — posting only to a private staff channel.

## What it does
- **`/dmquota weekly`** — each DM's rifts for the week, a `+DTA` flag (2+ rifts),
  and DM-of-the-Week nominees (top 3 by rifts, ties included).
- **`/dmquota monthly`** — role-aware activity check: Full DM (role `DM`) needs
  4 rifts **or** 1 exploration; Apprentice DM needs 2 rifts. DM role outranks
  Apprentice if someone has both.
- **`/dmquota help`** — usage, in Discord.
- **Automatic posts** — weekly every Sunday 00:01 UTC, monthly on the 1st 00:01 UTC.

No AI and no external calls: it's deterministic regex over the Game Log, and the
only thing it sends anywhere is the table it posts to the private channel. All
time logic is pinned to UTC.

## Repo contents
- `dmquota_bot.py` — the entire bot (~300 lines, commented).
- `Dockerfile`, `docker-compose.yml`, `.env.example` — containerized deploy.
- `README.md` — this file (full setup below).

## A note on parsing
The Game Log is free-form text, so rift/exploration detection is **heuristic
regex**, not a parser of structured data. It handles the formats seen in practice
(see the `classify()` function and its comments), but edge cases exist — verify
flags against the source when it matters. The durable fix is standardizing how
rifts get logged (a template or a log command) so there's nothing to infer.

---

# Setup

Set up `dmquota_bot.py` as an always-on Discord bot so staff can run `/dmquota`
in the private audit channel (and get automatic weekly/monthly posts).

**Order:** Discord setup (A–B) → pick a host (C) → install & keep it running (D).

**Who does this:** whoever hosts the bot holds its token and effectively controls
it, so the host should do Part A and keep the token. (Could be Kain, Stetsed on
his server rack — whoever owns the machine it runs on.)

> **Heads-up: you may see a second bot already in the server.** Ryan set up an
> earlier bot during testing (a one-off message export). The bot you create here
> is **separate and owned entirely by you**. The two don't interfere. If you want
> no leftover bot you don't own, you can **Kick** the old one *after* yours works
> (Server Settings → Integrations / Members; needs Manage Server). Optional —
> leaving it idle does no harm.

---

## Part A — Create the bot  (host does this, in their own Discord account)

1. <https://discord.com/developers/applications> → **New Application** → name it
   "DMquota Bot" → create.
2. **Bot** (left sidebar) → **Privileged Gateway Intents** → turn ON **both**:
   - **Message Content Intent** (read the log posts), and
   - **Server Members Intent** (so `/dmquota monthly` can read each DM's role).
   Save.
3. **Reset Token** → copy → store it safely (a password manager). Shown once; you
   can always reset again. This goes in `DISCORD_BOT_TOKEN` in Part D. **Never
   paste it into chat or commit it to a file.**
4. Invite it: **OAuth2 → URL Generator** →
   - **Scopes:** **bot** *and* **applications.commands**.
   - **Bot Permissions:** **View Channels** + **Read Message History** only.
   - Copy the URL at the bottom.
5. Open the URL, choose **Avalor**, authorize (needs **Manage Server**). The bot
   appears in the member list.

## Part B — IDs & channel permissions

6. Discord → **Settings → Advanced → Developer Mode** ON.
7. Right-click **Copy ID** for each, paste into the CONFIG block at the top of
   `dmquota_bot.py`:
   - **Avalor server** → `GUILD_ID`
   - **Game Log forum** channel → `GAMELOG_FORUM_ID`
   - **private audit channel** → `AUDIT_CHANNEL_ID`
   - (optional) a **staff role** → `STAFF_ROLE_ID` to limit who can run commands;
     leave `None` to let anyone in the private channel run them.
8. In the **private channel** → **Permissions** → add the bot's role (or the bot)
   and allow **View Channel** + **Send Messages**. A private channel is invisible
   to anyone not explicitly added, so this is required for the bot to post there
   (including the automatic weekly/monthly posts). Game Log read access came from
   the Part A invite.

---

## Part C — Choose a host  (do ONE)

### Option C-1 — Your own always-on machine  ·  *server rack, home server, NAS, Pi*

Best if you already have a machine that stays powered on. Free, fully yours,
nothing touches a third party.

1. Make sure it runs **Linux** (these instructions, and the systemd step in D,
   assume Linux) with **Python 3.10+**: `python3 --version`.
2. That's it for Part C — go to **Part D** and run the steps directly on that
   machine (open a terminal on it; you can skip the SSH step).

> Windows-only rack? It still works, but "keep it alive" uses Task Scheduler or
> NSSM instead of systemd. Ask and I'll provide the Windows variant.

### Option C-2 — Free Oracle Cloud VM  ·  *if you have no always-on machine*

1. Sign up at <https://www.oracle.com/cloud/free/>. A real card is needed for
   identity check, but **Always Free** resources don't charge. (Signup is finicky;
   if rejected, try another browser/card or retry later — an Oracle quirk.)
2. Console → **Compute → Instances → Create Instance**:
   - **Image:** Ubuntu 22.04.
   - **Shape:** *Change shape* → an **Always Free-eligible** one (`VM.Standard.A1.Flex`
     or `VM.Standard.E2.1.Micro`). **Don't pick a non-free shape**, or you'll be billed.
   - **SSH keys:** *Generate a key pair* and **download the private key now** (you
     log in with it; without it you'd recreate the instance).
   - **Create**, wait for state **Running**, and copy the **Public IP**.
3. Go to **Part D**; you'll connect over SSH.

---

## Part D — Install, run, and keep it alive

Run on the host machine. For C-1 open a terminal on it directly; for C-2 (Oracle)
SSH in first. Replace `USER` with your Linux username (`ubuntu` on Oracle Ubuntu).

1. **(Oracle only) SSH in:**
   ```
   ssh -i /path/to/your-private-key ubuntu@<PUBLIC_IP>
   ```
   If it refuses the key: `chmod 600 /path/to/your-private-key` and retry.

2. **Install Python tools:**
   ```
   sudo apt update && sudo apt install -y python3 python3-pip python3-venv
   ```

3. **Put the bot file on the machine.** On Oracle, copy it from your computer:
   ```
   scp -i /path/to/your-private-key dmquota_bot.py USER@<PUBLIC_IP>:~/
   ```
   On your own machine, just save `dmquota_bot.py` to your home folder. Then:
   ```
   mkdir -p ~/dmquota && mv ~/dmquota_bot.py ~/dmquota/
   ```

4. **Environment + dependency:**
   ```
   cd ~/dmquota
   python3 -m venv venv
   ./venv/bin/pip install -U discord.py
   ```

5. **Test run:**
   ```
   export DISCORD_BOT_TOKEN="paste-the-token-here"
   ./venv/bin/python dmquota_bot.py
   ```
   You should see `Logged in as ... Commands ready: /dmquota ...  | auto-posts ON`.
   In Discord, run `/dmquota weekly` in the private channel — a table back means
   it works. Stop the test with **Ctrl-C**.

6. **Keep it running across reboots (systemd):**
   ```
   sudo nano /etc/systemd/system/dmquota.service
   ```
   Paste this, replacing `USER` with your username:
   ```ini
   [Unit]
   Description=DMquota Bot
   After=network-online.target
   Wants=network-online.target

   [Service]
   User=USER
   WorkingDirectory=/home/USER/dmquota
   Environment=DISCORD_BOT_TOKEN=paste-the-token-here
   ExecStart=/home/USER/dmquota/venv/bin/python /home/USER/dmquota/dmquota_bot.py
   Restart=always
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```
   Enable and start:
   ```
   sudo systemctl daemon-reload
   sudo systemctl enable --now dmquota
   sudo systemctl status dmquota      # should say "active (running)"
   ```
   - Lock the unit file (it holds the token): `sudo chmod 600 /etc/systemd/system/dmquota.service`
   - Live logs: `journalctl -u dmquota -f`
   - After editing the bot later: `sudo systemctl restart dmquota`

The bot now stays online, reconnects on its own, survives reboots, runs `/dmquota`
on demand, and auto-posts the weekly (Sunday 00:01 UTC) and monthly (1st, 00:01
UTC) audits to the private channel.

### Part D (alternative) — Docker

If you'd rather run it containerized (recommended if your host already runs
Docker), use the included `Dockerfile`, `docker-compose.yml`, and `.env.example`
instead of the systemd steps above. Put all four files (`dmquota_bot.py`,
`Dockerfile`, `docker-compose.yml`, `.env.example`) in one folder, fill in the
config IDs in `dmquota_bot.py`, then:

```
cp .env.example .env          # then edit .env and paste the real bot token
docker compose up -d --build  # build + run in the background
docker compose logs -f        # watch startup; expect "Commands ready: /dmquota ..."
```

- `restart: unless-stopped` in the compose file is the container equivalent of the
  systemd auto-restart — it comes back after crashes and host reboots.
- The token lives only in `.env` (keep it out of version control); it's never
  baked into the image.
- After editing the bot: `docker compose up -d --build` again.
- All time logic is pinned to UTC in code, so the container's timezone is irrelevant.

---

## Quick reference

| Thing | Where / how |
|---|---|
| Bot token | Dev Portal → Bot → Reset Token; stored only in the systemd unit file |
| The four IDs | CONFIG block at top of `dmquota_bot.py` |
| Who can run it | `STAFF_ROLE_ID` (None = anyone in the private channel) |
| Weekly audit | `/dmquota weekly` — +DTA at 2+ rifts, top-3 DMotW nominees (ties incl). Defaults to current week. |
| Monthly quota | `/dmquota monthly` — Full DM: 4 rifts or 1 explo; Apprentice DM: 2 rifts. Defaults to last 30 days. |
| Usage help | `/dmquota help` — prints a cheat-sheet (only the runner sees it). |
| Time window | `week:N` Sunday-aligned (0=current, 1=last week) · `days:N` rolling · `start:YYYY-MM-DD end:YYYY-MM-DD` exact range. All UTC. |
| Auto-posts | Weekly Sunday 00:01 UTC (completed week); monthly 1st 00:01 UTC (previous calendar month). Built into the bot — no cron. Toggle/retime in CONFIG (`AUTO_POST`, `MONTHLY_MODE`, ...). |
| Restart after edits | `sudo systemctl restart dmquota` |
| Live logs | `journalctl -u dmquota -f` |

## If something goes wrong

- **Oracle signup rejected** → different browser/card, or retry later.
- **`/dmquota` doesn't appear** → invite was missing `applications.commands`; redo Part A step 4–5.
- **"only works in the audit channel"** → `AUDIT_CHANNEL_ID` doesn't match the channel you typed in.
- **Everyone shows "no DM role"** → the **Server Members Intent** is off (Part A step 2), or the role names in CONFIG don't match the server's ("DM" / "Apprentice DM").
- **Can't post / permission error** → redo Part B step 8 on the private channel.
- **Service won't start** → `journalctl -u dmquota -f` shows the real error (usually a wrong path or missing token in the unit file).
