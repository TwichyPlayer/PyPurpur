from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
from collections import deque
from pathlib import Path

import aiofiles
import aiohttp

from java_installer import get_java_executable, install_java, java_is_ready
from modrinth import modrinth

log = logging.getLogger("pypurpur.server")

SERVER_DIR = Path("server")
PLUGINS_DIR = SERVER_DIR / "plugins"
INDEX_FILE = PLUGINS_DIR / ".pypurpur_index.json"
PURPUR_JAR = SERVER_DIR / "purpur.jar"
EULA_FILE = SERVER_DIR / "eula.txt"
PROPS_FILE = SERVER_DIR / "server.properties"

_CHAT_RE = re.compile(r"<(\w+)> (.+)")
_JOIN_RE = re.compile(r"(\w+) joined the game")
_LEAVE_RE = re.compile(r"(\w+) left the game")
_ANSI_RE = re.compile(r"\x1b\\[[0-9;]*m")

_DEFAULT_PROPS = """\
online-mode=false
view-distance=6
simulation-distance=4
max-players=20
motd=PyPurpur | Powered by Python
"""

# ───────────────────────── Plugin index ─────────────────────────

class PluginIndex:
    def __init__(self) -> None:
        self._data: dict[str, dict] = {}
        if INDEX_FILE.exists():
            try:
                self._data = json.loads(INDEX_FILE.read_text())
            except Exception:
                pass

    def save(self) -> None:
        PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
        INDEX_FILE.write_text(json.dumps(self._data, indent=2))

    def add(self, slug: str, pid: str, vid: str, file: str) -> None:
        self._data[slug] = {
            "project_id": pid,
            "version_id": vid,
            "filename": file,
        }
        self.save()

    def get(self, slug: str) -> dict | None:
        return self._data.get(slug)


# ───────────────────────── ServerManager ─────────────────────────

class ServerManager:
    def __init__(
    self,
    version: str,
    min_ram: int,
    max_ram: int,
    auto_update: bool = False,
    update_channel_id: int | None = None,
) -> None:
    self.version = version
    self.min_ram = min_ram
    self.max_ram = max_ram
    self.auto_update = auto_update
    self.update_channel_id = update_channel_id
    self.version = version
    self.min_ram = min_ram
    self.max_ram = max_ram

        self.process: asyncio.subprocess.Process | None = None
        self.logs: deque[str] = deque(maxlen=300)

        self.plugins = PluginIndex()

    @property
    def is_running(self) -> bool:
        return self.process is not None and self.process.returncode is None

    def _jvm_cmd(self) -> list[str]:
        return [
            get_java_executable(),
            f"-Xms{self.min_ram}M",
            f"-Xmx{self.max_ram}M",
            "-jar",
            "purpur.jar",
            "--nogui",
        ]

    async def _download(self, url: str, dest: Path, session: aiohttp.ClientSession):
        async with session.get(url) as r:
            r.raise_for_status()
            async with aiofiles.open(dest, "wb") as f:
                async for chunk in r.content.iter_chunked(8192):
                    await f.write(chunk)

    async def setup(self) -> list[str]:
        msgs: list[str] = []

        SERVER_DIR.mkdir(exist_ok=True)
        PLUGINS_DIR.mkdir(exist_ok=True)

        if not java_is_ready():
            await install_java(msgs)

        async with aiohttp.ClientSession() as session:
            if not PURPUR_JAR.exists():
                await self._download(
                    f"https://api.purpurmc.org/v2/purpur/{self.version}/latest/download",
                    PURPUR_JAR,
                    session,
                )
                msgs.append("✅ Purpur downloaded.")

        if not EULA_FILE.exists():
            EULA_FILE.write_text("eula=true\n")

        if not PROPS_FILE.exists():
            PROPS_FILE.write_text(_DEFAULT_PROPS)

        return msgs

    async def start(self) -> list[str]:
        if self.is_running:
            return ["Server already running"]

        msgs = await self.setup()

        self.process = await asyncio.create_subprocess_exec(
            *self._jvm_cmd(),
            cwd=SERVER_DIR,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        asyncio.create_task(self._read_logs())
        msgs.append("🚀 Server started.")
        return msgs

    async def _read_logs(self):
        assert self.process and self.process.stdout
        while True:
            line = await self.process.stdout.readline()
            if not line:
                break
            clean = _ANSI_RE.sub("", line.decode(errors="ignore")).strip()
            self.logs.append(clean)