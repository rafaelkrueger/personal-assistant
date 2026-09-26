# API da Cassandra

Esta é a mesma API que a UI web da Cassandra (a página servida em `/`) usa — não
é uma versão reduzida nem paralela. Tudo o que a UI faz (conversar, mexer nas
listas, alarmes, rotinas, agenda, configurações, trocar o LLM) tem um endpoint
equivalente aqui.

- **Base URL (rede local):** `http://192.168.100.49:8080` (o Raspberry Pi; o nome
  `raspberrypi.local` não resolve a partir do PC Windows — use o IP).
- **Base URL (pública):** `https://cassandra-rafaelkrueger.netlify.app` — o site
  no Netlify repassa `/api/*` para o Pi por um túnel da Cloudflare. Endereço
  estável, mas o proxy do Netlify **corta a requisição em ~26 s**.
- **Formato:** JSON (UTF-8) em todo lugar. Todas as escritas são `POST`
  (exceto `PUT /api/llm`, aceito como sinônimo do `POST`).
- **Autenticação:** nenhuma. É um sistema de uma casa só.
- **Erros:** `{"error": "mensagem"}` com `400` (entrada inválida), `404` (rota
  inexistente) ou `500` (falha interna, ex.: o LLM sem créditos).

```
Servidor: .venv/bin/python main.py   (web em 0.0.0.0:8080 — WEB_HOST / WEB_PORT)
No Pi roda como serviço systemd do usuário: systemctl --user {status,restart} cassandra-assistant
```

Veja também [`CAPABILITIES.md`](./CAPABILITIES.md) (resumo em prosa do que ela
faz e não faz), [`../ai.md`](../ai.md) (arquitetura e variáveis do `.env`) e
[`../scripts/raspberry-pi/README.md`](../scripts/raspberry-pi/README.md)
(serviços, túnel e site no Raspberry Pi).

---

## 1. Visão geral

A Cassandra é um processo só (`main.py`) com duas entradas que compartilham o
**mesmo assistente, a mesma memória e o mesmo histórico**:

- **Voz** (`INPUT_MODE=auto`/`mic`): microfone plugado no Pi. O nome é detectado
  localmente (Vosk); só a fala que começa com "Cassandra" é transcrita e
  atendida.
- **Web** (esta API + a UI): texto.

Cada pedido passa por um roteador de **skills** (alarme, timer, agenda, compras,
tarefas, rotinas, busca na internet via web-agent) e, se nenhuma servir, pelo
**chat geral** com o LLM (OpenAI ou DeepSeek — seção 9). A resposta é
**falada em voz alta** na caixa de som da casa.

### Ativação pelo nome (wake word)

O chat segue a mesma regra da voz: **só atende depois de ouvir o nome**.

- Mensagem começando com o nome (`"cassandra, que horas são?"`) → ativa e
  atende o pedido na hora.
- Só o nome (`"cassandra"`) → ativa e responde "Ativada. Pode mandar o pedido.".
- Com a sessão ativa, as próximas mensagens não precisam do nome.
- Uma despedida ("tchau", "pode ir", "obrigado, era só isso") encerra a sessão.
- Sem o nome e sem sessão ativa → a mensagem é **ignorada** (registrada como
  "passiva") e a resposta explica que é preciso chamar pelo nome.

Aliases aceitos: `ASSISTANT_ALIASES` do `.env` (padrão `cassandra,casandra,cassanda`).

---

## 2. Chat

### `POST /api/chat`
**Body:** `{ "message": "cassandra, adiciona leite na lista de compras" }`

Processa a mensagem (regra do nome acima) e **responde assim que o texto está
pronto** — a fala sai em segundo plano, depois da resposta HTTP. Quando o nome é
detectado, toca também o som de ativação.

**Resposta `200`:**
```json
{
  "reply": "Leite adicionado à lista de compras.",
  "dismissed": false,
  "activated": true,
  "history": [
    { "role": "user", "content": "cassandra, adiciona leite na lista de compras",
      "source": "web_wake_inline", "kind": "chat", "timestamp": "2026-09-25 21:34:15" },
    { "role": "assistant", "content": "Leite adicionado à lista de compras.",
      "source": "assistant", "kind": "chat", "timestamp": "2026-09-25 21:34:17" }
  ]
}
```
- `activated`: `false` quando a mensagem foi ignorada por falta do nome.
- `dismissed`: `true` quando a mensagem encerrou a sessão (despedida).
- `history`: a conversa inteira (voz + web). `kind` é `chat`, `system` ou
  `passive`.

`400` se `message` vier vazio; `500` se o LLM falhar (ex.:
`"Internal error: Error code: 429 ... insufficient_quota"`).

Tempo típico: 2–5 s com DeepSeek/OpenAI. Perguntas que caem na busca da
internet dependem do web-agent (dezenas de segundos) — pela URL pública, acima
de ~26 s o Netlify devolve `504` (a Cassandra ainda responde e fala, mas o
cliente perde o texto; use a URL da rede local para pedidos longos).

### `POST /api/reset`
Limpa a memória e o histórico da conversa e encerra a sessão. `{ "ok": true }`.

### `GET /api/history`
`{ "history": [ ...itens como acima... ] }`

### `GET /api/dashboard`
Tudo o que a tela inicial usa, numa chamada:
```json
{ "history": [...], "shopping": [...], "todos": [...], "alarms": [...], "alarm_ringing": false }
```

---

## 3. Lista de compras

Item: `{ "id": "a1b2c3d4e5", "name": "leite", "created_at": "2026-09-25 21:34:17" }`

| Endpoint | Body | Resposta |
|---|---|---|
| `POST /api/shopping/add` | `{ "name": "leite" }` | `{ "shopping": [itens] }` — `400` sem `name` |
| `POST /api/shopping/remove` | `{ "id": "a1b2c3d4e5" }` | `{ "shopping": [itens] }` |

A lista também vem em `GET /api/dashboard` (`shopping`). Esses endpoints **não
passam pelo LLM e não falam** em voz alta.

---

## 4. Tarefas (to-do)

Tarefa: `{ "id": "...", "title": "pagar a conta de luz", "completed": false, "created_at": "..." }`

| Endpoint | Body | Resposta |
|---|---|---|
| `POST /api/todos/add` | `{ "title": "pagar a conta de luz" }` | `{ "todos": [tarefas] }` — `400` sem `title` |
| `POST /api/todos/toggle` | `{ "id": "...", "completed": true }` | `{ "todos": [tarefas] }` — `400` sem `id` |
| `POST /api/todos/remove` | `{ "id": "..." }` | `{ "todos": [tarefas] }` |

---

## 5. Alarmes

Alarme:
```json
{
  "id": "...", "label": "Acordar", "time_hhmm": "07:30",
  "recurring_daily": true, "days_of_week": [0, 1, 2, 3, 4],
  "next_trigger_at": "2026-09-26T07:30:00", "enabled": true
}
```
`days_of_week`: `0` = segunda … `6` = domingo; `null` = todos os dias.

| Endpoint | Body | Resposta |
|---|---|---|
| `POST /api/alarms/add` | `{ "time_hhmm": "07:30", "recurring_daily": true, "label": "Acordar", "days_of_week": [0,1,2,3,4] }` | `{ "alarms": [alarmes] }` — `400` sem `time_hhmm` ou horário inválido |
| `POST /api/alarms/remove` | `{ "id": "..." }` | `{ "alarms": [alarmes] }` |
| `POST /api/alarms/stop` | — | `{ "alarm_ringing": false }` — silencia o alarme que está tocando |

Só `time_hhmm` é obrigatório (`label` padrão "Alarme"; `recurring_daily` padrão
`false`). Quando dispara, o alarme toca na caixa de som e pode disparar rotinas
ligadas a ele (seção 6). A lista também vem em `GET /api/dashboard`.

**Timers** não têm endpoint próprio: peça pelo chat (`"cassandra, timer de 10 minutos"`).

---

## 6. Rotinas

Uma rotina executa uma lista de ações quando um gatilho acontece.

```json
{
  "id": "...", "name": "Bom dia",
  "trigger": { "type": "alarm", "alarm_id": "<id do alarme>", "time_hhmm": "" },
  "actions": [ { "type": "falar", "text": "Bom dia!" }, { "type": "clima", "text": "" }, { "type": "noticias", "text": "" } ],
  "enabled": true, "created_at": "..."
}
```
- `trigger.type`: `"time"` (usa `time_hhmm`, ex. `"07:00"`) ou `"alarm"` (usa
  `alarm_id` — roda quando aquele alarme dispara).
- `actions[].type`: `falar` (fala `text`), `noticias`, `cotacao`, `clima`,
  `esporte`, `transito`. As cinco últimas pesquisam via **web-agent** e são
  puladas se ele estiver indisponível.

| Endpoint | Body | Resposta |
|---|---|---|
| `GET /api/routines` | — | `{ "routines": [rotinas] }` |
| `POST /api/routines/add` | `{ "name": "...", "trigger": {...}, "actions": [...] }` | `{ "routine": {...}, "routines": [...] }` — `400` sem `name` ou `actions` |
| `POST /api/routines/toggle` | `{ "id": "...", "enabled": false }` | `{ "routines": [...] }` |
| `POST /api/routines/run` | `{ "id": "..." }` | `{ "ok": true }` — executa agora (fala na caixa de som) |
| `POST /api/routines/remove` | `{ "id": "..." }` | `{ "routines": [...] }` |

---

## 7. Agenda (CalDAV)

Integra com qualquer calendário CalDAV (Google Calendar com senha de app,
iCloud, Nextcloud…). A senha fica só no aparelho e nunca volta pela API.

| Endpoint | Body / query | Resposta |
|---|---|---|
| `GET /api/calendar/status` | — | `{ "configured": true, "username": "...", "url": "..." }` |
| `POST /api/calendar/configure` | `{ "url": "...", "username": "...", "password": "..." }` | `{ "ok": true, "message": "..." }` — `400` se faltar campo |
| `POST /api/calendar/disconnect` | — | `{ "ok": true }` |
| `GET /api/agenda/events?days=7` | `days` padrão 7 (a partir de hoje) | `{ "configured": true, "events": [eventos] }` (`configured: false` e lista vazia sem calendário) |
| `POST /api/agenda/events/add` | `{ "title": "Dentista", "date": "2026-09-30", "start": "14:00", "end": "15:00", "description": "" }` | `{ "event": {...} }` — `400` se faltar campo, `500` se o servidor recusar |
| `POST /api/agenda/events/delete` | `{ "event_id": "<id do evento>" }` | `{ "ok": true }` |

Evento: `{ "id": "<url do evento>", "uid": "...", "title": "...", "start": "...", "end": "...", "description": "...", "start_raw": "2026-09-30T14:00:00" }`.

---

## 8. Configurações da UI

### `GET /api/settings`
```json
{
  "modules": { "chat": true, "shopping": true, "todos": true, "alarms": true, "routines": true, "agenda": true },
  "voice": { "enabled": true, "engine": "auto", "tts_model": "tts-1", "tts_voice": "nova",
             "fallback_lang": "pt", "fallback_rate": 160 },
  "sounds": { "enabled": true },
  "session": { "wake_timeout": 30 },
  "_runtime": { "assistant_name": "cassandra", "input_mode": "auto", "llm": "DeepSeek · deepseek-flash", ... }
}
```
- `voice.engine`: `auto` (OpenAI enquanto houver créditos; senão voz feminina
  grátis local), `openai`, `espeak` (grátis, feminina, instantânea) ou `piper`
  (grátis, masculina, mais lenta).
- `voice.enabled: false` desliga a fala (as respostas continuam em texto).
- `_runtime` é só leitura (vem do `.env`/processo).

### `POST /api/settings`
Body: qualquer subconjunto do objeto acima (mesclado com o que já existe). Vale
na hora, sem reiniciar. Devolve o objeto completo.
### `POST /api/settings/reset`
Volta tudo ao padrão. Devolve o objeto completo.

---

## 9. LLM (`/api/llm`)

Mesmo formato do orchestrator, do editor e do web-agent. Provider ativo
(`openai` | `deepseek`) + modelo e chave de cada um. A troca vale na hora.

### `GET /api/llm`
```json
{
  "llm_provider": "deepseek", "providers": ["openai", "deepseek"],
  "openai_model": "gpt-4o-mini", "openai_api_key_set": true, "openai_api_key_preview": "sk-···qA4A",
  "deepseek_model": "deepseek-flash", "deepseek_base_url": "https://api.deepseek.com",
  "deepseek_api_key_set": true, "deepseek_api_key_preview": "sk-···ba59",
  "audio_available": true
}
```
A chave nunca volta — só `*_set` e um preview. `audio_available` indica se há
chave da OpenAI (a DeepSeek não tem voz nem transcrição: sem OpenAI, a voz usa
o motor grátis local e a transcrição do microfone é local).

### `POST /api/llm` (ou `PUT`)
Campos parciais — só o que muda. Chave vazia/omitida **nunca apaga** a salva.
```json
{ "llm_provider": "deepseek", "deepseek_api_key": "sk-...", "deepseek_model": "deepseek-flash" }
```
`400` com provider inválido. Devolve o mesmo formato do `GET`.

---

## 10. Web-agent

### `GET /api/web-agent-status`
`{ "connected": true, "url": "http://desktop-cc6nlck.local:8001" }`

Checa agora (pode levar alguns segundos se ele estiver desligado). A Cassandra
checa sozinha a cada 15 s e só usa o web-agent enquanto ele responde; depois de
uma falha numa tarefa, fica 5 min sem usá-lo. Configuração: `WEB_AGENT_URL`
(uma ou mais URLs separadas por vírgula), `WEB_SEARCH_ENABLED` (`auto` |
`false`), `WEB_AGENT_TIMEOUT`.

---

## 11. Página

### `GET /`
A UI web (HTML único, sem build). É a mesma página publicada no Netlify.

---

## 12. Integração com o orchestrator

Ainda não existe adapter da Cassandra em `orchestrator/app/adapters/`. Um
adapter precisa só de:

1. **Pedido em linguagem natural** → `POST /api/chat` com
   `{"message": "cassandra, <pedido>"}` (sempre com o nome na frente — a sessão
   pode ter sido encerrada por outra pessoa, por voz). Resultado: `reply`.
   Timeout de cliente de ~120 s cobre inclusive buscas via web-agent.
2. **Pedido estruturado** (quando o orchestrator já sabe exatamente o que
   fazer) → endpoints diretos: `POST /api/shopping/add`, `/api/todos/add`,
   `/api/alarms/add`, `GET /api/dashboard`… São instantâneos, determinísticos e
   não falam em voz alta.
3. **Status/saúde** → `GET /api/settings` (200 = no ar).

Cuidados para quem despacha:
- **Tudo que passa por `/api/chat` é falado em voz alta na casa.**
- A conversa é **única** e compartilhada com a voz e a UI — um despacho entra no
  mesmo histórico que o usuário vê.
- Não há conceito de tarefa/`job_id`: a resposta já é o resultado final.
- Não há callback para o orchestrator (a Cassandra não inicia pedidos para
  outros agentes pelo orchestrator; ela chama o web-agent direto).

### Exemplo (curl)
```bash
BASE=http://192.168.100.49:8080

# Pedido em linguagem natural (é falado em voz alta na casa)
curl -s -X POST $BASE/api/chat -H "Content-Type: application/json" \
  -d '{"message":"cassandra, quanto é 7 vezes 8?"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['reply'])"

# Pedido estruturado (não fala, não usa o LLM)
curl -s -X POST $BASE/api/shopping/add -H "Content-Type: application/json" -d '{"name":"café"}'
curl -s -X POST $BASE/api/alarms/add -H "Content-Type: application/json" \
  -d '{"time_hhmm":"07:30","recurring_daily":true,"label":"Acordar"}'

# O que está na lista, nas tarefas e nos alarmes
curl -s $BASE/api/dashboard
```
