"""Sons: volume no pw-play e o som de espera em loop (cassandra/sounds.py)."""
import time

from cassandra import sounds


class _Proc:
    def poll(self):
        return 0

    def terminate(self):
        pass


def test_waiting_loops_softly_and_stops_with_the_block(monkeypatch):
    played = []

    class Fake:
        def play(self, path, wait=False, volume=None):
            played.append((path, volume))
            time.sleep(0.05)
            return _Proc()

    monkeypatch.setattr(sounds.SoundPlayer, "default", Fake())
    with sounds.waiting():
        time.sleep(0.3)
    count = len(played)
    time.sleep(0.2)
    assert count >= 2 and len(played) == count  # tocou em loop e parou quando o bloco acabou
    assert all(v == sounds.WAITING_VOLUME < 1 for _p, v in played)


def test_pw_play_gets_the_volume(monkeypatch, tmp_path):
    f = tmp_path / "s.wav"
    f.write_bytes(b"x")
    player = sounds.SoundPlayer.__new__(sounds.SoundPlayer)
    player._backend, player.enabled = "pw-play", True
    assert player._command(str(f), 0.45) == ["pw-play", "--volume", "0.45", str(f)]
    assert player._command(str(f), None) == ["pw-play", str(f)]
