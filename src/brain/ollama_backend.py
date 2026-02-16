"""
Ollama Backend - Connect to local Ollama server for LLM inference
"""
import json
import urllib.request
import urllib.error
from typing import Optional, Dict, List
from pathlib import Path


class OllamaBackend:
    """Backend for Ollama local LLM server
    
    Connects to Ollama API at localhost:11434
    Provides generate, summarize, classify methods
    """
    
    def __init__(self, base_url: str = "http://localhost:11434", timeout: int = 30):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.name = "ollama"
        self._available_models = None
        self._is_ready = None
    
    def is_ready(self) -> bool:
        """Check if Ollama server is running"""
        if self._is_ready is not None:
            return self._is_ready
        
        try:
            url = f"{self.base_url}/api/tags"
            req = urllib.request.Request(url, method='GET')
            with urllib.request.urlopen(req, timeout=5) as response:
                self._is_ready = response.status == 200
                return self._is_ready
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
            self._is_ready = False
            return False
    
    def list_models(self) -> List[str]:
        """Get list of available models from Ollama"""
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
        """Check if a specific model is available"""
        models = self.list_models()
        # Handle both exact match and partial match (e.g., "phi3:mini" matches "phi3:mini")
        return any(model_name in m or m in model_name for m in models)
    
    def generate(self, prompt: str, model: str = "phi3:mini", context: str = "") -> str:
        """Generate response using Ollama
        
        Args:
            prompt: User prompt
            model: Model name to use
            context: Additional context
        
        Returns:
            Generated text response
        """
        if not self.is_ready():
            return "[Ollama not available]"
        
        # Build full prompt with context
        full_prompt = prompt
        if context:
            full_prompt = f"Context:\n{context}\n\nQuestion: {prompt}\n\nAnswer:"
        
        try:
            url = f"{self.base_url}/api/generate"
            payload = {
                "model": model,
                "prompt": full_prompt,
                "stream": False,
                "options": {
                    "temperature": 0.7,
                    "num_predict": 256
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
                result = json.loads(response.read().decode())
                return result.get('response', '[No response]')
        
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return f"[Model '{model}' not found. Run: ollama pull {model}]"
            return f"[Ollama error: {e.code}]"
        except Exception as e:
            return f"[Ollama error: {str(e)}]"
    
    def summarize(self, text: str, model: str = "phi3:mini") -> str:
        """Summarize text using Ollama"""
        prompt = f"Summarize the following text in 2-3 sentences:\n\n{text}\n\nSummary:"
        return self.generate(prompt, model)
    
    def classify(self, text: str, model: str = "phi3:mini") -> Dict:
        """Classify intent of text"""
        prompt = f"""Classify the following text into one category.
Categories: finance, planning, habit, general, greeting

Text: {text}

Category (one word only):"""
        
        result = self.generate(prompt, model)
        category = result.strip().lower().split()[0] if result else 'general'
        
        return {
            'category': category,
            'confidence': 0.8  # Placeholder confidence
        }
    
    def get_status(self) -> str:
        """Get formatted status of Ollama"""
        if not self.is_ready():
            return """
❌ Ollama Status: NOT RUNNING

To start Ollama:
1. Install: https://ollama.ai
2. Run: ollama serve
3. Pull a model: ollama pull phi3:mini
"""
        
        models = self.list_models()
        output = "\n✓ Ollama Status: RUNNING\n"
        output += f"  URL: {self.base_url}\n\n"
        
        if models:
            output += "📦 Available Models:\n"
            for m in models:
                output += f"  • {m}\n"
        else:
            output += "⚠️ No models installed.\n"
            output += "  Run: ollama pull phi3:mini\n"
        
        return output
    
    def refresh(self):
        """Clear cached state and refresh"""
        self._is_ready = None
        self._available_models = None


# Singleton instance
_ollama_instance = None

def get_ollama(base_url: str = None) -> OllamaBackend:
    """Get Ollama backend singleton"""
    global _ollama_instance
    if _ollama_instance is None:
        _ollama_instance = OllamaBackend(base_url or "http://localhost:11434")
    return _ollama_instance
