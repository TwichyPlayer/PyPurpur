# main.py — PyPurpur Discord Bot v3 (legacy embeds / views)
# Requires discord.py == 2.5.2

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path

import discord
from discord import app_commands
from dotenv import load_dotenv

from modrinth import modrinth
from server_manager import PLUGINS_DIR, PURPUR_JAR, ServerManager

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pypurpur.bot")

# ── Config helpers ────────────────────────────────────────────────────────────

load_dotenv()

def _cfg(key: str, default: str = "") -> str:
    cfg = Path("config.txt")
    if cfg.exists():
        for line in cfg.read_text().splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() == key:
                return v.strip()
    return os.getenv(key, default)

def _set_config(key: str, value: str) -> None:
    cfg = Path("config.txt")
    text = cfg.read_text() if cfg.exists() else ""
    pat = re.compile(rf"^{re.escape(key)}=.*", re.MULTILINE)
    if pat.search(text):
        cfg.write_text(pat.sub(f"{key}={value}", text))
    else:
        cfg.write_text(text.rstrip() + f"\n{key}={value}\n")

# ── Environment ───────────────────────────────────────────────────────────────

TOKEN:          str       = os.environ["DISCORD_TOKEN"]
OWNER_ID:       int       = int(os.environ["OWNER_ID"])
MC_VERSION:     str       = _cfg("MC_VERSION",  "1.21.11")
MIN_RAM:        int       = int(_cfg("MIN_RAM",  "512"))
MAX_RAM:        int       = int(_cfg("MAX_RAM",  "3072"))
AUTO_UPDATE:    bool      = _cfg("AUTO_UPDATE_PLUGINS", "false").lower() == "true"
UPDATE_CH_RAW:  str       = _cfg("UPDATE_CHANNEL_ID", "")
UPDATE_CHANNEL: int|None  = int(UPDATE_CH_RAW) if UPDATE_CH_RAW.isdigit() else None
EPHEMERAL:      bool      = _cfg("EPHEMERAL_RESPONSES", "true").lower() == "true"

# ── Shared state ──────────────────────────────────────────────────────────────

server = ServerManager(
    version=MC_VERSION, min_ram=MIN_RAM, max_ram=MAX_RAM,
    auto_update=AUTO_UPDATE, update_channel_id=UPDATE_CHANNEL,
)

PURPUR_VERSIONS = [
    "1.21.1","1.21.2","1.21.3","1.21.4","1.21.5",
    "1.21.6","1.21.7","1.21.8","1.21.9","1.21.10","1.21.11",
]

# ── Whitelist helpers ─────────────────────────────────────────────────────────

WHITELIST_FILE = Path("whitelist.json")

def _load_whitelist() -> list[int]:
    if WHITELIST_FILE.exists():
        try:
            return [int(x) for x in json.loads(WHITELIST_FILE.read_text())]
        except Exception:
            pass
    return []

def _save_whitelist(ids: list[int]) -> None:
    WHITELIST_FILE.write_text(json.dumps([str(x) for x in ids]))

def is_authorized(user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True
    return user_id in _load_whitelist()

# ── Colours ───────────────────────────────────────────────────────────────────

PURPUR = discord.Colour(0x9B59B6)
RED    = discord.Colour(0xE74C3C)
GREEN  = discord.Colour(0x2ECC71)
ORANGE = discord.Colour(0xE67E22)
GREY   = discord.Colour(0x95A5A6)
BLUE   = discord.Colour(0x3498DB)
CYAN   = discord.Colour(0x1ABC9C)
YELLOW = discord.Colour(0xF1C40F)

# ── Emojis ────────────────────────────────────────────────────────────────────
# FIX: PartialEmoji requires name="" for custom emoji IDs

def _e(eid: int) -> discord.PartialEmoji:
    return discord.PartialEmoji(name="", id=eid)

EMO = {
    # Gameplay
    "spectator":     _e(1476024269359284364),
    "adventure":     _e(1476024621043159093),
    "survival":      _e(1476024271221428446),
    "creative":      _e(1476024272471199850),
    # Player actions
    "kill":          _e(1476019100357627955),
    "ban":           _e(1476022393901154376),
    "kick":          _e(1476020091505348609),
    "heal":          _e(1476019095366275236),
    "feed":          _e(1476019090106617978),
    "starve":        _e(1476019087669727274),
    "damage":        _e(1476019098524848189),
    "gamemode":      _e(1476019086600175829),
    # Access denied
    "access_denied": _e(1476022393901154376),
    # About
    "claude":        _e(1476053013125922999),
    "mojang":        _e(1476053395436474449),
    "mixedstudios":  _e(1476055111863373835),
}

# ── Bot setup ─────────────────────────────────────────────────────────────────

class PyPurpurBot(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(
            client=self,
            allowed_installs=app_commands.AppInstallationType(guild=True, user=True),
            allowed_contexts=app_commands.AppCommandContext(
                guild=True, dm_channel=True, private_channel=True,
            ),
        )

    async def setup_hook(self) -> None:
        await self.tree.sync()
        log.info("Global commands synced.")

    async def on_ready(self) -> None:
        await self.change_presence(activity=discord.Game(name="☁️  /help • PyPurpur"))
        log.info("Logged in as %s (%s)", self.user, self.user.id)  # type: ignore[union-attr]


bot  = PyPurpurBot()
tree = bot.tree

# ── Access control ────────────────────────────────────────────────────────────

async def _check(interaction: discord.Interaction) -> bool:
    """Return True if authorized. Send access-denied and return False if not."""
    if is_authorized(interaction.user.id):
        return True
    em = discord.Embed(
        description=(
            f"{EMO['access_denied']}  **Access Denied.**\n"
            "-# You're not authorized to use PyPurpur commands."
        ),
        colour=RED,
    )
    await interaction.response.send_message(embed=em, ephemeral=True)
    return False

async def _need_running(interaction: discord.Interaction) -> bool:
    """Return True (and reply) if server is NOT running."""
    if server.is_running:
        return False
    await _err(interaction, "The Minecraft server is not running.")
    return True

# ── Shorthand responders ─────────────────────────────────────────────────────

async def _ok(i: discord.Interaction, msg: str) -> None:
    await i.response.send_message(
        embed=discord.Embed(description=f"✅  {msg}", colour=GREEN),
        ephemeral=EPHEMERAL,
    )

async def _err(i: discord.Interaction, msg: str) -> None:
    await i.response.send_message(
        embed=discord.Embed(description=f"❌  {msg}", colour=RED),
        ephemeral=True,   # errors are always private
    )

# ── ANSI chat formatter ───────────────────────────────────────────────────────

def _fmt_chat(entries: list[tuple]) -> str:
    _AG, _ABG, _AY, _GY, _R = "\u001b[2;32m","\u001b[1;32m","\u001b[2;33m","\u001b[2;30m","\u001b[0m"
    lines: list[str] = []
    for kind, time, player, extra in entries:
        ts = f"{_GY}[{time}]{_R}"
        if kind == "chat":
            lines.append(f"{ts} <{player}> {extra}")
        elif kind == "advancement":
            lines.append(f"{ts} {player} has made the advancement {_AG}[{_ABG}{extra}{_R}{_AG}]{_R}")
        elif kind == "join":
            lines.append(f"{ts} {_AG}{player} joined the game{_R}")
        elif kind == "leave":
            lines.append(f"{ts} {_AY}{player} left the game{_R}")
    return "\n".join(lines) or "— no messages yet —"

# ═════════════════════════════════════════════════════════════════════════════=
#  COMMANDS (legacy embeds + views)
# ═════════════════════════════════════════════════════════════════════════════=

# ── /help ─────────────────────────────────────────────────────────────────────

@tree.command(name="help", description="Show all available PyPurpur commands.")
async def cmd_help(interaction: discord.Interaction) -> None:
    if not await _check(interaction): return

    desc = (
        "# 📖  PyPurpur — Commands\n"
        "-# Open-source Minecraft ↔ Discord bridge\n\n"
        "**⚙️  Server Control**\n"
        "`/start` • `/stop` • `/restart` • `/reinstall` • `/pause`\n\n"
        "**🖥️  Console & Chat**\n"
        "`/run` • `/chat` • `/say` • `/broadcast`\n\n"
        "**📊  Status**\n"
        "`/stats` • `/online` • `/seed` • `/tps`\n\n"
        "**🌍  World**\n"
        "`/time` • `/weather`\n\n"
        "**👤  Players**\n"
        "`/player` • `/operator` • `/deoperator` • `/give` • `/whitelist`\n\n"
        "**🔌  Plugins**\n"
        "`/plugins`\n\n"
        "**ℹ️  Other**\n"
        "`/about` • `/help`\n\n"
        f"-# Server version: **{server.version}** • RAM: {server.min_ram}M–{server.max_ram}M"
    )
    em = discord.Embed(title="📖  PyPurpur — Commands", description=desc, colour=PURPUR)
    await interaction.response.send_message(embed=em, ephemeral=EPHEMERAL)


# ── /about ────────────────────────────────────────────────────────────────────

@tree.command(name="about", description="About PyPurpur.")
async def cmd_about(interaction: discord.Interaction) -> None:
    if not await _check(interaction): return

    desc = (
        "Open-source Minecraft server control bridge for Discord.\n"
        "Built entirely in Python.\n\n"
        f"{EMO['mixedstudios']}  **Founder / Project Lead** — Mixed Studios\n"
        f"{EMO['claude']}  **AI Development Assistance** — Claude (Anthropic)\n"
        f"{EMO['mojang']}  **Game** — Minecraft Java Edition by Mojang Studios\n\n"
        "**Tech Stack**\n"
        "Python 3.11+ • discord.py 2.5 • Purpur Server • Modrinth API\n\n"
        "**Links**\n"
        "[GitHub](https://github.com/MixedStudios/pypurpur) • "
        "[Purpur](https://purpurmc.org) • "
        "[Modrinth](https://modrinth.com) • "
        "[Adoptium](https://adoptium.net)\n\n"
        "-# PyPurpur is not affiliated with Mojang Studios or Microsoft."
    )
    em = discord.Embed(title="🟣  PyPurpur", description=desc, colour=PURPUR)
    await interaction.response.send_message(embed=em, ephemeral=EPHEMERAL)


# ── /start ────────────────────────────────────────────────────────────────────

class VersionSelect(discord.ui.Select):
    def __init__(self) -> None:
        latest = PURPUR_VERSIONS[-1]
        options = [
            discord.SelectOption(
                label=f"{'⭐ ' if v == latest else ''}{v}",
                value=v,
                description="Latest stable" if v == latest else None,
                default=(v == latest),
            )
            for v in reversed(PURPUR_VERSIONS)  # newest at top
        ]
        super().__init__(
            placeholder="Choose a Purpur version…",
            min_values=1, max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        # Legacy flow: disable select, edit original embed to show starting state
        if not is_authorized(interaction.user.id):
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"{EMO['access_denied']}  **Access Denied.**", colour=RED
                ), ephemeral=True,
            )
            return

        ver = self.values[0]
        # disable this select so user can't pick again
        self.disabled = True
        # edit original message to show starting info
        start_em = discord.Embed(
            title="🚀  Starting Server…",
            description=f"Version: **{ver}** — downloading Purpur + plugins…",
            colour=ORANGE,
        )
        await interaction.response.edit_message(embed=start_em, view=self.view)

        server.version = ver
        _set_config("MC_VERSION", ver)

        try:
            msgs = await server.start()
        except Exception as exc:
            body = f"```\n{exc}\n```"
            # Replace the message with an error embed and remove the view
            await interaction.edit_original_response(embed=discord.Embed(title="💥  Failed to Start", description=body, colour=RED), view=None)
            return

        body = "\n".join(msgs)
        if len(body) > 3800: body = "…" + body[-3800:]
        done_em = discord.Embed(
            title=f"✅  Purpur {ver} Starting",
            description=f"{body}\n\n-# Server may take 30–60 s to fully load.",
            colour=GREEN,
        )
        await interaction.edit_original_response(embed=done_em, view=None)


@tree.command(name="start", description="Start the Minecraft server.")
async def cmd_start(interaction: discord.Interaction) -> None:
    if not await _check(interaction): return
    if server.is_running:
        await _err(interaction, "Server is already running!"); return

    if not PURPUR_JAR.exists():
        # Build an embed message with a View containing VersionSelect
        em = discord.Embed(
            title="🟣  Choose a Minecraft Version",
            description="Select the Purpur version to install. ⭐ = latest stable.",
            colour=PURPUR,
        )
        v = discord.ui.View(timeout=120)
        v.add_item(VersionSelect())
        await interaction.response.send_message(embed=em, view=v, ephemeral=EPHEMERAL)
        return

    await interaction.response.defer(thinking=True)
    try:
        msgs = await server.start()
    except Exception as exc:
        await interaction.followup.send(
            embed=discord.Embed(title="💥  Failed", description=f"```\n{exc}\n```", colour=RED)
        )
        return

    body = "\n".join(msgs)
    if len(body) > 3800: body = "…" + body[-3800:]
    em = discord.Embed(
        title=f"🚀  Server Starting — Purpur {server.version}",
        description=f"{body}\n\n-# 30–60 s to finish loading.",
        colour=GREEN,
    )
    await interaction.followup.send(embed=em)


# ── /stop ─────────────────────────────────────────────────────────────────────

@tree.command(name="stop", description="Stop the Minecraft server gracefully.")
async def cmd_stop(interaction: discord.Interaction) -> None:
    if not await _check(interaction): return
    if await _need_running(interaction): return
    ok = await server.stop()
    if ok: await _ok(interaction, "Stop command sent — server shutting down.")
    else:  await _err(interaction, "Failed to send stop command.")


# ── /restart ──────────────────────────────────────────────────────────────────

@tree.command(name="restart", description="Restart the Minecraft server.")
async def cmd_restart(interaction: discord.Interaction) -> None:
    if not await _check(interaction): return
    if await _need_running(interaction): return
    ok = await server.restart()
    if ok: await _ok(interaction, "Restart command sent.")
    else:  await _err(interaction, "Failed to send restart command.")


# ── /reinstall ────────────────────────────────────────────────────────────────

class ReinstallConfirmView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=30)

    @discord.ui.button(label="Yes — wipe & reinstall", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not is_authorized(interaction.user.id):
            await interaction.response.send_message(
                embed=discord.Embed(description=f"{EMO['access_denied']}  **Access Denied.**", colour=RED),
                ephemeral=True,
            ); return
        self.stop()
        # show an intermediate "reinstalling" embed
        await interaction.response.edit_message(embed=discord.Embed(title="🔄  Reinstalling…", description="Wiping server directory…", colour=ORANGE), view=None)

        msgs = await server.reinstall()
        body = "\n".join(msgs)
        if len(body) > 3800: body = "…" + body[-3800:]

        em = discord.Embed(title="✅  Reinstall Complete", description=f"{body}", colour=GREEN)
        await interaction.followup.send(embed=em, ephemeral=True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(embed=discord.Embed(title="❌  Cancelled", description="Re-install was cancelled.", colour=GREY), view=None)


@tree.command(name="reinstall", description="Wipe the server folder and reinstall from scratch.")
async def cmd_reinstall(interaction: discord.Interaction) -> None:
    if not await _check(interaction): return
    em = discord.Embed(
        title="⚠️  Reinstall Confirmation",
        description=(
            "This will **permanently delete** the `server/` directory:\n"
            "• World data\n• Plugins\n• All configs\n\n**This cannot be undone.**"
        ),
        colour=RED,
    )
    await interaction.response.send_message(embed=em, view=ReinstallConfirmView(), ephemeral=True)


# ── /pause ───────────────────────────────────────────────────────────────────

@tree.command(name="pause", description="Toggle /tick freeze — pauses all game logic.")
async def cmd_pause(interaction: discord.Interaction) -> None:
    if not await _check(interaction): return
    if await _need_running(interaction): return
    if server.tick_frozen:
        await server.send_command("tick unfreeze")
        server.tick_frozen = False
        msg, col = "▶️  Server **unpaused** (`/tick unfreeze` sent).", GREEN
    else:
        await server.send_command("tick freeze")
        server.tick_frozen = True
        msg, col = "⏸️  Server **paused** (`/tick freeze` sent).", ORANGE
    await interaction.response.send_message(
        embed=discord.Embed(description=msg, colour=col), ephemeral=EPHEMERAL
    )


# ── /run ──────────────────────────────────────────────────────────────────────

@tree.command(name="run", description="Execute any command in the server console.")
@app_commands.describe(command="Console command (without leading /)")
async def cmd_run(interaction: discord.Interaction, command: str) -> None:
    if not await _check(interaction): return
    if await _need_running(interaction): return
    await interaction.response.defer(thinking=True)
    await server.send_command(command)
    await asyncio.sleep(1.5)
    lines = server.recent_logs(15)
    body = "\n".join(lines) or "— no output —"
    if len(body) > 3900: body = "…" + body[-3900:]
    await interaction.followup.send(
        embed=discord.Embed(
            title=f"🖥️  `/{command}`",
            description=f"```ansi\n{body}\n```",
            colour=BLUE,
        ).set_footer(text="Last 15 log lines"),
        ephemeral=EPHEMERAL,
    )


# ── /chat ─────────────────────────────────────────────────────────────────────

@tree.command(name="chat", description="Show the latest ingame chat log (ANSI coloured).")
async def cmd_chat(interaction: discord.Interaction) -> None:
    if not await _check(interaction): return
    if await _need_running(interaction): return
    body = _fmt_chat(server.recent_chat(20))
    if len(body) > 3900: body = "…" + body[-3900:]
    await interaction.response.send_message(
        embed=discord.Embed(
            title="💬  Latest Chat Log",
            description=f"```ansi\n{body}\n```",
            colour=PURPUR,
        ).set_footer(text="Up to 20 most recent entries"),
        ephemeral=EPHEMERAL,
    )


# ── /say ──────────────────────────────────────────────────────────────────────

@tree.command(name="say", description="Broadcast a styled message to all players.")
@app_commands.describe(message="The message to broadcast ingame")
async def cmd_say(interaction: discord.Interaction, message: str) -> None:
    if not await _check(interaction): return
    if await _need_running(interaction): return
    safe = message.replace('"', '\\"')
    ok = await server.send_command(
        f'tellraw @a {{"text":"<×> {safe}","italic":true,"color":"green"}}'
    )
    if ok:
        await interaction.response.send_message(
            embed=discord.Embed(description=f"📣  Sent:\n> *{message}*", colour=GREEN),
            ephemeral=EPHEMERAL,
        )
    else:
        await _err(interaction, "Failed to send message.")


# ── /broadcast ───────────────────────────────────────────────────────────────

_MC_COLOURS = ["gold","yellow","green","aqua","red","light_purple","white","gray","dark_gray","dark_blue"]

class BroadcastColourSelect(discord.ui.Select):
    def __init__(self, message: str) -> None:
        self._msg = message
        super().__init__(
            placeholder="Pick a colour…",
            options=[discord.SelectOption(label=c.replace("_"," ").title(), value=c) for c in _MC_COLOURS],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        colour = self.values[0]
        safe = self._msg.replace('"', '\\"')
        ok = await server.send_command(
            f'tellraw @a {{"text":"[Broadcast] {safe}","bold":true,"color":"{colour}"}}'
        )
        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"📢  Broadcast sent in **{colour}**:\n> {self._msg}",
                colour=GREEN if ok else RED,
            ), ephemeral=True,
        )

class BroadcastView(discord.ui.View):
    def __init__(self, message: str) -> None:
        super().__init__(timeout=60)
        # In legacy mode, adding a Select at top-level is valid (we use embed+view)
        self.add_item(BroadcastColourSelect(message))


@tree.command(name="broadcast", description="Send a bold coloured broadcast to all players.")
@app_commands.describe(message="The message to broadcast")
async def cmd_broadcast(interaction: discord.Interaction, message: str) -> None:
    if not await _check(interaction): return
    if await _need_running(interaction): return
    em = discord.Embed(
        description=f"📢  Choose a colour for:\n> *{message}*",
        colour=PURPUR,
    )
    await interaction.response.send_message(embed=em, view=BroadcastView(message), ephemeral=True)


# ── /stats ────────────────────────────────────────────────────────────────────

def _stats_embed_and_view() -> tuple[discord.Embed, discord.ui.View]:
    status  = "🟢  **Online**"  if server.is_running else "🔴  **Offline**"
    frozen  = "⏸️  Frozen"       if server.tick_frozen else "▶️  Running"
    plugs   = server.plugin_index.all_slugs()
    plug_str = ", ".join(f"`{s}`" for s in plugs) if plugs else "*None installed*"
    logs     = "\n".join(server.recent_logs(5)) or "— no output —"
    if len(logs) > 600: logs = "…" + logs[-600:]

    desc = (
        f"**Status:** {status}\n"
        f"**Version:** `{server.version}`\n"
        f"**Tick:** {frozen}\n"
        f"**RAM:** `{server.min_ram}M – {server.max_ram}M`\n"
        f"**Auto-Update:** {'✅' if server.auto_update else '❌'}\n\n"
        f"**🔌  Plugins**\n{plug_str}\n\n"
        f"**🖥️  Recent Log**\n```ansi\n{logs}\n```"
    )
    em = discord.Embed(title="📊  Server Status", description=desc, colour=PURPUR if server.is_running else GREY)

    class StatsView(discord.ui.View):
        def __init__(self) -> None:
            super().__init__(timeout=300)

        @discord.ui.button(label="🔄  Refresh", style=discord.ButtonStyle.secondary)
        async def refresh(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
            if not is_authorized(interaction.user.id):
                await interaction.response.send_message(
                    embed=discord.Embed(description=f"{EMO['access_denied']}  **Access Denied.**", colour=RED),
                    ephemeral=True,
                ); return
            # update the embed content by editing with a fresh embed and same view
            new_em, _ = _stats_embed_and_view()
            await interaction.response.edit_message(embed=new_em, view=self)

    return em, StatsView()

@tree.command(name="stats", description="Interactive server status panel.")
async def cmd_stats(interaction: discord.Interaction) -> None:
    if not await _check(interaction): return
    em, view = _stats_embed_and_view()
    await interaction.response.send_message(embed=em, view=view, ephemeral=EPHEMERAL)


# ── /online ───────────────────────────────────────────────────────────────────

@tree.command(name="online", description="Show currently online players.")
async def cmd_online(interaction: discord.Interaction) -> None:
    if not await _check(interaction): return
    if await _need_running(interaction): return
    await interaction.response.defer(thinking=True)
    await server.send_command("list")
    await asyncio.sleep(1.2)
    lines = server.recent_logs(5)
    list_line = next((l for l in reversed(lines) if "There are" in l), None)
    desc = list_line or "Could not retrieve player list from log."
    await interaction.followup.send(
        embed=discord.Embed(title="👥  Online Players", description=desc, colour=CYAN),
        ephemeral=EPHEMERAL,
    )


# ── /seed ─────────────────────────────────────────────────────────────────────

@tree.command(name="seed", description="Show the current world seed.")
async def cmd_seed(interaction: discord.Interaction) -> None:
    if not await _check(interaction): return
    if await _need_running(interaction): return
    await interaction.response.defer(thinking=True)
    await server.send_command("seed")
    await asyncio.sleep(1.2)
    lines = server.recent_logs(5)
    seed_line = next((l for l in reversed(lines) if "Seed:" in l), None)
    desc = seed_line or "Could not read seed from log."
    await interaction.followup.send(
        embed=discord.Embed(title="🌱  World Seed", description=f"`{desc}`", colour=GREEN),
        ephemeral=EPHEMERAL,
    )


# ── /tps ──────────────────────────────────────────────────────────────────────

@tree.command(name="tps", description="Show current server TPS (via /tps).")
async def cmd_tps(interaction: discord.Interaction) -> None:
    if not await _check(interaction): return
    if await _need_running(interaction): return
    await interaction.response.defer(thinking=True)
    await server.send_command("tps")
    await asyncio.sleep(1.2)
    lines = server.recent_logs(6)
    tps_line = next((l for l in reversed(lines) if "TPS" in l), None)
    desc = tps_line or "Could not read TPS from log."
    colour = GREEN if "20.0" in desc else (ORANGE if "15" in desc else RED)
    await interaction.followup.send(
        embed=discord.Embed(title="⚡  Server TPS", description=f"```\n{desc}\n```", colour=colour),
        ephemeral=EPHEMERAL,
    )


# ── /time ─────────────────────────────────────────────────────────────────────

class TimeSelect(discord.ui.Select):
    _TIMES = {
        "☀️  Day":      "1000",
        "🌇  Noon":     "6000",
        "🌆  Sunset":   "12000",
        "🌙  Night":    "13000",
        "🌌  Midnight": "18000",
        "🌅  Sunrise":  "23000",
    }

    def __init__(self) -> None:
        super().__init__(
            placeholder="Select time of day…",
            options=[discord.SelectOption(label=k, value=v) for k, v in self._TIMES.items()],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        label = next(k for k, v in self._TIMES.items() if v == self.values[0])
        ok = await server.send_command(f"time set {self.values[0]}")
        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"{label}  Time set to `{self.values[0]}` ticks.",
                colour=GREEN if ok else RED,
            ), ephemeral=EPHEMERAL,
        )


@tree.command(name="time", description="Set the server time of day.")
async def cmd_time(interaction: discord.Interaction) -> None:
    if not await _check(interaction): return
    if await _need_running(interaction): return
    v = discord.ui.View(); v.add_item(TimeSelect())
    await interaction.response.send_message(embed=discord.Embed(description="🕐  Choose a time of day:", colour=PURPUR), view=v, ephemeral=True)


# ── /weather ──────────────────────────────────────────────────────────────────

class WeatherSelect(discord.ui.Select):
    def __init__(self) -> None:
        super().__init__(
            placeholder="Select weather…",
            options=[
                discord.SelectOption(label="☀️  Clear",   value="clear"),
                discord.SelectOption(label="🌧️  Rain",    value="rain"),
                discord.SelectOption(label="⛈️  Thunder", value="thunder"),
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        ok = await server.send_command(f"weather {self.values[0]}")
        labels = {"clear": "☀️  Clear", "rain": "🌧️  Rain", "thunder": "⛈️  Thunder"}
        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"{labels[self.values[0]]}  Weather set to `{self.values[0]}`.",
                colour=GREEN if ok else RED,
            ), ephemeral=EPHEMERAL,
        )


@tree.command(name="weather", description="Set the server weather.")
async def cmd_weather(interaction: discord.Interaction) -> None:
    if not await _check(interaction): return
    if await _need_running(interaction): return
    v = discord.ui.View(); v.add_item(WeatherSelect())
    await interaction.response.send_message(embed=discord.Embed(description="🌤️  Choose weather:", colour=PURPUR), view=v, ephemeral=True)


# ── /give ─────────────────────────────────────────────────────────────────────

@tree.command(name="give", description="Give an item to a player.")
@app_commands.describe(player="Target player username", item="Item ID (e.g. diamond)", amount="Amount (1–64)")
async def cmd_give(
    interaction: discord.Interaction,
    player: str, item: str, amount: int = 1,
) -> None:
    if not await _check(interaction): return
    if await _need_running(interaction): return
    amount = max(1, min(amount, 64))
    ok = await server.send_command(f"give {player} {item} {amount}")
    if ok:
        await _ok(interaction, f"Gave **{amount}x {item}** to **{player}**.")
    else:
        await _err(interaction, "Failed to send give command.")


# ── /operator ─────────────────────────────────────────────────────────────────

@tree.command(name="operator", description="Grant operator status to a player.")
@app_commands.describe(username="Minecraft username")
async def cmd_op(interaction: discord.Interaction, username: str) -> None:
    if not await _check(interaction): return
    if await _need_running(interaction): return
    ok = await server.send_command(f"op {username}")
    if ok: await _ok(interaction, f"Granted operator to **{username}**.")
    else:  await _err(interaction, "Failed to send op command.")


# ── /deoperator ───────────────────────────────────────────────────────────────

@tree.command(name="deoperator", description="Revoke operator status from a player.")
@app_commands.describe(username="Minecraft username")
async def cmd_deop(interaction: discord.Interaction, username: str) -> None:
    if not await _check(interaction): return
    if await _need_running(interaction): return
    ok = await server.send_command(f"deop {username}")
    if ok: await _ok(interaction, f"Revoked operator from **{username}**.")
    else:  await _err(interaction, "Failed to send deop command.")


# ── /whitelist ────────────────────────────────────────────────────────────────

class MCWhitelistModal(discord.ui.Modal, title="Minecraft Whitelist"):
    username = discord.ui.TextInput(
        label="Player Username",
        placeholder="e.g. Steve",
        min_length=1, max_length=32,
    )
    action = discord.ui.TextInput(
        label="Action",
        placeholder="add  or  remove",
        min_length=3, max_length=6,
        default="add",
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        act = self.action.value.strip().lower()
        if act not in ("add", "remove"):
            await interaction.response.send_message(
                embed=discord.Embed(description='❌  Action must be `add` or `remove`.', colour=RED),
                ephemeral=True,
            ); return
        ok = await server.send_command(f"whitelist {act} {self.username.value}")
        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"✅  `/whitelist {act} {self.username.value}` sent." if ok
                            else "❌  Server not running.",
                colour=GREEN if ok else RED,
            ), ephemeral=EPHEMERAL,
        )


class DiscordWhitelistModal(discord.ui.Modal, title="Discord Whitelist"):
    user_id_input = discord.ui.TextInput(
        label="Discord User ID",
        placeholder="e.g. 123456789012345678",
        min_length=17, max_length=20,
    )
    action = discord.ui.TextInput(
        label="Action",
        placeholder="add  or  remove",
        min_length=3, max_length=6,
        default="add",
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        act = self.action.value.strip().lower()
        if act not in ("add", "remove"):
            await interaction.response.send_message(
                embed=discord.Embed(description='❌  Action must be `add` or `remove`.', colour=RED),
                ephemeral=True,
            ); return
        try:
            uid = int(self.user_id_input.value.strip())
        except ValueError:
            await interaction.response.send_message(
                embed=discord.Embed(description='❌  Invalid Discord User ID.', colour=RED),
                ephemeral=True,
            ); return

        wl = _load_whitelist()
        if act == "add":
            if uid not in wl:
                wl.append(uid)
            _save_whitelist(wl)
            msg = f"✅  <@{uid}> added to the PyPurpur whitelist."
        else:
            if uid in wl:
                wl.remove(uid)
            _save_whitelist(wl)
            msg = f"🗑️  <@{uid}> removed from the PyPurpur whitelist."

        await interaction.response.send_message(
            embed=discord.Embed(description=msg, colour=GREEN), ephemeral=EPHEMERAL
        )


class WhitelistTypeSelect(discord.ui.Select):
    def __init__(self) -> None:
        super().__init__(
            placeholder="Choose whitelist type…",
            options=[
                discord.SelectOption(
                    label="🎮  Minecraft Player",
                    value="minecraft",
                    description="Add/remove a player from the server whitelist",
                ),
                discord.SelectOption(
                    label="💬  Discord User",
                    value="discord",
                    description="Allow/revoke a Discord user's access to bot commands",
                ),
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.values[0] == "minecraft":
            await interaction.response.send_modal(MCWhitelistModal())
        else:
            await interaction.response.send_modal(DiscordWhitelistModal())


@tree.command(name="whitelist", description="Manage Minecraft or Discord bot whitelist.")
async def cmd_whitelist(interaction: discord.Interaction) -> None:
    if not await _check(interaction): return
    v = discord.ui.View(); v.add_item(WhitelistTypeSelect())
    em = discord.Embed(
        title="📋  Whitelist Manager",
        description=(
            "**🎮  Minecraft** — add/remove players from the server's `/whitelist`\n"
            "**💬  Discord** — grant/revoke access to PyPurpur bot commands"
        ),
        colour=PURPUR,
    )
    await interaction.response.send_message(embed=em, view=v, ephemeral=True)


# ── /player ───────────────────────────────────────────────────────────────────

class GamemodeSelect(discord.ui.Select):
    def __init__(self, username: str) -> None:
        self.username = username
        super().__init__(
            placeholder="Select gamemode…",
            options=[
                discord.SelectOption(label="Survival",  value="survival",  emoji=EMO["survival"],  description="Normal gameplay"),
                discord.SelectOption(label="Creative",  value="creative",  emoji=EMO["creative"],  description="Unlimited resources, flight"),
                discord.SelectOption(label="Adventure", value="adventure", emoji=EMO["adventure"], description="Limited block breaking"),
                discord.SelectOption(label="Spectator", value="spectator", emoji=EMO["spectator"], description="Invisible observer"),
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        gm = self.values[0]
        await server.send_command(f"gamemode {gm} {self.username}")
        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"{EMO[gm]}  Set **{self.username}** to `{gm}`.",
                colour=GREEN,
            ), ephemeral=True,
        )


class PlayerControlView(discord.ui.View):
    """
    Legacy embed + view player panel.
    """

    def __init__(self, username: str) -> None:
        super().__init__(timeout=300)
        self.username = username

        # Health & Food buttons
        self.add_item(self._btn("Heal",   discord.ButtonStyle.success,   "heal",   self._heal))
        self.add_item(self._btn("Damage", discord.ButtonStyle.danger,    "damage", self._damage))
        self.add_item(self._btn("Feed",   discord.ButtonStyle.success,   "feed",   self._feed))
        self.add_item(self._btn("Starve", discord.ButtonStyle.secondary, "starve", self._starve))

        # Kill
        self.add_item(self._btn("Kill", discord.ButtonStyle.danger, "kill", self._kill))

        # Moderation
        self.add_item(self._btn("Kick", discord.ButtonStyle.secondary, "kick", self._kick))
        self.add_item(self._btn("Ban",  discord.ButtonStyle.danger,    "ban",  self._ban))

        # Gamemode select at top-level (legacy view — allowed with embed)
        self.add_item(GamemodeSelect(username))

    def _btn(self, label, style, emo_key, cb):
        b = discord.ui.Button(label=label, style=style, emoji=EMO[emo_key])
        b.callback = cb
        return b

    # ── Action callbacks ──────────────────────────────────────────────────────

    async def _heal(self, i):
        await server.send_command(f"effect give {self.username} instant_health 1 0 true")
        await i.response.send_message(embed=discord.Embed(description=f"{EMO['heal']}  Healed **{self.username}** (+2 ❤️).", colour=GREEN), ephemeral=True)

    async def _damage(self, i):
        await server.send_command(f"damage {self.username} 2")
        await i.response.send_message(embed=discord.Embed(description=f"{EMO['damage']}  Damaged **{self.username}** (−1 ❤️).", colour=RED), ephemeral=True)

    async def _feed(self, i):
        await server.send_command(f"effect give {self.username} saturation 3 1 true")
        await i.response.send_message(embed=discord.Embed(description=f"{EMO['feed']}  Fed **{self.username}** (+1 🍗).", colour=GREEN), ephemeral=True)

    async def _starve(self, i):
        await server.send_command(f"effect give {self.username} hunger 10 5 true")
        await i.response.send_message(embed=discord.Embed(description=f"{EMO['starve']}  Starved **{self.username}** (−1 🍗).", colour=ORANGE), ephemeral=True)

    async def _kill(self, i):
        await server.send_command(f"kill {self.username}")
        await i.response.send_message(embed=discord.Embed(description=f"{EMO['kill']}  Killed **{self.username}**.", colour=RED), ephemeral=True)

    async def _kick(self, i):
        await server.send_command(f"kick {self.username} Kicked by operator via PyPurpur.")
        await i.response.send_message(embed=discord.Embed(description=f"{EMO['kick']}  Kicked **{self.username}**.", colour=ORANGE), ephemeral=True)

    async def _ban(self, i):
        await server.send_command(f"ban {self.username} Banned by operator via PyPurpur.")
        await i.response.send_message(embed=discord.Embed(description=f"{EMO['ban']}  Banned **{self.username}**.", colour=RED), ephemeral=True)


@tree.command(name="player", description="Open the player control panel.")
@app_commands.describe(username="Minecraft username of the target player")
async def cmd_player(interaction: discord.Interaction, username: str) -> None:
    if not await _check(interaction): return
    if await _need_running(interaction): return

    # Build an embed for the player panel
    em = discord.Embed(
        title=f"{EMO['survival']}  {username} — Player Control Panel",
        description="-# Control player: health, gamemode, moderation.",
        colour=PURPUR,
    )
    em.set_thumbnail(url=f"https://mc-heads.net/avatar/{username}/64")
    view = PlayerControlView(username)
    await interaction.response.send_message(embed=em, view=view, flags=None, ephemeral=EPHEMERAL)


# ── /plugins ──────────────────────────────────────────────────────────────────

class PluginActionSelect(discord.ui.Select):
    """Install / uninstall dropdown for a single result page."""

    def __init__(self, results: list) -> None:
        self._results = results
        options = []
        for proj in results:
            installed = server.plugin_index.get(proj.slug) is not None
            options.append(discord.SelectOption(
                label=f"{'✅ Uninstall' if installed else '⬇️ Install'}: {proj.title}"[:100],
                value=proj.slug,
                description=proj.description[:50] if proj.description else None,
            ))
        super().__init__(placeholder="Install or uninstall a plugin…", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await _check(interaction): return
        slug    = self.values[0]
        proj    = next((p for p in self._results if p.slug == slug), None)
        if not proj:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌  Plugin not found.", colour=RED), ephemeral=True
            ); return

        installed = server.plugin_index.get(slug) is not None
        await interaction.response.defer(thinking=True)

        if installed:
            msg = await server.uninstall_plugin(slug)
            await interaction.followup.send(
                embed=discord.Embed(description=msg, colour=ORANGE), ephemeral=True
            )
        else:
            import aiohttp as _ah
            msgs: list[str] = []
            try:
                ver = await modrinth.get_latest_version(proj.id, server.version)
                if ver is None:
                    await interaction.followup.send(
                        embed=discord.Embed(
                            description=f"❌  No compatible version of **{proj.title}** for MC `{server.version}`.",
                            colour=RED,
                        ), ephemeral=True
                    ); return
                async with _ah.ClientSession() as s:
                    PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
                    await server.install_plugin(proj, ver, s, msgs)
                await interaction.followup.send(
                    embed=discord.Embed(
                        title=f"✅  Installed `{proj.title}`",
                        description="\n".join(msgs),
                        colour=GREEN,
                    ), ephemeral=True
                )
            except Exception as exc:
                await interaction.followup.send(
                    embed=discord.Embed(description=f"❌  Install failed: {exc}", colour=RED),
                    ephemeral=True,
                )


class MarketplaceView(discord.ui.View):
    PAGE = 5

    def __init__(self, query: str, results: list, total: int, page: int) -> None:
        super().__init__(timeout=300)
        self.query   = query
        self.results = results
        self.total   = total
        self.page    = page
        self._rebuild()

    def _rebuild(self) -> None:
        self.clear_items()
        if self.results:
            self.add_item(PluginActionSelect(self.results))
        max_p = max(0, (self.total - 1) // self.PAGE)
        prev = discord.ui.Button(label="◀ Prev", style=discord.ButtonStyle.secondary, disabled=self.page == 0)
        nxt  = discord.ui.Button(label="Next ▶", style=discord.ButtonStyle.secondary, disabled=self.page >= max_p)
        prev.callback = self._prev
        nxt.callback  = self._next
        # legacy embed+view flow: top-level buttons are OK
        self.add_item(prev); self.add_item(nxt)

    async def _prev(self, i): await self._go(i, self.page - 1)
    async def _next(self, i): await self._go(i, self.page + 1)

    async def _go(self, interaction: discord.Interaction, new_page: int) -> None:
        await interaction.response.defer()
        results, total = await _do_search(self.query, new_page)
        self.results = results; self.total = total; self.page = new_page
        self._rebuild()
        await interaction.edit_original_response(
            embed=_market_embed(self.query, results, total, new_page), view=self
        )


async def _do_search(query: str, page: int) -> tuple[list, int]:
    offset  = page * MarketplaceView.PAGE
    results = await modrinth.search(query, server.version, limit=MarketplaceView.PAGE, offset=offset)
    total   = offset + len(results) + (MarketplaceView.PAGE if len(results) == MarketplaceView.PAGE else 0)
    return results, total


def _market_embed(query: str, results: list, total: int, page: int) -> discord.Embed:
    em = discord.Embed(
        title=f"🔌  Plugin Marketplace — MC {server.version}",
        description=f"**Search:** {query or 'trending'}\n-# Purpur / Paper / Spigot / Bukkit compatible\n",
        colour=PURPUR,
    )
    if not results:
        em.description += "\n*No plugins found.*"; return em
    for proj in results:
        inst = server.plugin_index.get(proj.slug) is not None
        cats = " • ".join(proj.categories[:3])
        em.add_field(
            name=f"{'✅ ' if inst else '🔌 '}{proj.title}",
            value=(
                f"{proj.description[:100]}{'…' if len(proj.description) > 100 else ''}\n"
                f"`{cats}` • ⬇️ {proj.downloads:,} • [Modrinth]({proj.page_url})"
            ),
            inline=False,
        )
    max_p = max(0, (total - 1) // MarketplaceView.PAGE)
    em.set_footer(text=f"Page {page + 1} / {max_p + 1}")
    return em


@tree.command(name="plugins", description="Browse & manage plugins from Modrinth.")
@app_commands.describe(search="Plugin name or keyword (blank = trending)")
async def cmd_plugins(interaction: discord.Interaction, search: str = "") -> None:
    if not await _check(interaction): return
    await interaction.response.defer(thinking=True)
    try:
        results, total = await _do_search(search, 0)
    except Exception as exc:
        await interaction.followup.send(
            embed=discord.Embed(description=f"❌  Modrinth error: {exc}", colour=RED)
        ); return
    await interaction.followup.send(
        embed=_market_embed(search, results, total, 0),
        view=MarketplaceView(search, results, total, 0),
        ephemeral=EPHEMERAL,
    )


# ═════════════════════════════════════════════════════════════════════════════=
#  Entry point
# ═════════════════════════════════════════════════════════════════════════════=

if __name__ == "__main__":
    bot.run(TOKEN)