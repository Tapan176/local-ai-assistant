"""Serving the web UI so that a deployed update actually reaches an already-open phone.

Problems this solves
- ``StaticFiles`` sends no Cache-Control, leaving freshness to browser heuristics. We send ``no-cache`` (always revalidate;
  an unchanged file costs one tiny 304).
- A page that stays open keeps running the JavaScript it loaded, possibly for days (installed apps and background tabs).
  The server stamps every build with a content hash (``/health`` -> ``web_version``) and injects the same hash into
  ``app.js`` itself, so the running page can tell that it is out of date and offer a Reload.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from fastapi import Request, Response
from fastapi.staticfiles import StaticFiles

WEB_DIR = Path(__file__).resolve().parents[2] / "web"
PLACEHOLDER = "__WEB_VERSION__"
_UI_SUFFIXES = {".html", ".js", ".css", ".webmanifest", ".svg", ".png"}


def web_version(web_dir: Path = WEB_DIR) -> str:
    """Short content hash of every UI file: changes exactly when the UI changes (new files are picked up automatically)."""
    digest = hashlib.sha256()
    for path in sorted(web_dir.rglob("*")):
        if path.is_file() and path.suffix in _UI_SUFFIXES:
            digest.update(path.relative_to(web_dir).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:10]


def server_version() -> str:
    """The deployed commit (Render sets RENDER_GIT_COMMIT), or 'dev'."""
    return (os.getenv("RENDER_GIT_COMMIT") or "")[:7] or "dev"


class NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):  # type: ignore[no-untyped-def]
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def app_js_response(request: Request, web_dir: Path, version: str) -> Response:
    """app.js with the build hash injected, so the page knows which build it is."""
    etag = f'"{version}"'
    headers = {"Cache-Control": "no-cache", "ETag": etag}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    source = (web_dir / "app.js").read_text(encoding="utf-8").replace(PLACEHOLDER, version)
    return Response(source, media_type="text/javascript; charset=utf-8", headers=headers)
