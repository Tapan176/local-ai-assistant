"""
LLM Interface - Unified abstraction for local language models
Integrates with Model Router and multiple backends
Designed for offline operation
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from pathlib import Path


class LLMInterface(ABC):
    """Abstract base class for LLM implementations"""
    
    @abstractmethod
    def generate(self, prompt: str, context: str = "") -> str:
        """Generate text from prompt
        
        Args:
            prompt: The user's question or request
            context: Additional context to consider
        
        Returns:
            Generated response text
        """
        pass
    
    @abstractmethod
    def summarize(self, text: str) -> str:
        """Summarize given text
        
        Args:
            text: Text to summarize
        
        Returns:
            Summary of the text
        """
        pass
    
    @abstractmethod
    def classify_intent(self, text: str) -> Dict:
        """Classify the intent of user input
        
        Args:
            text: User input text
        
        Returns:
            Dict with intent classification
        """
        pass

    def list_models(self) -> str:
        """List available models. Override in subclasses."""
        return "No model listing available"

    def set_model(self, model_name: str) -> str:
        """Set active model. Override in subclasses."""
        return f"Model switching not supported"

    def get_status(self) -> str:
        """Get LLM status. Override in subclasses."""
        return "Status not available"


class PlaceholderLLM(LLMInterface):
    """Placeholder implementation for when no LLM is available
    
    Provides basic rule-based responses until a local LLM is configured.
    """
    
    def __init__(self):
        self.name = "PlaceholderLLM"
        self.ready = True
    
    def generate(self, prompt: str, context: str = "") -> str:
        """Basic response generation without actual LLM
        
        Returns helpful message about LLM not being configured.
        """
        # Check for common question patterns
        prompt_lower = prompt.lower()
        
        if 'what' in prompt_lower and 'save' in prompt_lower:
            # Query about saved content
            return self._suggest_search(prompt)
        
        if 'summary' in prompt_lower or 'summarize' in prompt_lower:
            return "LLM not configured. Use 'report' command for summary."
        
        if 'plan' in prompt_lower:
            return "Use 'plan' command to see your daily plan."
        
        # Default response
        return (
            "🤖 LLM not configured yet.\n\n"
            "Available actions:\n"
            "  - Use 'search <keyword>' to find memories\n"
            "  - Use 'report' for comprehensive summary\n"
            "  - Use 'plan' for daily planning\n\n"
            "To enable AI: Configure a local LLM (Ollama, llama.cpp)"
        )
    
    def _suggest_search(self, prompt: str) -> str:
        """Suggest search command based on prompt"""
        # Extract potential keywords
        words = prompt.lower().split()
        skip_words = {'what', 'did', 'i', 'save', 'about', 'the', 'a', 'an', 'my'}
        keywords = [w for w in words if w not in skip_words and len(w) > 2]
        
        if keywords:
            return f"Try: search {keywords[0]}"
        return "Try using 'search <keyword>' to find specific content."
    
    def summarize(self, text: str) -> str:
        """Basic summarization - just truncate
        
        Real implementation would use an LLM.
        """
        if len(text) <= 200:
            return text
        
        # Simple truncation with ellipsis
        return text[:200] + "..."
    
    def classify_intent(self, text: str) -> Dict:
        """Basic intent classification using keywords
        
        Real implementation would use an LLM for better accuracy.
        """
        text_lower = text.lower()
        
        # Finance intents
        if any(word in text_lower for word in ['spend', 'expense', 'cost', 'pay']):
            return {'intent': 'expense_query', 'confidence': 0.6}
        
        if any(word in text_lower for word in ['earn', 'income', 'salary']):
            return {'intent': 'income_query', 'confidence': 0.6}
        
        # Memory intents
        if any(word in text_lower for word in ['remember', 'recall', 'what did']):
            return {'intent': 'memory_query', 'confidence': 0.6}
        
        # Journal intents
        if any(word in text_lower for word in ['journal', 'diary', 'log', 'wrote']):
            return {'intent': 'journal_query', 'confidence': 0.6}
        
        # Default
        return {'intent': 'unknown', 'confidence': 0.3}


class OllamaLLM(LLMInterface):
    """Ollama-based local LLM implementation
    
    Requires Ollama to be running locally.
    No internet required after model download.
    """
    
    def __init__(self, model_name: str = "llama2", base_url: str = "http://localhost:11434"):
        self.model_name = model_name
        self.base_url = base_url
        self.ready = False
        self._check_availability()
    
    def _check_availability(self):
        """Check if Ollama is available"""
        try:
            import urllib.request
            req = urllib.request.Request(f"{self.base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=2) as response:
                self.ready = response.status == 200
        except Exception:
            self.ready = False
    
    def generate(self, prompt: str, context: str = "") -> str:
        """Generate response using Ollama"""
        if not self.ready:
            return "Ollama not available. Run 'ollama serve' first."
        
        try:
            import json
            import urllib.request
            
            full_prompt = prompt
            if context:
                full_prompt = f"Context:\n{context}\n\nQuestion: {prompt}"
            
            data = json.dumps({
                "model": self.model_name,
                "prompt": full_prompt,
                "stream": False
            }).encode('utf-8')
            
            req = urllib.request.Request(
                f"{self.base_url}/api/generate",
                data=data,
                headers={'Content-Type': 'application/json'}
            )
            
            with urllib.request.urlopen(req, timeout=60) as response:
                result = json.loads(response.read().decode('utf-8'))
                return result.get('response', 'No response generated')
        
        except Exception as e:
            return f"Error generating response: {e}"
    
    def summarize(self, text: str) -> str:
        """Summarize text using Ollama"""
        prompt = f"Summarize this in 2-3 sentences:\n\n{text}"
        return self.generate(prompt)
    
    def classify_intent(self, text: str) -> Dict:
        """Classify intent using Ollama"""
        prompt = f"""Classify this user input into one of these categories:
- expense_query (asking about spending)
- income_query (asking about earnings)
- memory_query (asking to remember or recall)
- journal_query (asking about journal entries)
- reminder_query (asking about reminders)
- unknown

User input: {text}

Respond with only the category name."""
        
        response = self.generate(prompt)
        intent = response.strip().lower().replace(' ', '_')
        
        return {'intent': intent, 'confidence': 0.8}


def get_llm(backend: str = "unified", **kwargs) -> LLMInterface:
    """Factory function to get LLM instance
    
    Args:
        backend: Which LLM backend to use
            - 'unified': Smart routing (default)
            - 'placeholder': Basic rule-based
            - 'ollama': Ollama local LLM
        **kwargs: Backend-specific configuration
    
    Returns:
        LLMInterface instance
    """
    if backend == 'ollama':
        return OllamaLLM(
            kwargs.get('model_name', 'llama2'),
            kwargs.get('base_url', 'http://localhost:11434')
        )
    elif backend == 'unified':
        return UnifiedLLM(kwargs.get('data_dir'))
    else:
        return PlaceholderLLM()


class UnifiedLLM(LLMInterface):
    """Unified LLM that routes to appropriate backend
    
    Uses ModelRouter to select the best model for each task.
    Supports multiple backends: BitNet, Small, Tiny, Ollama.
    """
    
    def __init__(self, data_dir: Optional[Path] = None):
        self.name = "UnifiedLLM"
        self.data_dir = Path(data_dir) if data_dir else Path("data")
        
        # Import here to avoid circular imports
        from src.brain.router import get_router, ModelTier
        from src.brain.bitnet_backend import BitNetBackend
        from src.brain.small_backend import SmallBackend
        from src.brain.tiny_backend import TinyBackend
        
        self.router = get_router()
        
        # Initialize backends
        self.backends = {
            'tiny': TinyBackend(),
            'small': SmallBackend(),
            'bitnet': BitNetBackend(),
            'placeholder': PlaceholderLLM()
        }
        
        # Register with router
        self.router.register_backend('tiny', ModelTier.TINY, lambda: True)
        self.router.register_backend('small', ModelTier.SMALL, lambda: self.backends['small'].is_ready())
        self.router.register_backend('bitnet', ModelTier.HEAVY, lambda: self.backends['bitnet'].is_ready())
        self.router.register_backend('placeholder', ModelTier.TINY, lambda: True)
        
        # Try to add Ollama backend
        self._init_ollama()
    
    def _init_ollama(self):
        """Initialize Ollama backend if available"""
        try:
            from src.brain.ollama_backend import OllamaBackend
            from src.brain.router import ModelTier
            
            self.ollama = OllamaBackend()
            self.backends['ollama'] = self.ollama
            
            # Register Ollama as the preferred small/heavy backend if ready
            if self.ollama and self.ollama.is_ready():
                ollama_ref = self.ollama
                self.router.register_backend('ollama', ModelTier.SMALL, lambda: ollama_ref.is_ready())
                # Also make it available for heavy tasks
                self.router.register_backend('ollama_heavy', ModelTier.HEAVY, lambda: ollama_ref.is_ready())
        except ImportError:
            self.ollama = None
    
    def generate(self, prompt: str, context: str = "") -> str:
        """Generate response using appropriate backend"""
        from src.brain.router import TaskType
        
        task = self.router.infer_task_type(prompt)
        decision = self.router.route(task, {'text_length': len(context) if context else 0})
        
        # Use Ollama if available and decision points to it
        if decision.backend_name in ['ollama', 'ollama_heavy'] and self.ollama and self.ollama.is_ready():
            return self.ollama.generate(prompt, context=context)
        
        backend = self.backends.get(decision.backend_name, self.backends['placeholder'])
        return backend.generate(prompt, context)
    
    def summarize(self, text: str) -> str:
        """Summarize text using appropriate backend"""
        from src.brain.router import TaskType
        
        decision = self.router.route(TaskType.SUMMARIZE, {'text_length': len(text)})
        
        # Use Ollama if available
        if self.ollama and self.ollama.is_ready():
            return self.ollama.summarize(text)
        
        backend = self.backends.get(decision.backend_name, self.backends['tiny'])
        return backend.summarize(text)
    
    def classify_intent(self, text: str) -> Dict:
        """Classify user intent"""
        return self.backends['tiny'].classify(text)
    
    def set_model(self, model_name: str) -> str:
        """Set preferred model"""
        if model_name not in self.backends:
            available = ', '.join(self.backends.keys())
            return f"❌ Model '{model_name}' not found. Available: {available}"
        
        backend = self.backends[model_name]
        if hasattr(backend, 'is_ready') and not backend.is_ready():
            return f"⚠️ Model '{model_name}' not ready. Set as preference."
        
        self.router.set_user_preference(model_name)
        return f"✓ Switched to {model_name}"
    
    def list_models(self) -> str:
        """List available models"""
        output = self.router.list_models()
        
        # Add Ollama status
        if self.ollama:
            output += "\n" + self.ollama.get_status()
        
        return output
    
    def get_active_model(self) -> str:
        """Get currently active model name"""
        return self.router.get_active_model() or 'placeholder'
    
    def get_status(self) -> str:
        """Get full model status"""
        output = "\n🤖 MODEL STATUS\n"
        output += "=" * 50 + "\n\n"
        
        # Check Ollama
        if self.ollama:
            output += self.ollama.get_status()
        else:
            output += "Ollama: Not initialized\n"
        
        # Check other backends
        output += "\n📦 Registered Backends:\n"
        for name, backend in self.backends.items():
            ready = "✓" if hasattr(backend, 'is_ready') and backend.is_ready() else "○"
            output += f"  {ready} {name}\n"
        
        return output

