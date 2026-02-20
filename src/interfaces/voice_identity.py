"""Local voice identity store for optional strict speaker verification."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class VoiceIdentityStore:
    def __init__(self, data_dir: str = "data") -> None:
        self.base_dir = Path(data_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.base_dir / "voice_profiles.json"
        self.state = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"profiles": {}, "active_user": None}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"profiles": {}, "active_user": None}

    def _save(self) -> None:
        self.path.write_text(json.dumps(self.state, ensure_ascii=True, indent=2), encoding="utf-8")

    @staticmethod
    def build_fingerprint(raw_audio: bytes) -> str:
        return hashlib.sha256(raw_audio[:32000]).hexdigest()

    @staticmethod
    def _similarity(left: str, right: str) -> float:
        if not left or not right:
            return 0.0
        matches = sum(1 for a, b in zip(left, right) if a == b)
        return matches / max(len(left), 1)

    def register(self, user_id: str, raw_audio: bytes) -> None:
        fingerprint = self.build_fingerprint(raw_audio)
        self.state.setdefault("profiles", {})[user_id] = {"fingerprint": fingerprint}
        self.state["active_user"] = user_id
        self._save()

    def set_active_user(self, user_id: str) -> bool:
        profiles = self.state.get("profiles", {})
        if user_id not in profiles:
            return False
        self.state["active_user"] = user_id
        self._save()
        return True

    def verify(self, raw_audio: bytes, threshold: float = 0.72) -> dict[str, Any]:
        active = self.state.get("active_user")
        profiles = self.state.get("profiles", {})
        if not active or active not in profiles:
            return {"verified": True, "user_id": None, "score": None}
        known = str(profiles.get(active, {}).get("fingerprint", ""))
        candidate = self.build_fingerprint(raw_audio)
        score = self._similarity(known, candidate)
        return {"verified": score >= threshold, "user_id": active, "score": score}

