"""
modrinth.py — Modrinth API v2 client for PyPurpur.

ROOT CAUSE FIX: aiohttp raises "Only absolute URLs without path part are
supported" when ClientSession is given a base_url that contains a path
(e.g. "https://api.modrinth.com/v2").  Fix: never use base_url; always
build the full absolute URL before calling session.get().
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import aiohttp

log = logging.getLogger("pypurpur.modrinth")

# ── Constants ─────────────────────────────────────────────────────────────────

_BASE    = "https://api.modrinth.com/v2"          # used only for building URLs
_HEADERS = {"User-Agent": "PyPurpur/3.0 (github.com/MixedStudios/pypurpur)"}

# Loaders Purpur is compatible with (order matters for display)
LOADERS = ["purpur", "paper", "spigot", "bukkit"]


# ── Data models ───────────────────────────────────────────────────────────────

class ModrinthProject:
    def __init__(self, data: dict) -> None:
        self.id:          str        = data.get("project_id") or data.get("id", "")
        self.slug:        str        = data.get("slug", "")
        self.title:       str        = data.get("title", "")
        self.description: str        = data.get("description", "")
        self.icon_url:    str | None = data.get("icon_url")
        self.downloads:   int        = data.get("downloads", 0)
        self.followers:   int        = data.get("follows", 0)
        self.categories:  list[str]  = data.get("categories", [])
        self.page_url:    str        = f"https://modrinth.com/plugin/{data.get('slug','')}"

    def __repr__(self) -> str:
        return f"<ModrinthProject slug={self.slug!r}>"


class ModrinthVersion:
    def __init__(self, data: dict) -> None:
        self.id:             str        = data.get("id", "")
        self.project_id:     str        = data.get("project_id", "")
        self.name:           str        = data.get("name", "")
        self.version_number: str        = data.get("version_number", "")
        self.version_type:   str        = data.get("version_type", "release")
        self.loaders:        list[str]  = data.get("loaders", [])
        self.game_versions:  list[str]  = data.get("game_versions", [])
        self.dependencies:   list[dict] = data.get("dependencies", [])
        self.files:          list[dict] = data.get("files", [])

    @property
    def primary_file(self) -> dict | None:
        for f in self.files:
            if f.get("primary"):
                return f
        return self.files[0] if self.files else None

    @property
    def download_url(self) -> str | None:
        f = self.primary_file
        return f["url"] if f else None

    @property
    def filename(self) -> str | None:
        f = self.primary_file
        return f["filename"] if f else None

    @property
    def sha512(self) -> str | None:
        f = self.primary_file
        return f.get("hashes", {}).get("sha512") if f else None

    def __repr__(self) -> str:
        return f"<ModrinthVersion {self.version_number!r}>"


# ── Client ────────────────────────────────────────────────────────────────────

class ModrinthClient:
    """
    Async wrapper around the Modrinth v2 REST API.
    IMPORTANT: Every request uses a full absolute URL — no base_url on the
    ClientSession, which is the fix for the aiohttp path-part error.
    """

    async def _get(self, path: str, **params: Any) -> Any:
        """
        GET {_BASE}{path} with optional query params.
        path must start with '/', e.g. '/search', '/project/skinsrestorer'.
        """
        url = f"{_BASE}{path}"
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(headers=_HEADERS) as session:
            for attempt in range(3):
                async with session.get(url, params=params, timeout=timeout) as r:
                    if r.status == 429:
                        wait = int(r.headers.get("X-Ratelimit-Reset", "5"))
                        log.warning("Rate-limited by Modrinth; waiting %ds", wait)
                        await asyncio.sleep(wait)
                        continue
                    r.raise_for_status()
                    return await r.json()
        raise RuntimeError(f"Modrinth GET {url} failed after 3 attempts")

    # ── Search ───────────────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        mc_version: str,
        limit: int = 10,
        offset: int = 0,
    ) -> list[ModrinthProject]:
        """Search plugins filtered by MC version + compatible loaders."""
        facets = json.dumps([
            ["project_type:plugin"],
            [f"versions:{mc_version}"],
            [f"categories:{loader}" for loader in LOADERS],
        ])
        data = await self._get(
            "/search",
            query=query,
            facets=facets,
            limit=limit,
            offset=offset,
        )
        return [ModrinthProject(h) for h in data.get("hits", [])]

    # ── Project info ─────────────────────────────────────────────────────────

    async def get_project(self, id_or_slug: str) -> ModrinthProject:
        data = await self._get(f"/project/{id_or_slug}")
        return ModrinthProject(data)

    # ── Versions ─────────────────────────────────────────────────────────────

    async def get_versions(
        self, project_id: str, mc_version: str
    ) -> list[ModrinthVersion]:
        """Return stable versions for a project + MC version, newest first."""
        data = await self._get(
            f"/project/{project_id}/version",
            loaders=json.dumps(LOADERS),
            game_versions=json.dumps([mc_version]),
        )
        if not isinstance(data, list):
            return []
        versions = [ModrinthVersion(v) for v in data]
        stable = [v for v in versions if v.version_type == "release"]
        return stable if stable else versions

    async def get_latest_version(
        self, id_or_slug: str, mc_version: str
    ) -> ModrinthVersion | None:
        """Resolve latest stable version for a project + MC version."""
        versions = await self.get_versions(id_or_slug, mc_version)
        return versions[0] if versions else None

    # ── Dependency resolver ───────────────────────────────────────────────────

    async def resolve_dependencies(
        self,
        version: ModrinthVersion,
        mc_version: str,
        _seen: set[str] | None = None,
    ) -> list[tuple[ModrinthProject, ModrinthVersion]]:
        """Recursively collect required + optional dependencies."""
        if _seen is None:
            _seen = set()

        results: list[tuple[ModrinthProject, ModrinthVersion]] = []
        for dep in version.dependencies:
            dep_type = dep.get("dependency_type", "required")
            if dep_type not in ("required", "optional"):
                continue
            proj_id = dep.get("project_id")
            ver_id  = dep.get("version_id")
            if not proj_id or proj_id in _seen:
                continue
            _seen.add(proj_id)
            try:
                if ver_id:
                    raw = await self._get(f"/version/{ver_id}")
                    dep_ver = ModrinthVersion(raw)
                else:
                    dep_ver = await self.get_latest_version(proj_id, mc_version)
                if dep_ver is None:
                    continue
                dep_proj = await self.get_project(proj_id)
                results.append((dep_proj, dep_ver))
                sub = await self.resolve_dependencies(dep_ver, mc_version, _seen)
                results.extend(sub)
            except Exception as exc:
                log.warning("Dep resolution failed for %s: %s", proj_id, exc)

        return results

    # ── Update checker ────────────────────────────────────────────────────────

    async def check_updates(
        self,
        plugins_dir: Path,
        mc_version: str,
        index_map: dict[str, str],      # slug → project_id
    ) -> list[tuple[str, ModrinthVersion]]:
        """
        Returns list of (slug, latest_version) where an update is available.
        Detection is done by comparing the installed file's sha512 against
        the latest release's sha512.
        """
        updates: list[tuple[str, ModrinthVersion]] = []
        for slug, project_id in index_map.items():
            try:
                latest = await self.get_latest_version(project_id, mc_version)
                if latest is None or latest.download_url is None:
                    continue
                # find the installed jar
                installed = next(
                    (f for f in plugins_dir.glob("*.jar")
                     if f.name == latest.filename),
                    None,
                )
                if installed is None:
                    continue
                installed_hash = hashlib.sha512(installed.read_bytes()).hexdigest()
                if latest.sha512 and installed_hash != latest.sha512:
                    updates.append((slug, latest))
            except Exception as exc:
                log.warning("Update check failed for %s: %s", slug, exc)
        return updates


# ── Singleton ─────────────────────────────────────────────────────────────────

modrinth = ModrinthClient()
