# Health — API HTTP

Base: `http://192.168.100.49:8012` — roda no Raspberry Pi da casa (serviço `pulse-health`); em desenvolvimento, `http://127.0.0.1:8012` (porta em `HEALTH_PORT`). JSON em UTF-8. Erros: `{"detail": "mensagem legível"}`
(`400` pedido inválido, `404` não encontrado, `502` o modelo de IA falhou). Sem autenticação: roda local,
para uma pessoa só. A interface web fica em `GET /`.

Dados em `data/` (fora do git — são dados de saúde): `profile.json`, `exams.json`, `exams/<id>.*` (arquivos
originais), `chat.json`, `overview.json`, `checkup.json`, `checkup_suggestions.json`, `analysis.json`, `weight.json`, `meal_plan.json`, `llm_settings.json`.

---

## 1. Saúde do serviço

### `GET /api/health`
`{ "ok": true, "exams": 3, "llm": "OpenAI · gpt-4o-mini" }` — o maestro usa para o status online.

## 2. Perfil e metas

### `GET /api/profile`
```json
{ "name": "", "birth_date": "1990-05-10", "age": 36, "sex": "masculino", "height_cm": 178, "weight_kg": 82.5,
  "conditions": ["pré-diabetes"], "medications": ["metformina 500 mg no jantar"], "allergies": [],
  "family_history": ["diabetes tipo 2 (pai)"], "lifestyle": "…", "notes": "",
  "goals": [ { "text": "baixar a glicose de jejum para menos de 100", "created_at": "…" } ] }
```

### `PUT /api/profile`
Qualquer subconjunto dos campos acima (os que não vierem ficam como estão). Devolve o perfil completo.

## 3. Exames

### `POST /api/exams` (multipart/form-data)
Campos: `file` (PDF, JPG, PNG, WEBP ou TXT, até 20 MB) **ou** `text` (o exame colado), e opcionais `date`
(`AAAA-MM-DD`, se o laudo não trouxer) e `notes`. Síncrono (alguns segundos): lê o texto (PDF direto; foto pela
visão da OpenAI), extrai com o LLM e salva. Laudo com mais de ~1.500 caracteres tem os marcadores lidos em
pedaços, em paralelo (pedindo tudo de uma vez o modelo devolve só os primeiros), e uma chamada a mais para
título, data, pasta e resumo. PDF escaneado (sem texto) → `400` pedindo fotos das páginas.

Resposta (e formato de cada exame nas outras rotas):
```json
{ "id": "a1b2c3d4e5f6", "date": "2026-09-10", "title": "Perfil lipídico", "lab": "…", "notes": "",
  "summary": "Resumo em português simples…", "filename": "lipidograma.pdf", "created_at": "…",
  "altered": ["Colesterol LDL"],
  "markers": [ { "name": "Colesterol LDL", "value": 142, "value_text": "142", "unit": "mg/dL",
                 "reference": "< 130 mg/dL", "ref_low": null, "ref_high": 130, "flag": "alto" } ] }
```
`flag`: `normal`, `alto`, `baixo`, `critico` ou `indeterminado`. Os nomes dos marcadores seguem os que já
existem no histórico (para a evolução juntar o mesmo exame de datas diferentes).

Cada exame tem também `category`, a pasta dele no diretório: `sangue`, `urina` (urina e fezes), `imagem`,
`coracao` ou `outros`. O LLM escolhe ao ler; se não disser, sai do título e de haver marcadores.

### `GET /api/exams` → `{ "exams": [...], "categories": { "sangue": "Sangue", … } }` (o diretório, do mais recente ao mais antigo)
### `GET /api/exams/{id}` (inclui `text`, o texto lido) · `GET /api/exams/{id}/file`
### `POST /api/exams/{id}/reread` — lê de novo um exame guardado (marcadores, resumo, título, pasta) a partir do texto extraído na época, sem reenviar o arquivo. Devolve o exame. `400` se não há texto guardado.
### `PATCH /api/exams/{id}` — corrige `date`, `title`, `lab`, `notes`, `markers` ou `category` (`400` para pasta que não existe).
### `DELETE /api/exams/{id}`

### `GET /api/markers`
Evolução de cada marcador, do mais antigo ao mais recente:
`{ "markers": { "Colesterol LDL": [ { "date", "value", "unit", "flag", "ref", "exam_id" } ] } }`

## 4. Checkup

### `GET /api/checkup`
O que entra num checkup completo de rotina para o perfil (a lista é filtrada pelo sexo e pela idade), quando
cada item foi feito pela última vez e quando repetir. Do mais urgente ao mais tranquilo:
```json
{ "items": [ { "id": "lipidios", "kind": "lab", "name": "Colesterol total e frações e triglicerídeos", "why": "…",
               "from_exams": true, "interval_months": 12, "default_interval_months": 12, "done_date": null,
               "last_date": "2026-09-10", "last_source": "exam", "recheck": false,
               "due_date": "2027-09-10", "days_left": 332, "status": "ok" } ],
  "counts": { "overdue": 0, "soon": 1, "unknown": 9, "ok": 3, "off": 0 }, "pending": 9,
  "next": { "…o item em dia ou em breve que vence primeiro…" }, "needs_profile": false, "recheck_months": 3,
  "suggestions": { "items": [ { "id": "a1b2c3d4", "name": "Repetir a vitamina D", "kind": "lab",
                                "why": "Vitamina D 18 ng/mL em 10/03/2026, abaixo da referência.",
                                "when": "em 3 meses" } ],
                   "generated_at": "…", "stale": false, "has_exams": true },
  "progress": { "done": 4, "total": 15 } }
```
`progress`: quantos itens da rotina estão em dia (`ok` + `soon`) sobre o total que vale para o perfil (sem os `off`).
Duas coisas diferentes na mesma resposta: `items` é a **rotina** (igual para todo perfil parecido, com datas);
`suggestions` é o que os **resultados da pessoa** pedem para fazer agora (ver abaixo).
- `kind`: `lab` (sangue e urina), `exam` (outros exames) ou `visit` (consulta).
- `status`: `overdue` (venceu), `soon` (vence em até 30 dias), `ok`, `unknown` (nunca registrado) ou `off`
  (o usuário desligou). `pending` = vencidos + nunca registrados.
- `last_date` sai sozinha dos exames enviados (`last_source: "exam"`, pelo nome dos marcadores e pelo título do
  exame) ou de `done_date`, a data informada à mão (`"manual"`) — vale a mais recente.
- `recheck: true`: o último resultado veio alterado, então `due_date` é a última vez + `recheck_months` em vez
  do intervalo cheio.
- `needs_profile: true`: faltam sexo e/ou nascimento no perfil; os itens que dependem disso ficaram de fora.

- `suggestions.stale: true`: há exames e as sugestões ainda não foram geradas para o histórico atual (exame
  novo, apagado ou corrigido) — `items` vem vazio até um `POST /api/checkup/suggestions`.

### `POST /api/checkup/suggestions`
Lê os resultados e o perfil com o LLM (alguns segundos) e guarda até 6 indicações do que vale fazer agora por
causa deles — exame para repetir ou complementar, consulta com especialista —, cada uma citando o resultado que
a motiva. Rotina nunca feita não entra. Devolve o mesmo que o `GET`. `400` se não há exame nenhum, `502` se o
modelo falhou.

### `DELETE /api/checkup/suggestions/{id}`
Tira uma indicação da lista (já fez, ou decidiu não fazer). Devolve o mesmo que o `GET`.

### `GET /api/checkup/request`
O pedido de checkup completo, para levar ao médico: o que os resultados indicaram + a rotina atrasada, vencendo
ou nunca feita, por tipo e com o motivo. Sem LLM.
`{ "date", "person": "Nome, 40 anos, feminino", "count": 12, "groups": [ { "kind": "lab", "label": "Exames de
laboratório", "items": [ { "name", "reason", "source": "resultado | rotina" } ] } ], "notes": ["…"], "text": "a
mesma lista em texto puro, para copiar ou enviar" }`

### `PATCH /api/checkup/{id}`
**Body** (qualquer subconjunto): `{ "done_date": "2026-10-01", "interval_months": 6, "off": false }`.
`done_date` vazio apaga a data manual; `interval_months` vazio volta ao padrão (1 a 120). Devolve o mesmo que o
`GET`. `400` para data no futuro ou intervalo inválido, `404` se o item não existe.

## 5. Plano de peso

### `GET /api/weight`
Conta feita no servidor, sem LLM, a partir de altura, peso, nascimento e sexo do perfil (faltando algum:
`{ "ready": false, "missing": ["altura", …] }`):
```json
{ "ready": true, "weight_kg": 55.0, "height_cm": 180, "bmi": 17.0, "bmi_label": "abaixo do peso",
  "healthy_range": [59.9, 80.7], "target_kg": 71.3, "custom_target": false, "diff_kg": 16.3,
  "direction": "ganhar", "rest_kcal": 1550, "spend_kcal": 2131, "delta_kcal": 275, "calories": 2410,
  "weekly_kg": 0.25, "weeks": 66, "goal_date": "2028-01-18", "protein_g": 99, "carbs_g": 353, "fat_g": 67,
  "water_l": 1.9, "activity": "leve", "pace": 0.25, "log": [ { "date": "2026-10-13", "kg": 55.0 } ],
  "start_kg": 55.0, "moved_kg": 0.0, "floored": false, "see_doctor": false,
  "activities": { "sedentario": "…", "leve": "…", "moderado": "…", "intenso": "…" }, "paces": [0.25, 0.5] }
```
Faixa saudável = IMC 18,5 a 24,9; sem meta escolhida, a meta é o peso do IMC 22 (ou o peso atual, se já está na
faixa). Gasto em repouso por Mifflin-St Jeor, vezes o fator da atividade; `calories` = gasto ± o que o ritmo pede
(1 kg ≈ 7.700 kcal), com piso de 1.500/1.200 kcal para quem vai perder (`floored`). `direction`: `ganhar`,
`perder` ou `manter`.

`meal_plan` (na mesma resposta; `null` se ainda não foi gerado) são as refeições sugeridas para um dia:
`{ "date": "2026-10-13", "meals": [ { "name": "Café da manhã", "time": "07:00", "kcal": 557, "protein_g": 14,
"items": [ { "food": "pão francês", "qty": 150, "unit": "g", "measure": "3 pães", "kcal": 405, "protein_g": 14 } ] } ],
"total_kcal", "total_protein_g", "target_kcal", "generated_at", "for_today", "stale", "off_target" }` — toda
quantidade em `g` ou `ml`; as somas são feitas no servidor. `for_today`: foram feitas para hoje (cada dia tem
sugestões novas; as de ontem continuam aparecendo até as de hoje chegarem). `stale`: não são de hoje ou a meta
mudou mais de 100 kcal. `food_notes`: preferências e restrições de comida.

### `POST /api/weight/meal-plan` — `{ "notes": "não como peixe" }` (opcional; fica guardado)
O LLM sugere as refeições de hoje para a meta de calorias e os macros, com o perfil e os exames no contexto
(alguns segundos), sem repetir o que sugeriu da última vez. As refeições já marcadas hoje saem; os extras ficam. Se a soma fugir mais de 12% da meta, o servidor pede de novo dizendo a diferença (até 3 tentativas) e guarda a
tentativa mais próxima; se nem ela chegou perto, `meal_plan.off_target` vem `true`. Devolve o
mesmo que o `GET`. `400` se falta dado no perfil, `502` se o modelo falhou.

O dia a dia vem na mesma resposta:
- `today`: `{ "date", "meals": [0, 2], "extras": [ { "id", "food", "qty", "unit", "kcal", "estimated" } ], "kcal",
  "ratio", "hit", "over" }` — as refeições sugeridas marcadas hoje e o que foi comido por fora. `kcal` soma os
  dois; o dia conta (`hit`) a partir de `hit_ratio` (85%) da meta de calorias e, para quem quer perder peso, até
  110% dela (`over` = passou disso).
- `streak`: `{ "current", "best", "total", "month" }` — dias seguidos cumpridos (até hoje, ou até ontem se hoje
  ainda está em aberto), o recorde, o total e os deste mês.
- `calendar`: 35 dias, de domingo a sábado, terminando na semana de hoje: `{ "date", "kcal", "ratio", "hit", "future" }`.
- `journey`: `{ "start_kg", "target_kg", "pct" }` do peso da primeira pesagem até a meta (`null` para quem sempre
  esteve na faixa saudável).
- `badges`: `[ { "id", "label", "hint", "earned" } ]` — as conquistas (dias seguidos, pesagens, quilos, meta).

### `POST /api/weight/day` — `{ "meals": [0, 2] }` (índices das refeições sugeridas já feitas hoje) ou, sem sugestões, `{ "done": true }`
Substitui as refeições marcadas hoje.

### `POST /api/weight/extra` — `{ "food": "pão de queijo", "qty": 60, "unit": "g" | "ml", "kcal": 180 }`
Algo comido fora das sugestões; entra na conta do dia. Sem `kcal`, o LLM estima pelo alimento e pela quantidade
(`estimated: true`). `400` se falta o alimento, a quantidade ou a unidade.
### `DELETE /api/weight/extra/{id}`

### `PUT /api/weight` — `{ "activity", "pace": 0.25 | 0.5, "target_kg" }` (meta vazia = automática; `400` se a meta sai da faixa saudável)
### `POST /api/weight/log` — `{ "kg": 62.4, "date": "AAAA-MM-DD" }` (sem data = hoje; uma por dia). A pesagem mais recente vira o peso do perfil.
### `DELETE /api/weight/log/{AAAA-MM-DD}`
Os três devolvem o mesmo que o `GET`.

## 6. Análise do histórico

### `GET /api/analysis`
```json
{ "summary": "3 a 5 frases…", "generated_at": "…", "stale": false, "has_exams": true,
  "systems": [ { "name": "Colesterol e coração", "status": "atencao", "trend": "melhorou",
                 "finding": "LDL 142 mg/dL em 03/2026…", "action": "…" } ],
  "priorities": ["…"], "doctor_questions": ["…"] }
```
Sempre os mesmos 8 sistemas, na mesma ordem (Sangue, Glicose e metabolismo, Colesterol e coração, Fígado, Rins,
Tireoide e hormônios, Vitaminas e minerais, Imagem e outros laudos). `status`: `ok`, `atencao`, `alerta` ou
`sem_dados`. `trend`: `melhorou`, `piorou`, `estavel` ou `sem_comparacao`. `stale: true` = há exames e a análise
não foi feita para o histórico atual (vem vazia).

### `POST /api/analysis`
Lê todo o histórico e o perfil com o LLM (alguns segundos), guarda e devolve o mesmo que o `GET`. `400` sem
exame nenhum, `502` se o modelo falhou.

## 7. Conversa (é o que o maestro usa)

### `POST /api/chat`
**Body:** `{ "message": "meu colesterol melhorou?", "source": "maestro" }` (`source` opcional, só para o
histórico). Responde com todo o contexto (perfil, metas, exames, evolução, checkup, plano de peso, a última análise e as últimas 20 mensagens):
`{ "reply": "…" }`.

### `GET /api/chat` → `{ "messages": [ { "role", "content", "source", "ts" } ] }` · `DELETE /api/chat`

### `POST /api/overview` → `{ "text": "…", "generated_at": "…" }`
Panorama: como está, o que melhorou/piorou, prioridades para as metas e o que falar com o médico. Fica salvo;
`GET /api/overview` devolve o último (é descartado quando um exame é enviado, apagado ou corrigido).

## 8. LLM (mesmo formato dos outros agentes)

### `GET /api/llm`
`{ "llm_provider": "openai", "providers": ["openai","deepseek"], "openai_model", "openai_api_key_set",
"openai_api_key_preview", "deepseek_model", "deepseek_base_url", "deepseek_api_key_set",
"deepseek_api_key_preview", "vision_available" }` — nunca a chave em si.

### `PUT /api/llm` (ou `POST`)
Campos parciais; chave vazia/omitida nunca apaga a salva. Vale na hora, sem reiniciar.
