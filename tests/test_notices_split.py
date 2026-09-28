"""O aviso antes de uma tarefa demorada vira uma mensagem própria (assistant._notices)."""
import types

from cassandra import notices
from cassandra.assistant import CassandraAssistant


def _fake():
    me = types.SimpleNamespace(history=[], spoken=[])
    me._append_history = lambda role, content, source, kind: me.history.append(content)
    me._speak_in_background = lambda text, then_sound=None: me.spoken.append(text)
    return me


def _stream():
    yield notices.Notice("Um instante, estou buscando. ")
    yield "Amanhã faz 25 graus."


def test_text_chat_gets_the_notice_as_its_own_message_spoken_right_away():
    me, said = _fake(), []
    out = "".join(CassandraAssistant._notices(me, _stream(), said, speak_now=True))
    assert out == "Amanhã faz 25 graus."
    assert me.history == ["Um instante, estou buscando."] and me.spoken == me.history


def test_voice_keeps_the_notice_in_the_stream_to_speak_it_first():
    me, said = _fake(), []
    out = "".join(CassandraAssistant._notices(me, _stream(), said, speak_now=False))
    assert out.startswith("Um instante") and me.spoken == [] and said == ["Um instante, estou buscando."]
    assert isinstance(notices.searching(), notices.Notice)
