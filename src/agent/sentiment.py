"""
Sentiment Engine - Detects emotional valence and arousal from text.
Uses a lightweight lexicon approach for speed, suitable for real-time local use.
"""
from typing import Dict

class SentimentEngine:
    """
    Analyzes text for sentiment (positive/negative) and intensity.
    """
    
    # Tiny Lexicon (Example - expansion needed for production)
    # Valance: -5 (Negative) to +5 (Positive)
    LEXICON = {
        # Positives
        "good": 2, "great": 3, "awesome": 4, "excellent": 4, "amazing": 5,
        "love": 4, "like": 2, "happy": 3, "joy": 4, "thanks": 2,
        "cool": 2, "nice": 2, "better": 2, "best": 4, "wonderful": 4,
        "excited": 3, "fun": 3, "glad": 2, "perfect": 4, "calm": 2,
        
        # Negatives
        "bad": -3, "terrible": -4, "awful": -4, "horrible": -5, "worst": -5,
        "hate": -4, "dislike": -2, "sad": -3, "angry": -3, "upset": -3,
        "depressed": -4, "tired": -2, "exhausted": -3, "bored": -2,
        "stress": -3, "stressed": -3, "anxious": -3, "worry": -3, "scared": -3,
        "angry": -3, "mad": -3, "annoyed": -2, "frustrated": -3,
        "fail": -3, "failed": -3, "failure": -4, "wrong": -2, "mistake": -2
    }

    # Intensity modifiers
    MODIFIERS = {
        "very": 1.5, "really": 1.5, "so": 1.5, "extremely": 2.0, "super": 2.0,
        "not": -1.0, "dont": -1.0, "don't": -1.0, "didnt": -1.0, "never": -1.0
    }

    def analyze(self, text: str) -> Dict[str, float]:
        """
        Analyze text and return sentiment scores.
        Returns:
            {
                "valence": float (-1.0 to 1.0),
                "arousal": float (0.0 to 1.0),
                "emotion": str (label)
            }
        """
        words = text.lower().split()
        score = 0.0
        arousal_score = 0.0
        
        i = 0
        while i < len(words):
            word = words[i]
            
            # Check modifier
            modifier = 1.0
            if word in self.MODIFIERS:
                if i + 1 < len(words):
                    next_word = words[i+1]
                    if next_word in self.LEXICON:
                        val = self.LEXICON[next_word]
                        mod_val = self.MODIFIERS[word]
                        if mod_val < 0: # Negation
                            score += val * -0.5 # Flip sign and dampen
                        else:
                            score += val * mod_val
                            arousal_score += 0.5
                        i += 2
                        continue
            
            if word in self.LEXICON:
                val = self.LEXICON[word]
                score += val
                arousal_score += abs(val) * 0.1
            
            i += 1
            
        # Normalize
        # Simple normalization: clamp between -1 and 1 based on length/intensity
        # A sentence usually has 1-3 sentiment words. 
        # Max reasonable score ~10.
        normalized_valence = max(-1.0, min(1.0, score / 5.0))
        normalized_arousal = max(0.0, min(1.0, arousal_score / 3.0))

        return {
            "valence": normalized_valence,
            "arousal": normalized_arousal,
            "label": self._get_label(normalized_valence, normalized_arousal)
        }

    def _get_label(self, valence: float, arousal: float) -> str:
        if valence > 0.5: return "happy"
        if valence < -0.5: return "sad" if arousal < 0.5 else "angry"
        if arousal > 0.6: return "excited" if valence >= 0 else "stressed"
        return "neutral"
