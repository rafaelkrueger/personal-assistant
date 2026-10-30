# Bancada do microfone (wakebench)

Mede o gravador (`cassandra/vad_recorder.py`) e o detector do nome (Vosk, `cassandra/local_speech.py`) **reais** sobre
uma sala simulada: vozes sintéticas em português (edge-tts, 18 falantes), a uma distância (nível + reverberação), com
o chiado **real** do microfone do Pi e, se quiser, uma TV falando ao fundo. Tudo a 48 kHz, como o microfone USB entrega.

O que ela não mede: tempo real (o Pi lento, o buffer de 30 ms do microfone) e a nuvem (a transcrição) — isso foi
medido direto no Pi (ver o README principal, "Como ela ouve").

## Preparar (no PC)

```bash
python -m venv wb && wb/Scripts/python -m pip install vosk edge-tts numpy   # Windows; no Linux: wb/bin/python
wb/Scripts/python gen_corpus.py          # clips/ + corpus.json (~550 falas; precisa do ffmpeg)
scp -r <pi>:Desktop/personal-assistant/models/vosk-model-small-pt-0.3 .
mkdir real
# o chiado do microfone, com a Cassandra parada (o microfone fica preso a ela):
ssh <pi> 'systemctl --user stop cassandra-assistant; arecord -q -D hw:2,0 -f S16_LE -r 48000 -c 1 -d 25 /tmp/noise48k.wav; systemctl --user start cassandra-assistant'
scp <pi>:/tmp/noise48k.wav real/
```

`clips/`, `real/`, `results/` e o modelo ficam fora do git: as gravações são da casa (o repositório é público).

## Rodar

```bash
wb/Scripts/python run_bench.py nome --dist 2-3m,sala,longe --tv silencio,tv --speakers 6 --neg 0.5 \
    --set cassandra.vad_recorder.HPF_HZ=0            # qualquer constante de módulo; sim.NOISE_FILE='"noise2"' etc.
wb/Scripts/python summ.py nome outro                # compara rodadas já feitas
wb/Scripts/python tvonly.py nome                    # só a TV: candidatos a nome por minuto
```

Colunas: `acerto` = chamadas em que o Vosk achou o nome; `falso` = frases sem o nome que viraram candidato (cada uma
custa uma conferência na nuvem, que as descarta); `cand(s)` = segundos entre o fim do nome e o candidato; `fim(s)` /
`p90fim` = quanto a gravação demora para terminar depois da fala; `sem fim` = gravações que não terminaram até 7 s
depois da fala.
