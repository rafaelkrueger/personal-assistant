# Health — API HTTP

Base: `http://192.168.100.49:8012` — roda no Raspberry Pi da casa (serviço `pulse-health`); em desenvolvimento, `http://127.0.0.1:8012` (porta em `HEALTH_PORT`). JSON em UTF-8. Erros: `{"detail": "mensagem legível"}`
(`400` pedido inválido, `404` não encontrado, `502` o modelo de IA falhou). Sem autenticação: roda local,
para uma pessoa só. A interface web fica em `GET /`.

Dados em `data/` (fora do git — são dados de saúde): `profile.json`, `exams.json`, `exams/<id>.*` (arquivos
originais), `chat.json`, `overview.json`, `llm_settings.json`.

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
visão da OpenAI), extrai com o LLM e salva. PDF escaneado (sem texto) → `400` pedindo fotos das páginas.

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

### `GET /api/exams` · `GET /api/exams/{id}` (inclui `text`, o texto lido) · `GET /api/exams/{id}/file`
### `PATCH /api/exams/{id}` — corrige `date`, `title`, `lab`, `notes` ou `markers`.
### `DELETE /api/exams/{id}`

### `GET /api/markers`
Evolução de cada marcador, do mais antigo ao mais recente:
`{ "markers": { "Colesterol LDL": [ { "date", "value", "unit", "flag", "ref", "exam_id" } ] } }`

## 4. Conversa (é o que o maestro usa)

### `POST /api/chat`
**Body:** `{ "message": "meu colesterol melhorou?", "source": "maestro" }` (`source` opcional, só para o
histórico). Responde com todo o contexto (perfil, metas, exames, evolução e as últimas 20 mensagens):
`{ "reply": "…" }`.

### `GET /api/chat` → `{ "messages": [ { "role", "content", "source", "ts" } ] }` · `DELETE /api/chat`

### `POST /api/overview` → `{ "text": "…", "generated_at": "…" }`
Panorama: como está, o que melhorou/piorou, prioridades para as metas e o que falar com o médico. Fica salvo;
`GET /api/overview` devolve o último (é descartado quando um exame é enviado, apagado ou corrigido).

## 5. LLM (mesmo formato dos outros agentes)

### `GET /api/llm`
`{ "llm_provider": "openai", "providers": ["openai","deepseek"], "openai_model", "openai_api_key_set",
"openai_api_key_preview", "deepseek_model", "deepseek_base_url", "deepseek_api_key_set",
"deepseek_api_key_preview", "vision_available" }` — nunca a chave em si.

### `PUT /api/llm` (ou `POST`)
Campos parciais; chave vazia/omitida nunca apaga a salva. Vale na hora, sem reiniciar.
