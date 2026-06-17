import asyncio
import os
import time
from dotenv import load_dotenv
from supermemory import Supermemory

load_dotenv()

def test_supermemory_sync():
    api_key = os.getenv("TAPAN_SUPERMEMORY_API_KEY")
    client = Supermemory(api_key=api_key)
    
    # 1. ADD correctly
    print("--- Adding correctly ---")
    res = client.add(
        content="User likes to eat lasagna on Sundays with the family.",
        container_tag="verified_lasagna_tag", # String, not list
        metadata={"source": "test", "topic": "food"}
    )
    print("Add Response:", res)
    
    print("Waiting 15 seconds for backend to process...")
    time.sleep(15)
    
    # 2. SEARCH correctly
    print("--- Searching correctly ---")
    search_res = getattr(client.search, "execute")(
        q="lasagna",
        categories_filter=["verified_lasagna_tag"] # List of strings
    )
    results = getattr(search_res, "results", [])
    print(f"Results length: {len(results)}")
    
    for i, r in enumerate(results[:3]):
        print(f"[{i}] {r}")

if __name__ == "__main__":
    test_supermemory_sync()
