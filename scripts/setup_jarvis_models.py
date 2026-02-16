"""
Jarvis Model Setup Script
Pulls recommended models for TAPAN_AI (Jarvis) and updates configuration.
"""
import subprocess
import sys
import time
from pathlib import Path

# Recommended Models
MODELS = [
    "llama3.2:3b",       # Fast, chatty, good for Jarvis voice loop
    "phi3:mini",         # Strong reasoning, good for planning
    "nomic-embed-text"   # Efficient embeddings for RAG
]

def run_command(cmd):
    """Run shell command and stream output."""
    print(f"Running: {cmd}")
    try:
        process = subprocess.Popen(
            cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        for line in process.stdout:
            print(line, end="")
        process.wait()
        return process.returncode == 0
    except Exception as e:
        print(f"Error: {e}")
        return False

def check_ollama():
    """Check if Ollama is running."""
    print("Checking Ollama status...")
    if run_command("ollama list"):
        return True
    print("❌ Ollama is not running or not installed.")
    print("Please install Ollama from https://ollama.ai and run 'ollama serve'.")
    return False

def pull_models():
    """Pull required models."""
    print("\n📦 Pulling Jarvis Models (This may take time)...")
    for model in MODELS:
        print(f"\n⬇️ Pulling {model}...")
        if not run_command(f"ollama pull {model}"):
            print(f"❌ Failed to pull {model}")
        else:
            print(f"✅ {model} ready.")

def update_config():
    """Ensure configs/ollama.yaml is optimized."""
    config_path = Path(__file__).parent.parent / "configs" / "ollama.yaml"
    
    # Check if we need to update
    if config_path.exists():
        content = config_path.read_text()
        if "default_model: llama3.2:3b" in content:
            print("\n✅ Configuration already optimized.")
            return

    print("\n⚙️ Updating configs/ollama.yaml...")
    config_content = """ollama:
  host: http://localhost:11434
  default_model: llama3.2:3b
  fallback_models:
    - phi3:mini
    - qwen2.5:14b
    - gemma2:2b
  gpu_enabled: auto
  max_retries: 3
  timeout: 30
  stream: true
"""
    config_path.parent.mkdir(exist_ok=True)
    config_path.write_text(config_content)
    print("✅ Configuration updated.")

def main():
    print("🚀 Setting up Tapan_AI (Jarvis) Neural Engine...")
    
    if not check_ollama():
        sys.exit(1)
        
    pull_models()
    update_config()
    
    print("\n✨ Setup Complete! Jarvis is ready.")
    print("Run 'python start.py' to start.")

if __name__ == "__main__":
    main()
