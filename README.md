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

## Interface web (chat com historico e memoria)

Tambem e possivel conversar com a Cassandra pelo navegador, com historico persistente por sessao.

### Iniciar servidor web

```bash
python main.py
```

O `main.py` agora sobe:

- escuta principal da Cassandra (voz/texto)
- servidor web de chat no mesmo processo

Servidor web padrao: `http://localhost:8080`

Variaveis opcionais:

- `WEB_HOST` (padrao `0.0.0.0`)
- `WEB_PORT` (padrao `8080`)

### Como funciona a memoria unificada (voz + web)

- O chat web usa a mesma instancia/memoria do assistente principal
- Voce pode alternar entre voz e web mantendo o mesmo contexto
- Historico unificado e salvo em `data/conversation_history.json`
- No chat web, o botao "Nova conversa" limpa a memoria atual
- O chat web segue a logica de ativacao por wake word: use `cassandra, ...` para ativar
- O `on.mp3` toca quando a wake word e detectada (voz e web)
- No chat web, apos comando valido, a Cassandra responde no chat e tambem fala pela caixa de som
- No modo voz, apos cada resposta da Cassandra, toca `on.mp3` para sinalizar que voltou a escutar
- No modo voz, se o usuario nao responder por `WAKE_TIMEOUT_SECONDS`, toca `off.mp3` e entra em standby
- No modo web, nao ha timeout de standby: a sessao ativa permanece ate reset/fechamento da conversa

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
- Todo comando reconhecido apos ativacao em linha `[ACTION] ...` e em `data/action_commands.log`
- Toda fala ouvida fora de modo ativo em linha `[PASSIVE] ...` e em `data/passive_heard.log`

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

## CI/CD para Raspberry Pi (deploy automatico no push)

Este projeto inclui workflow em `.github/workflows/deploy-raspberry.yml` para deploy automatico no `push` da branch `main`.

### 1) Requisitos

- Runner GitHub Actions `self-hosted` no mesmo ambiente de rede (ou VPN) da Raspberry Pi
- SSH habilitado na Raspberry Pi

### 2) Secrets no repositorio GitHub

Configure estes secrets:

- `RPI_HOST` (ex.: `192.168.100.49`)
- `RPI_PORT` (ex.: `22`)
- `RPI_USER`
- `RPI_PASSWORD`
- `RPI_REMOTE_PATH` (ex.: `~/Desktop/personal-assistant`)
- `RPI_INPUT_MODE` (ex.: `mic` ou `text`)
- `RPI_VOICE_ENABLED` (ex.: `true` ou `false`)
- `RPI_INSTALL_SYSTEM_DEPS` (ex.: `false`; use `true` no primeiro deploy)

### 3) Como funciona

Ao fazer `git push` para `main`, o workflow:

1. Faz checkout do codigo
2. Instala `sshpass` e `rsync`
3. Roda `scripts/deploy_raspberry.sh`
4. Sincroniza arquivos para a Raspberry Pi (preserva `.env`, `data/` e `.venv/`)
5. Instala/atualiza dependencias Python
6. Reinicia `main.py` e mostra os ultimos logs
