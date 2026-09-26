# Cassandra - Assistente Pessoal

Projeto base de uma assistente pessoal chamada **Cassandra**, inspirada em assistentes como Alexa.

## Documentação técnica

Como nos outros agentes (web-agent, editor, maestro), a especificação fica em [`Docs/`](Docs/):

- [`Docs/CAPABILITIES.md`](Docs/CAPABILITIES.md) — o que a Cassandra pode e não pode fazer (em prosa; é o que o
  maestro lê para decidir se um pedido é para ela).
- [`Docs/API.md`](Docs/API.md) — todos os endpoints HTTP, formatos, erros e como integrar com o maestro.

## O que ela faz hoje

- So responde quando chamada por wake word (padrao `cassandra`, com aliases)
- Responde perguntas gerais usando OpenAI
- Pode ouvir pelo microfone em modo continuo (`INPUT_MODE=mic`)
- Consulta clima (via `wttr.in`)
- Registra e lista agenda local em `data/agenda.json`
- Alarmes programados (pontuais e recorrentes diarios)
- Lista de compras persistente
- Lista de tarefas persistente (com concluido/pendente)
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

## Modelo de IA (OpenAI ou DeepSeek)

Em **Configuracoes > Modelo de IA** (ou `GET`/`POST /api/llm`) da para escolher quem responde a Cassandra:
OpenAI ou DeepSeek, com modelo e chave de cada um. A troca vale na hora, sem reiniciar. As chaves ficam em
`data/llm_settings.json` (fora do git) e a API nunca devolve a chave, so um preview.

A DeepSeek so faz texto. Voz (TTS) e microfone (transcricao) continuam na OpenAI: com a DeepSeek ativa e
sem chave da OpenAI, a Cassandra fala com a voz local (espeak) e o modo microfone nao transcreve.

## Microfone e UI ao mesmo tempo

Com `INPUT_MODE=auto` (padrão sugerido) a Cassandra ouve o microfone **quando houver um plugado** e espera
em silêncio quando não houver — é só plugar um microfone USB e chamar pelo nome, sem reiniciar. O chat da
UI web funciona sempre, em qualquer modo, e também fala as respostas e toca os sons pela caixa de som.

Para o microfone plugado depois ser adotado sozinho, o Pi precisa do pacote `pipewire-alsa`
(`sudo apt install pipewire-alsa`): com ele a gravação passa pelo PipeWire, que converte a taxa de amostragem
e segue o microfone padrão.

## Voz da Cassandra (paga ou grátis)

Em **Configurações > Voz & TTS > Motor de voz**:

- **Automático** (padrão): voz da OpenAI (feminina, "nova") enquanto houver chave e créditos; se ela falhar
  (ex.: sem créditos), usa a voz feminina grátis do **espeak** e pula a OpenAI por 10 minutos.
- **OpenAI**: a mais natural, paga por caractere.
- **espeak**: `espeak-ng` com variante feminina — grátis, offline e instantânea (~80 ms por frase num
  Raspberry Pi 3), mas robótica. É o último recurso de qualquer motor.
- **Piper**: voz neural natural, grátis e offline, mas **masculina** (não há voz feminina em português no
  Piper) e ~3 s por frase num Pi 3. Só é carregada se for escolhida (`pt_BR-faber-medium`, ~63 MB, baixada
  sozinha para `models/piper/`).

Vozes femininas grátis testadas num Pi 3 e descartadas por lentidão: Edge TTS (~4,5 s por frase, online) e
Kokoro (`pf_dora`, ~25 s por frase).

O áudio sai pelo `pw-play` (PipeWire), direto na saída padrão — ex.: uma soundbar Bluetooth.

## Detecção do nome sem internet (modo microfone)

No modo microfone, a Cassandra reconhece o próprio nome **no aparelho**, com o Vosk (offline, grátis, modelo
pequeno em português de ~50 MB, baixado sozinho na primeira vez para `models/`). Fala sem o nome é
descartada ali mesmo: nada vai para a OpenAI. Só a fala que começa com "Cassandra" (e o que for dito
durante a sessão ativa) é transcrita.

```bash
WAKE_WORD_ENGINE=local        # local (padrão) | openai (transcreve toda fala na OpenAI, gasta créditos)
TRANSCRIPTION_PROVIDER=auto   # auto (OpenAI se houver chave; se falhar, local) | openai | local
```

Com `local` (ou `auto` sem chave/créditos), o comando também é transcrito pelo Vosk: grátis, mas leva
alguns segundos por frase num Raspberry Pi 3 e erra mais que a OpenAI. Se a OpenAI falhar (ex.: sem
créditos), a Cassandra usa só o local pelos 10 minutos seguintes.

## Outros agentes, sempre via maestro

A Cassandra **não fala com outros agentes direto**: pede ao **maestro** (a ponte entre todos os
agentes), que escolhe quem executa e devolve o resultado. Hoje isso é usado nas perguntas que precisam de
informação atual (notícias, cotações, clima, esportes, trânsito, busca geral) — o maestro despacha para
o web-agent.

O maestro roda no PC e nem sempre está ligado. A Cassandra checa a cada 15 s, em segundo plano, se ele
responde: ligado, ela usa; desligado (ou se o pedido falhar), ela responde só com o próprio LLM, sem esperar.
O status e a lista de agentes que ele controla aparecem em Configurações.

```bash
WEB_SEARCH_ENABLED=auto   # auto (padrão) = usa quando disponível; false = nunca usa
MAESTRO_URL=http://desktop-cc6nlck.local:8090,http://192.168.100.52:8090
MAESTRO_TOKEN=...    # o MAESTRO_SHARED_SECRET do maestro
MAESTRO_AGENT_NAME=personal-assistant
MAESTRO_TIMEOUT=120
```

O cliente é o plug-in `cassandra/maestro_link.py`, cópia de `maestro/plugin/maestro_link.py`
(o mesmo em todos os agentes). `MAESTRO_URL` aceita várias URLs, tentadas em ordem: prefira o nome
`.local` do PC, que continua valendo quando o roteador troca o IP. O maestro se chamava *orchestrator*:
os nomes antigos (`ORCHESTRATOR_URL`, `ORCHESTRATOR_TOKEN`, ...) continuam valendo.

## Interface web (dashboard)

Tambem e possivel usar a Cassandra pelo navegador com dashboard completo:

- Chat
- Lista de compras
- Lista de tarefas
- Alarmes

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

### Persistencia dos novos recursos

- Compras: `data/shopping_list.json`
- Tarefas: `data/todos.json`
- Alarmes: `data/alarms.json`

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

## Rodando no Raspberry Pi (serviços que sobem no boot)

Os serviços systemd, o túnel e a sincronização do site com o Netlify que rodam no Pi estão em
[`scripts/raspberry-pi/`](scripts/raspberry-pi/README.md), com o passo a passo de instalação.

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
7.Reiniciar servidor: systemctl --user restart cassandra-assistant.service