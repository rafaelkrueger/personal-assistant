"""Confirmação do nome pela transcrição (falsos positivos do Vosk)."""
from cassandra.input_sources import MicrophoneInputSource


def _src(transcript=None, error=False):
    m = MicrophoneInputSource.__new__(MicrophoneInputSource)
    m.assistant_name = "cassandra"
    m.wake_words = ["cassandra", "sandra", "alessandra"]

    def transcribe(_path):
        if error:
            raise RuntimeError("sem internet")
        return transcript

    m._transcribe = transcribe
    return m


def test_real_calls_are_confirmed():
    for text in ["Cassandra, que horas são?", "Cassandra.", "Ô Cassandra, liga a TV", "Kassandra, pausa",
                 "Sandra, que horas são", "Que horas são, Cassandra?"]:
        assert _src()._name_in(text), text


def test_house_conversation_is_rejected():
    for text in ["Porque são 2 senadores que você pode voltar, né?", "Tem uma lista de 10000 pessoas.",
                 "Eu falei com a Cassandra ontem sobre isso", "casa da sandra", "Sandro vem aqui", ""]:
        assert not _src()._name_in(text), text


def test_request_is_extracted_without_the_name():
    m = _src()
    assert m._without_name("Ô Cassandra, toca música") == "toca música"
    assert m._without_name("Que horas são, Cassandra?") == "Que horas são"
    assert m._without_name("Cassandra.") == ""


def test_verify_uses_the_transcription_and_falls_back_to_vosk_offline():
    assert _src("Cassandra, apaga a luz")._verify_name("x.wav", "cassandra [unk]") == (True, "Cassandra, apaga a luz")
    assert _src("o jogo foi bom")._verify_name("x.wav", "sandra [unk]")[0] is False
    assert _src(error=True)._verify_name("x.wav", "cassandra [unk]")[0] is True
    assert _src(error=True)._verify_name("x.wav", "sandra [unk]")[0] is False
