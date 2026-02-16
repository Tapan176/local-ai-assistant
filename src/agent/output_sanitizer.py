"""
Output Sanitizer - Output Security & formatting
"""
import re
import json

class OutputSanitizer:
    """
    Sanitizes output to ensure:
    - No JSON leaks
    - Plain text compatibility
    """
    
    @staticmethod
    def sanitize(text: str) -> str:
        if not text:
            return ""
            
        cleaned = str(text)
        
        # 1. Remove Markdown Code Blocks
        cleaned = re.sub(r"```(?:json)?", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.replace("```", "")
        
        # 2. Remove [AUDIT] tags (legacy)
        cleaned = re.sub(r"\[AUDIT\].*", "", cleaned, flags=re.IGNORECASE)
        
        # 3. Remove raw JSON objects
        # Heuristic: if it looks like a JSON object at start/end, try to parse and extract message
        try:
            trimmed = cleaned.strip()
            if (trimmed.startswith("{") and trimmed.endswith("}")) or \
               (trimmed.startswith("[") and trimmed.endswith("]")):
                 data = json.loads(trimmed)
                 if isinstance(data, dict):
                     # extract common response fields
                     return str(data.get("response") or data.get("message") or data.get("text") or "")
        except:
            pass
            
        return cleaned.strip()
