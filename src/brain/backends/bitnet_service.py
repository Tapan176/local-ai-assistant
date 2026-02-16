"""
BitNet Backend Service
Connects to local BitNet API (port 11435) for deep reasoning
"""
import requests
import json
from typing import Optional

class BitNetService:
  """Client for local BitNet inference service"""

  def __init__(self, base_url: str = "http://localhost:11435"):
    self.base_url = base_url

  def check_health(self) -> bool:
    """Check if BitNet service is reachable"""
    try:
      r = requests.get(f"{self.base_url}/health", timeout=2)
      return r.status_code == 200
    except:
      return False

  def generate(self, prompt: str, system: str = "") -> Optional[str]:
    """Generate text using BitNet"""
    try:
      payload = {
        "prompt": prompt,
        "system": system,
        "stream": False
      }

      r = requests.post(f"{self.base_url}/generate", json=payload, timeout=60)

      if r.status_code == 200:
        return r.json().get('response', '')
      else:
        print(f"BitNet Error: {r.status_code} - {r.text}")

    except Exception as e:
      print(f"BitNet connection error: {e}")

    return None
