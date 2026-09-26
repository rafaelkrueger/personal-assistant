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
  trânsito (essas cinco pesquisam na internet via web-agent).
- **Pesquisar na internet** (notícias, cotações, clima, esportes, trânsito,
  busca geral) **delegando ao web-agent**, mas só quando ele está ligado e
  respondendo. Se ele estiver desligado ou falhar, ela responde só com o
  próprio LLM.
- **Ouvir pelo microfone** (quando houver um plugado): detecta o nome
  "Cassandra" no próprio aparelho, sem mandar nada para a internet, e só então
  transcreve o comando.

## Não pode / não faz

- **Não navega na web por conta própria.** Toda pesquisa na internet é feita
  pelo **web-agent**; sem ele, ela não tem informação atual (notícias,
  preços, clima de hoje).
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
  funciona via web-agent (ou como resposta genérica do LLM).
- **Não ajusta o volume da caixa de som** hoje: a skill de volume usa `pactl`
  ou `amixer`, e no Raspberry Pi atual (sem `pactl`) o `amixer` mexe na saída
  de hardware do Pi, não na soundbar Bluetooth. O volume se ajusta no controle
  da própria soundbar.
- **Não controla outros aparelhos** da casa (luzes, TV, tomadas): não há
  integração com automação residencial.
- **O microfone é só local**: ela ouve apenas o que é falado perto do Raspberry
  Pi; hoje não há microfone plugado (a entrada por texto funciona sempre).

## Parâmetros de despacho

Ainda não há adapter da Cassandra no orchestrator. Para integrar, quem
despacha manda o pedido em linguagem natural em `POST /api/chat`, com o texto
**começando pelo nome dela** — `{"message": "cassandra, <pedido>"}` — e lê a
resposta em `reply` (ver [`API.md`](./API.md), seções 2 e 12). Nenhum outro
parâmetro é necessário. Para operações estruturadas (adicionar item de compra,
criar alarme, listar tarefas…) há endpoints próprios que não passam pelo LLM e
**não falam em voz alta** — preferíveis quando o pedido já chega estruturado.
