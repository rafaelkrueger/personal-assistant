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


def test_similar_words_no_longer_pass_as_the_name():
    # A semelhança solta de antes (>= 0,72) aceitava estas frases como chamada.
    for text in ["Cansada de esperar, ela foi embora.", "Casada há dez anos.", "O Alessandro chegou agora.",
                 "Canastra é um lugar lindo.", "Casa de Sandra.", "Você conhece a Cassandra do trabalho?"]:
        assert not _src()._name_in(text), text


def test_name_split_or_misspelled_by_the_transcription_still_calls():
    for text in ["Cas Sandra, que horas são?", "Casa Sandra, liga a TV.", "Cássandra, toca música",
                 "Cassandre, pausa", "Cacandra, que horas são?", "Oi, oi, Cassandra, liga a TV.", "Alessandra, liga a luz"]:
        assert _src()._name_in(text), text
    assert _src()._without_name("Cas Sandra, que horas são?") == "que horas são"
    assert _src()._without_name("Oi, oi, Cassandra, liga a TV.") == "liga a TV"


def test_sandro_as_first_word_is_only_a_candidate():
    from cassandra.local_speech import LocalSpeech

    speech = LocalSpeech(["cassandra", "sandra", "alessandra"])
    assert speech.has_name(["[unk]", "sandro", "[unk]"])  # "Cassandra" mal ouvido de longe → vai para a confirmação
    assert not speech.has_name(["casa", "da", "sandro"])
    assert not speech.has_name(["alessandro", "[unk]"])
    assert speech.has_name(["[unk]", "cassandra"])
    # ... e a confirmação descarta o Sandro de verdade.
    assert _src("Sandro, vem jantar")._verify_name("x.wav", "sandro [unk]")[0] is False


def test_agc_raises_quiet_speech_and_leaves_loud_speech_alone():
    import numpy as np

    from cassandra.local_speech import AGC_MAX_GAIN, _Agc

    def rms(b):
        x = np.frombuffer(b, dtype=np.int16).astype(np.float64)
        return float(np.sqrt(np.mean(x * x)))

    quiet = (np.sin(np.arange(480) / 3.0) * 700).astype(np.int16).tobytes()
    out = _Agc()(quiet)
    assert rms(out) > 3 * rms(quiet) and rms(out) <= AGC_MAX_GAIN * rms(quiet) + 1
    loud = (np.sin(np.arange(480) / 3.0) * 9000).astype(np.int16).tobytes()
    assert _Agc()(loud) == loud  # perto do microfone: sem ganho
