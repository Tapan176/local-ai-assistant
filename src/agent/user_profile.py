"""
User Profile Engine - Continuous learning from conversations.

Phase 17: Enhanced with adaptive intelligence:
- Learn preferences from every interaction
- Detect behavioral patterns and routines
- Infer current context (time, mood, activity)
- Suggest actions based on patterns
"""
import json
from pathlib import Path
from datetime import datetime, time, timedelta
from typing import Optional, Dict, Any, List


class UserProfile:
  """Manages user profile with continuous learning from interactions."""

  # Keywords for preference extraction
  LIKE_WORDS = {'love', 'like', 'enjoy', 'prefer', 'favorite', 'favourite',
                'pasand', 'achha', 'best', 'maza', 'fan'}
  DISLIKE_WORDS = {'hate', 'dislike', 'avoid', 'dont like', "don't like",
                   'nahi pasand', 'bad', 'worst'}

  FOOD_WORDS = {'pizza', 'pasta', 'sushi', 'burger', 'biryani', 'dosa',
                'chai', 'coffee', 'tea', 'roti', 'rice', 'dal', 'paneer',
                'chicken', 'mutton', 'fish', 'salad', 'fruit', 'chocolate',
                'ice cream', 'noodles', 'momos', 'samosa', 'maggi'}

  ACTIVITY_WORDS = {'gym', 'running', 'hiking', 'yoga', 'swimming',
                    'cycling', 'cricket', 'football', 'reading', 'gaming',
                    'cooking', 'painting', 'music', 'guitar', 'singing',
                    'dancing', 'meditation', 'walking', 'jogging', 'chess'}

  MOOD_KEYWORDS = {
    'happy': ['happy', 'great', 'excellent', 'awesome', 'amazing', 'wonderful',
              'fantastic', 'good', 'khush', 'mast', 'badhiya', 'yay', '😊', '🎉'],
    'sad': ['sad', 'upset', 'depressed', 'unhappy', 'down', 'dukhi',
            'udaas', 'low', 'crying', '😢', '😞'],
    'stressed': ['stressed', 'overwhelmed', 'busy', 'tired', 'exhausted',
                 'tension', 'pressure', 'thak', 'pareshan', 'frustrated'],
    'angry': ['angry', 'furious', 'mad', 'irritated', 'annoyed',
              'gussa', 'naraz', '😤', '😡'],
    'excited': ['excited', 'thrilled', 'eager', 'pumped', 'hyped',
                'josh', 'excited', '🔥', '💪'],
    'calm': ['calm', 'peaceful', 'relaxed', 'chill', 'shanti',
             'aaram', 'sukoon'],
  }

  def __init__(self, data_dir: Path):
    self.data_dir = Path(data_dir)
    self.profile_path = self.data_dir / "profile.json"
    self._load()

  # ── Persistence ──────────────────────────────────────────────

  def _load(self):
    """Load profile from disk"""
    if self.profile_path.exists():
      try:
        with open(self.profile_path, 'r', encoding='utf-8') as f:
          self.data = json.load(f)
      except (json.JSONDecodeError, IOError):
        self.data = self._defaults()
    else:
      self.data = self._defaults()
      self._save()

    # Ensure all keys exist (forward-compat)
    defaults = self._defaults()
    for key in defaults:
      if key not in self.data:
        self.data[key] = defaults[key]

  def _defaults(self) -> Dict:
    """Default profile structure"""
    return {
      "name": None,
      "occupation": None,
      "location": None,
      "preferences": {},        # {category: [{pref, confidence, count, source}]}
      "facts": [],
      "routines": [],           # [{name, day, hour, action, freq}]
      "interaction_log": [],    # [{ts, action, text_snippet}] — last 200
      "mood_history": [],       # [{ts, mood}] — last 50
      "created_at": datetime.now().strftime("%Y-%m-%d"),
      "updated_at": datetime.now().strftime("%Y-%m-%d")
    }

  def _save(self):
    """Save profile to disk"""
    self.data["updated_at"] = datetime.now().strftime("%Y-%m-%d")
    # Cap interaction log to last 200 entries
    self.data["interaction_log"] = self.data.get("interaction_log", [])[-200:]
    self.data["mood_history"] = self.data.get("mood_history", [])[-50:]
    try:
      with open(self.profile_path, 'w', encoding='utf-8') as f:
        json.dump(self.data, f, indent=2, ensure_ascii=False, default=str)
    except IOError:
      pass

  # ── Basic Getters/Setters (preserved from Phase 1) ──────────

  def get_name(self) -> Optional[str]:
    return self.data.get("name")

  def set_name(self, name: str):
    self.data["name"] = name
    self._save()

  def get_occupation(self) -> Optional[str]:
    return self.data.get("occupation")

  def set_occupation(self, occupation: str):
    self.data["occupation"] = occupation
    self._save()

  def get_location(self) -> Optional[str]:
    return self.data.get("location")

  def set_location(self, location: str):
    self.data["location"] = location
    self._save()

  def add_fact(self, fact: str):
    """Add a fact about the user"""
    if fact not in self.data["facts"]:
      self.data["facts"].append(fact)
      self._save()

  def get_facts(self) -> List[str]:
    return self.data.get("facts", [])

  def set_preference(self, key: str, value: Any):
    self.data["preferences"][key] = value
    self._save()

  def get_preference(self, key: str) -> Any:
    return self.data.get("preferences", {}).get(key)

  # ── Phase 17: Continuous Learning ───────────────────────────

  def learn_from_interaction(self, text: str, action: str = "",
                             intent: str = ""):
    """Learn from every user interaction.

    Called by Orchestrator after each process() call.
    Extracts preferences, detects mood, logs for pattern detection.
    """
    now = datetime.now()

    # 1. Log interaction (capped at 200)
    self.data.setdefault("interaction_log", []).append({
      "ts": now.isoformat(),
      "hour": now.hour,
      "weekday": now.weekday(),
      "action": action or intent,
      "snippet": text[:100]
    })

    # 2. Extract preferences
    self._extract_preferences(text)

    # 3. Detect and log mood
    mood = self.detect_mood(text)
    if mood != "neutral":
      self.data.setdefault("mood_history", []).append({
        "ts": now.isoformat(),
        "mood": mood
      })

    # 4. Auto-extract profile info
    self.extract_from_message(text)

    # 5. Detect patterns (every 20 interactions)
    log = self.data.get("interaction_log", [])
    if len(log) % 20 == 0 and len(log) >= 20:
      self._detect_patterns()

    self._save()

  def _extract_preferences(self, text: str):
    """Extract preferences from user message"""
    text_lower = text.lower()
    words = set(text_lower.split())

    has_like = bool(words & self.LIKE_WORDS)
    has_dislike = bool(words & self.DISLIKE_WORDS)

    if not (has_like or has_dislike):
      return

    sentiment = "likes" if has_like else "dislikes"

    # Food preferences
    found_foods = words & self.FOOD_WORDS
    for food in found_foods:
      self._add_learned_preference("food", food, sentiment, "inferred")

    # Activity preferences
    found_activities = words & self.ACTIVITY_WORDS
    for activity in found_activities:
      self._add_learned_preference("activity", activity, sentiment, "inferred")

    # Generic preference from longer text
    if not found_foods and not found_activities and len(text) > 10:
      # Store the whole preference text
      self._add_learned_preference("general", text[:80], sentiment, "explicit")

  def _add_learned_preference(self, category: str, item: str,
                              sentiment: str, source: str):
    """Add or reinforce a learned preference"""
    prefs = self.data.setdefault("preferences", {})
    cat_prefs = prefs.setdefault(category, [])

    # Check if preference already exists
    for pref in cat_prefs:
      if isinstance(pref, dict) and pref.get("item") == item:
        pref["count"] = pref.get("count", 1) + 1
        pref["confidence"] = min(1.0, pref.get("confidence", 0.5) + 0.1)
        pref["updated"] = datetime.now().isoformat()
        return

    # New preference
    cat_prefs.append({
      "item": item,
      "sentiment": sentiment,
      "confidence": 0.6 if source == "explicit" else 0.3,
      "count": 1,
      "source": source,
      "updated": datetime.now().isoformat()
    })

  def detect_mood(self, text: str) -> str:
    """Detect mood from text using keyword matching"""
    text_lower = text.lower()
    scores = {}

    for mood, keywords in self.MOOD_KEYWORDS.items():
      score = sum(1 for kw in keywords if kw in text_lower)
      if score > 0:
        scores[mood] = score

    if not scores:
      return "neutral"

    return max(scores, key=scores.get)

  def get_current_mood(self) -> str:
    """Get most recent detected mood"""
    history = self.data.get("mood_history", [])
    if not history:
      return "neutral"

    # Most recent non-stale mood (within last hour)
    now = datetime.now()
    for entry in reversed(history):
      try:
        ts = datetime.fromisoformat(entry["ts"])
        if (now - ts).total_seconds() < 3600:
          return entry["mood"]
      except (ValueError, KeyError):
        continue

    return "neutral"

  # ── Phase 17: Context Awareness ─────────────────────────────

  def get_current_context(self) -> Dict[str, Any]:
    """Get current user context (time, mood, inferred state)"""
    now = datetime.now()
    hour = now.hour

    # Time of day
    if 5 <= hour < 12:
      time_of_day = "morning"
    elif 12 <= hour < 17:
      time_of_day = "afternoon"
    elif 17 <= hour < 22:
      time_of_day = "evening"
    else:
      time_of_day = "night"

    # Day type
    day_type = "weekend" if now.weekday() >= 5 else "weekday"

    # Infer activity from recent interactions
    activity = self._infer_activity()

    return {
      "time_of_day": time_of_day,
      "day_type": day_type,
      "hour": hour,
      "weekday": now.weekday(),
      "mood": self.get_current_mood(),
      "activity": activity,
      "name": self.get_name(),
    }

  def _infer_activity(self) -> Optional[str]:
    """Infer current activity from recent interactions"""
    log = self.data.get("interaction_log", [])
    if not log:
      return None

    recent = log[-5:]
    actions = [entry.get("action", "") for entry in recent]
    snippets = " ".join(entry.get("snippet", "") for entry in recent).lower()

    if any(a in ("expense", "income", "balance") for a in actions):
      return "managing_finances"
    if any(a in ("remember", "memory") for a in actions):
      return "saving_info"
    if any(a in ("experience", "journal") for a in actions):
      return "journaling"
    if any(a in ("habit",) for a in actions):
      return "tracking_habits"
    if any(a in ("plan", "agenda") for a in actions):
      return "planning"
    if "work" in snippets or "office" in snippets:
      return "working"
    if "gym" in snippets or "exercise" in snippets or "workout" in snippets:
      return "exercising"

    return None

  # ── Phase 17: Pattern Detection ─────────────────────────────

  def _detect_patterns(self):
    """Detect routines from interaction history"""
    log = self.data.get("interaction_log", [])
    if len(log) < 10:
      return

    # Count (weekday, hour, action) combos
    pattern_counts: Dict[str, int] = {}
    for entry in log[-100:]:  # Last 100 interactions
      weekday = entry.get("weekday")
      hour = entry.get("hour")
      action = entry.get("action", "")
      if not action:
        continue
      key = f"{weekday}_{hour}_{action}"
      pattern_counts[key] = pattern_counts.get(key, 0) + 1

    # Create routine entries from patterns with 3+ occurrences
    routines = []
    total = len(log[-100:])
    for pattern, count in pattern_counts.items():
      if count >= 3:
        parts = pattern.split("_", 2)
        if len(parts) == 3:
          routines.append({
            "name": f"{parts[2]}_routine",
            "weekday": int(parts[0]),
            "hour": int(parts[1]),
            "action": parts[2],
            "frequency": round(count / max(total, 1), 2),
            "count": count
          })

    self.data["routines"] = routines

  def get_routines(self) -> List[Dict]:
    """Get detected routines"""
    return self.data.get("routines", [])

  def get_upcoming_routines(self, hours_ahead: int = 2) -> List[Dict]:
    """Get routines likely to happen in next N hours"""
    now = datetime.now()
    current_weekday = now.weekday()
    current_hour = now.hour
    upcoming = []

    for routine in self.data.get("routines", []):
      r_weekday = routine.get("weekday")
      r_hour = routine.get("hour", 0)
      freq = routine.get("frequency", 0)

      # Must match current day
      if r_weekday != current_weekday:
        continue

      # Must be within time window
      if current_hour <= r_hour <= current_hour + hours_ahead:
        if freq >= 0.1:  # At least 10% frequency
          upcoming.append(routine)

    return sorted(upcoming, key=lambda r: r.get("frequency", 0), reverse=True)

  def suggest_actions(self) -> List[str]:
    """Suggest actions based on context and patterns"""
    context = self.get_current_context()
    upcoming = self.get_upcoming_routines()
    suggestions = []

    # Routine-based suggestions
    for routine in upcoming[:2]:
      action = routine.get("action", "")
      suggestions.append(f"You usually do '{action}' around this time")

    # Context-based suggestions
    if context["time_of_day"] == "morning" and context["day_type"] == "weekday":
      suggestions.append("Review today's schedule?")
      suggestions.append("Check pending habits?")
    elif context["time_of_day"] == "evening":
      suggestions.append("Log today's experiences?")
      suggestions.append("Review spending for today?")
    elif context["time_of_day"] == "night":
      suggestions.append("Prepare tomorrow's plan?")

    # Mood-based suggestions
    if context["mood"] == "stressed":
      suggestions.append("Take a short break — you seem stressed 🧘")
    elif context["mood"] == "sad":
      suggestions.append("Want to talk about what's on your mind?")

    return suggestions[:4]

  def get_learned_preferences(self, category: str = None) -> List[Dict]:
    """Get learned preferences, optionally filtered by category"""
    prefs = self.data.get("preferences", {})

    if category:
      cat_prefs = prefs.get(category, [])
      if isinstance(cat_prefs, list):
        return sorted(cat_prefs,
                      key=lambda p: p.get("confidence", 0) if isinstance(p, dict) else 0,
                      reverse=True)
      return []

    all_prefs = []
    for cat, items in prefs.items():
      if isinstance(items, list):
        for item in items:
          if isinstance(item, dict):
            item_copy = item.copy()
            item_copy["category"] = cat
            all_prefs.append(item_copy)
    return sorted(all_prefs, key=lambda p: p.get("confidence", 0), reverse=True)

  def get_profile_summary(self) -> str:
    """Get a rich profile summary"""
    parts = []

    name = self.get_name()
    if name:
      parts.append(f"👤 {name}")

    occ = self.get_occupation()
    if occ:
      parts.append(f"💼 {occ}")

    loc = self.get_location()
    if loc:
      parts.append(f"📍 {loc}")

    # Top preferences
    top_prefs = self.get_learned_preferences()[:5]
    if top_prefs:
      pref_strs = []
      for p in top_prefs:
        sent = p.get("sentiment", "likes")
        item = p.get("item", "")
        conf = p.get("confidence", 0)
        pref_strs.append(f"{sent} {item} ({conf:.0%})")
      parts.append(f"❤️ Preferences: {', '.join(pref_strs)}")

    # Facts
    facts = self.get_facts()[:3]
    if facts:
      parts.append(f"📝 Facts: {'; '.join(facts)}")

    # Routines
    routines = self.get_routines()[:3]
    if routines:
      r_strs = [f"{r['action']} (day {r['weekday']} @{r['hour']}:00)"
                for r in routines]
      parts.append(f"🔄 Routines: {', '.join(r_strs)}")

    # Context
    ctx = self.get_current_context()
    parts.append(f"🕐 {ctx['time_of_day'].title()} | {ctx['day_type'].title()} | Mood: {ctx['mood']}")

    # Stats
    log_count = len(self.data.get("interaction_log", []))
    parts.append(f"📊 {log_count} interactions logged")

    return "\n".join(parts) if parts else "No profile data yet."

  # ── Backward-compatible extraction (Phase 1) ────────────────

  def extract_from_message(self, message: str):
    """Auto-extract profile info from user message"""
    msg_lower = message.lower()

    # Extract name patterns
    name_patterns = [
      "i am ", "my name is ", "call me ", "i'm ", "mera naam "
    ]
    for pattern in name_patterns:
      if pattern in msg_lower:
        idx = msg_lower.find(pattern) + len(pattern)
        rest = message[idx:].strip()
        name = rest.split()[0] if rest else None
        if name and len(name) > 1:
          name = name.strip(".,!?")
          if name[0].isupper() or pattern == "mera naam ":
            self.set_name(name.title())
            return f"Nice to meet you, {name.title()}!"

    # Extract occupation
    job_patterns = [
      "i work as ", "i am a ", "i'm a ", "my job is ", "profession is "
    ]
    for pattern in job_patterns:
      if pattern in msg_lower:
        idx = msg_lower.find(pattern) + len(pattern)
        rest = message[idx:].strip()
        words = []
        for word in rest.split():
          if word.lower() in ['in', 'at', 'for', 'and', 'the']:
            break
          words.append(word)
        if words:
          occupation = " ".join(words).strip(".,!?")
          self.set_occupation(occupation)

    # Extract location
    location_patterns = [
      "i live in ", "i am from ", "i'm from ", "based in ", "located in "
    ]
    for pattern in location_patterns:
      if pattern in msg_lower:
        idx = msg_lower.find(pattern) + len(pattern)
        rest = message[idx:].strip()
        location = rest.split()[0] if rest else None
        if location:
          self.set_location(location.strip(".,!?").title())

    return None

  def get_context_string(self) -> str:
    """Get profile as context string for LLM"""
    parts = []

    if self.data.get("name"):
      parts.append(f"User's name: {self.data['name']}")
    if self.data.get("occupation"):
      parts.append(f"Occupation: {self.data['occupation']}")
    if self.data.get("location"):
      parts.append(f"Location: {self.data['location']}")
    if self.data.get("facts"):
      parts.append(f"Known facts: {', '.join(self.data['facts'][:5])}")

    # Add learned preferences
    top_prefs = self.get_learned_preferences()[:5]
    if top_prefs:
      pref_parts = [f"{p.get('sentiment', 'likes')} {p.get('item', '')}"
                    for p in top_prefs]
      parts.append(f"Preferences: {', '.join(pref_parts)}")

    # Add mood context
    mood = self.get_current_mood()
    if mood != "neutral":
      parts.append(f"Current mood: {mood}")

    return "\n".join(parts) if parts else "No profile data yet."

  def to_dict(self) -> Dict:
    return self.data.copy()
