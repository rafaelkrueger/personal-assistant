# Cifra — API HTTP

Base: `http://192.168.100.49:8014` — roda no Raspberry Pi da casa (serviço `cifra-finance`); em desenvolvimento, `http://127.0.0.1:8014` (porta em `FINANCE_PORT`). JSON em UTF-8. Erros: `{"detail": "mensagem legível"}`
(`400` pedido inválido, `404` não encontrado, `413` arquivo grande demais, `502` o modelo de IA falhou). Sem
autenticação: roda local, para uma pessoa só. A interface web fica em `GET /` (e o rosto/cores dela em
`GET /persona.js`).

Dados em `data/` (fora do git — são dados financeiros): `profile.json`, `transactions.json`, `recurring.json`,
`imports.json`,
`statements/<id>.*` (arquivos originais dos extratos), `chat.json`, `overview.json`, `llm_settings.json`.

Valores em reais, sempre **positivos**; o que diz se entrou ou saiu é o `type` (`income` ou `expense`). Na entrada
aceita número (`1234.56`) ou texto no formato brasileiro (`"R$ 1.234,56"`); valor negativo vira despesa.

---

## 1. Saúde do serviço

### `GET /api/health`
`{ "ok": true, "transactions": 128, "month_balance": 1320.5, "llm": "OpenAI · gpt-4o-mini" }` — o maestro usa
para o status online.

## 2. Perfil e orçamentos

### `GET /api/profile`
```json
{ "name": "", "monthly_income": 5000,
  "debts": ["cartão Nubank: R$ 3.200 a 14% a.m."], "investments": ["reserva no Tesouro Selic: R$ 8.000"],
  "budgets": { "Mercado": 1200, "Lazer": 400 },
  "notes": "" }
```
`budgets` é o limite **mensal** de cada categoria de despesa.

### `PUT /api/profile`
Qualquer subconjunto dos campos acima (os que não vierem ficam como estão; `budgets` é substituído inteiro). Limite zero ou categoria sem nome são descartados. Devolve o perfil completo.

### `GET /api/categories`
`{ "expense": ["Moradia", "Mercado", …], "income": ["Salário", …] }` (despesas: Moradia, Mercado, Alimentação fora, Transporte, Saúde, Educação, Lazer, Assinaturas, Compras, Vestuário, Pets, Casa e manutenção, Beleza e cuidados, Viagem, Presentes e doações, Contas e serviços, Impostos e taxas, Dívidas e juros, Investimentos, Transferências, Outros; receitas: Salário, Benefícios, Freelance, Rendimentos, Outras receitas) — as categorias padrão mais as que já
apareceram nos lançamentos e nos orçamentos.

## 3. Lançamentos

Formato de um lançamento:
```json
{ "id": "a1b2c3d4e5f6", "date": "2026-10-03", "amount": 320.5, "type": "expense", "category": "Mercado",
  "description": "Supermercado Bom", "account": "Nubank", "source": "manual", "created_at": "…",
  "import_id": "…" }
```
`source`: `manual` (formulário/API), `chat` (contado na conversa), `quick`/`maestro` (frase solta), `fixo`
(gerado por um fixo de todo mês — aí vem o `recurring_id`) ou `import` (extrato — aí vem o `import_id`).

### `GET /api/transactions`
Query: `month=AAAA-MM` (padrão: o mês atual), `type=expense|income`, `category=`, `q=` (busca na descrição,
categoria e conta) e `all=true` (todos os meses). → `{ "month": "2026-10", "transactions": [ … ] }`, do mais
recente ao mais antigo.

### `POST /api/transactions`
**Body:** `{ "amount": 45.9, "type": "expense", "category": "Mercado", "description": "…", "date": "AAAA-MM-DD",
"account": "…" }` — só `amount` é obrigatório (sem `type` é despesa; sem `date` é hoje; sem `category` vai para
"Outros"/"Outras receitas"). Devolve o lançamento salvo.

### `POST /api/transactions/quick`
**Body:** `{ "text": "gastei 45 no mercado ontem e pago 90 de academia todo mês", "source": "maestro" }`. Só anota,
sem conversa: a mesma extração do chat transforma a frase em lançamentos avulsos e em fixos de todo mês (cria,
atualiza, remove) e salva. → `{ "transactions": [ … ], "recurring": [ … ], "removed": [ … ], "text": "Fixo de todo
mês: -R$ 90,00 · Academia (Saúde)\nLançado em 2026-10-03: -R$ 45,00 · mercado" }`. Nada a anotar → `400`.

### `POST /api/transactions/classify`
**Body:** `{}` (ou `{ "all": true }`). A IA revê o **tipo (categoria)** dos lançamentos e dos fixos que já existem —
por padrão só os que estão em "Outros"/"Outras receitas"; com `all`, todos. Tudo que tem a mesma descrição e tipo
recebe a mesma categoria, sempre uma das conhecidas (nunca inventa uma nova nem troca despesa por receita).
→ `{ "changed": [ { "description": "Ração do gato", "from": "Outros", "to": "Pets", "count": 4 } ], "count": 4 }`

Na extração (chat, frase solta, extrato) a IA já classifica cada lançamento com o mesmo guia: o que foi comprado
decide a categoria (Uber → Transporte, iFood → Alimentação fora, farmácia → Saúde, ração → Pets…).

### `PATCH /api/transactions/{id}` — corrige `date`, `amount`, `type`, `category`, `description` ou `account`.
### `DELETE /api/transactions/{id}`

## 4. Fixos de todo mês

Renda e gastos que se repetem (salário, aluguel, internet, assinaturas, parcelas). Cada fixo vira **um lançamento
por mês, no mês atual e já nos 2 seguintes** (`source: "fixo"`, na data do `day`), sozinho; a janela anda a cada
mês novo. Todo lançamento de um fixo leva o `recurring_id` — é a **tag "fixo"** que a UI mostra. Apagar um desses
lançamentos não o recria. Mudar o fixo (valor, dia) ajusta os lançamentos dele deste mês em diante; removê-lo tira
os dos meses seguintes (os deste mês e dos passados ficam). `GET /api/recurring` devolve também `months`, a janela
atual (ex.: `["2026-10", "2026-11", "2026-12"]`). Com entradas fixas cadastradas, `monthly_income` do perfil passa a ser a soma delas.

### `GET /api/recurring`
```json
{ "recurring": [ { "id": "…", "description": "Aluguel", "amount": 1800.0, "type": "expense",
                   "category": "Moradia", "day": 5, "posted": ["2026-10"], "created_at": "…" } ],
  "totals": { "income": 6500.0, "expenses": 1920.0 } }
```

### `POST /api/recurring`
**Body:** `{ "description": "Aluguel", "amount": 1800, "type": "expense", "category": "Moradia", "day": 5 }` —
`description` e `amount` obrigatórios; `day` de 1 a 28 (padrão 1). Mesmo nome e tipo de um fixo que já existe =
atualiza o valor (e o lançamento deste mês). Devolve o fixo.

### `DELETE /api/recurring/{id}` — tira o fixo; os lançamentos dele até este mês ficam, os dos meses seguintes saem.

## 4b. Extratos e faturas

### `POST /api/statements` (multipart/form-data)
Campos: `file` (CSV, OFX/QFX, PDF, JPG, PNG, WEBP ou TXT, até 20 MB) **ou** `text` (as linhas coladas), e opcional
`account` (nome da conta, gravado em cada lançamento). Síncrono (alguns segundos): lê o texto (PDF direto; foto
pela visão da OpenAI), o LLM extrai cada movimentação e salva. Linhas de saldo e totais são ignoradas; um
lançamento que já existe com a mesma data, valor, tipo e descrição é pulado (reimportar não duplica). PDF
escaneado (sem texto) → `400` pedindo fotos das páginas.

→ `{ "import": { "id", "filename", "account", "count": 23, "skipped": 0, "created_at" }, "transactions": [ … ],
"skipped": 0 }`

### `GET /api/imports` → `{ "imports": [ { "id", "filename", "account", "count", "created_at" } ] }`
### `DELETE /api/imports/{id}` → `{ "ok": true, "removed": 23 }`
Desfaz a importação: apaga o arquivo e todos os lançamentos que vieram dela.

## 4d. Patrimônio (investimentos e bens)

Cada item guarda o **valor de hoje** (a pessoa atualiza quando quiser) e, opcionalmente, quanto foi investido — daí
sai o rendimento. As dívidas ficam em `/api/debts` (seção 4f) e o saldo devedor delas conta para baixo no
patrimônio líquido (`totals.debts`); `POST /api/assets` com o tipo `Dívida` devolve `400`. A cada mudança o total do mês é guardado
(`data/networth.json`), e é assim que a evolução mês a mês se forma sozinha.

### `GET /api/assets`
```json
{ "assets": [ { "id": "…", "name": "Tesouro Selic 2029", "kind": "Renda fixa", "value": 18500.0, "invested": 16000.0,
                "institution": "Nubank", "notes": "", "gain": 2500.0, "gain_pct": 15.6, "updated_at": "…" } ],
  "totals": { "assets": 58500.0, "debts": 3200.0, "net": 55300.0, "invested": 46100.0, "gain": 4400.0, "gain_pct": 9.5 },
  "by_kind": [ { "kind": "Renda fixa", "total": 27700.0, "pct": 47.4 } ],
  "history": [ { "month": "2026-10", "label": "outubro/2026", "net": 55300.0 } ],
  "kinds": ["Renda fixa", "Ações", "Fundos imobiliários", "Fundos", "Cripto", "Previdência", "Caixa e reserva",
            "Imóvel", "Veículo", "Outros", "Dívida"] }
```
`gain`/`gain_pct` só existem para itens com `invested`; os totais de rendimento consideram só esses itens.

### `POST /api/assets`
**Body:** `{ "name": "Tesouro Selic 2029", "kind": "Renda fixa", "value": 18500, "invested": 16000, "institution": "Nubank" }`
— `name` e `value` obrigatórios. Mesmo nome de um item que já existe = atualiza o valor (o investido, a instituição
e as observações que vierem vazios ficam como estavam).

### `PATCH /api/assets/{id}` — muda qualquer campo (inclusive o nome). · `DELETE /api/assets/{id}`

**Produtos.** `GET /api/assets` devolve também `products`, o catálogo que a tela mostra ao adicionar (como numa
corretora): Tesouro Selic, Tesouro IPCA+, Tesouro Prefixado, CDB, LCI e LCA, Debêntures/CRI/CRA, Ações, Fundos
imobiliários, ETFs, BDRs, Fundos de investimento, Previdência privada, Criptomoedas, Dólar e outras moedas, Conta e
reserva, Poupança, Imóvel, Veículo e Outro. Cada um tem `id`, `name`, `group`, `kind` (o tipo em que entra
nos totais), `hint`, `icon` e `form` — o formulário que usa. Mandando `product` (o `id` ou o nome) no `POST`, o
`kind` é preenchido sozinho, e o item aceita os campos do formulário dele:

| `form` | Produtos | Campos além de `name`, `value`, `invested`, `institution` |
|---|---|---|
| `fixed` | Tesouro, CDB, LCI/LCA, crédito privado | `rate` (texto: "110% do CDI", "IPCA + 6%"), `maturity` (`AAAA-MM-DD`), `liquidity` |
| `units` | Ações, FIIs, ETFs, BDRs, cripto, moedas | `ticker`, `quantity`, `avg_price`, `price` — com `quantity` e `price`, `value = quantity × price`; com `quantity` e `avg_price`, `invested = quantity × avg_price`; sem `name`, vale o `ticker` |
| `fund` | Fundos, previdência | `rate` (referência, opcional) |
| `cash` | Conta, reserva, poupança, outro | — |
| `good` | Imóvel, veículo | `invested` = quanto pagou |

**Data da compra e valor calculado sozinho.** Todo item aceita `purchase_date` (`AAAA-MM-DD`, não pode ser futura).
Mandando `"auto": true` **sem** o valor de hoje, a Cifra calcula o valor agora e o mantém atualizado
(`app/pricing.py`):

| O quê | Como é calculado | Fonte pública (sem chave) | Precisa de |
|---|---|---|---|
| Renda fixa (Tesouro, CDB, LCI/LCA, crédito) | `invested` corrigido dia útil a dia útil desde a compra, conforme a `rate`: "110% do CDI", "CDI + 2%", "Selic + 0,05%", "IPCA + 6%", "13% a.a." (Tesouro Selic sem taxa = a Selic) | Banco Central do Brasil, SGS: CDI diário (série 12), Selic diária (11), IPCA mensal (433) | `invested`, `purchase_date`, `rate` |
| Ações, FIIs, ETFs, BDRs | `quantity` × cotação de agora | B3 (`cotacao.b3.com.br`, ~15 min de atraso); reserva: Yahoo Finance | `ticker`, `quantity` |
| Criptomoedas | `quantity` × cotação em reais | Mercado Bitcoin; reserva: CoinGecko | `ticker` (BTC, ETH…), `quantity` |
| Dólar, euro | `quantity` × PTAX | Banco Central (PTAX) | `ticker` (USD, EUR), `quantity` |

Sem `avg_price`, o preço médio vira o preço do dia da compra (histórico do Yahoo Finance para a bolsa, CoinGecko
para cripto — melhor esforço: se não vier, o item fica sem rendimento até você informar). O item ganha
`value_method` (a conta, em texto), `value_source` e `valued_at`. Itens automáticos são recalculados quando
`GET /api/assets` é chamado e o valor está velho (renda fixa: uma vez por dia; cotações: a cada 15 min); fonte fora
do ar mantém o último valor. Falta de dado ou papel desconhecido → `400` dizendo o que falta. Informar `value`
(ou `price`) com `"auto": false` volta o item para manual.

**Ativos em dólar.** O produto `exterior` ("Ações e ETFs no exterior", tipo `Exterior`) guarda `avg_price` e
`price` em **US$** e é sempre automático: `value` (em reais) = `quantity` × cotação em US$ × dólar PTAX do Banco
Central. A cotação vem do Yahoo Finance (não oficial — é a fonte gratuita e sem chave que cobre a bolsa americana);
se ela falhar, vale o último `price`. O item traz `currency: "USD"`, `value_usd` e `fx` (o dólar usado). O
`invested` é o custo em dólar convertido pelo dólar de hoje, então o rendimento mostrado é o do ativo em dólar,
sem o efeito do câmbio desde a compra.

**Para o número acompanhar o da corretora** (conferido com uma carteira real em 06/10/2026: CDBs em % do
CDI no centavo; total a 0,04%):
- **Dias úteis** vêm do calendário da Selic diária (série 11), e a correção conta da data da aplicação até ontem.
  O CDI de ontem, que o BCB só publica no dia seguinte, entra com a última taxa conhecida e se acerta sozinho.
- **IPCA+** entra pró-rata por dia útil (cada dia do mês carrega uma fração do IPCA do mês anterior). A convenção
  de cada emissor varia; por isso existe o **valor-base**: mandando `base_value` e `base_date` (um saldo conferido
  na corretora numa data), a correção parte dali em vez da data da aplicação. Na tela, é o campo "Valor hoje na
  corretora" do formulário de renda fixa.
- **Tesouro Direto**: item `tesouro-*` com `quantity` (quantidade de títulos) e o nome do título ("Tesouro Selic
  2031", "Tesouro IPCA+ 2035") vale `quantity` × preço de resgate oficial do dia
  (`tesourodireto.com.br/o/rentabilidade/resgatar`) — é a marcação a mercado, como a corretora mostra.
- **Atualização sozinha**: a cada 30 min (`CIFRA_REFRESH_MINUTES`; 0 desliga) o servidor recalcula os itens
  automáticos e grava o patrimônio do dia em `data/networth_daily.json`. `GET /api/assets` devolve esse histórico
  em `daily` (`[{ "date": "2026-10-06", "net": 55300.0 }]`, últimos 180 dias) — é a evolução dia a dia da tela.

Limites: fora do Tesouro com quantidade, o valor de renda fixa é o da curva do papel, **bruto de IR e IOF** — não é o preço de venda antecipada
(marcação a mercado) de um Tesouro IPCA+ ou Prefixado; o IPCA entra por mês fechado. Fundos e previdência não têm
cálculo automático. Na tela, a taxa de um item de renda fixa também aparece como "≈ X% a.a. hoje".

Pelo chat (`POST /api/chat`) e pela frase solta (`POST /api/transactions/quick`) a Cifra também mantém o patrimônio:
"tenho 12 mil no Tesouro Selic" (valor novo), "apliquei mais 500 no CDB" (aporte: soma no valor e no investido),
"vendi o carro" (remove). O que mudou volta em `assets` e `assets_removed`.

## 4f. Dívidas (financiamentos, empréstimos, cartão…)

`app/debts.py`, dados em `data/debts.json`. Cada dívida guarda o saldo devedor de hoje e, quando a pessoa souber, os
juros, a parcela e o número de parcelas; as contas são feitas no servidor, exatas. Dívidas antigas guardadas no
patrimônio (tipo `Dívida`) são trazidas para cá sozinhas na primeira leitura.

### `GET /api/debts`
```json
{ "debts": [ { "id": "…", "name": "Financiamento do carro", "kind": "Financiamento de veículo", "creditor": "Banco X",
               "balance": 24659.05, "balance_estimated": true, "original": null,
               "rate": "1,49% a.m.", "rate_month": 1.49, "rate_year": 19.42, "monthly_interest": 367.42,
               "installment": 890.0, "installments_total": 48, "installments_paid": 12, "installments_left": 36,
               "due_day": 10, "to_pay": 32040.0, "interest_left": 7380.95,
               "payoff_month": "2029-09", "payoff_label": "setembro/2029", "progress_pct": 25.0,
               "stuck": false, "status": "ativa", "payments": [], "notes": "" } ],
  "summary": { "count": 3, "paid_off": 0, "total": 35859.05, "monthly": 1340.0, "income_pct": 20.6,
               "interest_left": 10093.69, "monthly_interest": 1015.42, "avg_rate_month": 2.83,
               "debt_free_month": null, "debt_free_label": null, "priority": ["Cartão Nubank", "…"],
               "by_kind": [ { "kind": "Financiamento de veículo", "total": 24659.05, "pct": 68.8 } ], "text": "…" },
  "kinds": ["Financiamento imobiliário", "Financiamento de veículo", "Empréstimo pessoal", "Consignado",
            "Cartão de crédito", "Cheque especial", "Parcelamento", "Outras dívidas"] }
```
A lista vem na ordem de ataque: ativas primeiro, do juro mais alto para o mais baixo (`summary.priority` são os
nomes das que têm juros informados). `to_pay` = quanto ainda sai do bolso; `interest_left` = quanto disso é juro;
`monthly_interest` = quanto os juros custam por mês hoje; `stuck: true` = a parcela não cobre nem os juros do mês.
Sem `installments_total`, as parcelas que faltam são estimadas pelo saldo, pelos juros e pela parcela.
`debt_free_month` só aparece quando toda dívida ativa tem um fim calculado; `income_pct` usa a renda do perfil.

### `POST /api/debts`
**Body:** `{ "name": "Financiamento do carro", "creditor": "Banco X", "rate": "1,49% a.m.", "installment": 890,
"installments_total": 48, "installments_paid": 12, "due_day": 10 }` — `name` obrigatório, e o `balance` (saldo
devedor) **ou** `installment` + `installments_total` (aí o saldo é estimado: as parcelas que faltam trazidas a
valor de hoje pelos juros, `balance_estimated: true`). `rate` aceita "1,49% a.m.", "12% a.a." ou um número (ao mês;
com `"rate_period": "year"`, ao ano). Sem `kind`, o tipo sai do nome. Opcionais: `original` (valor contratado),
`start_date`, `notes`. Mesmo nome de uma dívida que já existe = atualiza só o que veio preenchido.

### `PATCH /api/debts/{id}` — os campos enviados substituem (vazio esvazia). · `DELETE /api/debts/{id}`

### `POST /api/debts/{id}/pay`
**Body (tudo opcional):** `{ "amount": 890, "date": "2026-10-10", "extra": false, "post": false }` — sem `amount`
vale a parcela. Parcela normal: os juros do mês (`saldo × taxa`) não abatem o saldo, o resto abate, e conta uma
parcela paga. `extra: true` é amortização: abate o saldo inteiro e encurta o prazo. `post: true` lança o pagamento
também como despesa em "Dívidas e juros" (não use se a parcela já é um fixo). Saldo zerado = `status: "quitada"`.
→ `{ "debt": {…}, "payment": { "date", "amount", "interest", "principal", "extra" }, "transaction": {…} | null }`

### `GET /api/debts/{id}/simulate?extra=300`
E se pagar R$ 300 a mais por mês? → `{ "extra", "current": { "payment", "months", "interest", "payoff_month" },
"with_extra": {…}, "months_saved", "interest_saved" }`. Precisa da parcela cadastrada (`400` sem ela).

Pelo chat e pela frase solta a Cifra também mantém as dívidas ("financiei o carro em 48x de 890", "paguei a parcela
do carro", "amortizei 2 mil", "quitei o cartão"): o que mudou volta em `debts` e `debts_removed`.

## 4e. Indicadores da economia

### `GET /api/indicators` (`?refresh=true` força a leitura)
Selic, CDI, IPCA (12 meses e do mês), dólar e euro, das séries oficiais do **Banco Central do Brasil** (SGS —
`api.bcb.gov.br/dados/serie/bcdata.sgs.<código>`; códigos 432, 4389, 13522, 433, 1 e 21619), sem chave de API.
```json
{ "indicators": [ { "key": "selic", "label": "Selic", "value": 13.75, "unit": "% a.a.", "date": "2026-10-05",
                    "previous": 14.25, "hint": "Meta da taxa Selic, definida pelo Copom", "code": 432 } ],
  "real_rate": 9.14, "updated_at": "2026-10-05T21:40:00", "source": "Banco Central do Brasil (SGS)", "stale": false }
```
`real_rate` é o juro real (Selic acima do IPCA de 12 meses). `previous` é o último valor diferente do atual (para a
seta do câmbio e para saber de quanto a Selic veio). Cache de 6 h na memória e em `data/indicators.json`: se o BCB
não responder, volta o último valor guardado com `"stale": true`; sem nada guardado, `503`. Os mesmos números entram
no contexto do chat (seção INDICADORES), e a Cifra só cita taxa que estiver lá.

## 4c. Notificações (histórico de lançamentos)

### `GET /api/activity?limit=100`
Cada pedido de lançamento que chegou — do maestro (ex.: a automação do iPhone), do chat, do formulário ou de um
extrato — com o texto original e o que aconteceu, do mais recente ao mais antigo (guarda os últimos 300):
```json
{ "activity": [ { "id": "…", "ts": "2026-10-04T12:10:15", "source": "maestro", "ok": true,
                  "text": "Compra aprovada de R$ 45,90 em SUPERMERCADO BOM",
                  "items": [ { "kind": "transaction", "type": "expense", "amount": 45.9,
                               "description": "Supermercado Bom", "category": "Mercado", "date": "2026-10-04" } ],
                  "error": "" } ] }
```
`source`: `maestro`, `chat`, `manual`, `import` ou `quick`. `items[].kind`: `transaction` (avulso), `fixed` (fixo
criado/atualizado) ou `removed` (fixo removido). Pedido que chegou e não lançou nada fica com `ok: false`, `items`
vazio e o motivo em `error` (ex.: "Não encontrei nenhum gasto ou receita nesse texto."). É a aba **Notificações**
da interface. Na primeira leitura o histórico é montado a partir do que já estava lançado.

## 5. Contas (sem LLM — números exatos)

### `GET /api/summary?month=AAAA-MM`
```json
{ "month": "2026-10", "label": "outubro/2026", "income": 5000.0, "expenses": 3679.5, "balance": 1320.5,
  "savings_rate": 26.4, "count": 41, "fixed": { "income": 6500.0, "expenses": 1920.0 },
  "by_category": [ { "category": "Mercado", "total": 1410.0, "budget": 1200, "pct": 118, "over": true } ],
  "income_by_category": [ { "category": "Salário", "total": 5000.0 } ],
  "top_expenses": [ { …lançamento… } ],
  "text": "Outubro/2026: receitas R$ 5.000,00, despesas R$ 3.679,50, saldo R$ 1.320,50 (26% da renda sobrou). …" }
```
`by_category` traz toda categoria com gasto **ou** com orçamento (ordenado pelo gasto); `pct` e `over` só fazem
sentido com `budget`. `savings_rate` é `null` sem receita no mês. `fixed` é a soma dos fixos de todo mês. `text` é o resumo em frases (o que o maestro
devolve em `action=summary`).

### `GET /api/history?months=12`
`{ "months": [ { "month": "2026-05", "label": "maio/2026", "income", "expenses", "balance" } ] }` — do mais antigo
ao mês atual, a partir do primeiro mês com lançamento (máx. 36).

## 6. Conversa (é o que o maestro usa)

### `POST /api/chat`
**Body:** `{ "message": "ganho 6500 por mês, pago 1800 de aluguel; hoje gastei 50 no cinema", "source": "maestro" }`
(`source` opcional, só para o histórico). Responde com todo o contexto (perfil, os fixos, o mês contra os
orçamentos, os últimos meses, os últimos 40 lançamentos e as últimas 20 mensagens) e **extrai e grava o que a
pessoa contou na mensagem**, separando o que é de todo mês do que é do momento:
```json
{ "reply": "…",
  "recurring":    [ …fixos criados ou atualizados (renda mensal, gastos fixos)… ],
  "removed":      [ …fixos removidos ("cancelei a academia")… ],
  "transactions": [ …lançamentos avulsos gravados (source "chat")… ] }
```
Perguntas e hipóteses não gravam nada (as três listas vêm vazias).

### `GET /api/chat` → `{ "messages": [ { "role", "content", "source", "ts" } ] }` · `DELETE /api/chat`

### `POST /api/overview` → `{ "text": "…", "generated_at": "…" }`
Panorama: como está, o que subiu/caiu, os ajustes de maior impacto e o que acompanhar. Fica salvo;
`GET /api/overview` devolve o último (é descartado quando um lançamento, extrato ou o perfil muda).

## 7. LLM (mesmo formato dos outros agentes)

### `GET /api/llm`
`{ "llm_provider": "openai", "providers": ["openai","deepseek"], "openai_model", "openai_api_key_set",
"openai_api_key_preview", "deepseek_model", "deepseek_base_url", "deepseek_api_key_set",
"deepseek_api_key_preview", "vision_available" }` — nunca a chave em si.

### `PUT /api/llm` (ou `POST`)
Campos parciais; chave vazia/omitida nunca apaga a salva. Vale na hora, sem reiniciar.
