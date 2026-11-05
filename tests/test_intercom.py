"""Interfone: os pedaços de áudio da página vão em ordem para a caixa e ela fica em silêncio enquanto isso."""
import pytest

from cassandra import intercom, speech_state


class _Pipe:
    def __init__(self):
        self.data = []
        self.closed = False

    def write(self, b):
        self.data.append(bytes(b))

    def flush(self):
        pass

    def close(self):
        self.closed = True


class _Proc:
    def __init__(self, *_a, **_k):
        self.stdin = _Pipe()

    def wait(self, timeout=None):
        return 0


@pytest.fixture
def ic(monkeypatch):
    procs = []

    def popen(*a, **k):
        procs.append(_Proc())
        return procs[-1]

    monkeypatch.setattr(intercom.subprocess, "Popen", popen)
    monkeypatch.setattr(intercom, "_watchdog", lambda _s: None)
    events = []
    intercom.set_listener(events.append)
    yield procs, events
    intercom.stop()
    intercom.set_listener(None)
    speech_state.cancel()  # sem a cauda de eco da sessão: os outros testes do microfone não a herdam


def test_chunks_play_in_order_and_late_ones_are_dropped(ic):
    procs, events = ic
    s = intercom.start()["session"]
    assert intercom.active() and events == [True] and speech_state.busy()
    pipe = procs[0].stdin
    lead = len(pipe.data)  # o sopro que acorda a caixa
    assert intercom.feed(s, 1, b"BB")
    assert pipe.data[lead:] == []  # o 0 ainda não chegou
    assert intercom.feed(s, 0, b"AA")
    assert pipe.data[lead:] == [b"AA", b"BB"]
    assert intercom.feed(s, 0, b"XX")  # repetido/atrasado: fora
    assert pipe.data[lead:] == [b"AA", b"BB"]
    assert intercom.feed("outra", 2, b"CC") is False


def test_a_missing_chunk_is_skipped_after_a_moment(ic, monkeypatch):
    procs, _ = ic
    s = intercom.start()["session"]
    pipe = procs[0].stdin
    lead = len(pipe.data)
    now = [100.0]
    monkeypatch.setattr(intercom.time, "monotonic", lambda: now[0])
    intercom.feed(s, 1, b"BB")
    now[0] += intercom._GAP_SECONDS + 0.1
    intercom.feed(s, 2, b"CC")
    assert pipe.data[lead:] == [b"BB", b"CC"]


def test_stop_ends_the_mode_and_no_sound_plays_while_on(ic, tmp_path):
    from cassandra.sounds import SoundPlayer

    procs, events = ic
    wav = tmp_path / "bip.wav"
    wav.write_bytes(b"RIFF")
    player = SoundPlayer()
    player._backend = "pw-play"
    s = intercom.start()["session"]
    assert player._command(str(wav), None) is None
    assert intercom.stop("de-outro-aparelho")["active"] is True  # sessão antiga não desliga a nova
    assert intercom.stop(s)["active"] is False
    assert events == [True, False] and procs[0].stdin.closed
    assert player._command(str(wav), None) is not None
    assert intercom.recently_active()
