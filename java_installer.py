from __future__ import annotations

import logging
import os
import platform
import shutil
import struct
import subprocess
import tarfile
import zipfile
from pathlib import Path

import aiofiles
import aiohttp

log = logging.getLogger("pypurpur.java")

TEMURIN_VER = 21
JDK_DIR = Path("jdk")


# ───────────────────────── Platform helpers ─────────────────────────

def _os_name() -> str:
    s = platform.system().lower()
    if s == "darwin":
        return "mac"
    if s == "windows":
        return "windows"
    return "linux"


def _arch() -> str:
    m = platform.machine().lower()
    if m in ("aarch64", "arm64"):
        return "aarch64"
    if struct.calcsize("P") == 8:
        return "x64"
    raise RuntimeError("32-bit systems are not supported by Java 21.")


def _java_bin_name() -> str:
    return "java.exe" if _os_name() == "windows" else "java"


# ───────────────────────── Java detection ─────────────────────────

def _java_version(java_path: str) -> int | None:
    try:
        r = subprocess.run(
            [java_path, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = r.stderr or r.stdout
        for token in output.replace('"', "").split():
            if token[0].isdigit():
                major = token.split(".")[0]
                if major == "1":
                    return int(token.split(".")[1])
                return int(major)
    except Exception:
        pass
    return None


def get_java_executable() -> str:
    java_bin = _java_bin_name()
    candidates: list[str] = []

    bundled = JDK_DIR / "bin" / java_bin
    if bundled.exists():
        candidates.append(str(bundled))

    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        p = Path(java_home) / "bin" / java_bin
        if p.exists():
            candidates.append(str(p))

    which = shutil.which("java")
    if which:
        candidates.append(which)

    for c in candidates:
        ver = _java_version(c)
        if ver and ver >= TEMURIN_VER:
            return c

    return "java"


def java_is_ready() -> bool:
    exe = get_java_executable()
    return bool(_java_version(exe))


# ───────────────────────── Internal helper ─────────────────────────

def _find_java_home(root: Path) -> Path | None:
    for p in root.rglob("bin/java"):
        return p.parent.parent
    for p in root.rglob("bin/java.exe"):
        return p.parent.parent
    return None


# ───────────────────────── Installer ─────────────────────────

async def install_java(msgs: list[str]) -> None:
    if JDK_DIR.exists() and java_is_ready():
        msgs.append("✅ Java already installed.")
        return

    os_name = _os_name()
    arch = _arch()

    url = (
        f"https://api.adoptium.net/v3/binary/latest/"
        f"{TEMURIN_VER}/ga/{os_name}/{arch}/jdk/hotspot/normal/eclipse"
    )

    msgs.append(f"☕ Downloading Java {TEMURIN_VER} ({os_name}/{arch})…")

    archive: Path | None = None

    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=600)
    ) as session:
        async with session.get(url, allow_redirects=True) as r:
            r.raise_for_status()

            name = r.headers.get("Content-Disposition", "")
            if "filename=" in name:
                filename = name.split("filename=")[-1].strip('"')
            else:
                ext = "zip" if os_name == "windows" else "tar.gz"
                filename = f"temurin-{TEMURIN_VER}.{ext}"

            archive = Path(filename)

            async with aiofiles.open(archive, "wb") as f:
                async for chunk in r.content.iter_chunked(65536):
                    await f.write(chunk)

    msgs.append("📦 Extracting JDK…")

    extract_root = Path("_jdk_extract")
    extract_root.mkdir(exist_ok=True)

    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(extract_root)
    else:
        with tarfile.open(archive) as tf:
            tf.extractall(extract_root)

    java_home = _find_java_home(extract_root)
    if not java_home:
        raise RuntimeError("Failed to locate Java inside extracted archive.")

    if JDK_DIR.exists():
        shutil.rmtree(JDK_DIR)

    shutil.move(str(java_home), JDK_DIR)

    shutil.rmtree(extract_root, ignore_errors=True)
    archive.unlink(missing_ok=True)

    java_exec = JDK_DIR / "bin" / _java_bin_name()
    if not java_exec.exists():
        raise RuntimeError("Java installed but java binary missing.")

    msgs.append(f"✅ Java {TEMURIN_VER} installed successfully.")