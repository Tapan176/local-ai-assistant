"""
Ollama Service - Lifecycle management for Ollama LLM server
"""
import subprocess
import json
import urllib.request
import urllib.error
from typing import List, Dict, Optional


class OllamaService:
  """Manage Ollama service lifecycle: check, pull models, get status."""

  HOST = "http://localhost:11434"

  @staticmethod
  def check_installed() -> bool:
    """Check if Ollama binary is installed."""
    try:
      result = subprocess.run(
        ['ollama', '--version'],
        capture_output=True, timeout=5
      )
      return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
      return False

  @staticmethod
  def is_running() -> bool:
    """Check if Ollama service is running on localhost."""
    try:
      url = f"{OllamaService.HOST}/api/tags"
      req = urllib.request.Request(url, method='GET')
      with urllib.request.urlopen(req, timeout=3) as response:
        return response.status == 200
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
      return False

  @staticmethod
  def list_models() -> List[str]:
    """List installed models."""
    if not OllamaService.is_running():
      return []
    try:
      url = f"{OllamaService.HOST}/api/tags"
      req = urllib.request.Request(url, method='GET')
      with urllib.request.urlopen(req, timeout=5) as response:
        data = json.loads(response.read().decode())
        return [m['name'] for m in data.get('models', [])]
    except Exception:
      return []

  @staticmethod
  def pull_model(model_name: str) -> bool:
    """Pull a model from Ollama registry."""
    try:
      result = subprocess.run(
        ['ollama', 'pull', model_name],
        capture_output=True, timeout=600
      )
      return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
      return False

  @staticmethod
  def get_status() -> Dict:
    """Get full Ollama status."""
    installed = OllamaService.check_installed()
    running = OllamaService.is_running()
    models = OllamaService.list_models() if running else []

    return {
      'installed': installed,
      'running': running,
      'models': models,
      'model_count': len(models),
    }

  @staticmethod
  def format_status() -> str:
    """Get formatted status string for CLI display."""
    status = OllamaService.get_status()

    if not status['installed']:
      return "❌ Ollama not installed. Get it from: https://ollama.com/download"

    if not status['running']:
      return "⚠️ Ollama installed but not running. Start with: ollama serve"

    parts = [f"✅ Ollama running | {status['model_count']} models available"]
    for m in status['models']:
      parts.append(f"  • {m}")

    if not status['models']:
      parts.append("  ⚠️ No models. Run: ollama pull qwen2.5:7b")

    return "\n".join(parts)
