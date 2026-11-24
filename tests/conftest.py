"""Hermetic test environment.

Several tests build their settings with ``Settings.from_env()``, which loads the project's ``.env``. That file holds real
credentials (database URL, LLM keys), so without this guard a test run would write rows into the production database and
spend real LLM tokens. Variables that already exist in the process environment are NOT overridden by ``.env``, so we
pin them to safe values *before* any test module imports the settings.

Database integration tests use their own explicit DSN (embedded Postgres, or TAPAN_TEST_DATABASE_URL) and never read these.
"""

from __future__ import annotations

import os

_BLANK = (
    "TAPAN_DATABASE_URL",
    "DATABASE_URL",
    "OPENROUTER_API_KEY",
    "openrouterKey",
    "OMNIROUTE_API_KEY",
    "TAPAN_OMNIROUTE_API_KEY",
    "TAPAN_SUPERMEMORY_API_KEY",
    "TAPAN_API_TOKEN",
)
for _name in _BLANK:
    os.environ[_name] = ""

os.environ["TAPAN_LLM_PROVIDER"] = "mock"
os.environ["TAPAN_ENV"] = "local"
os.environ["TAPAN_INTENT_CLASSIFIER"] = "heuristic"

from src.config.settings import Settings  # noqa: E402  (must come after the environment is pinned)

_leaked = Settings.from_env()
assert not _leaked.database_url, "tests must never run against a real database"
assert not (_leaked.openrouter_api_key or _leaked.omniroute_api_key), "tests must never call a real LLM"
assert _leaked.llm_provider == "mock"
