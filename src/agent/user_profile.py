"""
User Profile - Auto-extracted profile from conversations
"""
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List


class UserProfile:
  """Manages user profile with auto-extraction"""

  def __init__(self, data_dir: Path):
    self.data_dir = Path(data_dir)
    self.profile_path = self.data_dir / "profile.json"
    self._load()

  def _load(self):
    """Load profile from disk"""
    if self.profile_path.exists():
      with open(self.profile_path, 'r', encoding='utf-8') as f:
        self.data = json.load(f)
    else:
      self.data = {
        "name": None,
        "occupation": None,
        "location": None,
        "preferences": {},
        "facts": [],
        "created_at": datetime.now().strftime("%Y-%m-%d"),
        "updated_at": datetime.now().strftime("%Y-%m-%d")
      }
      self._save()

  def _save(self):
    """Save profile to disk"""
    self.data["updated_at"] = datetime.now().strftime("%Y-%m-%d")
    with open(self.profile_path, 'w', encoding='utf-8') as f:
      json.dump(self.data, f, indent=2, ensure_ascii=False)

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
        # Extract first word/name
        name = rest.split()[0] if rest else None
        if name and len(name) > 1:
          # Clean up name
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
        # Take words until common stop words
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

    return "\n".join(parts) if parts else "No profile data yet."

  def to_dict(self) -> Dict:
    return self.data.copy()
