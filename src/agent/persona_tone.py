"""
PHASE 12: Persona Tone System

Context-aware response formatting:
- default: Friendly Hinglish (70% English, 30% Hindi)
- decision: Structured with analysis
- ride: Short, quick responses
- desktop: Detailed explanations

Detects mode from:
- Query keywords
- Time of day
- Stress level
- Explicit mode request
"""
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum
import random


class ToneMode(Enum):
    FRIENDLY = "friendly"      # Default Hinglish style
    DECISION = "decision"      # Structured decision format
    RIDE = "ride"              # Short, quick responses
    DESKTOP = "desktop"        # Detailed explanations
    FORMAL = "formal"          # For work/boss contexts


@dataclass
class ToneConfig:
    mode: ToneMode
    hinglish_ratio: float      # 0.0 = pure English, 1.0 = max Hindi
    max_length: int            # chars limit (0 = no limit)
    use_emoji: bool
    use_bullets: bool
    greeting_style: str        # casual, friendly, formal


# Tone presets
TONE_PRESETS: Dict[ToneMode, ToneConfig] = {
    ToneMode.FRIENDLY: ToneConfig(
        mode=ToneMode.FRIENDLY,
        hinglish_ratio=0.3,
        max_length=0,
        use_emoji=True,
        use_bullets=True,
        greeting_style="casual"
    ),
    ToneMode.DECISION: ToneConfig(
        mode=ToneMode.DECISION,
        hinglish_ratio=0.15,
        max_length=0,
        use_emoji=True,
        use_bullets=True,
        greeting_style="formal"
    ),
    ToneMode.RIDE: ToneConfig(
        mode=ToneMode.RIDE,
        hinglish_ratio=0.2,
        max_length=150,
        use_emoji=False,
        use_bullets=False,
        greeting_style="none"
    ),
    ToneMode.DESKTOP: ToneConfig(
        mode=ToneMode.DESKTOP,
        hinglish_ratio=0.25,
        max_length=0,
        use_emoji=True,
        use_bullets=True,
        greeting_style="friendly"
    ),
    ToneMode.FORMAL: ToneConfig(
        mode=ToneMode.FORMAL,
        hinglish_ratio=0.0,
        max_length=0,
        use_emoji=False,
        use_bullets=True,
        greeting_style="formal"
    )
}


class PersonaTone:
    """
    Context-aware tone manager for TAPAN_AI responses.
    
    Adapts response style based on:
    - Query type (decision, casual, urgent)
    - Time of day
    - User's current stress/energy
    - Explicit mode request
    """
    
    def __init__(self):
        self.current_mode = ToneMode.FRIENDLY
        self._explicit_override = False
    
    # =====================================
    # HINGLISH PHRASES
    # =====================================
    
    HINGLISH_GREETINGS = {
        "casual": ["Haan bhai!", "Bol yaar", "Kya scene hai", "Batao batao"],
        "friendly": ["Hey!", "Alright", "Haan ji", "Sure thing"],
        "formal": ["Hello", "Yes", "Certainly", "Of course"],
        "none": []
    }
    
    HINGLISH_AFFIRMATIONS = [
        "Done bhai!", "Ho gaya", "Sorted!", "All set yaar",
        "Kar diya", "Theek hai", "Okay boss", "Pakka"
    ]
    
    HINGLISH_FILLERS = {
        "think": ["dekh", "actually", "matlab"],
        "wait": ["ruk", "hold on", "ek sec"],
        "sorry": ["yaar sorry", "oops", "my bad"],
        "great": ["mast!", "solid!", "badhiya!"]
    }
    
    HINGLISH_ENDINGS = [
        "Aur kuch?", "Theek hai na?", "Baki sab sorted?",
        "Let me know!", "Bol agar aur chahiye"
    ]
    
    # Decision-specific phrases
    DECISION_INTROS = [
        "Dekh, here's what I think:",
        "Chal analyze karte hain:",
        "Okay, let me break this down:",
        "Soch ke bol raha hoon:"
    ]
    
    POSITIVE_VERDICTS = [
        "Ja sakta hai!", "Go for it yaar", "Looks good!",
        "Approved from my side", "Karo, no issues"
    ]
    
    NEGATIVE_VERDICTS = [
        "Bhai, ruk ja", "Not a good idea right now",
        "Wait kar le", "Skip karo abhi", "Baad mein dekh lena"
    ]
    
    CAUTION_VERDICTS = [
        "Thoda soch le", "Ek baar aur dekh", "Hmm, risky hai",
        "Sleep on it?", "Confirm pehle"
    ]
    
    # =====================================
    # MODE DETECTION
    # =====================================
    
    DECISION_KEYWORDS = [
        "should i", "kya karun", "buy", "spend", "invest",
        "khareedna", "lena chahiye", "afford", "worth it",
        "better option", "suggest", "recommend", "sochna",
        "decision", "choice", "compare", "vs"
    ]
    
    RIDE_KEYWORDS = [
        "quick", "short", "fast", "jaldi", "briefly",
        "tldr", "summary", "ek line mein"
    ]
    
    FORMAL_KEYWORDS = [
        "boss", "office", "work", "client", "meeting",
        "professional", "formal"
    ]
    
    def detect_mode(self, query: str, stress_level: int = 3, 
                    is_mobile: bool = False) -> ToneMode:
        """Detect appropriate tone mode from query and context"""
        
        # Explicit override takes precedence
        if self._explicit_override:
            return self.current_mode
        
        query_lower = query.lower()
        
        # Check for explicit mode requests
        if "ride mode" in query_lower or is_mobile:
            return ToneMode.RIDE
        if "detailed" in query_lower or "explain" in query_lower:
            return ToneMode.DESKTOP
        if "formal" in query_lower or any(k in query_lower for k in self.FORMAL_KEYWORDS):
            return ToneMode.FORMAL
        
        # Decision queries
        if any(k in query_lower for k in self.DECISION_KEYWORDS):
            return ToneMode.DECISION
        
        # Ride mode for quick queries
        if any(k in query_lower for k in self.RIDE_KEYWORDS):
            return ToneMode.RIDE
        
        # High stress = shorter responses
        if stress_level >= 7:
            return ToneMode.RIDE
        
        # Default to friendly
        return ToneMode.FRIENDLY
    
    def set_mode(self, mode: ToneMode, override: bool = False):
        """Explicitly set tone mode"""
        self.current_mode = mode
        self._explicit_override = override
    
    def get_config(self, mode: ToneMode = None) -> ToneConfig:
        """Get configuration for a mode"""
        return TONE_PRESETS.get(mode or self.current_mode, TONE_PRESETS[ToneMode.FRIENDLY])
    
    # =====================================
    # RESPONSE FORMATTING
    # =====================================
    
    def get_greeting(self, mode: ToneMode = None) -> str:
        """Get appropriate greeting for mode"""
        config = self.get_config(mode)
        greetings = self.HINGLISH_GREETINGS.get(config.greeting_style, [])
        return random.choice(greetings) if greetings else ""
    
    def get_affirmation(self) -> str:
        """Get a Hinglish affirmation phrase"""
        return random.choice(self.HINGLISH_AFFIRMATIONS)
    
    def get_decision_intro(self) -> str:
        """Get intro for decision responses"""
        return random.choice(self.DECISION_INTROS)
    
    def get_verdict(self, verdict_type: str) -> str:
        """Get verdict phrase based on type"""
        if verdict_type in ["approved", "positive", "yes"]:
            return random.choice(self.POSITIVE_VERDICTS)
        elif verdict_type in ["denied", "negative", "no", "cannot_afford"]:
            return random.choice(self.NEGATIVE_VERDICTS)
        else:
            return random.choice(self.CAUTION_VERDICTS)
    
    def get_ending(self) -> str:
        """Get casual ending phrase"""
        return random.choice(self.HINGLISH_ENDINGS)
    
    def apply_hinglish(self, text: str, ratio: float = 0.3) -> str:
        """Apply Hinglish flavor to text"""
        # Simple word substitutions for flavor
        replacements = [
            ("yes", "haan"),
            ("no", "nahi"),
            ("okay", "theek hai"),
            ("wait", "ruk"),
            ("look", "dekh"),
            ("think", "soch"),
            ("money", "paisa"),
            ("tomorrow", "kal"),
            ("today", "aaj"),
            ("friend", "yaar"),
            ("let's see", "dekhte hain"),
            ("what", "kya"),
            ("done", "ho gaya"),
        ]
        
        # Apply some replacements based on ratio
        import random
        result = text
        for eng, hindi in replacements:
            if random.random() < ratio and eng.lower() in result.lower():
                # Case-insensitive replacement (first occurrence only)
                import re
                result = re.sub(re.escape(eng), hindi, result, count=1, flags=re.IGNORECASE)
        
        return result
    
    def truncate(self, text: str, max_length: int) -> str:
        """Truncate text to max length smartly"""
        if max_length <= 0 or len(text) <= max_length:
            return text
        
        # Find last sentence boundary before limit
        truncated = text[:max_length]
        last_period = max(truncated.rfind('.'), truncated.rfind('!'), truncated.rfind('?'))
        
        if last_period > max_length * 0.5:
            return truncated[:last_period + 1]
        
        return truncated.rsplit(' ', 1)[0] + "..."
    
    def format_response(self, content: str, mode: ToneMode = None,
                       add_greeting: bool = False, add_ending: bool = False) -> str:
        """Format response according to tone mode"""
        config = self.get_config(mode)
        
        result = content
        
        # Apply Hinglish flavor
        if config.hinglish_ratio > 0:
            result = self.apply_hinglish(result, config.hinglish_ratio)
        
        # Add greeting
        if add_greeting and config.greeting_style != "none":
            greeting = self.get_greeting(mode)
            if greeting:
                result = f"{greeting} {result}"
        
        # Add ending
        if add_ending and mode not in [ToneMode.RIDE, ToneMode.FORMAL]:
            result = f"{result}\n\n{self.get_ending()}"
        
        # Truncate for ride mode
        if config.max_length > 0:
            result = self.truncate(result, config.max_length)
        
        return result
    
    # =====================================
    # DECISION-SPECIFIC FORMATTING
    # =====================================
    
    def format_decision_response(self, analysis: Dict[str, Any]) -> str:
        """
        Format a structured decision response.
        
        Structure:
        - Intro (Hinglish)
        - Key facts (bullet points)
        - Verdict with reasoning
        - Alternatives
        """
        lines = []
        
        # Intro
        lines.append(f"{self.get_decision_intro()}\n")
        
        # Amount and item
        amount = analysis.get("amount", 0)
        item = analysis.get("item", "this purchase")
        lines.append(f"**{item}: ₹{amount:,.0f}**\n")
        
        # Key facts
        lines.append("**Quick Facts:**")
        
        if "affordability_pct" in analysis:
            pct = analysis["affordability_pct"]
            emoji = "🟢" if pct < 20 else ("🟡" if pct < 40 else "🔴")
            lines.append(f"  {emoji} {pct}% of your balance")
        
        if "days_of_spending" in analysis:
            lines.append(f"  📊 = {analysis['days_of_spending']} days of typical spending")
        
        if analysis.get("upcoming_bills"):
            lines.append(f"  📅 Bills coming: ₹{analysis['upcoming_bills']:,.0f}")
        
        if analysis.get("emi_safe") is not None:
            emi_status = "✅ EMI-safe" if analysis["emi_safe"] else "❌ EMI risky"
            lines.append(f"  {emi_status} (₹{analysis.get('emi_amount', 0):,.0f}/month)")
        
        # Verdict
        rec = analysis.get("recommendation", "unknown")
        verdict = self.get_verdict(rec)
        reasoning = analysis.get("reasoning", "")
        lines.append(f"\n**Verdict:** {verdict}")
        lines.append(f"  → {reasoning}")
        
        # Warnings
        if analysis.get("warnings"):
            lines.append("\n**⚠️ Watch out:**")
            for w in analysis["warnings"][:3]:
                lines.append(f"  • {w}")
        
        # Alternatives
        if analysis.get("alternatives"):
            lines.append("\n**Options:**")
            for a in analysis["alternatives"][:3]:
                lines.append(f"  → {a}")
        
        return "\n".join(lines)
    
    def format_quick_verdict(self, analysis: Dict[str, Any]) -> str:
        """Short verdict for ride mode"""
        rec = analysis.get("recommendation", "unknown")
        amount = analysis.get("amount", 0)
        
        verdicts = {
            "approved": f"✅ ₹{amount:,.0f} go for it!",
            "caution": f"⚠️ ₹{amount:,.0f} - soch le ek baar",
            "wait": f"⏳ Better wait - bills aa rahe hain",
            "split": f"📊 Split into EMIs of ₹{analysis.get('emi_amount', 0):,.0f}",
            "cannot_afford": f"❌ Can't afford - ₹{analysis.get('balance', 0):,.0f} hai balance"
        }
        
        return verdicts.get(rec, f"🤔 Not sure about ₹{amount:,.0f}")
    
    # =====================================
    # DAILY PLAN FORMATTING
    # =====================================
    
    def format_daily_greeting(self, plan: Dict[str, Any]) -> str:
        """Format morning/daily plan greeting"""
        energy = plan.get("energy_level", 5)
        mood = plan.get("mood", "neutral")
        pending = len(plan.get("habits_pending", []))
        reminders = len(plan.get("reminders", []))
        
        # Energy-based greeting
        if energy >= 7:
            intro = "Good morning boss! 💪 Energy full hai aaj!"
        elif energy >= 4:
            intro = "Morning! Chalo, let's make it a good day."
        else:
            intro = "Hey, take it easy today. 😴 Low energy mode."
        
        # Quick summary
        summary = []
        if pending > 0:
            summary.append(f"{pending} habits pending")
        if reminders > 0:
            summary.append(f"{reminders} reminders today")
        
        if summary:
            intro += f"\n\nToday: {', '.join(summary)}"
        
        return intro


# Singleton instance
_tone_manager = PersonaTone()


def get_tone_manager() -> PersonaTone:
    """Get the global tone manager instance"""
    return _tone_manager


def detect_tone(query: str, stress: int = 3, mobile: bool = False) -> ToneMode:
    """Quick tone detection helper"""
    return _tone_manager.detect_mode(query, stress, mobile)


def format_response(content: str, query: str = "", add_flavor: bool = True) -> str:
    """Quick format helper"""
    mode = detect_tone(query)
    return _tone_manager.format_response(content, mode, add_greeting=add_flavor)
