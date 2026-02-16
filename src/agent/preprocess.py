"""
Preprocessor - Multi-intent decomposition and fuzzy matching
"""
import re
from typing import List, Dict

class Preprocessor:
    """Preprocesses user input for multi-intent and correction"""
    
    def __init__(self):
        self.split_patterns = [
            r'\s+and\s+(?:then\s+)?',
            r'\s+then\s+',
            r'\s+after that\s+',
            r'\.\s+'
        ]
        
        self.corrections = {
            "tommorow": "tomorrow",
            "tommorrow": "tomorrow",
            "cal": "call",
            "remind me to": "remember to",
            "activa": "activa", # Keep proper nouns
            "mon": "mom", # Context dependent, but simple here
        }
    
    def normalize(self, text: str) -> str:
        """Fix common spelling errors"""
        words = text.split()
        fixed = [self.corrections.get(w.lower(), w) for w in words]
        return " ".join(fixed)
    
    def decompose(self, text: str) -> List[str]:
        """Split into multiple atomic intents"""
        text = self.normalize(text)
        
        # Split by regex
        parts = [text]
        for pattern in self.split_patterns:
            new_parts = []
            for part in parts:
                split_res = re.split(pattern, part, flags=re.IGNORECASE)
                new_parts.extend([p.strip() for p in split_res if p.strip()])
            parts = new_parts
            
        return parts

# Example usage
if __name__ == "__main__":
    p = Preprocessor()
    t = "remove call mom tomorrow and add reminder to buy milk"
    print(p.decompose(t))
