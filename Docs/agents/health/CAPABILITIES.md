# O que o Health pode e não pode fazer

> Saúde pessoal com contexto: lê exames (PDF, foto ou texto), guarda o histórico, acompanha a evolução de cada marcador e orienta com base no perfil, nas condições e nas metas do usuário.

O Health é o agente de saúde do usuário. Roda no Raspberry Pi da casa (porta 8012), com os dados só na pasta `data/` dele:
perfil (idade, sexo, altura, peso, condições, medicamentos, alergias, histórico familiar, hábitos e **metas**)
e todos os exames já enviados, com os marcadores extraídos. Cada resposta leva em conta todo esse contexto.

## Pode
- **Responder perguntas de saúde do usuário com base nos exames e no perfil dele**: "meu colesterol melhorou?",
  "o que meus últimos exames dizem?", "estou com a vitamina D baixa?", "como está minha glicose?",
  "o que fazer para baixar o LDL?", "que exames devo repetir?".
- **Comparar exames ao longo do tempo** (cada marcador: valores, datas, referência, alterado ou não).
- **Orientar para as metas do usuário** (ex.: perder peso, baixar colesterol, melhorar o sono): alimentação,
  atividade física, hábitos, acompanhamento — personalizado para as condições e remédios dele.
- **Gerar um panorama da saúde**: como está, o que melhorou/piorou, prioridades e o que conversar com o médico.
- **Ler exames novos** (PDF, foto ou texto) — pela UI ou pela API (`POST /api/exams`).

## Não pode / não faz
- **Não substitui médico**: não dá diagnóstico definitivo, não prescreve e **nunca manda começar, parar ou mudar
  dose de remédio**. Em sinais de urgência, manda procurar atendimento.
- Não marca consultas, não compra remédios e não pesquisa na internet (pesquisa é o **web-agent**).
- Não sabe de exames que não foram enviados a ele.
- Os dados ficam só no Raspberry Pi da casa, mas o conteúdo das perguntas e dos exames vai para o provedor de LLM escolhido
  (OpenAI ou DeepSeek). Fotos de exames são lidas pela OpenAI.

## Parâmetros de despacho
Nenhum é necessário: o pedido em si (`task_summary`) vira uma pergunta no chat do Health, que responde com todo
o contexto de saúde. Opcional:
- `{"action": "overview"}` — gera o panorama completo da saúde (como está, evolução, prioridades, o que falar com
  o médico) em vez de responder uma pergunta.
