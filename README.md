# Cassandra - Assistente Pessoal

Projeto base de uma assistente pessoal chamada **Cassandra**, inspirada em assistentes como Alexa.

## O que ela faz hoje

- So responde quando chamada por wake word (padrao `cassandra`, com aliases)
- Responde perguntas gerais usando OpenAI
- Pode ouvir pelo microfone em modo continuo (`INPUT_MODE=mic`)
- Consulta clima (via `wttr.in`)
- Registra e lista agenda local em `data/agenda.json`
- Organiza cada habilidade em pastas dentro de `skills/`

## Estrutura

```text
.
├── cassandra/
│   ├── assistant.py
│   ├── config.py
│   ├── openai_client.py
│   └── router.py
├── skills/
│   ├── base.py
│   ├── general_chat/
│   │   └── skill.py
│   ├── schedule/
│   │   └── skill.py
│   └── weather/
│       └── skill.py
├── main.py
└── requirements.txt
```

## Instalar e rodar

1. Crie um ambiente virtual:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Instale as dependencias:

```bash
pip install -r requirements.txt
```

3. Configure as variaveis de ambiente:

```bash
cp .env.example .env
export OPENAI_API_KEY="sua-chave-aqui"
export OPENAI_MODEL="gpt-4o-mini"
export ASSISTANT_NAME="cassandra"
export ASSISTANT_ALIASES="cassandra,casandra,cassanda"
export INPUT_MODE="text"
export TRANSCRIPTION_MODEL="gpt-4o-mini-transcribe"
export TRANSCRIPTION_LANGUAGE="pt"
export TRANSCRIPTION_PROMPT="A fala principal e em portugues do Brasil. Preserve nomes proprios e titulos de musicas no idioma original."
export MIC_CHUNK_SECONDS="1"
export MIC_DEBUG="true"
export WAKE_TIMEOUT_SECONDS="10"
export ON_SOUND_PATH="assets/on.mp3"
export OFF_SOUND_PATH="assets/off.mp3"
export COMMAND_CAPTURE_MAX_SECONDS="12"
export COMMAND_SILENCE_CHUNKS="3"
export COMMAND_END_SILENCE_SECONDS="3.0"
export VOICE_ENABLED="true"
export VOICE_LANG="pt-br"
export VOICE_RATE="165"
```

4. Inicie:

```bash
python main.py
```

## Exemplos de comando

- `cassandra, que horas sao em toquio?`
- `cassandra, como esta o tempo em curitiba?`
- `cassandra, marcar compromisso Reuniao com Joao sexta 15:00`
- `cassandra, mostrar agenda`

## Modo microfone com logs

Para debugar se ela esta ouvindo, rode com:

```bash
export INPUT_MODE="mic"
export MIC_DEBUG="true"
python main.py
```

Com isso, o terminal mostra:

- Transcricao de cada trecho capturado do microfone
- Texto recebido pelo roteador
- Se a wake word (ex.: `cassandra`) foi detectada ou ignorada

Quando detectar a wake word, toca `assets/on.mp3`. Se nao houver pedido em 10 segundos, toca `assets/off.mp3`.
Depois da wake word, a captura de comando fica mais paciente: ela junta trechos por ate `COMMAND_CAPTURE_MAX_SECONDS` e so finaliza apos silencio suficiente (`COMMAND_SILENCE_CHUNKS` + `COMMAND_END_SILENCE_SECONDS`).

Comandos de despedida (`tchau`, `ate logo`, `encerrar`, `desligar`, etc.) fazem a Cassandra se despedir, tocar `off.mp3` e parar de ouvir.

## Voz da Cassandra

A Cassandra pode falar as respostas em voz alta usando TTS local.

- `VOICE_ENABLED=true`: ativa a voz
- `VOICE_LANG=pt-br`: idioma/voz
- `VOICE_RATE=165`: velocidade da fala

Para priorizar portugues na escuta (sem perder titulos em ingles), use:

```bash
export TRANSCRIPTION_LANGUAGE="pt"
export TRANSCRIPTION_PROMPT="A fala principal e em portugues do Brasil. Preserve nomes proprios e titulos de musicas no idioma original."
```

Se aparecer erro de `arecord`, instale:

```bash
sudo apt-get update && sudo apt-get install -y alsa-utils
```

## Como adicionar uma skill nova

1. Crie uma pasta em `skills/nova_skill/`
2. Implemente `skill.py` herdando de `Skill`
3. Registre a skill em `cassandra/assistant.py` dentro da lista do `SkillRouter`

Assim cada habilidade fica isolada e facil de evoluir.
