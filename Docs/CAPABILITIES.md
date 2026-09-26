# O que a Cassandra pode e não pode fazer

> Assistente pessoal da casa (estilo Alexa) num Raspberry Pi: conversa por voz e texto, fala em voz alta pela caixa de som, e cuida de lista de compras, tarefas, alarmes, timers, rotinas e agenda.

A Cassandra roda num Raspberry Pi 3 ligado à caixa de som da casa (uma soundbar
LG, via Bluetooth). Ela atende por voz (microfone, quando houver um plugado —
só responde depois de ouvir o nome "Cassandra") e por texto (UI web e API
HTTP). Voz e texto compartilham a **mesma conversa e memória**. Detalhes
técnicos e exemplos de API estão em [`API.md`](./API.md) — este arquivo é só
"o que ela faz e não faz".

## Pode

- **Conversar e responder perguntas** de conhecimento geral com um LLM
  (OpenAI ou DeepSeek, trocável em tempo real pela UI ou por `/api/llm`).
- **Falar em voz alta na casa**: toda resposta dada por ela sai pela caixa de
  som (voz "nova" da OpenAI enquanto houver créditos; sem créditos, uma voz
  feminina grátis e local). É o jeito de **avisar alguém que está em casa**
  (ex.: "Cassandra, avise que o jantar está pronto").
- **Lista de compras**: adicionar, remover e listar itens (por voz ou pela API).
- **Lista de tarefas (to-do)**: adicionar, marcar como feita, remover, listar.
- **Alarmes**: pontuais ou recorrentes (todo dia ou em dias da semana
  escolhidos), que tocam na casa.
- **Timers** por voz/texto ("Cassandra, timer de 10 minutos").
- **Agenda** (Google Calendar, iCloud, etc. via CalDAV), quando configurada:
  listar, criar e apagar eventos.
- **Rotinas**: sequências de ações disparadas por um horário ou por um
  alarme — falar um texto fixo, ou ler notícias, cotações, clima, esportes e
  trânsito (essas cinco pesquisam na internet via maestro).
- **Pesquisar na internet** (notícias, cotações, clima, esportes, trânsito,
  busca geral) **pedindo ao maestro** (que despacha para o web-agent),
  mas só quando ele está ligado e respondendo. Se ele estiver desligado ou o
  pedido falhar, ela responde só com o próprio LLM.
- **Pedir coisas a outros agentes, sempre através do maestro** (nunca
  direto): ela é origem de pedidos em `POST /maestro/request`, pelo
  plug-in `maestro_link`.
- **Ouvir pelo microfone** (quando houver um plugado): detecta o nome
  "Cassandra" no próprio aparelho, sem mandar nada para a internet, e só então
  transcreve o comando.

## Não pode / não faz

- **Não navega na web por conta própria.** Toda pesquisa na internet é pedida
  ao **maestro** (que usa o web-agent); sem ele, ela não tem informação
  atual (notícias, preços, clima de hoje).
- **Não edita vídeo nem publica em redes sociais** (isso é o **editor**) e
  **não escreve nem roda código** (isso é o **ide**).
- **Não é uma fila de tarefas longas.** Cada pedido é respondido na hora, em
  segundos; não há execução em segundo plano nem consulta de progresso.
- **Tudo o que ela responde pelo chat é falado em voz alta na casa.** Não
  mande para a Cassandra nada que não deva ser ouvido por quem está no
  ambiente.
- **Uma conversa só**, compartilhada entre voz, UI web e API — não existem
  conversas separadas por usuário ou por cliente.
- **Sem autenticação**: é um sistema de uma casa só.
- **Não dá previsão do tempo sozinha**: clima, notas e calculadora existem como
  skills no código, mas **não estão ativos** no assistente principal; clima só
  funciona via maestro (ou como resposta genérica do LLM).
- **Não ajusta o volume da caixa de som** hoje: a skill de volume usa `pactl`
  ou `amixer`, e no Raspberry Pi atual (sem `pactl`) o `amixer` mexe na saída
  de hardware do Pi, não na soundbar Bluetooth. O volume se ajusta no controle
  da própria soundbar.
- **Não controla outros aparelhos** da casa (luzes, TV, tomadas): não há
  integração com automação residencial.
- **O microfone é só local**: ela ouve apenas o que é falado perto do Raspberry
  Pi; hoje não há microfone plugado (a entrada por texto funciona sempre).

## Parâmetros de despacho

O maestro fala com ela pelo adapter `personal-assistant`
(`maestro/app/adapters/personal_assistant_adapter.py`). Sem nenhum
parâmetro, o pedido (`task_summary`) vai em linguagem natural para o chat
dela — **e a resposta é falada em voz alta na casa**. Use assim para
conversar, avisar alguém em casa ou pedir algo que só ela resolve (timer,
rotina, agenda).

Para **avisar algo em voz alta na casa** (o texto exato, sem ela
reinterpretar), use `{"action": "say", "text": "O jantar está pronto!"}`.

Quando o pedido é uma destas operações, prefira mandar `parameters.action`
estruturado — é instantâneo, não usa o LLM dela e **não fala nada em voz
alta**:

- `{"action": "shopping_add", "items": ["leite", "pão"]}` — adiciona à lista
  de compras.
- `{"action": "todo_add", "title": "pagar a conta de luz"}` — cria uma tarefa.
- `{"action": "alarm_add", "time_hhmm": "07:30", "label": "Acordar"}` — cria
  um alarme. Por padrão toca **uma vez** (no próximo 07:30 — "amanhã às 7h30"
  é isso). Só mande `"recurring_daily": true` quando o pedido disser que
  repete todo dia; para dias específicos ("de segunda a sexta") mande só
  `"days_of_week": [0, 1, 2, 3, 4]` (0 = segunda … 6 = domingo) — isso já
  faz repetir nesses dias.
- `{"action": "status"}` — devolve a lista de compras, as tarefas pendentes e
  os alarmes ativos (para responder "o que tem na lista de compras?" sem
  acordar a casa).

Sem `action`, o texto enviado é `parameters.message` (se houver) ou o
`task_summary`. Detalhes em [`API.md`](./API.md), seção 12.
