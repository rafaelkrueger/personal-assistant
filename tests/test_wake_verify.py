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


def _early(transcripts, done_set=False, error=False):
    """Roda a conferência antecipada com transcrições combinadas; devolve (bipou, nº de transcrições)."""
    import threading

    from cassandra import input_sources

    m = _src()
    calls, wakes = [], []

    def transcribe(_path):
        calls.append(1)
        if error:
            raise RuntimeError("sem internet")
        return transcripts[len(calls) - 1]

    m._transcribe = transcribe
    m._signal_wake = lambda: wakes.append(1)
    done = threading.Event()
    if done_set:
        done.set()
    old, input_sources._EARLY_CHECKS = input_sources._EARLY_CHECKS, (0.01, 0.02)
    try:
        m._confirm_early([b"\x00\x00" * 480], done, threading.Event())
    finally:
        input_sources._EARLY_CHECKS = old
    return bool(wakes), len(calls)


def test_early_check_beeps_as_soon_as_the_name_opens_the_clip():
    assert _early(["Cassandra"]) == (True, 1)
    assert _early(["Ô Cassandra, que"]) == (True, 1)
    assert _early(["Cass", "Cassandra, que horas"]) == (True, 2)  # 1º trecho cortou o nome: a 2ª chance pega


def test_early_check_never_beeps_for_a_name_that_does_not_open_the_clip():
    # Nome no fim do trecho pode ser o meio de uma frase ("...com a Cassandra ontem"): fica para a conferência final.
    assert _early(["Eu falei com a Cassandra", "Eu falei com a Cassandra ontem"]) == (False, 2)
    assert _early(["Cansada de", "Cansada de esperar"]) == (False, 2)
    assert _early(["Cassandra"], done_set=True) == (False, 0)  # gravação já acabou: nada de transcrição extra
    assert _early(["Cassandra"], error=True) == (False, 1)


def _stream():
    from cassandra.local_speech import LocalSpeech, WakeStream

    ws = WakeStream.__new__(WakeStream)
    ws.speech = LocalSpeech(["cassandra", "sandra", "alessandra"])
    ws.name_start = None
    return ws


def test_name_after_a_pause_counts_even_with_tv_before_it():
    w = lambda word, s, e: {"word": word, "start": s, "end": e}  # noqa: E731
    ws = _stream()
    assert ws._check([w("[unk]", 0.4, 3.5), w("cassandra", 4.1, 4.8)])  # pausa de 0,6 s: chamada por cima da TV
    assert ws.name_start == 4.1
    ws = _stream()
    # Sem pausa: continua candidato pela regra antiga ([unk] não conta como palavra), mas SEM corte — a confirmação
    # transcreve tudo e, se o nome estiver no meio da frase, descarta.
    assert ws._check([w("[unk]", 0.4, 3.5), w("cassandra", 3.6, 4.2)]) and ws.name_start is None
    ws = _stream()
    # "sandro" nunca marca corte pela pausa (só o nome de verdade); como 1ª palavra reconhecida é candidato comum.
    assert ws._check([w("[unk]", 0.4, 3.5), w("sandro", 4.2, 4.6)]) and ws.name_start is None
    ws = _stream()
    assert not ws._check([w("casa", 0.4, 0.8), w("da", 0.8, 1.0), w("sandro", 1.6, 2.0)])
    ws = _stream()
    assert ws._check([w("cassandra", 0.2, 0.9), w("[unk]", 1.0, 2.0)]) and ws.name_start is None  # começo: sem corte


def test_trim_wav_keeps_only_from_the_name_on(tmp_path):
    import wave

    from cassandra.input_sources import _trim_wav

    src = tmp_path / "a.wav"
    with wave.open(str(src), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x01\x00" * 16000 * 3)
    out = _trim_wav(str(src), 1.0)
    with wave.open(out, "rb") as wf:
        assert wf.getnframes() == 16000 * 2 and wf.getframerate() == 16000


def test_short_names_never_count_in_the_middle_of_other_speech():
    w = lambda word, s, e: {"word": word, "start": s, "end": e}  # noqa: E731
    ws = _stream()
    # "Sandra" depois de uma pausa (novela) não marca corte; só a regra do começo vale (e a confirmação decide).
    ws._check([w("casa", 0.2, 0.5), w("nada", 0.6, 0.9), w("sandra", 1.6, 2.0)])
    assert ws.name_start is None
    # Na confirmação de um trecho recortado do meio, só o nome inteiro serve.
    assert not _src()._name_in("Sandra, vem cá", full_only=True)
    assert _src()._name_in("Cassandra, que horas são?", full_only=True)
    assert _src("Sandra, vem cá")._verify_name("x.wav", "sandra", full_only=True)[0] is False


def test_long_narrative_after_the_name_is_background_not_a_request():
    from cassandra.assistant import _looks_like_background

    tv = ("Mas faz parte da jornada. Só perguntaria, mas qual é a pior parte de viajar e fazer viagens? Eu diria que é "
          "isso, você tem que ser uma pessoa desapegada. Você tem que encontrar várias pessoas e tem que ficar normal.")
    assert _looks_like_background(tv)
    for request in ["que horas são?", "toca Legião Urbana no Spotify",
                    "me lembra amanhã de ligar pro dentista às três da tarde e depois passar no mercado pra comprar "
                    "pão, leite e ovos", "Liga a TV. Coloca na Netflix. E abaixa o volume."]:
        assert not _looks_like_background(request), request


def test_name_alone_reuses_the_early_check_when_only_the_pause_followed():
    import numpy as np

    t = np.arange(480) / 16000
    voice = sum(np.sin(2 * np.pi * 140 * k * t) for k in range(1, 12)) * 600  # harmônicos como uma vogal
    voiced = voice.astype(np.int16).tobytes()
    quiet = (np.random.default_rng(0).normal(0, 60, 480)).astype(np.int16).tobytes()
    m = _src()
    m._early = ("Cassandra.", 40)
    assert m._after_early_check([voiced] * 40 + [quiet] * 30) == "Cassandra."  # só a pausa depois: sem 2ª transcrição
    assert m._after_early_check([voiced] * 40 + [voiced] * 8 + [quiet] * 30) is None  # falou mais (o pedido)
    m._early = ("Cassandra, que", 40)
    assert m._after_early_check([voiced] * 40 + [quiet] * 30) is None  # o trecho já tinha parte do pedido
    m._early = ("", 0)
    assert m._after_early_check([quiet] * 30) is None


def test_the_beep_echo_after_the_name_is_not_the_request():
    import numpy as np

    t = np.arange(480) / 16000
    voiced = (sum(np.sin(2 * np.pi * 140 * k * t) for k in range(1, 12)) * 600).astype(np.int16).tobytes()
    quiet = (np.random.default_rng(0).normal(0, 60, 480)).astype(np.int16).tobytes()
    m = _src()
    m._early = ("Cassandra.", 40)
    frames = [voiced] * 40 + [voiced] * 6 + [quiet] * 30  # depois do nome: o eco do bip (soa "com voz")
    chimes = [False] * 40 + [True] * 6 + [False] * 30
    assert m._after_early_check(frames, chimes) == "Cassandra."  # o eco não é pedido: nada de 2ª transcrição
    assert m._after_early_check(frames) is None  # sem a marca, parecia que a pessoa tinha falado mais


def test_the_cloud_transcription_gets_the_cloud_audio(monkeypatch):
    from cassandra import input_sources

    sent = []
    m = _src()
    m.transcription_provider, m.transcription_model, m.transcription_language = "openai", "gpt-4o-transcribe", "pt"
    m.transcription_prompt, m._azure_down_until, m._openai_down_until, m.local = "", 0.0, 0.0, None
    m.llm = type("L", (), {"transcribe_audio_file": lambda self, path, **kw: sent.append(path) or "ok"})()
    monkeypatch.setattr(input_sources.llm_settings, "get",
                        lambda: {"stt_provider": "openai", "stt_model": "", "openai_api_key": "k"})
    m._cloud_for = {"gravacao.wav": "fala-24k.wav"}
    transcribe = MicrophoneInputSource._transcribe.__get__(m)  # o de verdade (o _src troca por um falso)
    assert transcribe("gravacao.wav") == "ok" and sent == ["fala-24k.wav"]  # a gravação inteira: só a fala, 24 kHz
    assert transcribe("trecho.wav") == "ok" and sent[-1] == "trecho.wav"  # recortes (conferência) seguem iguais
