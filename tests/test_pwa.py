"""The app must be installable on Android (and iOS): valid manifest, real icons, a service worker that is safe."""

from __future__ import annotations

import json
import re
import struct
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.config.settings import Settings
from src.interfaces.websocket_api import create_api

WEB = Path(__file__).resolve().parent.parent / "web"
MANIFEST = json.loads((WEB / "manifest.webmanifest").read_text(encoding="utf-8"))
INDEX = (WEB / "index.html").read_text(encoding="utf-8")


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG"
    return struct.unpack(">II", data[16:24])


def test_manifest_has_what_chrome_requires_to_offer_install():
    for key in ("name", "short_name", "start_url", "display", "icons", "id", "scope"):
        assert MANIFEST.get(key), f"manifest is missing {key}"
    assert MANIFEST["display"] in {"standalone", "fullscreen", "minimal-ui"}
    assert MANIFEST["start_url"].startswith(MANIFEST["scope"]), "start_url must be inside the scope"
    assert MANIFEST["theme_color"] and MANIFEST["background_color"]


def test_icons_exist_with_the_declared_sizes_and_include_maskable():
    sizes = set()
    purposes = set()
    for icon in MANIFEST["icons"]:
        path = WEB / icon["src"]
        assert path.exists(), f"missing icon file {icon['src']}"
        if icon["type"] == "image/png":
            w, h = png_size(path)
            assert f"{w}x{h}" == icon["sizes"], f"{icon['src']} is {w}x{h}, manifest says {icon['sizes']}"
            sizes.add(w)
        purposes.add(icon.get("purpose", "any"))
    assert {192, 512} <= sizes, "Android needs 192px and 512px PNG icons to install"
    assert "maskable" in purposes, "a maskable icon makes the home-screen icon fill Android's shape"
    assert png_size(WEB / "icons" / "apple-touch-icon.png") == (180, 180)


def test_shortcuts_point_inside_the_app():
    assert MANIFEST["shortcuts"], "app shortcuts (long-press the icon) are part of the install experience"
    for shortcut in MANIFEST["shortcuts"]:
        assert shortcut["url"].startswith(MANIFEST["scope"])
        assert (WEB / shortcut["icons"][0]["src"]).exists()


def test_index_links_everything_the_installer_needs():
    assert 'rel="manifest" href="manifest.webmanifest"' in INDEX
    assert 'rel="apple-touch-icon"' in INDEX
    assert f'name="theme-color" content="{MANIFEST["theme_color"]}"' in INDEX
    assert "viewport-fit=cover" in INDEX                                   # draw under notches; CSS uses safe-area insets
    viewport = re.search(r'name="viewport" content="([^"]+)"', INDEX).group(1)
    assert "user-scalable=no" not in viewport and "maximum-scale" not in viewport, "never disable pinch-zoom (accessibility)"


def _sw_code() -> str:
    """The service worker source without comment lines."""
    lines = (WEB / "sw.js").read_text(encoding="utf-8").splitlines()
    return chr(10).join(line for line in lines if not line.strip().startswith("//"))


def test_service_worker_never_intercepts_api_or_chat_traffic():
    code = _sw_code()
    fetch_listener = code[code.index('self.addEventListener("fetch"'):]
    fetch_listener = fetch_listener[: fetch_listener.index(chr(10) + "});") + 4]
    for forbidden in ("/api", "/chat", "/health", "websocket", "/telegram"):
        assert forbidden not in fetch_listener.lower(), f"the fetch interceptor mentions {forbidden}"
    assert 'request.method !== "GET"' in fetch_listener                       # only GETs are ever handled
    assert 'startsWith("/web/")' in code                                        # ...and only our own static files
    assert "respondWith" in code and "skipWaiting" in code and "clients.claim" in code
    # every cached shell file really exists, otherwise cache.addAll() fails and the worker never installs
    shell = re.search(r"const SHELL = \[(.*?)\];", code, re.S).group(1)
    for name in re.findall(r'"([^"]+)"', shell):
        assert (WEB / name).exists(), f"sw.js precaches {name}, which does not exist"


def test_the_only_api_call_the_worker_makes_is_the_signed_snooze_without_credentials():
    code = _sw_code()
    assert sorted(set(re.findall(r'"(/api/[^"]*)"', code))) == ["/api/push/action"]
    call = code[code.index('fetch("/api/push/action"'):]
    call = call[: call.index("});") + 3]
    assert 'method: "POST"' in call and 'credentials: "omit"' in call
    assert "authorization" not in code.lower() and "bearer" not in code.lower() and "localStorage" not in code   # the worker never holds the access token


@pytest.fixture
def client():
    settings = Settings(llm_provider="mock", environment="local", sqlite_path=":memory:")
    class Echo:
        async def handle_user_input(self, session_id, user_text):  # pragma: no cover - not used
            raise AssertionError
    with TestClient(create_api(Echo(), settings)) as c:
        yield c


def test_the_running_app_serves_the_pwa_files_with_the_right_types(client):
    expected = {
        "/web/manifest.webmanifest": "manifest",
        "/web/sw.js": "javascript",
        "/web/icons/icon-192.png": "image/png",
        "/web/icons/icon-512.png": "image/png",
        "/web/icons/icon-maskable-512.png": "image/png",
        "/web/icons/apple-touch-icon.png": "image/png",
        "/web/icon.svg": "image/svg+xml",
    }
    for url, kind in expected.items():
        r = client.get(url)
        assert r.status_code == 200, url
        assert kind in r.headers["content-type"], (url, r.headers["content-type"])
    assert client.get("/web/manifest.webmanifest").json()["id"] == "/web/"
    # the service worker lives inside the manifest scope, so it is allowed to control the app
    assert "/web/sw.js".startswith(MANIFEST["scope"])
