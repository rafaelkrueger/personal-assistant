"""Pausa da música ao ouvir o nome (cassandra/music_pause.py)."""
from cassandra.music_pause import MusicPause


class FakeSpotify:
    configured = connected = True
    device_name = "Cassandra"

    def __init__(self, playing=True, device="Cassandra"):
        self.control_gen = 0
        self.calls = []
        self.state = {"is_playing": playing, "device": {"id": "d1", "name": device}}

    def playback(self):
        return self.state

    def _player(self, method, path, params=None):
        self.calls.append(path)


def _cycle(sp, during=None):
    m = MusicPause(sp)
    m._pause()
    if during:
        during(sp)
    m._resume()
    return sp.calls


def test_pauses_and_resumes_our_own_speaker():
    assert _cycle(FakeSpotify()) == ["/me/player/pause", "/me/player/play"]


def test_does_not_resume_when_the_request_controlled_the_music():
    def user_paused(sp):
        sp.control_gen += 1  # "pausa a música" / "toca outra"
    assert _cycle(FakeSpotify(), user_paused) == ["/me/player/pause"]


def test_ignores_nothing_playing_or_other_devices():
    assert _cycle(FakeSpotify(playing=False)) == []
    assert _cycle(FakeSpotify(device="Celular")) == []
