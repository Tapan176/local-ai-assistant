"""Quick script to find available free models on OpenRouter."""
import httpx
import os
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("OPENROUTER_API_KEY", "")

r = httpx.get(
    "https://openrouter.ai/api/v1/models",
    headers={"Authorization": f"Bearer {api_key}"},
)
data = r.json()
models = data.get("data", [])

free_models = []
for m in models:
    pricing = m.get("pricing", {})
    prompt_price = float(pricing.get("prompt", "1") or "1")
    completion_price = float(pricing.get("completion", "1") or "1")
    if prompt_price == 0 and completion_price == 0:
        free_models.append(m["id"])

free_models.sort()
for fm in free_models:
    print(fm)
