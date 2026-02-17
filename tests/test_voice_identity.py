from pathlib import Path

from src.io.voice_identity import VoiceIdentityStore


def test_register_set_active_and_verify(tmp_path: Path):
    store = VoiceIdentityStore(tmp_path)
    owner_audio = (b"owner-voice-sample-" * 4000)[:50000]
    intruder_audio = (b"intruder-voice-" * 4000)[:50000]

    store.register("tapan", owner_audio)
    assert store.set_active_user("tapan")

    ok = store.verify(owner_audio)
    bad = store.verify(intruder_audio)

    assert ok["verified"] is True
    assert bad["verified"] is False


def test_no_active_user_allows_voice(tmp_path: Path):
    store = VoiceIdentityStore(tmp_path)
    res = store.verify(b"random")
    assert res["verified"] is True
    assert res["user_id"] is None
