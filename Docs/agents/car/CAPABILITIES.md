# O que o Torque pode e não pode fazer

> O carro do usuário em dia: guarda o km, os abastecimentos, os serviços feitos e os prazos (IPVA, licenciamento, seguro, CNH), calcula o consumo e o custo por km e avisa o que está vencendo no plano de manutenção.

O Torque é o agente do carro do usuário (nome técnico: `car`). Roda no Raspberry Pi da casa (porta 8015), com os
dados só na pasta `data/` dele: o veículo (marca, modelo, ano, placa, combustível, tanque), as leituras do
hodômetro, os abastecimentos, o histórico de serviços, o **plano de manutenção** (cada item com o intervalo em km
e/ou meses e a última vez em que foi feito) e os **prazos** (IPVA, licenciamento, seguro, CNH, multas). As contas
(km estimado de hoje, km por mês, consumo de tanque cheio a tanque cheio, custo por km, o que venceu ou está para
vencer) são feitas por ele, exatas; cada resposta leva em conta todo esse contexto.

## Pode
- **Dizer como está o carro**: quantos km tem (o último registrado e a estimativa de hoje pelo ritmo de uso), quanto
  roda por mês, o consumo médio, o que está vencido ou vencendo e quanto custou no mês. "Como está meu carro?",
  "o que está para vencer?", "preciso fazer alguma coisa antes de viajar?".
- **Descobrir o plano de manutenção e a ficha técnica do modelo do usuário**: com a marca, o modelo e o ano
  cadastrados, ele pede ao **web-agent** (pelo maestro) o plano de revisões de fábrica e a ficha técnica daquele
  carro e monta o plano sozinho — ajusta os intervalos, acrescenta o que o modelo tem (ex.: fluido do CVT) e
  desliga o que não se aplica (ex.: correia dentada num motor com corrente). "Monta o plano de manutenção do meu
  carro", "pesquisa as revisões do meu modelo". Leva alguns minutos e roda em segundo plano; sem o web-agent, usa
  o que o modelo de IA conhece do carro e marca os itens como estimados.
- **Acompanhar a manutenção**: troca de óleo, filtros, pneus (rodízio, alinhamento), freios, correia, velas,
  bateria, arrefecimento… Cada item vence por km ou por tempo, o que vier primeiro. "Quando é a próxima troca de
  óleo?", "quanto falta para a correia dentada?". O plano já vem com os intervalos típicos e o usuário ajusta pelo
  manual: "no meu carro o óleo é a cada 5 mil km", "acrescenta higienização do ar todo ano".
- **Anotar o que o usuário contar, em linguagem natural**:
  - o km: "o carro está com 48.250 km";
  - abastecimentos: "abasteci 40 litros por 236 reais com 48.300 km", "coloquei 150 de gasolina" — inclusive a
    notificação do banco de uma compra em posto;
  - serviços feitos: "troquei o óleo ontem com 48 mil km, paguei 280 na oficina do Zé", "fiz alinhamento e
    balanceamento" — e o item do plano passa a contar a partir dali;
  - prazos: "o IPVA vence dia 15 de março, 1.850 reais", "o seguro vence em 10/08/2027", "paguei o licenciamento"
    (o que é anual já fica agendado para o ano seguinte);
  - dados do carro: "tenho um Onix 2020 flex, tanque de 44 litros".
- **Fazer as contas de combustível e de custo**: km por litro (de tanque cheio a tanque cheio), autonomia com o
  tanque cheio, custo do combustível por km, quanto o carro custou por mês (combustível, manutenção e documentos) e
  o custo total por km rodado. "Quanto meu carro faz por litro?", "quanto gastei com o carro esse mês?".
- **Orientar sobre cuidados com o carro**: o que cada manutenção faz, o que acontece se atrasar, o que conferir
  antes de pegar estrada, as causas mais comuns de um sintoma e a urgência — sempre mandando ao mecânico quando é
  caso de oficina.
- **Dar a situação exata do carro** (km, alertas, próximo vencimento, custo do mês) na hora, sem passar pelo
  modelo de IA.

## Não pode / não faz
- **Não é mecânico e não vê o carro**: não diagnostica defeito com certeza, não lê o painel nem a central (sem
  OBD), não sabe onde o carro está nem o nível real do tanque. Só enxerga o que foi registrado nele.
- **Não consulta a internet por conta própria**: a única pesquisa que ele pede (ao web-agent, pelo maestro) é a
  do plano de fábrica e da ficha técnica do modelo. Multas, débitos de IPVA, tabela FIPE, recall, preço de peça ou
  de combustível, endereço de oficina ou posto — isso é pedido direto para o **web-agent**.
- Não agenda revisão, não paga IPVA, seguro nem multa, não fala com oficina ou seguradora.
- Não cria lembretes falados nem alarmes (isso é a **Cassandra**, `personal-assistant`): ele mostra o que está
  vencendo quando perguntam ou quando a tela é aberta.
- Não cuida das finanças em geral (isso é a **Cifra**, `finance`): os gastos do carro registrados aqui não são
  lançados nela.
- **Efeito colateral**: um pedido que conta um km, um abastecimento, um serviço, um prazo ou um dado do carro
  **grava** isso nos dados do usuário. Perguntas e hipóteses não gravam nada.
- Antes da pesquisa do modelo, os intervalos do plano são os típicos de carro de passeio. Depois dela, valem os
  encontrados — que vêm de páginas da internet e do modelo de IA, não de uma base oficial: o manual do carro manda.
- Os dados ficam só no Raspberry Pi da casa, mas o conteúdo das conversas vai para o provedor de LLM escolhido
  (OpenAI ou DeepSeek).

## Parâmetros de despacho
Nenhum é necessário: o pedido em si (`task_summary`) vira uma mensagem no chat do Torque, que responde com todo o
contexto do carro e já anota o que o usuário contou. Mande o pedido com as palavras e os números do usuário, sem
resumir (ex.: "abasteci 40 litros por 236 reais com 48.300 km", "troquei o óleo ontem"). Opcionais:
- `{"action": "add"}` — o pedido é **só** para anotar ("o carro está com 48.250 km", "abasteci 150 reais",
  "troquei o filtro de ar hoje", "o IPVA vence dia 15/03"): grava e devolve a confirmação curta, sem análise nem
  conversa. Use quando o usuário só quer registrar; é o caminho mais rápido.
- `{"action": "status"}` — a situação exata do carro agora (km, consumo, o que está vencido ou vencendo, próxima
  manutenção, custo do mês), sem IA (rápido). Use para "como está o carro?" e "tem algo vencendo no carro?".
