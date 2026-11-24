"""Weather: geocoding quirks, provider fallback (Open-Meteo -> MET Norway -> wttr.in), caching, stale fallback, the home city, the briefing."""

from __future__ import annotations

import asyncio
import json
import time

import httpx
import pytest

from src.agent import weather
from src.agent.skill import SkillContext
from src.agent.skills import build_registry
from src.agent.skills.briefing import build_briefing
from src.config.settings import Settings
from src.storage.sqlite_store import SQLiteStore

KOLKATA = "Asia/Kolkata"


def place(name, admin1, country, cc, pop, tz, lat=10.0, lon=20.0):
    return {"name": name, "admin1": admin1, "country": country, "country_code": cc, "population": pop,
            "timezone": tz, "latitude": lat, "longitude": lon}


# Shapes copied from what the real geocoder returns (it only knows current official names, and matches a bare name only).
GEO = {
    "bengaluru": [place("Bengaluru", "Karnataka", "India", "IN", 8495492, KOLKATA, 12.97, 77.59)],
    "bangalore": [place("Bangalore Town", "Sindh", "Pakistan", "PK", None, "Asia/Karachi", 24.9, 67.0)],
    "mumbai": [place("Mumbai", "Maharashtra", "India", "IN", 12691836, KOLKATA, 19.07, 72.88)],
    "pune": [place("Pune", "Maharashtra", "India", "IN", 3124458, KOLKATA, 18.52, 73.86)],
    "surat": [place("Surat", "Auvergne-Rhône-Alpes", "France", "FR", 405, "Europe/Paris", 45.0, 4.0),
              place("Surat", "Queensland", "Australia", "AU", 405, "Australia/Brisbane", -27.1, 149.0),
              place("Surat", "Gujarat", "India", "IN", 4591246, KOLKATA, 21.17, 72.83)],
    "london": [place("London", "England", "United Kingdom", "GB", 8961989, "Europe/London", 51.5, -0.12),
               place("London", "Ontario", "Canada", "CA", 352395, "America/Toronto", 42.98, -81.25),
               place("London", "Kentucky", "United States", "US", 7993, "America/New_York", 37.1, -84.0)],
    "home": [place("Homyel", "Gomel Region", "Belarus", "BY", 481000, "Europe/Minsk", 52.4, 31.0)],   # the bug: a placeholder resolving to a real place
}
FORECAST = {
    "current": {"temperature_2m": 30.0, "apparent_temperature": 31.1, "relative_humidity_2m": 44, "wind_speed_10m": 7.2, "weather_code": 0},
    "daily": {"time": ["2026-11-24", "2026-11-25"], "temperature_2m_max": [31, 30], "temperature_2m_min": [20, 19],
              "precipitation_probability_max": [0, None], "weather_code": [0, 999]},
}


# Shapes copied from the real MET Norway (compact) and wttr.in (j1) responses, trimmed. Times are UTC, as MET sends them.
def met_entry(time_utc, temp, symbol, pop=None, humidity=50.0, wind=2.0):
    block = {"summary": {"symbol_code": symbol}, "details": {} if pop is None else {"probability_of_precipitation": pop}}
    return {"time": time_utc, "data": {"instant": {"details": {"air_temperature": temp, "relative_humidity": humidity, "wind_speed": wind}},
                                       "next_6_hours": block, "next_1_hours": {"summary": {"symbol_code": symbol}, "details": {}}}}


MET = {"properties": {"timeseries": [
    met_entry("2026-11-24T10:00:00Z", 30.0, "partlycloudy_day", 10, 44.0, 2.0),      # 15:30 in Kolkata, the 24th
    met_entry("2026-11-24T18:00:00Z", 24.0, "clearsky_night"),                       # 23:30 on the 24th
    met_entry("2026-11-24T19:00:00Z", 22.0, "clearsky_night"),                       # 00:30 on the 25th: a new LOCAL day
    met_entry("2026-11-25T06:30:00Z", 29.0, "lightrainshowers_day", 60),             # 12:00 on the 25th
]}}
WTTR = {"current_condition": [{"temp_C": "31", "FeelsLikeC": "33", "humidity": "40", "windspeedKmph": "9", "weatherDesc": [{"value": "Sunny"}]}],
        "weather": [{"date": "2026-11-24", "maxtempC": "32", "mintempC": "21",
                     "hourly": [{"chanceofrain": "0"}, {"chanceofrain": "0"}, {"chanceofrain": "0"}, {"chanceofrain": "0"},
                                {"chanceofrain": "20", "weatherDesc": [{"value": "Partly cloudy"}]}]}]}
NOMINATIM = [{"name": "Surat", "lat": "21.1702", "lon": "72.8311", "display_name": "Surat, Gujarat, India",
              "address": {"state": "Gujarat", "country": "India", "country_code": "in"}},
             {"name": "Surat", "lat": "-27.1", "lon": "149.0", "display_name": "Surat, Queensland, Australia",
              "address": {"state": "Queensland", "country": "Australia", "country_code": "au"}}]


class FakeOpenMeteo:
    def __init__(self):
        self.geo_calls, self.forecast_calls = [], 0
        self.forecast_script: list = []        # consumed in order: ints are HTTP statuses, exceptions are raised, dicts are bodies, "badjson" is garbage
        self.geo_status = 200                  # set to 429 to simulate the shared-IP rate limit that broke production
        self.met_calls = self.wttr_calls = self.nominatim_calls = 0
        self.met_script: list = []             # same scripting, for the fallbacks; by default they are "down" (503) so only Open-Meteo answers
        self.wttr_script: list = []
        self.nominatim_script: list = []
        self.user_agents: dict[str, str] = {}

    @staticmethod
    def _reply(script: list, default) -> httpx.Response:
        step = script.pop(0) if script else default
        if isinstance(step, Exception):
            raise step
        if isinstance(step, int):
            return httpx.Response(step, json={"reason": "x"})
        return httpx.Response(200, json=step)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        self.user_agents[host] = request.headers.get("user-agent", "")
        if host == "api.met.no":
            self.met_calls += 1
            return self._reply(self.met_script, 503)
        if host == "wttr.in":
            self.wttr_calls += 1
            return self._reply(self.wttr_script, 503)
        if host == "nominatim.openstreetmap.org":
            self.nominatim_calls += 1
            return self._reply(self.nominatim_script, 503)
        if host == "geocoding-api.open-meteo.com":
            name = request.url.params["name"]
            assert int(request.url.params["count"]) >= 5, "ranking needs more than one candidate"
            self.geo_calls.append(name)
            if self.geo_status != 200:
                return httpx.Response(self.geo_status, json={"reason": "x"})
            results = GEO.get(name)
            return httpx.Response(200, json={"results": results} if results else {"generationtime_ms": 0.2})
        assert host == "api.open-meteo.com"
        self.forecast_calls += 1
        step = self.forecast_script.pop(0) if self.forecast_script else FORECAST
        if isinstance(step, Exception):
            raise step
        if step == "badjson":
            return httpx.Response(200, content=b"<html>oops</html>")
        if isinstance(step, int):
            return httpx.Response(step, json={"reason": "x"})
        return httpx.Response(200, json=step)


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    weather.clear_caches()
    monkeypatch.setattr(weather, "RETRY_DELAYS", (0, 0))
    yield
    weather.clear_caches()


@pytest.fixture
def api():
    return FakeOpenMeteo()


@pytest.fixture
async def http(api):
    async with httpx.AsyncClient(transport=httpx.MockTransport(api)) as client:
        yield client


@pytest.fixture
def settings():
    return Settings(llm_provider="mock", environment="local", sqlite_path=":memory:", timezone=KOLKATA, home_location="")


@pytest.fixture
async def store():
    s = SQLiteStore(":memory:")
    await s.initialize()
    return s


# ── geocoding ───────────────────────────────────────────────────────
async def test_renamed_indian_cities_are_translated_for_indian_users(http, api):
    got = await weather.geocode(http, "Bangalore", KOLKATA)
    assert got["name"] == "Bengaluru" and got["country"] == "India"
    assert api.geo_calls == ["bengaluru"]                                        # asked for the official name first
    weather.clear_caches()
    assert (await weather.geocode(http, "Bombay", KOLKATA))["name"] == "Mumbai"
    weather.clear_caches()
    abroad = await weather.geocode(http, "Bangalore", "America/New_York")        # not applied outside India: could be somewhere else
    assert abroad["country"] == "Pakistan"


@pytest.mark.parametrize("query,tz,country", [
    ("Surat", KOLKATA, "India"), ("Surat", "", "India"),                         # population alone picks the big one too
    ("Surat, France", KOLKATA, "France"), ("Surat, Gujarat", "Europe/Paris", "India"), ("surat , AU", "", "Australia"),
    ("London, UK", "", "United Kingdom"), ("London, United Kingdom", "", "United Kingdom"), ("London, Ontario", "", "Canada"),
    ("London, Canada", "", "Canada"), ("London, USA", "", "United States"), ("  London  ", "Europe/London", "United Kingdom"),
])
async def test_ambiguous_names_pick_the_intended_place(http, query, tz, country):
    assert (await weather.geocode(http, query, tz))["country"] == country


async def test_postal_codes_are_dropped_when_the_full_string_finds_nothing(http, api):
    assert (await weather.geocode(http, "Pune 411001", KOLKATA))["name"] == "Pune"
    assert api.geo_calls == ["pune 411001", "pune"]


@pytest.mark.parametrize("placeholder", ["home", "Home", "HOME ", "here", "my city", "your-city", "", "  ", "changeme", "TBD", "n/a"])
async def test_placeholders_are_never_sent_to_the_geocoder(http, api, placeholder):
    with pytest.raises(weather.WeatherError, match="don't know your city"):
        await weather.geocode(http, placeholder)
    assert api.geo_calls == []                                                   # "home" must never become Homyel, Belarus


async def test_unknown_place_has_a_helpful_message(http):
    with pytest.raises(weather.WeatherError, match="couldn't find a place called “Atlantis”"):
        await weather.geocode(http, "Atlantis")


async def test_geocoding_is_cached(http, api):
    for _ in range(3):
        await weather.geocode(http, "Mumbai", KOLKATA)
    await weather.geocode(http, "  mumbai ", KOLKATA)                            # same place, different spelling of spaces/case
    assert api.geo_calls == ["mumbai"]


# ── resilience ──────────────────────────────────────────────────────
async def test_transient_failures_are_retried(http, api):
    api.forecast_script = [503, httpx.ConnectTimeout("slow"), FORECAST]
    text = await weather.fetch_weather(http, "Mumbai", 2, KOLKATA)
    assert api.forecast_calls == 3 and text.startswith("Mumbai, Maharashtra, India: now 30.0°C")
    assert api.met_calls == 0                                                    # the fallback is for a provider that stays down, not a blip


async def test_forecast_is_cached_so_the_today_panel_does_not_hammer_the_api(http, api):
    for _ in range(10):
        await weather.fetch_weather(http, "Mumbai", 1, KOLKATA)
    assert api.forecast_calls == 1 and api.geo_calls == ["mumbai"]


@pytest.mark.parametrize("script,message", [
    ([503, 503, 503], "busy or unreachable"),
    ([429, 429, 429], "busy or unreachable"),
    ([httpx.ConnectTimeout("slow")] * 3, "busy or unreachable"),
    ([httpx.ConnectError("dns")] * 3, "busy or unreachable"),
    (["badjson"], "unreadable"),
    ([{"current": None}], "incomplete"),
])
async def test_failures_become_plain_messages_not_stack_traces(http, api, script, message):
    api.forecast_script = list(script)
    with pytest.raises(weather.WeatherError, match=message):
        await weather.fetch_weather(http, "Mumbai", 1, KOLKATA)


async def test_client_errors_are_not_retried(http, api):
    api.forecast_script = [400]
    with pytest.raises(weather.WeatherError, match="rejected the request \\(HTTP 400\\)"):
        await weather.fetch_weather(http, "Mumbai", 1, KOLKATA)
    assert api.forecast_calls == 1


async def test_last_good_forecast_is_served_when_the_service_is_down(http, api):
    await weather.fetch_weather(http, "Mumbai", 1, KOLKATA)
    key = next(iter(weather._FORECAST._data))
    fresh_until, stored_at, value = weather._FORECAST._data[key]
    weather._FORECAST._data[key] = (0, time.monotonic() - 1500, value)           # expired 25 minutes ago
    api.forecast_script = [503, 503, 503]
    text = await weather.fetch_weather(http, "Mumbai", 1, KOLKATA)
    assert "Live data unavailable; this is from 25 min ago" in text and "30.0°C" in text
    weather._FORECAST._data[key] = (0, time.monotonic() - weather.STALE_OK_SECONDS - 60, value)   # too old to be useful
    api.forecast_script = [503, 503, 503]
    with pytest.raises(weather.WeatherError):
        await weather.fetch_weather(http, "Mumbai", 1, KOLKATA)


async def test_formatting_survives_missing_and_unknown_values(http, api):
    api.forecast_script = [{"current": {"temperature_2m": 5}, "daily": {"time": ["2026-11-24", "2026-11-25"], "weather_code": [999]}}]
    text = await weather.fetch_weather(http, "Mumbai", 2, KOLKATA)
    assert "now 5°C (feels –)" in text and "unknown conditions" in text and "rain chance –" in text
    api.forecast_script = [FORECAST]
    weather.clear_caches()
    text = await weather.fetch_weather(http, "Mumbai", 2, KOLKATA)
    assert "2026-11-25: 19–30°C, unknown conditions, rain chance –" in text      # null precipitation and an unmapped weather code


async def test_cache_is_bounded(http, api):
    for i in range(weather.CACHE_MAX + 20):
        weather._GEO.put(("k", i), {"x": i})
    assert len(weather._GEO._data) == weather.CACHE_MAX


# ── provider fallback (the production failure: Open-Meteo answers 429 for every request from Render's shared IPs) ──
async def test_rate_limited_primary_falls_back_to_met_norway(http, api):
    api.forecast_script = [429]
    api.met_script = [MET]
    text = await weather.fetch_weather(http, "Mumbai", 2, KOLKATA)
    assert "now 30.0°C" in text and "partly cloudy" in text and "humidity 44%" in text and "wind 7.2 km/h" in text
    assert api.forecast_calls == 1 and api.met_calls == 1                       # 429 is not retried: it would only make the limit worse


async def test_a_rate_limited_provider_is_skipped_for_the_cooldown_not_asked_again(http, api):
    api.forecast_script = [429]
    api.met_script = [MET, MET, MET]
    await weather.fetch_weather(http, "Mumbai", 2, KOLKATA)
    weather._FORECAST.clear()                                                    # force a refetch, as after the 10 minute cache
    await weather.fetch_weather(http, "Mumbai", 2, KOLKATA)
    await weather.fetch_weather(http, "Pune", 2, KOLKATA)
    assert api.forecast_calls == 1 and api.met_calls == 3
    weather._COOLDOWN["open-meteo"] = time.monotonic() - 1                       # cooldown over: the primary is tried again
    weather._FORECAST.clear()
    api.forecast_script = [FORECAST]
    await weather.fetch_weather(http, "Mumbai", 2, KOLKATA)
    assert api.forecast_calls == 2


async def test_met_days_follow_the_local_calendar_not_utc(http, api):
    api.forecast_script, api.met_script = [429], [MET]
    place_ = {"name": "Mumbai", "admin1": "", "country": "", "latitude": 19.07, "longitude": 72.88, "timezone": KOLKATA}
    data = await weather.forecast(http, place_, 2)
    daily = data["daily"]
    assert daily["time"] == ["2026-11-24", "2026-11-25"]
    assert daily["temperature_2m_max"] == [30.0, 29.0] and daily["temperature_2m_min"] == [24.0, 22.0]   # 00:30 IST belongs to the 25th
    assert daily["precipitation_probability_max"] == [10, 60]
    assert daily["weather_code"] == [2, 80]                                      # partlycloudy_day -> 2, lightrainshowers_day -> 80


@pytest.mark.parametrize("symbol,code", [
    ("clearsky_day", 0), ("clearsky_night", 0), ("fair_polartwilight", 1), ("cloudy", 3), ("fog", 45), ("heavyrain", 65),
    ("rainandthunder", 95), ("lightrainshowersandthunder_day", 95), ("snow", 73), ("heavysleetshowers_night", 67), ("brandnew_symbol", None),
])
def test_met_symbols_map_to_wmo_codes(symbol, code):
    assert weather._met_code(symbol) == code


async def test_wttr_is_the_last_resort_and_uses_its_own_description(http, api):
    api.forecast_script = [429]
    api.met_script = [503, 503, 503]
    api.wttr_script = [WTTR]
    text = await weather.fetch_weather(http, "Mumbai", 1, KOLKATA)
    assert "now 31.0°C (feels 33.0°C), sunny, humidity 40%, wind 9.0 km/h" in text
    assert "2026-11-24: 21.0–32.0°C, partly cloudy, rain chance 20%" in text


async def test_all_providers_down_gives_the_first_providers_plain_message(http, api):
    api.forecast_script = [503, 503, 503]
    with pytest.raises(weather.WeatherError, match="busy or unreachable"):
        await weather.fetch_weather(http, "Mumbai", 1, KOLKATA)
    assert api.forecast_calls == 3 and api.met_calls == 3 and api.wttr_calls == 3  # each provider got its retries, then the next was tried


async def test_garbage_from_a_fallback_is_an_error_not_a_crash(http, api):
    api.forecast_script, api.met_script, api.wttr_script = [429], [{"properties": {"timeseries": []}}], [{"weather": []}]
    with pytest.raises(weather.WeatherError):
        await weather.fetch_weather(http, "Mumbai", 1, KOLKATA)


async def test_stale_forecast_still_covers_a_total_outage_with_fallbacks_down_too(http, api):
    await weather.fetch_weather(http, "Mumbai", 1, KOLKATA)
    key = next(iter(weather._FORECAST._data))
    _, _, value = weather._FORECAST._data[key]
    weather._FORECAST._data[key] = (0, time.monotonic() - 1500, value)
    api.forecast_script = [429]
    text = await weather.fetch_weather(http, "Mumbai", 1, KOLKATA)
    assert "this is from 25 min ago" in text


async def test_geocoding_falls_back_to_nominatim_when_the_primary_is_rate_limited(http, api):
    api.geo_status = 429
    api.nominatim_script = [NOMINATIM]
    got = await weather.geocode(http, "Surat, India", KOLKATA)
    assert got["name"] == "Surat" and got["country"] == "India" and abs(got["latitude"] - 21.1702) < 1e-6
    assert got["timezone"] == KOLKATA                                            # Nominatim has no zone: the user's own is the best guess
    await weather.geocode(http, "Surat, India", KOLKATA)                         # cached: neither service is asked again
    assert api.nominatim_calls == 1 and api.geo_calls == ["surat"]


async def test_geocode_unknown_place_does_not_fall_back_and_unavailable_is_distinct(http, api):
    with pytest.raises(weather.WeatherError, match="couldn't find a place called “Atlantis”"):
        await weather.geocode(http, "Atlantis")
    assert api.nominatim_calls == 0                                              # the geocoder answered; the fallback would only guess
    api.geo_status = 503
    with pytest.raises(weather.WeatherError, match="busy or unreachable"):
        await weather.geocode(http, "Surat")                                     # both geocoders down (nominatim defaults to 503)


async def test_requests_to_third_parties_identify_the_software_never_the_user(http, api):
    api.forecast_script, api.met_script = [429], [MET]
    await weather.fetch_weather(http, "Mumbai", 1, KOLKATA)
    api.geo_status, api.nominatim_script = 429, [NOMINATIM]
    await weather.geocode(http, "Surat", KOLKATA)
    for host in ("api.met.no", "nominatim.openstreetmap.org"):
        agent = api.user_agents[host].lower()
        assert agent.startswith("personal-assistant-weather/") and "tapan" not in agent and "@" not in agent and "github" not in agent


# ── skills ──────────────────────────────────────────────────────────
@pytest.fixture
async def ctx(http, settings, store):
    return SkillContext(settings=settings, store=store, http=http, session_id="t")


async def run(settings, ctx, name, **args):
    return await build_registry(settings).execute(name, args, ctx)


async def test_weather_without_a_city_asks_for_one_instead_of_guessing(settings, ctx, api):
    ok, text = await run(settings, ctx, "get_weather")
    assert ok and "don't know your city" in text and "set_home_location" in text and api.geo_calls == []


async def test_placeholder_in_the_env_var_is_ignored_like_unset(settings, ctx, api):
    settings.home_location = "home"
    ok, text = await run(settings, ctx, "get_weather")
    assert "don't know your city" in text and api.geo_calls == []


async def test_a_real_env_city_works(settings, ctx):
    settings.home_location = "Surat, Gujarat"
    ok, text = await run(settings, ctx, "get_weather", days=1)
    assert ok and text.startswith("Surat, Gujarat, India: now 30.0°C")


async def test_home_city_is_set_in_chat_stored_and_reused_without_geocoding(settings, ctx, api, store):
    ok, text = await run(settings, ctx, "set_home_location", city="Pune 411001")
    assert ok and "Home city saved: Pune, Maharashtra, India" in text
    api.geo_calls.clear()
    ok, text = await run(settings, ctx, "get_weather")
    assert text.startswith("Pune, Maharashtra, India: now") and api.geo_calls == []          # coordinates were stored: no lookup needed
    await run(settings, ctx, "set_home_location", city="Mumbai")                              # changing it replaces, not duplicates
    assert (await store.fetchone("SELECT COUNT(*) AS n FROM app_settings WHERE id = 'home_location'"))["n"] == 1
    assert "Mumbai" in (await run(settings, ctx, "get_weather"))[1]


async def test_chat_choice_wins_over_the_env_var(settings, ctx):
    settings.home_location = "London"
    await run(settings, ctx, "set_home_location", city="Surat")
    assert "Surat" in (await run(settings, ctx, "get_weather"))[1]


async def test_an_unknown_home_city_is_rejected_and_not_saved(settings, ctx, store):
    ok, text = await run(settings, ctx, "set_home_location", city="Atlantis")
    assert "couldn't find" in text and (await store.fetchone("SELECT COUNT(*) AS n FROM app_settings"))["n"] == 0
    ok, text = await run(settings, ctx, "set_home_location", city="home")
    assert "don't know your city" in text and (await store.fetchone("SELECT COUNT(*) AS n FROM app_settings"))["n"] == 0


async def test_explicit_location_overrides_home(settings, ctx):
    await run(settings, ctx, "set_home_location", city="Surat")
    assert "London, England, United Kingdom" in (await run(settings, ctx, "get_weather", location="London, UK"))[1]


async def test_service_outage_is_reported_to_the_model_as_text(settings, ctx, api):
    api.forecast_script = [503, 503, 503]
    ok, text = await run(settings, ctx, "get_weather", location="Mumbai")
    assert ok and "busy or unreachable" in text


# ── briefing ────────────────────────────────────────────────────────
async def test_briefing_says_when_no_city_is_set(settings, ctx):
    data = await build_briefing(ctx)
    assert data["home_location"] is None and "weather" not in data and "weather_error" not in data


async def test_briefing_includes_weather_for_the_saved_city(settings, ctx):
    await run(settings, ctx, "set_home_location", city="Surat")
    data = await build_briefing(ctx)
    assert data["home_location"] == "Surat, Gujarat, India" and data["weather"].startswith("Surat, Gujarat, India: now")


async def test_briefing_survives_and_explains_a_weather_outage(settings, ctx, api):
    await run(settings, ctx, "set_home_location", city="Surat")
    weather.clear_caches()
    api.forecast_script = [503, 503, 503]
    data = await build_briefing(ctx)
    assert "weather" not in data and "busy or unreachable" in data["weather_error"] and "open_tasks" in data and data["home_location"]


async def test_briefing_never_hangs_on_slow_weather(settings, ctx, monkeypatch):
    async def never(*a, **k):
        raise asyncio.TimeoutError
    await run(settings, ctx, "set_home_location", city="Surat")
    monkeypatch.setattr(weather, "weather_text", never)
    assert "slow" in (await build_briefing(ctx))["weather_error"]


async def test_briefing_reports_an_unresolvable_env_city(settings, ctx):
    settings.home_location = "Atlantis"
    data = await build_briefing(ctx)
    assert "couldn't find" in data["weather_error"] and data["home_location"] is None
