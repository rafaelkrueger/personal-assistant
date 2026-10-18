# Lume (learning) — API

Base: `http://127.0.0.1:8016` (neste PC). Sem autenticação: só deve ficar acessível na rede de casa. Tudo em JSON;
erros voltam como `{ "detail": "mensagem legível" }` com `400` (dado faltando ou inválido), `404` (não encontrado)
ou `502` (o modelo de IA falhou).

Minutos aceitam número ou texto (`40`, `"90 min"`, `"1h30"`, `"2 horas"`); datas são `AAAA-MM-DD` (sem data vale
hoje). Uma matéria pode ser indicada pelo `subject_id` ou, onde dito, pelo nome (`subject`) — nome que não existe
cria a matéria.

- [1. Saúde do serviço](#1-saúde-do-serviço)
- [2. Perfil, situação e progresso](#2-perfil-situação-e-progresso)
- [3. Matérias, plano e materiais](#3-matérias-plano-e-materiais)
- [4. Sessões de estudo](#4-sessões-de-estudo)
- [5. Flashcards](#5-flashcards)
- [6. Quizzes, provações e chefes](#6-quizzes-provações-e-chefes)
- [6b. O herói (XP e nível)](#6b-o-herói-xp-e-nível)
- [7. Conversa](#7-conversa)
- [8. LLM](#8-llm-mesmo-formato-dos-outros-agentes)

## 1. Saúde do serviço

### `GET /api/health`
`{ "ok": true, "level": 4, "xp": 712, "streak": 6, "today_minutes": 65, "subjects": 2, "cards_due": 4, "llm": "OpenAI · gpt-4o-mini" }` —
`subjects` conta as matérias ativas.

## 2. Perfil, situação e progresso

### `GET /api/profile` · `PUT /api/profile`
`{ "name", "daily_minutes", "weekly_minutes", "study_days": [0..6] (0 = segunda), "style", "notes" }` — o `PUT`
muda só os campos enviados; campo desconhecido é ignorado. Padrão: 30 min/dia, 180 min/semana, seg a sex.

### `GET /api/status`
Tudo de uma vez, sem LLM:
```json
{ "profile": { "…": "…" },
  "hero": { "level": 6, "rank": "Escriba", "xp": 1762, "xp_level": 1500, "xp_next": 2100, "xp_today": 85 },
  "stats": { "today": 65, "daily_goal": 40, "week": 250, "weekly_goal": 240, "week_expected": 240, "last_week": 215,
             "month": 980, "total": 1465, "sessions": 41, "avg_focus": 3.6, "week_start": "2026-10-12",
             "streak": { "current": 6, "best": 6, "studied_today": true, "days_total": 37 },
             "weeks": [ { "start": "2026-07-27", "minutes": 120 } ], "by_subject": [ { "…": "…" } ] },
  "subjects": [ { "id", "name", "status", "progress": 0.25, "modules_done": 1, "modules_total": 4, "minutes",
                  "week_minutes", "days_left": 16, "mastery": { "…": "…" }, "cards": { "total": 2, "due": 2 },
                  "next_module": "Derivadas" } ],
  "cards_due": 4,
  "alerts": [ { "level": "soon", "kind": "deadline", "title": "Cálculo I",
                "text": "Cálculo I: faltam 16 dia(s) para o prazo e o plano está em 25%." } ],
  "text": "Sequência de 6 dia(s) estudando (hoje já conta). Hoje: 1 h 05 min de 40 min; …" }
```
- `streak.current`: dias seguidos com estudo; hoje sem estudo ainda não quebra a sequência.
- `week_expected`: a meta da semana proporcional aos dias de estudo do perfil que já chegaram.
- `alerts[].level`: `overdue` | `soon` | `info`. `kind`: `deadline` (prazo vencido, ou em até 21 dias com o plano
  abaixo de 75%), `idle` (matéria ativa sem estudo há mais de 7 dias), `mastery` (domínio abaixo de 60%), `cards`
  (cards para hoje), `goal` (semana abaixo de 80% do esperado), `start` (nenhuma matéria), `boss` (todos os módulos
  da região vencidos: o chefe está pronto para a luta).
- `text` é o que um orquestrador devolveria em `action=status`.

### `GET /api/stats?days=84`
O mesmo `stats` acima com `series` (`[{ "date", "minutes" }]`, um por dia, para o calendário), mais `cards` (ver
`GET /api/cards`) e `quizzes` (o histórico de notas — ver `GET /api/quizzes`).

## 3. Matérias, o mapa e os materiais

O plano de cada matéria é um MAPA: `units` são as regiões, em ordem; cada região tem módulos (`modules[].unit_id`)
e um chefe (`boss`). Uma região abre quando o chefe da anterior é derrotado; os módulos de uma região fechada vêm com
`locked: true`. **Um módulo só fica `done` vencendo a provação dele** (ou derrotando o chefe da região).

### `GET /api/subjects`
`{ "subjects": [...], "levels": ["iniciante", "básico", "intermediário", "avançado"], "resource_kinds": [...] }` —
as ativas primeiro (a estudada mais recentemente antes). Cada matéria:
```json
{ "id", "name", "realm", "goal", "level", "target_date", "weekly_minutes", "status": "active | paused | done", "notes",
  "units": [ { "id", "title", "description", "topics": [], "index", "boss": { "name", "epithet", "lore",
               "kind": "dragao | lich | golem | espectro | aranha | minotauro | hidra | cavaleiro" },
               "modules_done", "modules_total", "minutes_total", "unlocked", "conquered", "boss_ready",
               "boss_defeated_at", "attempts", "boss_best" } ],
  "modules": [ { "id", "unit_id", "title", "description", "objectives": [], "lessons": [], "practice", "est_minutes",
                 "status": "todo | doing | done", "locked", "started_at", "done_at", "done_via": "trial | boss",
                 "trials", "trial_best" } ],
  "units_total", "units_conquered", "current_unit": { "…região atual…": "…" },
  "next_boss": { "unit_id", "title", "boss" } ou null,
  "resources": [ { "id", "title", "url", "kind", "notes", "done" } ],
  "plan_summary", "planned_at",
  "progress": 0.25, "modules_done", "modules_total", "next_module": { "…módulo…": "…" }, "left_minutes",
  "minutes", "week_minutes", "sessions", "last_date", "idle_days", "days_left",
  "mastery": { "score": 0.72, "quizzes": 3, "last": 0.8, "last_date", "trend": 0.12,
               "modules": { "<module_id>": { "score", "date" } } } ,
  "cards": { "total", "due", "mature" } }
```

### `POST /api/subjects`
Cria (ou atualiza a de mesmo nome): `{ "name" (obrigatório), "goal", "level", "target_date", "weekly_minutes",
"notes", "plan": true, "plan_notes" }` — com `plan: true` já começa a montar o plano.

### `GET /api/subjects/{id}` · `PATCH` · `DELETE`
O `GET` traz a matéria com `recent_sessions`, `quizzes` (histórico de notas) e `planner` (andamento do plano). O
`PATCH` aceita os campos do `POST` e `status`. Apagar leva os módulos e materiais; as sessões ficam no histórico.

### `POST /api/subjects/{id}/plan` · `GET /api/subjects/{id}/plan`
`{ "notes": "mais prática e menos teoria" }` (opcional) → começa a traçar o mapa em segundo plano, em etapas: o mapa
(regiões, tópicos e chefes — de 2 a 18 regiões pelo tamanho do assunto), cada região em detalhe (de 5 a 12 módulos
com objetivos, lições e prática; várias ao mesmo tempo, `LEARNING_PLAN_WORKERS`, padrão 4) e os materiais. O `GET`
dá o andamento: `{ "status": "idle | running | done | error", "step", "units_done", "units_total", "summary",
"units", "modules", "source": "ia | web", "error" }`. Os módulos feitos ou em andamento ficam (pelo título); os
feitos que somem do mapa novo vão para a região "Saber já conquistado"; uma região com o mesmo nome continua
conquistada. Materiais novos se somam aos existentes.

### `POST /api/subjects/{id}/modules` · `PATCH .../modules/{mid}` · `DELETE .../modules/{mid}`
`{ "title", "description", "objectives": [], "lessons": [], "practice", "est_minutes", "status": "todo | doing",
"unit_id", "position" }` — `position` (0 = primeiro) muda a ordem; sem `unit_id`, o módulo novo vai para a região
atual. `status: "done"` → `400` (só a provação conclui).

### `GET /api/subjects/{id}/modules/{mid}/lesson` · `POST` (o mesmo caminho)
O pergaminho do módulo: `{ "module_id", "subject_id", "title", "text" (Markdown), "words", "created_at" }`. O `GET`
dá `404` se ainda não foi escrito; o `POST` (`{ "force": true }` reescreve) escreve pela IA na primeira vez e põe o
módulo em "estudando". A provação é montada em cima deste texto.

### `POST /api/subjects/{id}/modules/{mid}/trial`
A provação do módulo (sem gabarito), difícil e corrigida com rigor: 5 de múltipla escolha, 3 escritas (peso 1,5) e 2
tarefas práticas (peso 2), limiar 80%. Depois de uma derrota, a revanche só abre 1 h depois (`400` até lá). Se já há uma
começada, devolve ela. `400` se a região está fechada.

### `POST /api/subjects/{id}/units/{uid}/boss`
A luta com o chefe da região, no nível da prova mais exigente: 6 de múltipla escolha, 4 escritas e 4 práticas sobre
todos os módulos dela, limiar 85% — ou 95% (`early: true`) se ainda faltam módulos; revanche só 6 h depois de perder. Vencer conquista a região (os módulos que faltavam ficam
`done_via: "boss"`) e abre a próxima. `400` se a região está fechada.

### `POST /api/subjects/{id}/resources` · `PATCH .../resources/{rid}` · `DELETE .../resources/{rid}`
`{ "title", "url" (só http/https), "kind", "notes", "done" }`.

## 4. Sessões de estudo

### `GET /api/sessions?subject_id=&days=`
`{ "sessions": [ { "id", "date", "minutes", "subject_id", "subject", "module_id", "module", "topic", "notes",
"focus": 1..5, "kind", "source" } ] }` — da mais recente à mais antiga.

### `POST /api/sessions` · `DELETE /api/sessions/{id}`
`{ "minutes" (obrigatório, até 16 h), "subject_id" ou "subject", "date", "module" (id ou título), "module_done",
"topic", "notes", "focus", "kind": "estudo | revisão | exercícios | aula | leitura | pomodoro" }` — com `module`,
o módulo passa para "estudando" (ou "feito", com `module_done: true`).

## 5. Flashcards

### `GET /api/cards?subject_id=&q=`
`{ "cards": [...], "stats": { "total", "due", "new", "learning", "mature", "reviewed_today", "retention",
"reviews_30d", "reviews_by_day" } }`. Cada card: `{ "id", "front", "back", "tags", "subject_id", "subject",
"ease", "interval", "reps", "lapses", "due", "last_review", "history": [{ "date", "grade" }], "suspended",
"state": "new | learning | mature", "is_due", "source" }`. `retention` = revisões que não foram "errei", nos
últimos 30 dias.

### `GET /api/cards/due?subject_id=&limit=50`
Os cards para revisar agora: atrasados e em estudo primeiro, depois até 20 novos. Suspensos ficam de fora.

### `POST /api/cards` · `PATCH /api/cards/{id}` · `DELETE /api/cards/{id}`
`{ "front", "back", "subject_id" ou "subject", "tags" }` (um card com a mesma frente na mesma matéria não
duplica). O `PATCH` aceita também `suspended` e `reset: true` (volta a ser novo).

### `POST /api/cards/{id}/review`
`{ "grade": "again | hard | good | easy" }` → o card com o novo `interval` (dias) e `due`. SM-2 simplificado:
again = volta hoje (facilidade −0,2); hard = ×1,2 (−0,15); good = 1, 3, depois × facilidade; easy = 4 na primeira,
depois × facilidade × 1,3 (+0,15). Facilidade mínima 1,3; intervalo máximo 365 dias.

### `POST /api/cards/generate`
`{ "subject_id", "topic", "text" (material colado), "count": 8 }` → `{ "cards": [...] }`, já na revisão. Usa IA.

## 6. Quizzes, provações e chefes

Toda atividade tem `kind`: `practice` (treino livre da Arena, não conclui nada), `trial` (provação de um módulo) ou
`boss` (chefe de uma região), `threshold` (0 no treino), `intro` (a fala do adversário), `foe` e `battle`:
`{ "state": "fighting | victory | defeat | done", "answered", "total", "threshold", "enemy_hp", "enemy_max",
"hero_hp", "hero_max" }` — cada acerto tira vida do adversário (até `limiar × questões × 100`), cada erro tira a sua
(o resto); quem zerar primeiro perde, então vencer é acertar pelo menos o limiar. Terminada: `status: "done"`,
`score` (sobre as respondidas) e `outcome`.

### `GET /api/quizzes?subject_id=`
`{ "quizzes": [...], "history": [ { "id", "date", "score", "title", "subject_id", "module_id", "questions" } ],
"mastery": { "<subject_id>": { …ver matéria… } } }`. Quiz ainda não respondido vem **sem** `answer` e
`explanation` nas questões.

### `POST /api/quizzes`
`{ "subject_id" ou "topic" (um dos dois), "module_id", "count": 6 (2–20), "difficulty": "fácil | média | difícil",
"open_questions": 0 }` → o quiz (sem gabarito). Usa IA. Cada questão: `{ "type": "choice", "question", "options" }`
ou `{ "type": "open" | "practice", "question" }`.

### `GET /api/quizzes/{id}` · `DELETE /api/quizzes/{id}`

### `POST /api/quizzes/{id}/answer`
`{ "index": 0, "answer": 2 }` (o índice da alternativa, ou o texto) — responde UMA questão, na ordem → `{ "result":
{ "index", "score", "given", "feedback", "answer", "explanation", "type" }, "battle", "quiz" }`. Quando alguém zera
a vida (ou acabam as questões), a atividade termina e o resultado vale na hora. Fora de ordem ou já terminada → `400`.

### `POST /api/quizzes/{id}/submit`
`{ "answers": [2, 0, "texto da resposta aberta"] }` → o quiz com o gabarito, `results` (`{ "index", "question",
"given", "score": 0..1, "feedback" }`) e `score` (média). A aberta é corrigida pela IA; se ela falhar, fica com 0 e
um aviso para comparar com a resposta esperada. Responder de novo → `400`.

### `POST /api/quizzes/{id}/cards`
As questões com nota abaixo de 1 viram flashcards (frente = pergunta, verso = resposta certa + explicação).

## 6b. O herói (XP e nível)

### `GET /api/hero`
`{ "name", "hero_class": "mago | guerreiro | ladino | clerigo", "level", "rank", "next_rank", "xp", "xp_level",
"xp_next", "xp_today", "attributes": [{ "id", "label", "value": 0..100, "hint" }], "skills": [{ "subject_id",
"name", "level": 1..100, "xp", "progress" }], "achievements": [{ "id", "title", "description", "earned",
"progress", "have", "goal" }], "achievements_earned", "quests": [{ "id", "title", "detail", "progress", "done",
"xp", "go" }], "chronicle": [{ "date", "xp", "kind", "text" }], "facts" }` — tudo calculado dos registros: 1 XP por
10 minutos, 1 por card lembrado, 4 × os acertos ponderados de cada provação ou chefe VENCIDO (1 × no treino), +100
na primeira vitória de cada provação, +500 no primeiro chefe de cada região, +10 por dia com a meta cumprida;
derrota: −40 (provação) e −150 (chefe), sem nunca baixar o nível alcançado. O nível N começa em 60·(N−1)^1,9 XP
(nível 10 ≈ 3 900 XP; 20 ≈ 16 000). `xp_lost` é o total perdido em derrotas.

## 7. Conversa

### `POST /api/chat`
`{ "message", "source": "ui" }` → `{ "reply", "noted", "profile", "subjects", "sessions", "modules", "cards",
"generated", "resources", "plans", "removed" }` — `noted` é, em linhas, exatamente o que foi gravado nesta mensagem
(vazio quando nada). Duas chamadas ao modelo: extração e resposta.

### `POST /api/quick`
`{ "text" }` → só anota, sem conversa: `{ "text": "Sessão em 16/10/2026: 25 min de Física", … }`. `400` se não
houver nada a anotar.

### `GET /api/chat` · `DELETE /api/chat`
A conversa guardada (até 200 mensagens) / apagar.

## 8. LLM (mesmo formato dos outros agentes)

### `GET /api/llm` · `PUT /api/llm` (ou `POST`)
`{ "llm_provider": "openai | deepseek", "openai_model", "openai_api_key", "deepseek_model", "deepseek_api_key",
"deepseek_base_url" }` — campo vazio não apaga o que já está salvo; o `GET` nunca devolve a chave (só
`*_api_key_set` e um preview).
