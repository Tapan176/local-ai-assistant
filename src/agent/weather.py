"""Weather from free, key-less providers with automatic fallback: forgiving geocoding, caching, and a home city set in chat.

Providers, tried in order: Open-Meteo, then MET Norway (api.met.no), then wttr.in. On Render, Open-Meteo answers 429 for
every request because the egress IPs are shared by many apps, so a single provider is not enough. A 429 puts that provider
on a 10 minute cooldown instead of being retried (retrying a rate limit only makes it worse); every provider's answer is
converted to Open-Meteo's shape so the formatting code does not care where it came from.

Why this is more than two HTTP calls
- Open-Meteo's geocoder matches a bare *name* only. "Surat, India" or "Pune 411001" fail, "Bangalore" resolves to a town in
  Pakistan (it only knows "Bengaluru"), and a placeholder like "home" resolves to Homyel, Belarus. We therefore parse
  "City, Region/Country", drop postal codes, translate well-known renamed Indian cities, ignore placeholders, and rank
  candidates by qualifier match, then timezone match, then population.
- The free API is rate limited per IP and Render's egress IPs are shared. Results are cached (geocoding 24 h, forecast 10 min),
  transient failures are retried, and if the service is down the last good forecast is served (marked as such).
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MET_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
WTTR_URL = "https://wttr.in/{lat},{lon}"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# MET Norway and Nominatim require an identifying User-Agent. It names the software only: no person, repo or contact.
USER_AGENT = {"User-Agent": "personal-assistant-weather/1.0"}
COOLDOWN_SECONDS = 600
_COOLDOWN: dict[str, float] = {}

RETRY_DELAYS = (0.5, 1.5)               # seconds between attempts; tests patch this to zero
GEO_TTL = 24 * 3600
FORECAST_TTL = 600
STALE_OK_SECONDS = 3 * 3600             # how old a cached forecast may be when the live service is failing
CACHE_MAX = 256
HOME_KEY = "home_location"

PLACEHOLDERS = {
    "", "home", "here", "my city", "city", "your city", "your-city", "location", "default", "tbd", "changeme",
    "change me", "none", "n/a", "na", "null", "example", "xxx",
}
# Open-Meteo only knows current official names. These are tried first, and only for a user whose timezone is India's.
INDIA_ALIASES = {
    "bangalore": "bengaluru", "bombay": "mumbai", "madras": "chennai", "calcutta": "kolkata", "poona": "pune",
    "baroda": "vadodara", "trivandrum": "thiruvananthapuram", "cochin": "kochi", "mysore": "mysuru", "gurgaon": "gurugram",
    "benares": "varanasi", "banaras": "varanasi", "pondicherry": "puducherry", "allahabad": "prayagraj",
    "bhubaneshwar": "bhubaneswar", "vizag": "visakhapatnam", "ahmedabad city": "ahmedabad", "new bombay": "navi mumbai",
}
COUNTRY_ALIASES = {
    "uk": "gb", "united kingdom": "gb", "england": "gb", "scotland": "gb", "wales": "gb", "great britain": "gb",
    "usa": "us", "united states": "us", "america": "us", "uae": "ae", "emirates": "ae",
}

WMO = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "freezing fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "rain showers", 81: "rain showers", 82: "violent showers", 85: "snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "severe thunderstorm with hail",
}


class WeatherError(Exception):
    """Carries a message that is safe and useful to show to the user (and to the model)."""


class RateLimited(WeatherError):
    """HTTP 429: do not retry this provider for a while."""


class _TTLCache:
    def __init__(self, ttl: float) -> None:
        self.ttl = ttl
        self._data: dict[Any, tuple[float, float, Any]] = {}      # key -> (fresh_until, stored_at, value)

    def get(self, key: Any, *, max_age: float | None = None) -> Any | None:
        item = self._data.get(key)
        if not item:
            return None
        fresh_until, stored_at, value = item
        now = time.monotonic()
        if max_age is None:
            return value if now < fresh_until else None
        return value if now - stored_at <= max_age else None

    def put(self, key: Any, value: Any) -> None:
        if len(self._data) >= CACHE_MAX:
            self._data.pop(next(iter(self._data)))                  # oldest insertion
        now = time.monotonic()
        self._data[key] = (now + self.ttl, now, value)

    def age(self, key: Any) -> float | None:
        item = self._data.get(key)
        return None if not item else time.monotonic() - item[1]

    def clear(self) -> None:
        self._data.clear()


_GEO = _TTLCache(GEO_TTL)
_FORECAST = _TTLCache(FORECAST_TTL)


def clear_caches() -> None:
    _GEO.clear()
    _FORECAST.clear()
    _COOLDOWN.clear()


def _cooling(name: str) -> bool:
    return _COOLDOWN.get(name, 0) > time.monotonic()


def _norm(text: str) -> str:
    return " ".join(str(text).lower().split())


def is_placeholder(location: str | None) -> bool:
    return _norm(location or "") in PLACEHOLDERS


# ── HTTP with retries ───────────────────────────────────────────────
BUSY = "The weather service is busy or unreachable right now. Try again in a minute."


async def _get_json(http: httpx.AsyncClient, url: str, params: dict[str, Any] | None = None, *, headers: dict[str, str] | None = None) -> dict[str, Any]:
    """GET and decode JSON. A top-level list is returned as {"_list": [...]}."""
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            resp = await http.get(url, params=params, headers=headers, timeout=10.0)
        except httpx.TransportError:                                 # timeouts, DNS, connection resets
            pass
        else:
            if resp.status_code == 429:
                raise RateLimited(BUSY)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                except ValueError:
                    raise WeatherError("The weather service sent an unreadable response. Try again shortly.") from None
                if isinstance(data, dict):
                    return data
                if isinstance(data, list):
                    return {"_list": data}
                raise WeatherError("The weather service sent an unexpected response. Try again shortly.")
            if resp.status_code not in (500, 502, 503, 504):
                raise WeatherError(f"The weather service rejected the request (HTTP {resp.status_code}).")
        if attempt < len(RETRY_DELAYS):
            await asyncio.sleep(RETRY_DELAYS[attempt])
    raise WeatherError(BUSY)


# ── geocoding ───────────────────────────────────────────────────────
def _name_candidates(name: str, tz_hint: str) -> list[str]:
    base = _norm(name)
    out: list[str] = []
    if tz_hint == "Asia/Kolkata" and base in INDIA_ALIASES:
        out.append(INDIA_ALIASES[base])
    out.append(base)
    no_digits = " ".join(w for w in base.split() if not any(c.isdigit() for c in w))   # "pune 411001" -> "pune"
    if no_digits and no_digits not in out:
        out.append(no_digits)
    return out


def _pick(results: list[dict[str, Any]], name: str, qualifiers: list[str], tz_hint: str) -> dict[str, Any]:
    def haystack(place: dict[str, Any]) -> set[str]:
        return {_norm(str(place.get(k, ""))) for k in ("country", "country_code", "admin1", "admin2", "admin3")} - {""}

    def score(place: dict[str, Any]) -> tuple:
        fields = haystack(place)
        qualified = bool(qualifiers) and all(any(q == f or (len(q) > 2 and q in f) for f in fields) for q in qualifiers)
        return (
            qualified,                                              # "Surat, Gujarat" must beat a bigger Surat elsewhere
            _norm(place.get("name", "")) == name,                    # exact name beats a partial match
            bool(tz_hint) and place.get("timezone") == tz_hint,      # prefer the user's own region over a larger namesake abroad
            place.get("population") or 0,
        )

    return max(results, key=score)


def _place(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": raw.get("name", ""), "admin1": raw.get("admin1", ""), "country": raw.get("country", ""),
        "latitude": float(raw["latitude"]), "longitude": float(raw["longitude"]), "timezone": raw.get("timezone", ""),
    }


def label(place: dict[str, Any]) -> str:
    parts = [place.get("name", "")]
    if place.get("admin1") and place["admin1"] != place.get("name"):
        parts.append(place["admin1"])
    if place.get("country"):
        parts.append(place["country"])
    return ", ".join(p for p in parts if p)


async def geocode(http: httpx.AsyncClient, query: str, tz_hint: str = "") -> dict[str, Any]:
    cleaned = " ".join(str(query).split())
    if is_placeholder(cleaned):
        raise WeatherError("I don't know your city yet. Tell me, for example: “my city is Surat”.")
    parts = [p.strip() for p in cleaned.split(",") if p.strip()]
    qualifiers = [COUNTRY_ALIASES.get(_norm(q), _norm(q)) for q in parts[1:]]
    key = (_norm(cleaned), tz_hint)
    cached = _GEO.get(key)
    if cached:
        return cached
    not_found = WeatherError(f"I couldn't find a place called “{cleaned}”. Try just the city, like “Surat” or “Surat, India”.")
    primary_failed = _cooling("open-meteo-geo")
    if not primary_failed:
        try:
            for name in _name_candidates(parts[0], tz_hint):
                data = await _get_json(http, GEO_URL, {"name": name, "count": 10, "language": "en"})
                results = [r for r in (data.get("results") or []) if isinstance(r, dict) and "latitude" in r and "longitude" in r]
                if results:
                    place = _place(_pick(results, name, qualifiers, tz_hint))
                    _GEO.put(key, place)
                    return place
        except RateLimited:
            _COOLDOWN["open-meteo-geo"] = time.monotonic() + COOLDOWN_SECONDS
            primary_failed = True
        except WeatherError:
            primary_failed = True
        else:
            raise not_found                                           # the geocoder answered and does not know it: no fallback
    # The primary geocoder is rate limited or down: Nominatim (OpenStreetMap) needs no key and the lookup is cached for a day.
    try:
        place = await _geocode_nominatim(http, parts[0], qualifiers, tz_hint)
    except WeatherError:
        raise WeatherError(BUSY) from None
    if place is None:
        raise not_found
    _GEO.put(key, place)
    return place


async def _geocode_nominatim(http: httpx.AsyncClient, name: str, qualifiers: list[str], tz_hint: str) -> dict[str, Any] | None:
    query = _name_candidates(name, tz_hint)[0]
    data = await _get_json(http, NOMINATIM_URL, {"q": query, "format": "jsonv2", "limit": 10, "addressdetails": 1, "accept-language": "en"}, headers=USER_AGENT)
    results = []
    for row in data.get("_list") or []:
        if not isinstance(row, dict) or "lat" not in row or "lon" not in row:
            continue
        addr = row.get("address") or {}
        results.append({
            "name": row.get("name") or str(row.get("display_name", "")).split(",")[0], "admin1": addr.get("state", ""),
            "country": addr.get("country", ""), "country_code": str(addr.get("country_code", "")).upper(),
            "latitude": row["lat"], "longitude": row["lon"], "timezone": tz_hint or "UTC", "population": None,
        })
    return _place(_pick(results, query, qualifiers, tz_hint)) if results else None


# ── forecast ────────────────────────────────────────────────────────
async def _open_meteo(http: httpx.AsyncClient, place: dict[str, Any], days: int) -> dict[str, Any]:
    return await _get_json(http, FORECAST_URL, {
        "latitude": place["latitude"], "longitude": place["longitude"],
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
        "timezone": "auto", "forecast_days": days,
    })


# MET Norway symbol -> the nearest WMO code (so one table describes the weather whichever provider answered).
_MET_CODES = {
    "clearsky": 0, "fair": 1, "partlycloudy": 2, "cloudy": 3, "fog": 45,
    "lightrain": 61, "rain": 63, "heavyrain": 65, "lightrainshowers": 80, "rainshowers": 81, "heavyrainshowers": 82,
    "lightsleet": 66, "sleet": 67, "heavysleet": 67, "lightsleetshowers": 66, "sleetshowers": 67, "heavysleetshowers": 67,
    "lightsnow": 71, "snow": 73, "heavysnow": 75, "lightsnowshowers": 85, "snowshowers": 85, "heavysnowshowers": 86,
}


def _met_code(symbol: Any) -> int | None:
    if not isinstance(symbol, str) or not symbol:
        return None
    base = symbol.rsplit("_", 1)[0] if symbol.endswith(("_day", "_night", "_polartwilight")) else symbol
    if "thunder" in base:
        return 95
    return _MET_CODES.get(base)


def _met_to_open_meteo(data: dict[str, Any], tz_name: str, days: int) -> dict[str, Any]:
    series = (data.get("properties") or {}).get("timeseries")
    if not isinstance(series, list) or not series:
        raise WeatherError("The weather service sent incomplete data. Try again shortly.")
    try:
        tz = ZoneInfo(tz_name or "UTC")
    except Exception:  # noqa: BLE001 - an unknown zone name must not break the forecast
        tz = ZoneInfo("UTC")
    first = series[0].get("data") or {}
    now = first.get("instant", {}).get("details") or {}
    summary = (first.get("next_1_hours") or first.get("next_6_hours") or {}).get("summary") or {}
    wind = now.get("wind_speed")
    current = {
        "temperature_2m": now.get("air_temperature"), "apparent_temperature": None,
        "relative_humidity_2m": None if now.get("relative_humidity") is None else round(now["relative_humidity"]),
        "wind_speed_10m": None if wind is None else round(wind * 3.6, 1), "weather_code": _met_code(summary.get("symbol_code")),
    }
    per_day: dict[str, dict[str, Any]] = {}
    for entry in series:
        try:
            local = datetime.fromisoformat(str(entry["time"]).replace("Z", "+00:00")).astimezone(tz)
        except (KeyError, ValueError):
            continue
        details = (entry.get("data") or {}).get("instant", {}).get("details") or {}
        bucket = per_day.setdefault(local.date().isoformat(), {"temps": [], "pop": [], "symbol": None, "gap": 99})
        if details.get("air_temperature") is not None:
            bucket["temps"].append(details["air_temperature"])
        block = (entry.get("data") or {}).get("next_6_hours") or (entry.get("data") or {}).get("next_1_hours") or {}
        pop = (block.get("details") or {}).get("probability_of_precipitation")
        if pop is not None:
            bucket["pop"].append(pop)
        symbol = (block.get("summary") or {}).get("symbol_code")
        if symbol and abs(local.hour - 12) < bucket["gap"]:           # the symbol nearest midday describes the day
            bucket["symbol"], bucket["gap"] = symbol, abs(local.hour - 12)
    dates = sorted(per_day)[:days]
    return {"current": current, "daily": {
        "time": dates,
        "temperature_2m_max": [max(per_day[d]["temps"]) if per_day[d]["temps"] else None for d in dates],
        "temperature_2m_min": [min(per_day[d]["temps"]) if per_day[d]["temps"] else None for d in dates],
        "precipitation_probability_max": [max(per_day[d]["pop"]) if per_day[d]["pop"] else None for d in dates],
        "weather_code": [_met_code(per_day[d]["symbol"]) for d in dates],
    }}


async def _met_norway(http: httpx.AsyncClient, place: dict[str, Any], days: int) -> dict[str, Any]:
    data = await _get_json(http, MET_URL, {"lat": round(place["latitude"], 4), "lon": round(place["longitude"], 4)}, headers=USER_AGENT)
    return _met_to_open_meteo(data, place.get("timezone", ""), days)


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    number = _to_float(value)
    return None if number is None else round(number)


def _wttr_to_open_meteo(data: dict[str, Any], days: int) -> dict[str, Any]:
    now_list, day_list = data.get("current_condition"), data.get("weather")
    if not isinstance(now_list, list) or not now_list or not isinstance(day_list, list) or not day_list:
        raise WeatherError("The weather service sent incomplete data. Try again shortly.")

    def text(item: Any) -> str | None:
        values = item.get("weatherDesc") if isinstance(item, dict) else None
        return str(values[0].get("value", "")).strip().lower() or None if isinstance(values, list) and values and isinstance(values[0], dict) else None

    now = now_list[0]
    current = {
        "temperature_2m": _to_float(now.get("temp_C")), "apparent_temperature": _to_float(now.get("FeelsLikeC")),
        "relative_humidity_2m": _to_int(now.get("humidity")), "wind_speed_10m": _to_float(now.get("windspeedKmph")),
        "weather_code": None, "description": text(now),
    }
    rows = [d for d in day_list if isinstance(d, dict)][:days]
    def noon(day: dict[str, Any]) -> dict[str, Any]:                  # the 12:00 slot describes the day
        hourly = day.get("hourly")
        return hourly[4] if isinstance(hourly, list) and len(hourly) > 4 and isinstance(hourly[4], dict) else {}

    return {"current": current, "daily": {
        "time": [d.get("date") for d in rows],
        "temperature_2m_max": [_to_float(d.get("maxtempC")) for d in rows],
        "temperature_2m_min": [_to_float(d.get("mintempC")) for d in rows],
        "precipitation_probability_max": [max([_to_int(h.get("chanceofrain")) or 0 for h in d.get("hourly") or [{}]]) for d in rows],
        "weather_code": [None for _ in rows], "description": [text(noon(d)) for d in rows],
    }}


async def _wttr(http: httpx.AsyncClient, place: dict[str, Any], days: int) -> dict[str, Any]:
    url = WTTR_URL.format(lat=round(place["latitude"], 3), lon=round(place["longitude"], 3))
    return _wttr_to_open_meteo(await _get_json(http, url, {"format": "j1", "lang": "en"}, headers=USER_AGENT), days)


PROVIDERS = (("open-meteo", _open_meteo), ("met-norway", _met_norway), ("wttr.in", _wttr))


async def forecast(http: httpx.AsyncClient, place: dict[str, Any], days: int = 3) -> dict[str, Any]:
    key = (round(place["latitude"], 2), round(place["longitude"], 2), days)
    fresh = _FORECAST.get(key)
    if fresh:
        return fresh
    first_error: WeatherError | None = None
    for name, fetch in PROVIDERS:
        if _cooling(name):
            continue
        try:
            data = await fetch(http, place, days)
            if not isinstance(data.get("current"), dict) or not isinstance(data.get("daily"), dict):
                raise WeatherError("The weather service sent incomplete data. Try again shortly.")
        except RateLimited as exc:
            _COOLDOWN[name] = time.monotonic() + COOLDOWN_SECONDS
            first_error = first_error or exc
            continue
        except WeatherError as exc:
            first_error = first_error or exc
            continue
        data["_source"] = name
        _FORECAST.put(key, data)
        return data
    stale = _FORECAST.get(key, max_age=STALE_OK_SECONDS)           # every provider failed: an older forecast beats nothing, and we say so
    if stale:
        return {**stale, "_age_minutes": int((_FORECAST.age(key) or 0) / 60)}
    raise first_error or WeatherError(BUSY)


def _num(value: Any, suffix: str = "") -> str:
    return "–" if value is None else f"{value}{suffix}"


def format_weather(place: dict[str, Any], data: dict[str, Any], days: int = 3) -> str:
    cur, daily = data["current"], data["daily"]
    line = (
        f"{label(place)}: now {_num(cur.get('temperature_2m'), '°C')} (feels {_num(cur.get('apparent_temperature'), '°C')}), "
        f"{cur.get('description') or WMO.get(cur.get('weather_code'), 'unknown conditions')}, humidity {_num(cur.get('relative_humidity_2m'), '%')}, "
        f"wind {_num(cur.get('wind_speed_10m'), ' km/h')}."
    )
    if data.get("_age_minutes") is not None:
        line += f" (Live data unavailable; this is from {data['_age_minutes']} min ago.)"
    lines = [line]
    dates = daily.get("time") or []
    for i, day in enumerate(dates[:days]):
        def at(name: str) -> Any:
            series = daily.get(name) or []
            return series[i] if i < len(series) else None

        lines.append(
            f"{day}: {_num(at('temperature_2m_min'))}–{_num(at('temperature_2m_max'), '°C')}, "
            f"{at('description') or WMO.get(at('weather_code'), 'unknown conditions')}, rain chance {_num(at('precipitation_probability_max'), '%')}"
        )
    return "\n".join(lines)


async def weather_text(http: httpx.AsyncClient, place: dict[str, Any], days: int = 3) -> str:
    return format_weather(place, await forecast(http, place, days), days)


async def fetch_weather(http: httpx.AsyncClient, location: str, days: int = 3, tz_hint: str = "") -> str:
    """Convenience: geocode a free-text location and return the formatted forecast."""
    return await weather_text(http, await geocode(http, location, tz_hint), days)


# ── the user's home city ────────────────────────────────────────────
async def save_home(store: Any, place: dict[str, Any]) -> None:
    await store.execute(
        "INSERT INTO app_settings (id, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (HOME_KEY, json.dumps(place), datetime.now(timezone.utc).isoformat()),
    )


async def home_place(store: Any, settings: Any, http: httpx.AsyncClient) -> dict[str, Any] | None:
    """The city chosen in chat, else TAPAN_HOME_LOCATION; None if neither is a real city. May raise WeatherError."""
    row = await store.fetchone("SELECT value FROM app_settings WHERE id = ?", (HOME_KEY,))
    if row:
        try:
            place = json.loads(row["value"])
            if isinstance(place, dict) and "latitude" in place and "longitude" in place:
                return place
        except ValueError:
            pass
    configured = (settings.home_location or "").strip()
    if is_placeholder(configured):
        return None
    return await geocode(http, configured, settings.timezone)
