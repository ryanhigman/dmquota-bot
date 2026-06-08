#!/usr/bin/env python3
"""
DMquota Bot   (v0.9)

A small resident Discord bot. One command group, run in the private audit channel,
PLUS automatic scheduled posts (no cron needed -- the schedule lives in the bot).

  /dmquota weekly   -- the weekly rift audit:
                       * each DM's rift count (+ explorations, for context),
                       * a +DTA flag for DMs who ran 2+ rifts in the window,
                       * DM-of-the-Week nominees: top 3 by rifts, ties included.
                       Defaults to the CURRENT week (since Sunday 00:00 UTC).

  /dmquota monthly  -- the monthly activity requirement, role-aware:
                       * Full DM (role "DM"):                  4 rifts OR 1 explo
                       * Apprentice DM (role "Apprentice DM"): 2 rifts
                       * Someone with BOTH roles -> held to the Full DM quota.
                       Defaults to the last 30 days.

  /dmquota help     -- prints a usage cheat-sheet (only you see it).

AUTOMATIC POSTS (configurable in CONFIG; all UTC)
  * Weekly  -- every Sunday at 00:01, posts the week that just completed.
  * Monthly -- on the 1st at 00:01, posts the previous calendar month
               (set MONTHLY_MODE="rolling30" for a literal last-30-days window).
  These post straight to the audit channel; no command needed.

TIME WINDOW (server time is UTC; weeks reset Sunday 00:00), priority order:
    1. start/end dates -> exact range (end inclusive of that whole day).
    2. week:N (weekly only) -> Sunday-aligned: 0=current, 1=last completed, ...
    3. days:N -> rolling last N days.

No AI, no external calls, nothing leaves this machine except what it posts to the
private channel.

WHAT IT NEEDS
    pip install -U discord.py
    Token in an environment variable (NOT in this file):
        export DISCORD_BOT_TOKEN="..."        # Linux/Mac
    Bot permissions:
        Game Log forum  -> View Channels, Read Message History
        Private channel -> View Channel, Send Messages
    Privileged intents: Message Content AND Server Members. Enable both in the
        Dev Portal.
    Invite scope: bot + applications.commands.

CLASSIFICATION (see classify())
    rift  = a log entry naming a tier (T1-T5 / Tier I-V), with rewards.
    explo = a log entry with "QLXP" or the word "explor..." (long-form one-shots);
            detected first, so "T5 Exploration" counts as an explo, not a rift.
    Skipped: bots, chatter, reward/tier REFERENCE tables (3+ tiers in one message).
    CRXP is NOT an explo marker -- some DMs use it on normal rifts.
"""

import os
import re
from datetime import datetime, timedelta, timezone
from datetime import time as dtime

import discord
from discord import app_commands
from discord.ext import tasks

# ----------------------------------------------------------------- CONFIG
GUILD_ID           = 000000000000000000   # Avalor server ID
GAMELOG_FORUM_ID   = 000000000000000000   # the Game Log forum channel ID
AUDIT_CHANNEL_ID   = 000000000000000000   # the private channel the commands work in

# Weekly audit
DEFAULT_DTA_RIFTS  = 2                     # >= this many rifts -> extra DTA eligible
DEFAULT_TOP        = 3                     # DM-of-the-Week nominee depth (ties included)

# Monthly quota -- role-aware
QUOTA_DAYS         = 30                    # rolling monthly window (fallback)
FULL_DM_ROLE_NAME  = "DM"                  # Full DM role (takes precedence)
APP_DM_ROLE_NAME   = "Apprentice DM"       # Apprentice DM role
FULL_MIN_RIFTS     = 4                     # Full DM: this many rifts...
FULL_MIN_EXPLOS    = 1                     # ...OR this many explorations
APP_MIN_RIFTS      = 2                     # Apprentice DM: this many rifts

# Who may run the commands:
#   None          -> anyone who can see the private channel
#   <role id int> -> only members with that role
STAFF_ROLE_ID      = None

# Scheduled auto-posts (the bot posts to the audit channel on its own; no cron)
AUTO_POST          = True                  # master switch for scheduled posts
AUTO_HOUR_UTC      = 0                      # daily tick time, hour (UTC)
AUTO_MINUTE_UTC    = 1                      # daily tick time, minute (UTC) -> 00:01
WEEKLY_AUTO        = True                   # auto-post the weekly audit every Sunday
MONTHLY_AUTO       = True                   # auto-post the monthly quota on the 1st
MONTHLY_MODE       = "calendar"             # "calendar" = previous full month (recommended)
                                            # "rolling30" = literal last-30-days lookback
# -------------------------------------------------------------------------

TIER_RE   = re.compile(r"(?im)\bt(?:ier)?\s*-?\s*([1-5]|i{1,3}|iv|v)\b")
REWARD_RE = re.compile(r"(?i)\b(?:rpxp|crxp|qlxp|rift\s*xp|xp|gold|coins?|gp|loot)\b")
# (exploration is detected by the words "explor..." / "qlxp" inside classify())


def classify(content: str):
    """Return 'rift', 'explo', or None for a single message."""
    if not content or len(content.strip()) < 15:
        return None
    tiers = TIER_RE.findall(content)
    if len(tiers) >= 3:                 # reward table / tier-guideline paste
        return None
    low = content.lower()
    has_reward = bool(REWARD_RE.search(content))
    if "qlxp" in low:
        return "explo"
    if "explor" in low and (has_reward or tiers or "@" in content):
        return "explo"
    if tiers:
        return "rift"
    return None


def role_of(member):
    """'Full', 'App', or None. 'DM' takes precedence over 'Apprentice DM'."""
    if member is None:
        return None
    names = {r.name for r in getattr(member, "roles", [])}
    if FULL_DM_ROLE_NAME in names:
        return "Full"
    if APP_DM_ROLE_NAME in names:
        return "App"
    return None


def _parse_day(s):
    return datetime.strptime(s.strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)


def resolve_window(days=None, start=None, end=None, week=None):
    """Return (after|None, before|None, label). All UTC.
    Priority: start/end > week > days. Caller ensures one is set."""
    now = datetime.now(timezone.utc)
    if start or end:
        after = _parse_day(start) if start else None
        before = (_parse_day(end) + timedelta(days=1)) if end else None   # end inclusive
        return after, before, f"{start or 'start'} to {end or 'now'} (UTC)"
    if week is not None:
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        days_since_sunday = (now.weekday() + 1) % 7      # Mon=0..Sun=6 -> Sun=0
        cur = midnight - timedelta(days=days_since_sunday)
        if week <= 0:
            return cur, None, f"current week (since {cur:%a %Y-%m-%d}, UTC)"
        after = cur - timedelta(days=7 * week)
        before = cur - timedelta(days=7 * (week - 1))
        return after, before, f"week of {after:%a %Y-%m-%d} (UTC)"
    return now - timedelta(days=days), None, f"last {days} days"


def previous_month_range(now):
    """(after, before, label) for the full calendar month before `now`. UTC."""
    first_this = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start = (first_this - timedelta(days=1)).replace(day=1)
    return start, first_this, f"{start:%B %Y}"           # before is exclusive -> month fully covered


intents = discord.Intents.default()
intents.message_content = True
intents.members = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


@client.event
async def on_ready():
    guild = discord.Object(id=GUILD_ID)
    tree.copy_global_to(guild=guild)
    await tree.sync(guild=guild)
    if AUTO_POST and not scheduler.is_running():
        scheduler.start()
    print(f"Logged in as {client.user}. Commands ready: /dmquota weekly|monthly|help"
          + ("  | auto-posts ON" if AUTO_POST else ""))


async def tally(forum: discord.ForumChannel, after, before):
    """Return (records, n_threads). Each record:
       {'label': str, 'member': Member|None, 'rift': int, 'explo': int}."""
    recs = {}
    threads = list(forum.threads)
    async for t in forum.archived_threads(limit=None):
        threads.append(t)
    for t in threads:
        owner_id = t.owner_id
        owner = t.owner or (forum.guild.get_member(owner_id) if owner_id else None)
        label = (owner.display_name if owner else None) or t.name or f"thread-{t.id}"
        key = owner_id or f"thread-{t.id}"
        rec = recs.setdefault(key, {"label": label, "member": owner, "rift": 0, "explo": 0})
        if owner and rec["member"] is None:
            rec["member"], rec["label"] = owner, label
        async for msg in t.history(limit=None, after=after, before=before, oldest_first=True):
            if msg.author.bot:
                continue
            if owner_id and msg.author.id != owner_id:
                continue
            kind = classify(msg.content)
            if kind:
                rec[kind] += 1
    return list(recs.values()), len(threads)


def nominees(records, top):
    scored = [(r["label"], r["rift"]) for r in records if r["rift"] > 0]
    if not scored:
        return []
    counts_desc = sorted({n for _, n in scored}, reverse=True)
    threshold = counts_desc[min(top, len(counts_desc)) - 1]
    groups = []
    for cnt in counts_desc:
        if cnt < threshold:
            break
        names = sorted(name for name, n in scored if n == cnt)
        groups.append((cnt, names))
    return groups


def _cap(out):
    return out if len(out) <= 1990 else out[:1980] + "\n```\n(truncated)"


async def build_weekly(forum, after, before, label, dta, top):
    records, n_threads = await tally(forum, after, before)
    rows = sorted(records, key=lambda r: (r["rift"], r["explo"]), reverse=True)
    width = max((len(r["label"]) for r in rows), default=2)
    header = f"{'DM'.ljust(width)}  rifts  explos  +DTA"
    lines = [header, "-" * len(header)]
    for r in rows:
        flag = "yes" if r["rift"] >= dta else ""
        lines.append(f"{r['label'].ljust(width)}  {r['rift']:>5}  {r['explo']:>6}  {flag}")
    out = (f"**Weekly rift audit -- {label}  (extra DTA at {dta}+ rifts)**\n"
           f"```\n" + "\n".join(lines) + "\n```")
    groups = nominees(records, top)
    if groups:
        nom = [f"{cnt:>3}  " + ", ".join(names) for cnt, names in groups]
        out += ("\n**DM of the Week nominees** (most rifts, ties included):\n```\n"
                + "\n".join(nom) + "\n```")
    out += f"\n_Scanned {n_threads} log posts._"
    return _cap(out)


async def build_monthly(forum, after, before, label):
    records, n_threads = await tally(forum, after, before)
    rows = sorted(records, key=lambda r: (r["rift"], r["explo"]), reverse=True)
    width = max((len(r["label"]) for r in rows), default=2)
    header = f"{'DM'.ljust(width)}  role  rifts  explos  status"
    lines = [header, "-" * len(header)]
    for r in rows:
        role = role_of(r["member"])
        if role == "Full":
            ok = r["rift"] >= FULL_MIN_RIFTS or r["explo"] >= FULL_MIN_EXPLOS
            rlabel, status = "Full", ("OK" if ok else "BELOW")
        elif role == "App":
            ok = r["rift"] >= APP_MIN_RIFTS
            rlabel, status = "App ", ("OK" if ok else "BELOW")
        else:
            rlabel, status = "?   ", "no DM role"
        lines.append(f"{r['label'].ljust(width)}  {rlabel}  {r['rift']:>5}  {r['explo']:>6}  {status}")
    out = (f"**Monthly activity -- {label}**  "
           f"(Full: {FULL_MIN_RIFTS} rifts or {FULL_MIN_EXPLOS} explo | "
           f"App: {APP_MIN_RIFTS} rifts)\n"
           f"```\n" + "\n".join(lines) + "\n```")
    out += f"\n_Scanned {n_threads} log posts._"
    return _cap(out)


async def guard(interaction: discord.Interaction) -> bool:
    if interaction.channel_id != AUDIT_CHANNEL_ID:
        await interaction.response.send_message(
            "This command only works in the audit channel.", ephemeral=True)
        return False
    if STAFF_ROLE_ID is not None:
        if not any(r.id == STAFF_ROLE_ID for r in getattr(interaction.user, "roles", [])):
            await interaction.response.send_message(
                "You don't have permission to run this.", ephemeral=True)
            return False
    return True


def get_forum():
    forum = client.get_channel(GAMELOG_FORUM_ID)
    return forum if isinstance(forum, discord.ForumChannel) else None


# ============================================================ /dmquota group
dmquota = app_commands.Group(name="dmquota",
                             description="DM activity audits for the Game Log forum.")


@dmquota.command(name="weekly",
                 description="Weekly rift audit: DTA eligibility + DM-of-the-Week nominees.")
@app_commands.describe(
    week="Sunday-aligned week: 0=current (default), 1=last completed, 2=two ago, ...",
    days="Rolling window in days (alternative to week)",
    start="Range start YYYY-MM-DD (UTC)", end="Range end YYYY-MM-DD (UTC, inclusive)",
    dta="Rifts needed for extra DTA (default 2)",
    top="Top places for nominees (default 3, ties included)")
async def weekly(interaction: discord.Interaction,
                 week: int = None, days: int = None, start: str = None, end: str = None,
                 dta: int = DEFAULT_DTA_RIFTS, top: int = DEFAULT_TOP):
    if not await guard(interaction):
        return
    if start is None and end is None and week is None and days is None:
        week = 0
    try:
        after, before, label = resolve_window(days, start, end, week)
    except ValueError:
        await interaction.response.send_message(
            "Dates must be YYYY-MM-DD (e.g. 2026-05-01).", ephemeral=True)
        return
    await interaction.response.defer(thinking=True)
    forum = get_forum()
    if not forum:
        await interaction.followup.send("GAMELOG_FORUM_ID isn't a forum channel -- check config.")
        return
    await interaction.followup.send(await build_weekly(forum, after, before, label, dta, top))


@dmquota.command(name="monthly",
                 description="Monthly activity requirement, by DM role (Full vs Apprentice).")
@app_commands.describe(
    days="Rolling window in days (default 30; ignored if start/end given)",
    start="Range start YYYY-MM-DD (UTC)", end="Range end YYYY-MM-DD (UTC, inclusive)")
async def monthly(interaction: discord.Interaction,
                  days: int = None, start: str = None, end: str = None):
    if not await guard(interaction):
        return
    if start is None and end is None and days is None:
        days = QUOTA_DAYS
    try:
        after, before, label = resolve_window(days, start, end)
    except ValueError:
        await interaction.response.send_message(
            "Dates must be YYYY-MM-DD (e.g. 2026-05-01).", ephemeral=True)
        return
    await interaction.response.defer(thinking=True)
    forum = get_forum()
    if not forum:
        await interaction.followup.send("GAMELOG_FORUM_ID isn't a forum channel -- check config.")
        return
    await interaction.followup.send(await build_monthly(forum, after, before, label))


HELP_TEXT = (
    "**DM activity audits — how to use**\n"
    "Run these in this channel. All dates are UTC; weeks reset Sunday 00:00.\n\n"
    "**`/dmquota weekly`** — rift audit for a week.\n"
    "Shows each DM's rifts, `+DTA` = yes for 2+ rifts, and DM-of-the-Week "
    "nominees (top 3 by rifts, ties included).\n"
    "• no options → current week (since Sunday)\n"
    "• `week:1` last completed week · `week:2` two weeks ago\n"
    "• `days:7` rolling · `start:2026-05-04 end:2026-05-10` exact range\n"
    "• `dta:2` DTA threshold · `top:3` nominee depth\n\n"
    "**`/dmquota monthly`** — activity requirement by role.\n"
    "• Full DM (role \"DM\"): 4 rifts OR 1 exploration\n"
    "• Apprentice DM: 2 rifts · both roles → held to Full\n"
    "• no options → last 30 days · `start:2026-05-01 end:2026-05-31` for a calendar month\n\n"
    "**Automatic posts:** the weekly audit posts every Sunday 00:01 UTC, and the "
    "monthly quota posts on the 1st 00:01 UTC — no command needed.\n"
    "Counts come from the Game Log; bot posts and reward reference tables are ignored."
)


@dmquota.command(name="help", description="How to use the audit commands.")
async def help_cmd(interaction: discord.Interaction):
    await interaction.response.send_message(HELP_TEXT, ephemeral=True)


tree.add_command(dmquota)


# ============================================================ scheduled posts
@tasks.loop(time=dtime(hour=AUTO_HOUR_UTC, minute=AUTO_MINUTE_UTC, tzinfo=timezone.utc))
async def scheduler():
    """Daily tick at AUTO_HOUR:AUTO_MINUTE UTC. Posts weekly on Sundays and
    monthly on the 1st, straight to the audit channel."""
    now = datetime.now(timezone.utc)
    channel = client.get_channel(AUDIT_CHANNEL_ID)
    forum = get_forum()
    if channel is None or forum is None:
        print("scheduler: audit channel or forum unavailable; skipping tick.")
        return
    try:
        if WEEKLY_AUTO and now.weekday() == 6:                 # Sunday
            after, before, label = resolve_window(week=1)      # the week that just ended
            msg = await build_weekly(forum, after, before, label, DEFAULT_DTA_RIFTS, DEFAULT_TOP)
            await channel.send("**[Automated weekly audit]**\n" + msg)
        if MONTHLY_AUTO and now.day == 1:
            if MONTHLY_MODE == "rolling30":
                after, before, label = resolve_window(days=30)
            else:
                after, before, label = previous_month_range(now)
            msg = await build_monthly(forum, after, before, label)
            await channel.send("**[Automated monthly audit]**\n" + msg)
    except Exception as e:
        print(f"scheduler error: {e}")


@scheduler.before_loop
async def _before_scheduler():
    await client.wait_until_ready()


if __name__ == "__main__":
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        raise SystemExit("Set the DISCORD_BOT_TOKEN environment variable first.")
    client.run(token)
