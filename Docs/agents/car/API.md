# Torque (car) — API

Base: `http://192.168.100.49:8015` (no Raspberry Pi) ou `http://127.0.0.1:8015` (neste PC). Sem autenticação: só
deve ficar acessível na rede de casa. Tudo em JSON; erros voltam como `{ "detail": "mensagem legível" }` com `400`
(dado faltando ou inválido), `404` (não encontrado) ou `502` (o modelo de IA falhou).

Números aceitam o formato brasileiro em texto (`"48.250"`, `"236,00"`, `"5,899"`); datas são `AAAA-MM-DD` (sem
data vale hoje).

- [1. Saúde do serviço](#1-saúde-do-serviço)
- [2. O carro e a situação geral](#2-o-carro-e-a-situação-geral)
- [3. Hodômetro](#3-hodômetro)
- [4. Abastecimentos](#4-abastecimentos)
- [5. Manutenção](#5-manutenção)
- [6. Prazos](#6-prazos)
- [7. Conversa (é o que o maestro usa)](#7-conversa-é-o-que-o-maestro-usa)
- [8. LLM](#8-llm-mesmo-formato-dos-outros-agentes)

## 1. Saúde do serviço

### `GET /api/health`
`{ "ok": true, "vehicle": "Chevrolet Onix 2020", "km": 48250, "alerts": 2, "llm": "DeepSeek · deepseek-flash" }` —
`km` é a estimativa de hoje; `alerts` conta o que está vencido ou vencendo. O maestro usa para o status online e
para o painel do agente.

## 2. O carro e a situação geral

### `GET /api/vehicle` · `PUT /api/vehicle`
`{ "nickname", "make", "model", "year", "engine", "plate", "color", "fuel", "tank_liters", "notes" }` — o `PUT` muda só os
campos enviados; campo desconhecido é ignorado.

### `GET /api/status`
Tudo de uma vez, sem LLM:
```json
{ "label": "Chevrolet Onix 2020",
  "vehicle": { "…": "…" },
  "mileage": { "km": 48250, "date": "2026-10-01", "km_per_month": 1015, "estimated_km": 48487,
               "days_since": 7, "stale": false },
  "fuel": { "count": 12, "km_per_liter": 11.9, "last_km_per_liter": 12.4, "cost_per_km": 0.46, "range_km": 524,
            "month_total": 472.0, "total": 5210.3, "last": { "…": "…" }, "segments": [ { "…": "…" } ] },
  "alerts": [ { "level": "overdue", "kind": "maintenance", "title": "Troca de óleo e filtro de óleo",
                "text": "Troca de óleo e filtro de óleo: faltam 5.000 km e venceu em 03/09/2026." } ],
  "plan_counts": { "overdue": 1, "soon": 1, "unknown": 9, "ok": 2 },
  "next_maintenance": { "…item do plano…": "…" }, "next_reminder": { "…prazo…": "…" },
  "costs": { "…ver /api/costs…": "…" },
  "text": "Chevrolet Onix 2020: 48.487 km (estimado). Você roda cerca de 1.015 km por mês. …" }
```
- `mileage.km` é o maior km registrado (leituras, abastecimentos e serviços); `km_per_month` sai dos últimos 180
  dias (precisa de duas leituras com 14 dias ou mais entre elas); `estimated_km` projeta até hoje por esse ritmo;
  `stale` = última leitura há mais de 45 dias.
- `alerts[].level`: `overdue` (vencido), `soon` (vence em até 30 dias ou 1.000 km) ou `info` (hodômetro
  desatualizado ou não informado). `kind`: `maintenance`, `reminder` ou `odometer`.
- `text` é o que o maestro devolve em `action=status`.

### `GET /api/costs?months=12`
`{ "months": [ { "month": "2026-10", "label": "outubro/2026", "fuel", "maintenance", "documents", "total" } ],
"this_month": {…}, "by_kind": { "fuel", "maintenance", "documents" }, "total", "cost_per_km", "km_tracked" }` —
combustível = abastecimentos; manutenção = custo dos serviços; documentos = prazos marcados como pagos.
`cost_per_km` = tudo ÷ km entre a primeira e a última leitura.

## 3. Hodômetro

### `GET /api/odometer` → `{ "readings": [ { "id", "date", "km", "source" } ], "mileage": {…} }`
### `POST /api/odometer` — **Body:** `{ "km": 48250, "date": "2026-10-08" }`
### `DELETE /api/odometer/{id}`

## 4. Abastecimentos

### `GET /api/fuel`
`{ "fills": [ { "id", "date", "km", "liters", "total", "price_liter", "fuel", "full", "station", "source" } ],
"stats": {…}, "fuels": ["Gasolina", "Etanol", "Diesel", "GNV", "Gasolina aditivada"] }`

O consumo (`stats.km_per_liter`) é medido **de tanque cheio a tanque cheio**: km rodados ÷ litros colocados até
encher de novo; abastecimento parcial (`full: false`) entra na soma dos litros do trecho. Precisa de dois
abastecimentos de tanque cheio com `km`. `stats.segments` traz cada trecho (`date`, `km`, `liters`, `cost`,
`km_per_liter`); `range_km` = consumo × `tank_liters` do carro.

### `POST /api/fuel`
**Body:** `{ "date", "km": 48300, "liters": 40, "total": 236, "price_liter": 5.9, "fuel": "Gasolina", "full": true,
"station": "Posto X" }` — precisa de `liters` ou `total`; com dois de (`liters`, `total`, `price_liter`) o
terceiro sai da conta. `full` padrão `true`.

### `DELETE /api/fuel/{id}`

## 5. Manutenção

### `GET /api/plan`
`{ "plan": [ { "id", "name", "interval_km", "interval_months", "last_km", "last_date", "notes", "enabled",
"due_km", "due_date", "km_left", "days_left", "expected_date", "status" } ], "mileage": {…} }`

O plano nasce com 13 itens típicos de carro de passeio (óleo, filtros, pneus, freios, arrefecimento, velas,
correia, bateria, palhetas) — o que vale é o manual do carro. Cada item vence por km (`last_km + interval_km`) ou
por tempo (`last_date + interval_months`), o que vier primeiro. `status`: `overdue`, `soon` (até 1.000 km ou 30
dias), `ok`, `unknown` (nunca registrado: não dá para saber) ou `off` (`enabled: false`). `expected_date` é a data
prevista pelo ritmo de uso. A lista vem ordenada: vencidos, em breve, sem registro, em dia.

### `POST /api/plan`
**Body:** `{ "name": "Troca de óleo", "interval_km": 5000, "interval_months": 6, "last_km": 45000,
"last_date": "2026-03-10" }` — precisa de `name` e de um intervalo. Mesmo nome de um item que já existe (ou
contido nele: "troca de óleo" acha "Troca de óleo e filtro de óleo") = atualiza só o que veio preenchido.

Cada item traz também `source`: `"manual"` (intervalo do plano de fábrica, achado pela pesquisa), `"ia"` (estimado
pelo modelo de IA) ou `""` (típico ou definido por você).

### `POST /api/plan/research` · `GET /api/plan/research`
Descobre o plano de manutenção e a ficha técnica **do modelo cadastrado** e grava no plano. O `POST` começa (`400`
se faltar marca, modelo ou ano) e roda em segundo plano; o `GET` acompanha:
```json
{ "status": "done", "car": "Honda HR-V EX CVT 2017 Flex", "source": "web", "current": true, "ready": true,
  "step": "", "summary": "…", "sources": ["https://…"], "web_error": "",
  "updated": ["Troca de óleo e filtro de óleo"], "added": ["Fluido da transmissão CVT"],
  "disabled": ["Correia dentada"], "specs_count": 9, "started_at": "…", "finished_at": "…" }
```
- `status`: `idle` (nunca feita), `running` (`step` diz em que pé está), `done` ou `error` (`error` diz por quê).
- Como funciona (`app/research.py`): (1) pede ao **web-agent**, pelo maestro (`POST /maestro/request`,
  `target_agent: "web-agent"`, `deep_search`), o plano de revisões de fábrica e a ficha técnica; (2) o modelo de IA
  transforma o texto em itens e ficha; (3) itens que já existem têm os intervalos trocados (a "última vez" fica),
  os novos são criados e os que não se aplicam ao carro são desligados (`enabled: false`).
- `source: "web"` = veio da pesquisa; `"ia"` = o maestro/web-agent não respondeu (`web_error` diz por quê) e o plano
  saiu do que o modelo de IA conhece — itens marcados como estimados.
- `current: false` = a pesquisa guardada é de outro modelo (o carro foi trocado depois).
- Salvar o carro com marca, modelo, ano ou motor diferentes (`PUT /api/vehicle`) dispara a pesquisa sozinho
  (`research_started: true` na resposta); `CAR_AUTO_RESEARCH=0` desliga. No chat, "monta o plano de manutenção do
  meu carro" também dispara (`research` na resposta).
- Precisa de `MAESTRO_URL`, `MAESTRO_TOKEN` e `MAESTRO_AGENT_NAME=car` no `.env` (ver `.env.example`).

### `GET /api/specs`
`{ "items": [ { "label": "Óleo do motor", "value": "0W-20 API SN" } ], "source": "web" | "ia", "updated_at": "…" }`
— a ficha técnica achada pela pesquisa.

### `PATCH /api/plan/{id}` — os campos enviados substituem (`{ "enabled": false }` desliga). · `DELETE /api/plan/{id}`

### `GET /api/services` → `{ "services": [ { "id", "date", "km", "items": ["…"], "description", "cost", "shop" } ] }`

### `POST /api/services`
**Body:** `{ "date": "2026-10-07", "km": 48000, "items": ["Troca de óleo e filtro de óleo"], "description":
"troca de lâmpada", "cost": 280, "shop": "Oficina do Zé" }` — precisa de `items` ou `description`. Cada entrada de
`items` pode ser o nome ou o `id` de um item do plano: a "última vez" dele passa a ser a deste serviço (um serviço
mais antigo não desfaz um mais novo). Nome que não está no plano fica só no histórico. Sem `km`, vale o km do
carro.

### `DELETE /api/services/{id}` — apaga o registro; a "última vez" no plano não volta sozinha.

## 6. Prazos

### `GET /api/reminders`
`{ "reminders": [ { "id", "name", "kind", "due_date", "amount", "yearly", "notes", "days_left", "status",
"paid": [ { "date", "amount", "due_date" } ] } ], "kinds": ["IPVA", "Licenciamento", "Seguro", "CNH", "Multa",
"Financiamento", "Outro"] }` — ordenados pelo vencimento; `status`: `overdue`, `soon` (até 30 dias) ou `ok`.

### `POST /api/reminders`
**Body:** `{ "name": "IPVA", "due_date": "2027-03-15", "amount": 1850 }` — precisa do nome (ou `kind`) e da data.
Sem `kind`, sai do nome; sem `yearly`, IPVA, licenciamento e seguro são anuais. Mesmo nome = atualiza.

### `PATCH /api/reminders/{id}` · `DELETE /api/reminders/{id}`

### `POST /api/reminders/{id}/done`
**Body (opcional):** `{ "amount": 1900, "date": "2026-10-08" }` — marca como pago (sem `amount` vale o previsto). O
que é anual tem o vencimento empurrado um ano; o resto sai da lista. O valor entra nos custos (`documents`).

## 7. Conversa (é o que o maestro usa)

### `POST /api/chat`
**Body:** `{ "message": "troquei o óleo ontem com 48 mil km e abasteci 40 litros por 236", "source": "maestro" }`

Duas chamadas ao modelo: a primeira extrai e grava o que a pessoa contou; a segunda responde com o contexto já
atualizado e a lista exata do que foi gravado.
```json
{ "reply": "Anotei. A próxima troca de óleo é com 58.000 km ou em outubro de 2027…",
  "noted": "Serviço em 07/10/2026 com 48.000 km: Troca de óleo e filtro de óleo\nAbastecimento em 08/10/2026: 40 l · R$ 236,00 · tanque cheio",
  "vehicle": [], "odometer": [], "fuel": [ {…} ], "services": [ {…} ], "reminders": [], "reminders_done": [],
  "plan": [], "removed": [] }
```
`noted` vem vazio quando nada foi gravado (uma pergunta, por exemplo).

### `POST /api/quick`
**Body:** `{ "text": "o carro está com 48.250 km", "source": "maestro" }` — só anota, sem conversa (uma chamada ao
modelo). Devolve os mesmos campos de registros e `text` com a confirmação. `400` se não houver nada a anotar. É o
`action=add` do maestro.

### `GET /api/chat` → `{ "messages": [ { "role", "content", "source", "ts" } ] }` · `DELETE /api/chat`

## 8. LLM (mesmo formato dos outros agentes)

### `GET /api/llm`
`{ "llm_provider": "openai", "providers": ["openai", "deepseek"], "openai_model", "openai_api_key_set",
"openai_api_key_preview", "deepseek_model", "deepseek_base_url", "deepseek_api_key_set",
"deepseek_api_key_preview" }` — nunca a chave em si.

### `PUT /api/llm` (ou `POST`)
**Body:** `{ "llm_provider": "deepseek", "deepseek_api_key": "sk-…", "deepseek_model": "deepseek-flash" }` — campo
vazio não apaga o que já está salvo. `400` para provedor desconhecido.
