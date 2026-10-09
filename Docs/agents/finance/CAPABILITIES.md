# O que a Cifra pode e não pode fazer

> Finanças pessoais com contexto: de uma mensagem em linguagem natural extrai a renda e os gastos fixos de todo mês e os gastos do momento, anota tudo, compara com o orçamento de cada categoria e orienta com base nos números reais do usuário.

A Cifra é o agente de finanças pessoais do usuário (nome técnico: `finance`). Roda no Raspberry Pi da casa (porta 8014), com os
dados só na pasta `data/` dela: perfil (renda mensal, dívidas, investimentos e reservas, **orçamento mensal por
categoria**), os **fixos de todo mês** (salário,
aluguel, internet, assinaturas, parcelas — entram sozinhos nos lançamentos de cada mês) e todos os lançamentos
(data, valor, receita ou despesa, categoria, descrição, conta). As contas (resumo do mês, evolução mês a mês) são calculadas por
ela, exatas; cada resposta leva em conta todo esse contexto.

## Pode
- **Organizar as finanças a partir de uma mensagem só**: o usuário conta do jeito dele ("ganho 6500 por mês, pago
  1800 de aluguel, 120 de internet e 90 de academia; hoje gastei 45 no mercado") e ela separa o que é **fixo de
  todo mês** (renda e gastos mensais) do que é **gasto ou receita do momento**, anota cada item e confirma.
  O que o usuário disser que é fixo ganha a tag "fixo" e já fica lançado no mês atual e nos 2 seguintes (a
  janela anda a cada mês). Também atualiza ("meu aluguel subiu para 1900") e remove ("cancelei a academia") um
  fixo — os lançamentos deste mês em diante acompanham.
- **Anotar gastos e receitas contados em linguagem natural**: "gastei 45 no mercado", "paguei 120 de luz ontem",
  "recebi 5000 de salário", "anota 30 de uber e 18 de almoço". Ela **classifica o tipo de cada gasto** sozinha
  (Mercado, Transporte, Alimentação fora, Saúde, Pets, Viagem, Assinaturas… — 21 tipos de despesa e 5 de receita)
  e confirma o que lançou.
- **Acompanhar o patrimônio**: investimentos, reservas e bens, com o valor de hoje, o rendimento e a evolução
  mês a mês. O usuário conta e ela guarda ou atualiza: "tenho 12 mil no Tesouro Selic", "meu CDB está em 5.300",
  "apliquei mais 500 nas ações", "vendi o carro". E responde: "quanto eu tenho investido?", "qual meu patrimônio?",
  "como está dividido?".
- **Cuidar das dívidas**: financiamentos (casa, carro), empréstimos, consignado, cartão, cheque especial e
  parcelamentos. O usuário conta e ela guarda ou atualiza: "financiei o carro em 48x de 890, já paguei 12", "devo
  3.200 no cartão a 14% ao mês", "paguei a parcela do carro", "amortizei 2 mil do financiamento", "quitei o
  empréstimo". Com os juros e a parcela ela calcula, exato: o saldo devedor, quanto ainda vai ser pago, quanto disso
  é juro, quando acaba, quanto da renda as parcelas levam e qual dívida atacar primeiro. E responde: "quanto eu
  devo?", "quando termino de pagar o carro?", "qual dívida pago primeiro?".
- **Responder perguntas sobre o dinheiro do usuário com base nos lançamentos dele**: "quanto gastei esse mês?",
  "quanto já foi de mercado?", "estourei algum orçamento?", "como estou em relação ao mês passado?", "onde dá para
  cortar?", "quanto sobrou do salário?".
- **Orientar sobre sobras e dívidas do usuário**: quanto dá para guardar por mês, qual dívida
  atacar primeiro, como montar a reserva de emergência, onde está a maior folga do orçamento.
- **Gerar um panorama das finanças**: como está, o que subiu ou caiu em relação aos meses anteriores, os ajustes de
  maior impacto e o que acompanhar no próximo mês.
- **Dar o resumo exato de um mês** (receitas, despesas, saldo, maiores categorias, orçamentos estourados) na hora,
  sem passar pelo modelo de IA.
- **Ler extratos e faturas** (CSV, OFX, PDF, foto ou texto colado) e lançar cada movimentação — pela UI ou pela API
  (`POST /api/statements`). Reimportar o mesmo extrato não duplica.

## Não pode / não faz
- **Não é consultoria de investimentos nem contabilidade**: explica princípios (reserva, diversificação, juros,
  pagar dívida cara antes de investir), mas não recomenda comprar ou vender um ativo específico, não promete
  rendimento e não faz declaração de imposto de renda.
- **Não movimenta dinheiro**: não paga contas, não faz PIX, não acessa banco nem corretora. Só enxerga o que foi
  lançado ou importado nela.
- Não pesquisa cotações, preços, taxas ou notícias na internet (pesquisa é o **web-agent**).
- Não cuida de lista de compras, lembretes ou alarmes (isso é a **Cassandra**, `personal-assistant`).
- **Efeito colateral**: um pedido que conta um gasto, uma receita ou algo que se repete todo mês **grava** um
  lançamento ou um fixo nos dados do usuário. Perguntas e hipóteses ("e se eu gastar 500?") não gravam nada.
- Os dados ficam só no Raspberry Pi da casa, mas o conteúdo das perguntas, dos lançamentos e dos extratos vai para o provedor de
  LLM escolhido (OpenAI ou DeepSeek). Fotos de extratos são lidas pela OpenAI.

## Parâmetros de despacho
Nenhum é necessário: o pedido em si (`task_summary`) vira uma mensagem no chat da Cifra, que responde com todo o
contexto financeiro e já organiza o que o usuário contou (fixos de todo mês e lançamentos do momento). Mande o
pedido com as palavras e os valores do usuário, sem resumir (ex.: "ganho 6500 por mês e pago 1800 de aluguel",
"gastei 45 reais no mercado hoje"). Se o usuário disse que é fixo ou de todo mês, mantenha isso no pedido.
Opcionais:
- `{"action": "add"}` — o pedido é **só** para anotar ("lança 45 no mercado e 20 de uber", "recebi 300 de um
  freela", "anota 90 de academia como gasto fixo"): grava os lançamentos e os fixos e devolve a confirmação curta,
  sem análise nem conversa. Use quando o usuário só quer registrar; é o caminho mais rápido.
- `{"action": "summary"}` — resumo exato do mês atual, sem IA (rápido). Com `"month": "AAAA-MM"` para outro mês:
  `{"action": "summary", "month": "2026-09"}`.
- `{"action": "overview"}` — gera o panorama completo das finanças (como está, evolução, ajustes de maior impacto)
  em vez de responder uma pergunta.
