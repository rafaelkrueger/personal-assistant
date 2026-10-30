"""Gera as falas da bancada (edge-tts): chamadas com o nome, frases sem o nome e a "TV" de fundo.

Saída: clips/<id>.wav (48 kHz mono s16) + corpus.json com texto, rótulo e onde o nome termina (segundos).
"""
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import edge_tts

OUT = Path(__file__).parent / "clips"
OUT.mkdir(exist_ok=True)

POS = [  # o nome chama (começo ou fim)
    "Cassandra.", "Cassandra?", "Cassandra, que horas são?", "Cassandra, liga a TV.",
    "Cassandra, toca Legião Urbana no Spotify.", "Ô Cassandra, qual a previsão do tempo pra amanhã?",
    "Cassandra, aumenta o volume.", "Cassandra, pausa a música.", "Cassandra, coloca um alarme pras seis e meia.",
    "Ei Cassandra, apaga a luz da sala.", "Cassandra, pergunta pro Pulse quanto eu dormi essa noite.",
    "Cassandra, me lembra de tomar o remédio às oito.", "Que horas são, Cassandra?", "Tá me ouvindo, Cassandra?",
    "Cassandra!", "Ô Cassandra!", "Cassandra... tá aí?",
]
# Palavras soltas parecidas com o nome (nomes, exclamações): o pior caso para o bip na hora, que vale para o nome
# dito sozinho. Nenhuma pode bipar.
HARD = [
    "Cansada.", "Casada.", "Sandra!", "Alessandra?", "Amanda!", "Fernanda.", "Leandra?", "Cássia!", "Cassino.",
    "Varanda.", "Lasanha!", "Alexandre!", "Alexandra!", "Cachorra!", "Vanessa!", "Andressa!", "Kassab.", "Assando.",
    "Cansado.", "Passando!", "Comanda.", "Propaganda.", "Ciranda.", "Quitanda.", "Sacada!", "Escandalosa!",
    "Cascavel!", "Cassiano!", "Casa nova.", "Clara!", "Sandro!", "Alessandro?", "Miranda!", "Iolanda!", "Wanda!",
    "Brenda!", "Samanta!", "Casanova.", "Cansei.", "Sandrinha!", "Leandro!", "Fernando!", "Ô Sandra!",
    "Que saudade!", "Tá cansada?", "Cadê a Sandra?", "Cássio!", "Teodora!",
]
NEG = [  # não pode ativar
    "A casa da Sandra fica perto daqui.", "Eu tô muito cansada hoje.", "O Alessandro ligou de novo.",
    "Eu falei com a Cassandra ontem à noite.", "Liga a TV, por favor.", "Que horas são?",
    "Vamos jantar daqui a pouco?", "Cadê a chave do carro?", "A Sandra disse que vem amanhã.",
    "Passa o sal, por favor.", "Ela é casada com o Alexandre.", "Hoje o trânsito estava terrível na avenida.",
    "O governo anunciou novas medidas para a economia nesta segunda-feira.", "Você viu o jogo ontem? Foi incrível.",
    "Minha sandália quebrou.", "Casa, comida e roupa lavada.",
]
TV = [
    "Boa noite. Começa agora o jornal da noite, com as principais notícias do dia no Brasil e no mundo.",
    "O presidente do Banco Central afirmou nesta terça-feira que a inflação deve continuar em queda nos próximos meses.",
    "Na previsão do tempo, uma frente fria chega ao sul do país e as temperaturas caem bastante no fim de semana.",
    "No futebol, o time da casa venceu por dois a um, com um gol aos quarenta e cinco minutos do segundo tempo.",
    "Você não entende, eu fiz tudo isso por nós dois! Não, agora chega, eu não quero mais ouvir as suas desculpas.",
    "Os moradores reclamam da falta de iluminação na rua e pedem uma solução urgente para a prefeitura.",
    "A campanha de vacinação foi prorrogada até o fim do mês em todos os postos de saúde da cidade.",
    "Eu nunca imaginei que você seria capaz de mentir pra mim desse jeito, depois de tudo que a gente passou.",
]
SPEAKERS = [  # (voz, velocidade, tom)
    ("pt-BR-AntonioNeural", "+0%", "+0Hz"), ("pt-BR-FranciscaNeural", "+0%", "+0Hz"),
    ("pt-BR-ThalitaMultilingualNeural", "+0%", "+0Hz"), ("pt-PT-DuarteNeural", "+0%", "+0Hz"),
    ("pt-PT-RaquelNeural", "+0%", "+0Hz"), ("en-US-AndrewMultilingualNeural", "+0%", "+0Hz"),
    ("en-US-AvaMultilingualNeural", "+0%", "+0Hz"), ("en-US-BrianMultilingualNeural", "+0%", "+0Hz"),
    ("en-US-EmmaMultilingualNeural", "+0%", "+0Hz"), ("de-DE-FlorianMultilingualNeural", "+0%", "+0Hz"),
    ("fr-FR-VivienneMultilingualNeural", "+0%", "+0Hz"), ("it-IT-GiuseppeMultilingualNeural", "+0%", "+0Hz"),
    ("pt-BR-AntonioNeural", "+15%", "-6Hz"), ("pt-BR-FranciscaNeural", "-10%", "+8Hz"),
    ("pt-BR-ThalitaMultilingualNeural", "+12%", "-8Hz"), ("en-US-AndrewMultilingualNeural", "-8%", "+5Hz"),
    ("en-US-AvaMultilingualNeural", "+10%", "-5Hz"), ("pt-PT-DuarteNeural", "-10%", "+6Hz"),
]


async def synth(sem, cid, text, voice, rate, pitch):
    wav = OUT / f"{cid}.wav"
    if wav.exists() and (OUT / f"{cid}.json").exists():
        return json.loads((OUT / f"{cid}.json").read_text(encoding="utf-8"))
    async with sem:
        for attempt in range(4):
            try:
                comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, boundary="WordBoundary")
                audio, words = b"", []
                async for chunk in comm.stream():
                    if chunk["type"] == "audio":
                        audio += chunk["data"]
                    elif chunk["type"] == "WordBoundary":
                        words.append({"w": chunk["text"], "start": chunk["offset"] / 1e7,
                                      "end": (chunk["offset"] + chunk["duration"]) / 1e7})
                break
            except Exception as exc:  # noqa: BLE001
                if attempt == 3:  # o serviço recusa algumas combinações de voz e frase: fica sem essa
                    print(f"sem áudio para {cid} ({text!r}, {voice}): {exc}", file=sys.stderr)
                    return None
                await asyncio.sleep(2 + attempt * 3)
    mp3 = OUT / f"{cid}.mp3"
    mp3.write_bytes(audio)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(mp3), "-ac", "1", "-ar", "48000", str(wav)],
                   check=True)
    mp3.unlink()
    meta = {"id": cid, "text": text, "voice": voice, "rate": rate, "pitch": pitch, "words": words}
    (OUT / f"{cid}.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return meta


async def main():
    sem = asyncio.Semaphore(6)
    jobs = []
    for si, (voice, rate, pitch) in enumerate(SPEAKERS):
        for pi, text in enumerate(POS):
            jobs.append(synth(sem, f"p{pi:02d}_s{si:02d}", text, voice, rate, pitch))
        for ni, text in enumerate(NEG):
            jobs.append(synth(sem, f"n{ni:02d}_s{si:02d}", text, voice, rate, pitch))
        for hi, text in enumerate(HARD):
            jobs.append(synth(sem, f"h{hi:02d}_s{si:02d}", text, voice, rate, pitch))
    tv_voices = ["pt-BR-AntonioNeural", "pt-BR-FranciscaNeural", "pt-BR-ThalitaMultilingualNeural"]
    for ti, text in enumerate(TV):
        jobs.append(synth(sem, f"tv{ti:02d}", text, tv_voices[ti % 3], "+5%", "+0Hz"))
    metas = [m for m in await asyncio.gather(*jobs) if m]
    corpus = []
    for m in metas:
        label = {"t": "tv", "p": "pos", "h": "hard"}.get(m["id"][0], "neg")
        corpus.append({**m, "label": label})
    (Path(__file__).parent / "corpus.json").write_text(json.dumps(corpus, ensure_ascii=False, indent=1),
                                                         encoding="utf-8")
    print(len(corpus), "clips")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
