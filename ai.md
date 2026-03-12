# Cassandra - Documento de Arquitetura e Regras de Negocio

Este documento descreve como a assistente pessoal **Cassandra** funciona hoje: regras de negocio, arquitetura tecnica, fluxo de execucao, organizacao de skills e diretrizes de evolucao.

## 1) Objetivo do sistema

A Cassandra e uma assistente pessoal por voz/texto, inspirada em assistentes como Alexa, com foco em:

- ativacao por wake word;
- resposta em linguagem natural;
- execucao de habilidades (skills) separadas por dominio;
- baixa friccao para adicionar novas skills.

## 2) Regras de negocio

As regras abaixo definem o comportamento esperado do produto.

### 2.1 Ativacao por nome

- A assistente **so processa pedidos apos detectar wake word**.
- Wake word principal vem de `ASSISTANT_NAME`.
- Variacoes aceitas vem de `ASSISTANT_ALIASES`.
- A deteccao considera:
  - match direto no inicio da frase (`cassandra, ...`);
  - tolerancia a pequenas variacoes de transcricao (fuzzy match no primeiro token).

### 2.2 Sessao ativa e timeout

- Quando wake word e detectada:
  - toca `ON_SOUND_PATH` (padrao `assets/on.mp3`);
  - abre uma janela de sessao ativa por `WAKE_TIMEOUT_SECONDS` (padrao 10s).
- Durante sessao ativa, o usuario pode falar sem repetir a wake word.
- Se o timeout expira sem novo pedido:
  - toca `OFF_SOUND_PATH` (padrao `assets/off.mp3`);
  - encerra a sessao ativa.

### 2.3 Entrada por microfone ou texto

- `INPUT_MODE=text`: entrada via terminal.
- `INPUT_MODE=mic`: entrada via microfone com captura em pequenos blocos.
- Em modo microfone:
  - o audio e capturado por `arecord`;
  - o audio e transcrito pela API da OpenAI.

### 2.4 Idioma e transcricao

- Idioma principal da transcricao e configurado por `TRANSCRIPTION_LANGUAGE` (padrao `pt`).
- Prompt de transcricao e configurado por `TRANSCRIPTION_PROMPT`.
- Regra esperada: priorizar portugues e preservar nomes/titulos em idioma original quando necessario.

### 2.5 Resposta por voz

- Quando `VOICE_ENABLED=true`, as respostas sao faladas localmente via TTS.
- Backends suportados automaticamente:
  - `espeak` (preferencial, se instalado);
  - `spd-say` (fallback).
- Parametros:
  - `VOICE_LANG` (padrao `pt-br`);
  - `VOICE_RATE` (velocidade, padrao 165).

### 2.6 Roteamento para skills

- Todo comando valido e encaminhado para `SkillRouter`.
- O router seleciona a primeira skill cujo `can_handle()` retornar `True`.
- A ultima skill deve atuar como fallback de conversa geral.

### 2.7 Persistencia de agenda

- Compromissos sao gravados em `data/agenda.json`.
- Regra atual: persistencia local simples, sem banco externo.

## 3) Arquitetura tecnica

## 3.1 Estrutura de diretorios (resumo)

- `main.py`: ponto de entrada.
- `cassandra/`: nucleo da aplicacao.
  - `assistant.py`: loop principal, wake word, sessao ativa, timeout, execucao de skills.
  - `config.py`: leitura/validacao de configuracoes via `.env`.
  - `input_sources.py`: adaptadores de entrada (`text` e `mic`).
  - `openai_client.py`: cliente OpenAI para chat e transcricao.
  - `router.py`: roteador de skills.
  - `sounds.py`: player para sons de ativacao/desativacao.
  - `voice.py`: saida de voz local (TTS).
- `skills/`: modulo de habilidades.
  - `base.py`: contrato abstrato de skill.
  - `schedule/skill.py`: agenda.
  - `weather/skill.py`: clima.
  - `general_chat/skill.py`: fallback conversacional.
- `assets/`: midias de audio (on/off).
- `data/`: armazenamento local de dados.

## 3.2 Componentes e responsabilidades

- **Assistant**: orquestra todo o ciclo de vida.
- **InputSource**: encapsula origem de entrada.
- **LLMService**: integra com OpenAI.
- **SkillRouter**: desacopla decisao de skill.
- **Skill**: contrato padrao para extensibilidade.
- **SoundPlayer/VoiceOutput**: feedback sonoro e fala.

## 3.3 Fluxo de execucao (alto nivel)

1. Carrega configuracoes via `.env`.
2. Inicializa componentes (input, llm, router, audio).
3. Recebe entrada do usuario.
4. Detecta wake word.
5. Gerencia sessao ativa + timeout + sons.
6. Roteia comando para skill adequada.
7. Retorna resposta em texto e voz.

## 4) Contrato de skills

Toda nova skill deve implementar:

- `can_handle(text: str) -> bool`
- `handle(text: str) -> str`

Boas praticas:

- manter cada skill em sua propria pasta (`skills/nome_da_skill/`);
- evitar efeitos colaterais inesperados em `can_handle`;
- tratar erros e retornar mensagens claras ao usuario;
- manter `handle` curto, delegando logica complexa para funcoes auxiliares.

## 5) Configuracao por ambiente (.env)

Principais variaveis:

- OpenAI:
  - `OPENAI_API_KEY`
  - `OPENAI_MODEL`
- Wake word:
  - `ASSISTANT_NAME`
  - `ASSISTANT_ALIASES`
- Entrada:
  - `INPUT_MODE` (`text` ou `mic`)
  - `MIC_CHUNK_SECONDS`
  - `MIC_DEBUG`
- Transcricao:
  - `TRANSCRIPTION_MODEL`
  - `TRANSCRIPTION_LANGUAGE`
  - `TRANSCRIPTION_PROMPT`
- Sessao/sons:
  - `WAKE_TIMEOUT_SECONDS`
  - `ON_SOUND_PATH`
  - `OFF_SOUND_PATH`
- Voz:
  - `VOICE_ENABLED`
  - `VOICE_LANG`
  - `VOICE_RATE`

## 6) Dependencias externas

- Python libs:
  - `openai`
  - `requests`
  - `python-dotenv`
- Ferramentas do sistema:
  - `arecord` para captura de microfone;
  - `ffplay`/`mpg123`/`mpv`/`cvlc`/`play` para sons on/off;
  - `espeak` ou `spd-say` para fala TTS.

## 7) Observabilidade e debug

Quando `MIC_DEBUG=true`, o sistema exibe:

- transcricao capturada do microfone;
- eventos de roteamento;
- deteccao/ignorancia da wake word;
- eventos de timeout da sessao.

Recomendacao: manter `MIC_DEBUG=false` em uso normal e `true` apenas para diagnostico.

## 8) Limitacoes atuais

- Transcricao e resposta dependem de latencia de rede/API.
- Nao ha controle de contexto conversacional de longo prazo.
- Agenda e local (arquivo json), sem sincronizacao em nuvem.
- Nao ha autenticacao de usuario.
- Nao existe suite formal de testes automatizados no momento.

## 9) Seguranca e governanca

- Nunca commitar chave de API em repositorio.
- Usar `.env` local e manter `.env` no `.gitignore`.
- Rotacionar chaves se houver exposicao acidental.
- Para producao, considerar gerenciador de segredos.

## 10) Roadmap sugerido

- Streaming/realtime para reduzir latencia percebida.
- Memoria conversacional com contexto curto e seguro.
- Skills de musica, notificacoes e integracao com calendario real.
- Testes automatizados (unitario + integracao) por skill.
- Empacotamento como servico (systemd/docker) para execucao continua.

---

Documento mantido para orientar evolucao tecnica e funcional da Cassandra.
