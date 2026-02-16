#!/usr/bin/env python3
"""
Setup Ollama for TAPAN_AI
Checks installation, service status, and pulls recommended models.
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(project_root))

from src.service.ollama_service import OllamaService

RECOMMENDED_MODELS = [
  "qwen2.5:7b",
  "llama3.2:3b",
]


def main():
  print("🔧 Setting up Ollama for TAPAN_AI...\n")

  # 1. Check installed
  if not OllamaService.check_installed():
    print("❌ Ollama not found!")
    print("Install from: https://ollama.com/download")
    print("\nOn Linux/Mac:")
    print("  curl https://ollama.com/install.sh | sh")
    print("\nOn Windows:")
    print("  Download from https://ollama.com/download")
    sys.exit(1)

  print("✅ Ollama installed")

  # 2. Check running
  if not OllamaService.is_running():
    print("⚠️  Ollama service not running")
    print("Start it with: ollama serve")
    print("Then re-run this script.")
    sys.exit(1)

  print("✅ Ollama service running")

  # 3. Pull recommended models
  print("\n📦 Pulling recommended models...")
  for model in RECOMMENDED_MODELS:
    print(f"  • Pulling {model}...", end=" ", flush=True)
    if OllamaService.pull_model(model):
      print("✅")
    else:
      print("⚠️ failed (you can pull it manually)")

  # 4. Show status
  print("\n📊 Final Status:")
  models = OllamaService.list_models()
  for model in models:
    print(f"  • {model}")

  print("\n✨ Setup complete! Try:")
  print("  python start_agent.py")
  print("  > ask what is 2+2?")
  print("  > llm status")


if __name__ == "__main__":
  main()
