"""Internet skills: web search, page fetch (SSRF-guarded) and weather (Open-Meteo, no API key)."""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import httpx

from src.agent import weather
from src.agent.skill import SkillContext, SkillRegistry, schema

USER_AGENT = "Mozilla/5.0 (compatible; TapanAI/2.0; personal assistant)"
MAX_BYTES = 1_500_000
MAX_REDIRECTS = 4


# ── SSRF guard ──────────────────────────────────────────────────────
class UnsafeURL(ValueError):
    pass


async def assert_public_url(url: str) -> str:
    """Raise UnsafeURL unless the URL is http(s) and every resolved address is a public IP."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeURL("Only http(s) URLs are allowed.")
    host = parsed.hostname
    try:
        literal = ipaddress.ip_address(host)
        addresses = [str(literal)]
    except ValueError:
        try:
            infos = await asyncio.to_thread(socket.getaddrinfo, host, parsed.port or 443, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise UnsafeURL(f"Cannot resolve host '{host}'.") from exc
        addresses = [info[4][0] for info in infos]
    for addr in addresses:
        if not ipaddress.ip_address(addr.split("%")[0]).is_global:
            raise UnsafeURL("Refusing to fetch private/local network addresses.")
    return url


class _TextExtractor(HTMLParser):
    _SKIP = {"script", "style", "noscript", "svg", "head", "nav", "footer", "form", "iframe"}
    _BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.title = ""
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "title":
            self._in_title = True
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self._skip_depth:
            self.parts.append(data)


def html_to_text(html: str) -> tuple[str, str]:
    parser = _TextExtractor()
    parser.feed(html)
    text = unescape("".join(parser.parts))
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return parser.title.strip(), text


async def fetch_url(ctx: SkillContext, args: dict[str, Any]) -> str:
    url = str(args["url"]).strip()
    if "://" not in url:
        url = "https://" + url
    max_chars = min(max(int(args.get("max_chars") or 5000), 500), 20000)

    for _ in range(MAX_REDIRECTS + 1):
        try:
            await assert_public_url(url)
        except UnsafeURL as exc:
            return f"Blocked: {exc}"
        async with ctx.http.stream(
            "GET", url, headers={"User-Agent": USER_AGENT}, timeout=15.0, follow_redirects=False
        ) as resp:
            if resp.is_redirect:
                location = resp.headers.get("location")
                if not location:
                    return "Redirect without a location."
                url = urljoin(url, location)
                continue
            if resp.status_code >= 400:
                return f"The page returned HTTP {resp.status_code}."
            ctype = resp.headers.get("content-type", "").lower()
            if not any(t in ctype for t in ("text/", "json", "xml")):
                return f"Unsupported content type '{ctype or 'unknown'}' (only text pages are supported)."
            body = bytearray()
            async for chunk in resp.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_BYTES:
                    break
            raw = bytes(body[:MAX_BYTES]).decode(resp.encoding or "utf-8", errors="replace")
            if "html" in ctype:
                title, text = html_to_text(raw)
                head = f"Title: {title}\n" if title else ""
            else:
                head, text = "", raw
            clipped = text[:max_chars] + ("…[truncated]" if len(text) > max_chars else "")
            return f"URL: {url}\n{head}{clipped}"
    return "Too many redirects."


# ── web search (DuckDuckGo HTML endpoint, no key needed) ────────────
_ANCHOR_RE = re.compile(r'<a[^>]+class="[^"]*result__a[^"]*"[^>]*>', re.DOTALL)
_HREF_RE = re.compile(r'href="([^"]+)"')
_SNIPPET_RE = re.compile(r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', re.DOTALL)
_TITLE_RE = re.compile(r"(.*?)</a>", re.DOTALL)


def _clean(fragment: str) -> str:
    return unescape(re.sub(r"<[^>]+>", "", fragment or "")).strip()


def _real_url(href: str) -> str:
    href = unescape(href)
    if href.startswith("//"):
        href = "https:" + href
    query = parse_qs(urlparse(href).query)
    return unquote(query["uddg"][0]) if "uddg" in query else href


def parse_search_results(html: str, limit: int) -> list[dict[str, str]]:
    anchors = list(_ANCHOR_RE.finditer(html))
    results: list[dict[str, str]] = []
    for i, anchor in enumerate(anchors):
        block_end = anchors[i + 1].start() if i + 1 < len(anchors) else len(html)
        href = _HREF_RE.search(anchor.group(0))
        if not href:
            continue
        url = _real_url(href.group(1))
        if not url.startswith("http") or "duckduckgo.com/y.js" in url:  # skip ads
            continue
        title = _TITLE_RE.match(html, anchor.end())
        snippet = _SNIPPET_RE.search(html, anchor.end(), block_end)
        results.append(
            {
                "title": _clean(title.group(1) if title else ""),
                "url": url,
                "snippet": _clean(snippet.group(1) if snippet else ""),
            }
        )
        if len(results) >= limit:
            break
    return results


async def web_search(ctx: SkillContext, args: dict[str, Any]) -> Any:
    query = str(args["query"]).strip()
    limit = min(max(int(args.get("max_results") or 5), 1), 10)
    resp = await ctx.http.post(
        "https://html.duckduckgo.com/html/",
        data={"q": query},
        headers={"User-Agent": USER_AGENT},
        timeout=15.0,
    )
    if resp.status_code != 200:
        return f"Search failed (HTTP {resp.status_code}). Try again shortly."
    results = parse_search_results(resp.text, limit)
    return results or "No results found (the search provider may be rate-limiting). Try rephrasing."


# ── weather (see src/agent/weather.py) ─────────────────────────────
async def get_weather(ctx: SkillContext, args: dict[str, Any]) -> str:
    days = min(max(int(args.get("days") or 3), 1), 7)
    try:
        location = str(args.get("location") or "").strip()
        if location:
            place = await weather.geocode(ctx.http, location, ctx.settings.timezone)
        else:
            place = await weather.home_place(ctx.store, ctx.settings, ctx.http)
            if place is None:
                return "I don't know your city yet. Ask the user which city they live in, then call set_home_location."
        return await weather.weather_text(ctx.http, place, days)
    except weather.WeatherError as exc:
        return str(exc)                                  # a plain-language reason the model can relay or act on


async def set_home_location(ctx: SkillContext, args: dict[str, Any]) -> str:
    try:
        place = await weather.geocode(ctx.http, str(args["city"]), ctx.settings.timezone)
    except weather.WeatherError as exc:
        return str(exc)
    await weather.save_home(ctx.store, place)
    return f"Home city saved: {weather.label(place)}. I'll use it for the weather and your daily briefing."


def register(registry: SkillRegistry) -> None:
    registry.add(
        "web_search",
        "Search the internet for current information, news, facts, prices, documentation. Returns titles, URLs, snippets. "
        "Follow up with fetch_url on the best result when snippets are not enough.",
        schema({"query": {"type": "string"}, "max_results": {"type": "integer"}}, ["query"]),
        web_search,
    )
    registry.add(
        "fetch_url",
        "Download a public web page and return its readable text. Cannot access private/local network addresses.",
        schema({"url": {"type": "string"}, "max_chars": {"type": "integer"}}, ["url"]),
        fetch_url,
    )
    registry.add(
        "get_weather",
        "Current weather and a short forecast for a city. Omit location to use the user's saved home city. "
        "If the result says the home city is unknown, ask the user where they live and call set_home_location.",
        schema({"location": {"type": "string", "description": "City, optionally with region/country: 'Surat' or 'Surat, India'"},
                "days": {"type": "integer"}}),
        get_weather,
    )
    registry.add(
        "set_home_location",
        "Save the city the user lives in, used for the default weather and the daily briefing. Call it whenever the user "
        "says where they live ('my city is Surat', 'I live in Pune', 'set my location to Mumbai').",
        schema({"city": {"type": "string", "description": "City, optionally with region/country"}}, ["city"]),
        set_home_location,
    )
