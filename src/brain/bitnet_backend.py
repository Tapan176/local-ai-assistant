"""
BitNet Backend - Local inference using compiled llama.cpp/BitNet
"""
import subprocess
import sys
import os
from pathlib import Path
from typing import Dict, List, Optional

class BitNetBackend:
  """Backend for running local GGUF/BitNet models via CLI"""

  def __init__(self, model_path: Optional[str] = None):
    self.name = "bitnet"
    self.tier = "heavy"
    self._model_path = model_path
    self._binary_path = None
    self.ready = False
    
    self._auto_configure()

  def _auto_configure(self):
    """Auto-detect binary and model paths"""
    try:
      project_root = Path(__file__).parent.parent.parent.resolve()
      bitnet_dir = project_root / "bitnet"
      
      # 1. Find Binary
      bin_dir = bitnet_dir / "bin"
      candidates = ["llama-cli.exe", "main.exe", "llama-server.exe"]
      
      for c in candidates:
        p = bin_dir / c
        if p.exists():
          self._binary_path = str(p)
          break
          
      if not self._binary_path:
        self.ready = False
        return

      # 2. Find Model
      if not self._model_path:
        models_dir = bitnet_dir / "models"
        # Search specifically for BitNet/TinyLlama first
        specific = models_dir / "tinyllama.gguf"
        if specific.exists():
          self._model_path = str(specific)
        else:
          # Find any .gguf
          ggufs = list(models_dir.glob("**/*.gguf"))
          if ggufs:
            self._model_path = str(ggufs[0])
            
      if self._binary_path and self._model_path and Path(self._model_path).exists():
        self.ready = True
      else:
        self.ready = False
        
    except Exception as e:
      print(f"BitNet Config Error: {e}")
      self.ready = False

  def generate(self, prompt: str, context: str = "", 
         max_tokens: int = 512, temperature: float = 0.7) -> str:
    """Generate response using subprocess CLI"""
    if not self.ready:
      return "BitNet model not found or configured."

    full_prompt = prompt
    if context:
      full_prompt = f"Context:\n{context}\n\nQuestion: {prompt}\n\nAnswer:"

    # Build command for llama-cli
    cmd = [
      self._binary_path,
      "-m", self._model_path,
      "-p", full_prompt,
      "-n", str(max_tokens),
      "--temp", str(temperature),
      "-t", "4",  # threads
      "--no-display-prompt", 
      "--log-disable"
    ]

    try:
      # Run blocking inference
      result = subprocess.run(
        cmd, 
        capture_output=True, 
        text=True, 
        encoding='utf-8',
        errors='ignore'
      )
      
      if result.returncode != 0:
        return f"[BitNet Error: {result.stderr.strip()}]"
        
      return result.stdout.strip()

    except Exception as e:
      return f"[BitNet Exception: {str(e)}]"

  def is_ready(self) -> bool:
    return self.ready
    
  def summarize(self, text: str) -> str:
    """Summarize using BitNet"""
    return self.generate(f"Summarize this:\n{text}", max_tokens=100)
    
  def classify(self, text: str) -> Dict:
    """Classify intent"""
    # Simple classification prompt
    prompt = f"Classify intent: {text}\nCategories: finance, planning, chat\nCategory:"
    res = self.generate(prompt, max_tokens=10)
    return {"category": res.strip().lower().split()[0], "confidence": 0.7}
