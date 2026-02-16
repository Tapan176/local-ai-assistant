"""
BitNet Local Backend
Runs llama-cli.exe directly via subprocess
"""
import subprocess
import json
from pathlib import Path
from typing import Optional

class BitNetLocal:
  """Direct execution of BitNet via llama-cli"""

  def __init__(self, binary_path: str, model_path: str):
    self.binary_path = Path(binary_path).resolve()
    self.model_path = Path(model_path).resolve()

  def check_health(self) -> bool:
    """Check if binary and model exist"""
    return self.binary_path.exists() and self.model_path.exists()

  def generate(self, prompt: str, system: str = "") -> Optional[str]:
    """Generate text using subprocess"""
    try:
      # Construct full prompt with system prompt if needed
      # Basic prompt format for now, can be adjusted for specific model templates
      full_prompt = f"{system}\nUser: {prompt}\nAssistant:" if system else f"User: {prompt}\nAssistant:"

      cmd = [
        str(self.binary_path),
        "-m", str(self.model_path),
        "-p", full_prompt,
        "-n", "512",       # Max tokens
        "--temp", "0.7",   # Temperature
        "--no-display-prompt", # Don't echo prompt
        "-c", "2048"       # Context size
      ]

      print(f"\n   (Local AI taking over... loading {self.model_path.name})...")

      # Run process
      result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding='utf-8', # Force UTF-8
        errors='replace',
        timeout=120  # 2 minute timeout
      )

      if result.returncode == 0:
        # Output might contain logs on stderr, stdout should be the text
        # Ideally we need to parse out just the response if the binary is chatty
        return result.stdout.strip()
      else:
        print(f"BitNet Local Error: {result.stderr}")
        return None

    except subprocess.TimeoutExpired:
      print("❌ BitNet Local Timeout (2 mins)")
      return None
    except Exception as e:
      print(f"BitNet Execution Error: {e}")
      return None
