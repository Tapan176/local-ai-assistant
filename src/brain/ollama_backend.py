"""
Ollama Backend - Local LLM server with streaming + model management
Phase 16: Enhanced with streaming, model switching, retry logic
"""
import json
import urllib.request
import urllib.error
from typing import Optional, Dict, List, Iterator
from pathlib import Path


class OllamaConnectionError(Exception):
  """Raised when Ollama is not reachable or returns an error."""
  pass


class OllamaBackend:
  """Backend for Ollama local LLM server.

  Connects to Ollama API at localhost:11434.
  Supports generate, streaming, summarize, classify, model switching.
  """

  def __init__(self, base_url: str = "http://localhost:11434",
               timeout: int = 30, max_retries: int = 3):
    self.base_url = base_url.rstrip('/')
    self.timeout = timeout
    self.max_retries = max_retries
    self.name = "ollama"
    self.current_model: str = ""  # Safe default
    self._available_models: List[str] = []
    self._is_ready: bool = False
    
    # Configuration
    self.config = self._load_config()
    if self.config.get("default_model"):
      self.current_model = self.config["default_model"]

  def _load_config(self) -> Dict:
    """Load config from configs/ollama.yaml (Manual parsing to avoid PyYAML dependency)."""
    try:
      config_path = Path(__file__).parent.parent.parent / "configs" / "ollama.yaml"
      if not config_path.exists():
        return {}
      
      conf = {"fallback_models": []}
      is_fallback_section = False
      
      for line in config_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"): continue
        
        if line.startswith("default_model:"):
          conf["default_model"] = line.split(":", 1)[1].strip()
          is_fallback_section = False
        elif line.startswith("fallback_models:"):
          is_fallback_section = True
        elif is_fallback_section and line.startswith("-"):
          model = line.replace("-", "").strip()
          conf["fallback_models"].append(model)
        elif ":" in line:
          is_fallback_section = False
          
      return conf
    except Exception:
      return {}

  def is_ready(self) -> bool:
    """Check if Ollama server is running."""
    if self._is_ready is not None:
      return self._is_ready

    try:
      url = f"{self.base_url}/api/tags"
      req = urllib.request.Request(url, method='GET')
      with urllib.request.urlopen(req, timeout=5) as response:
        self._is_ready = response.status == 200
        return self._is_ready
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
      self._is_ready = False
      return False

  # Alias for compatibility with user's spec
  is_available = is_ready

  def _get_model(self) -> str:
    """Get current model, auto-detecting if not set."""
    if self.current_model:
      return self.current_model

    # 1. Configured default
    cfg_default = self.config.get("default_model")
    if cfg_default and self.has_model(cfg_default):
      self.current_model = cfg_default
      return self.current_model

    # 2. Configured fallbacks
    for fb in self.config.get("fallback_models", []):
      if self.has_model(fb):
        self.current_model = fb
        return self.current_model
        
    # 3. Smart Defaults (Jarvis Optimization)
    # Prefer faster models if available
    preferred = ["llama3.2:3b", "phi3:mini", "gemma2:2b", "qwen2.5:7b"]
    for p in preferred:
      if self.has_model(p):
        self.current_model = p
        return self.current_model

    # 4. Auto-detect: pick first available
    models = self.list_models()
    if models:
      self.current_model = models[0]
      return self.current_model

    # 5. Last resort
    return "qwen2.5:7b"

  def list_models(self) -> List[str]:
    """Get list of available models from Ollama."""
    if not self.is_ready():
      return []

    if self._available_models is not None:
      return self._available_models

    try:
      url = f"{self.base_url}/api/tags"
      req = urllib.request.Request(url, method='GET')
      with urllib.request.urlopen(req, timeout=self.timeout) as response:
        data = json.loads(response.read().decode())
        self._available_models = [m['name'] for m in data.get('models', [])]
        return self._available_models
    except Exception:
      return []

  def has_model(self, model_name: str) -> bool:
    """Check if a specific model is available."""
    models = self.list_models()
    return any(model_name in m or m in model_name for m in models)

  def switch_model(self, model_name: str) -> bool:
    """Switch the active model.

    Returns True if model is available and switched.
    """
    if self.has_model(model_name):
      self.current_model = model_name
      return True
    return False

  def generate(self, prompt: str, context: str = "",
               model: str = None, **kwargs) -> str:
    """Generate response using Ollama with retry logic.

    Args:
      prompt: User prompt
      context: Additional context
      model: Model name (uses current_model if None)
      **kwargs: Additional options (e.g., max_tokens, temperature)

    Returns:
      Generated text response
    """
    if not self.is_ready():
      return "[Ollama not available]"

    model = model or self._get_model()

    # Build full prompt with context
    full_prompt = prompt
    if context:
      full_prompt = f"Context:\n{context}\n\nQuestion: {prompt}\n\nAnswer:"

    # Map kwargs to Ollama options
    options = {
      "temperature": kwargs.get("temperature", 0.7),
      "num_predict": kwargs.get("max_tokens", 512),  # Map max_tokens to num_predict
      **{k: v for k, v in kwargs.items() if k not in ["temperature", "max_tokens"]}
    }

    last_error = None
    for attempt in range(self.max_retries):
      try:
        url = f"{self.base_url}/api/generate"
        payload = {
          "model": model,
          "prompt": full_prompt,
          "stream": False,
          "options": options
        }

        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
          url,
          data=data,
          headers={'Content-Type': 'application/json'},
          method='POST'
        )

        with urllib.request.urlopen(req, timeout=self.timeout) as response:
          result = json.loads(response.read().decode())
          return result.get('response', '[No response]')

      except urllib.error.HTTPError as e:
        if e.code == 404:
          return f"[Model '{model}' not found. Run: ollama pull {model}]"
        last_error = e
      except Exception as e:
        last_error = e

    return f"[Ollama error after {self.max_retries} retries: {last_error}]"

  def stream_generate(self, prompt: str, context: str = "",
                      model: str = None) -> Iterator[str]:
    """Stream generated tokens from Ollama.

    Yields tokens as they are generated.

    Args:
      prompt: User prompt
      context: Additional context
      model: Model name (uses current_model if None)

    Yields:
      Token strings
    """
    if not self.is_ready():
      yield "[Ollama not available]"
      return

    model = model or self._get_model()

    full_prompt = prompt
    if context:
      full_prompt = f"Context:\n{context}\n\nQuestion: {prompt}\n\nAnswer:"

    try:
      url = f"{self.base_url}/api/generate"
      payload = {
        "model": model,
        "prompt": full_prompt,
        "stream": True,
        "options": {
          "temperature": 0.7,
          "num_predict": 512
        }
      }

      data = json.dumps(payload).encode('utf-8')
      req = urllib.request.Request(
        url,
        data=data,
        headers={'Content-Type': 'application/json'},
        method='POST'
      )

      with urllib.request.urlopen(req, timeout=self.timeout) as response:
        buffer = b""
        while True:
          chunk = response.read(1)
          if not chunk:
            break
          buffer += chunk
          if chunk == b"\n":
            try:
              line_data = json.loads(buffer.decode())
              if 'response' in line_data:
                yield line_data['response']
              if line_data.get('done', False):
                return
            except json.JSONDecodeError:
              pass
            buffer = b""

    except Exception as e:
      yield f"[Streaming error: {e}]"

  def embeddings(self, prompt: str, model: str = None) -> List[float]:
    """Generate embeddings for text."""
    if not self.is_ready():
      return []

    model = model or self.config.get("embedding_model", "nomic-embed-text")
    # Fallback to current model if embedding specific not set, 
    # but specific embedding models are better.
    if not self.has_model(model):
       # Try current model as fallback
       model = self._get_model()

    try:
      url = f"{self.base_url}/api/embeddings"
      payload = {
        "model": model,
        "prompt": prompt
      }

      data = json.dumps(payload).encode('utf-8')
      req = urllib.request.Request(
        url,
        data=data,
        headers={'Content-Type': 'application/json'},
        method='POST'
      )

      with urllib.request.urlopen(req, timeout=self.timeout) as response:
        result = json.loads(response.read().decode())
        return result.get('embedding', [])
    except Exception as e:
      print(f"[Ollama Embeddings Error]: {e}")
      return []

  def summarize(self, text: str, model: str = None) -> str:
    """Summarize text using Ollama."""
    prompt = f"Summarize the following text in 2-3 sentences:\n\n{text}\n\nSummary:"
    return self.generate(prompt, model=model)

  def classify(self, text: str, model: str = None) -> Dict:
    """Classify intent of text."""
    prompt = """Classify the following text into one category.
Categories: finance, planning, habit, general, greeting

Text: {text}

Category (one word only):""".format(text=text)

    result = self.generate(prompt, model=model)
    category = result.strip().lower().split()[0] if result else 'general'

    return {
      'category': category,
      'confidence': 0.8
    }

  def get_status(self) -> str:
    """Get formatted status of Ollama."""
    if not self.is_ready():
      return """
❌ Ollama Status: NOT RUNNING

To start Ollama:
1. Install: https://ollama.ai
2. Run: ollama serve
3. Pull a model: ollama pull qwen2.5:7b
"""

    models = self.list_models()
    active = self._get_model()

    output = "\n✅ Ollama Status: RUNNING\n"
    output += f"  URL: {self.base_url}\n"
    output += f"  Active Model: {active}\n\n"

    if models:
      output += "📦 Available Models:\n"
      for m in models:
        marker = " (active)" if m == active else ""
        output += f"  • {m}{marker}\n"
    else:
      output += "⚠️ No models installed.\n"
      output += "  Run: ollama pull qwen2.5:7b\n"

    return output

  def refresh(self):
    """Clear cached state and refresh."""
    self._is_ready = None
    self._available_models = None


# Singleton instance
_ollama_instance = None

def get_ollama(base_url: str = None) -> OllamaBackend:
  """Get Ollama backend singleton."""
  global _ollama_instance
  if _ollama_instance is None:
    _ollama_instance = OllamaBackend(base_url or "http://localhost:11434")
  return _ollama_instance
