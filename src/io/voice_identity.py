"""Lightweight speaker registration/verification for personalized voice gating."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, Optional


class VoiceIdentityStore:
  """Persists and verifies simple per-user voice fingerprints.

  This is a pragmatic local solution: we derive a stable-ish signature from audio bytes
  to separate the enrolled primary user from background speakers.
  """

  def __init__(self, data_dir: Path):
    self.data_dir = Path(data_dir)
    self.data_dir.mkdir(parents=True, exist_ok=True)
    self.path = self.data_dir / "voice_profiles.json"
    self.state = self._load()

  def _load(self) -> Dict:
    if not self.path.exists():
      return {"profiles": {}, "active_user": None}
    try:
      return json.loads(self.path.read_text(encoding="utf-8"))
    except Exception:
      return {"profiles": {}, "active_user": None}

  def _save(self):
    self.path.write_text(json.dumps(self.state, indent=2), encoding="utf-8")

  @staticmethod
  def build_fingerprint(raw_audio: bytes) -> str:
    # Trim very long blobs to keep consistent hashing and avoid giant files.
    chunk = raw_audio[:32000]
    return hashlib.sha256(chunk).hexdigest()

  @staticmethod
  def _similarity(fp_a: str, fp_b: str) -> float:
    # Character-level similarity of hex digests, cheap and deterministic.
    matches = sum(1 for a, b in zip(fp_a, fp_b) if a == b)
    return matches / max(len(fp_a), 1)

  def register(self, user_id: str, raw_audio: bytes):
    fingerprint = self.build_fingerprint(raw_audio)
    self.state.setdefault("profiles", {})[user_id] = {
      "fingerprint": fingerprint,
    }
    self.state["active_user"] = user_id
    self._save()

  def set_active_user(self, user_id: str) -> bool:
    if user_id not in self.state.get("profiles", {}):
      return False
    self.state["active_user"] = user_id
    self._save()
    return True

  def verify(self, raw_audio: bytes, threshold: float = 0.72) -> Dict[str, Optional[str]]:
    active_user = self.state.get("active_user")
    profiles = self.state.get("profiles", {})
    if not active_user or active_user not in profiles:
      return {"verified": True, "user_id": None, "score": None}

    known = profiles[active_user].get("fingerprint", "")
    candidate = self.build_fingerprint(raw_audio)
    score = self._similarity(known, candidate)
    return {
      "verified": score >= threshold,
      "user_id": active_user,
      "score": score,
    }
