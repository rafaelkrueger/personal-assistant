# O que o Lume pode e não pode fazer

> Os estudos do usuário em dia: monta o plano de estudos de cada matéria, registra o tempo estudado, marca o progresso (sequência, metas, módulos feitos, domínio medido em quizzes), revisa com flashcards de repetição espaçada e ensina como um tutor.

O Lume é o agente de estudos do usuário (nome técnico: `learning`, porta 8016), com os dados só na pasta `data/`
dele: o perfil (metas de tempo por dia e por semana, dias de estudo, como prefere aprender), as **matérias** (cada
uma com objetivo, nível, prazo, o **plano** em módulos — a fazer, estudando, feito — e os materiais), as **sessões
de estudo**, os **flashcards** e os **quizzes**. As contas (sequência de dias, minutos de hoje/semana/mês contra a
meta, quanto do plano foi feito, domínio de cada matéria e de cada módulo) são feitas por ele, exatas; cada
resposta leva em conta todo esse contexto.

## Pode
- **Traçar o mapa completo de estudos** de qualquer assunto, como num RPG: regiões em ordem de pré-requisito (de 2
  a 18, pelo tamanho do assunto — Engenharia de Software vira umas 15, com uns 100 módulos), cada uma com os
  módulos (objetivos, lições, prática, tempo) e um chefe no fim; e sugerir materiais. "Monta um plano para eu
  aprender SQL", "refaz meu plano de inglês focando em conversação". Refazer mantém o que já foi vencido. Leva de 1
  a 3 minutos, em segundo plano.
- **Escrever o pergaminho (a lição completa) de cada módulo**: explicação de cada lição com exemplos, erros comuns,
  resumo dos objetivos e exercícios com gabarito.
- **Montar e corrigir as provações e os chefes**, difíceis de propósito (como Dark Souls) e corrigidos com rigor:
  só vencer a provação (80%) conclui um módulo; derrotar o chefe (85%, ou 95% desafiando antes da hora) conquista a
  região e abre a próxima. Perder custa XP e a revanche só abre depois de um descanso. Questões de múltipla escolha,
  respostas escritas e tarefas práticas (código, contas, frases), uma a uma, num combate na tela.
- **Dar XP e níveis** pelo que foi PROVADO (vitórias em provações e chefes; minutos e revisões valem pouco), numa
  curva lenta como a de Dark Souls — derrotas custam XP, mas o nível alcançado nunca cai —, com
  título, atributos, uma perícia por matéria, conquistas, contratos do dia e a crônica.
- **Dizer como estão os estudos**: a sequência de dias, quanto estudou hoje e na semana contra a meta, quanto de cada
  plano está feito, o próximo módulo, o domínio nos quizzes e se está subindo, os cards para revisar, o que está
  atrasado. "Como foi minha semana?", "o que eu estudo hoje?", "estou no ritmo para a prova?".
- **Anotar o que o usuário contar, em linguagem natural**:
  - sessões: "estudei 40 minutos de cálculo", "fiz 2 pomodoros de inglês hoje", "li o capítulo 3 ontem por 1h";
  - módulos: "comecei limites", "acrescenta um módulo de integrais" ("terminei o módulo de derivadas" deixa o
    módulo em "estudando" e manda para a provação: contar não conclui);
  - matérias e metas: "quero aprender espanhol", "vou estudar para o ENEM até novembro", "meu nível é
    intermediário", "pausa cálculo", "quero estudar 1 hora por dia";
  - flashcards ditados ("cria um card: capital da Austrália → Camberra") e materiais ("anota o livro do Stewart").
- **Criar flashcards com a IA** sobre um tema ou a partir de um texto colado ("faz 10 cards de verbos irregulares"),
  que entram na revisão espaçada: cada card volta no dia certo pela resposta da última revisão.
- **Montar e corrigir quizzes** de múltipla escolha e abertos sobre uma matéria, um módulo ou um tema — cobrando de
  novo o que foi errado — e guardar a nota, que vira o domínio da matéria/módulo ao longo do tempo; as erradas
  viram flashcards. (O quiz é respondido na tela, na aba Quiz.)
- **Ensinar como tutor**: explicar com exemplos no nível do usuário, conferir o entendimento com uma pergunta, dar
  pistas em exercícios antes da resposta, corrigir frases em outra língua e conversar nela, passo a passo em
  matemática e código, sugerir o próximo passo concreto.
- **Dar a situação exata dos estudos** (sequência, tempo, planos, cards, avisos) na hora, sem passar pelo modelo de
  IA.

## Não pode / não faz
- **Não pesquisa na internet por conta própria**: os materiais do plano saem do que o modelo de IA conhece (com links
  só quando tem certeza). A pesquisa de materiais pelo **web-agent** (sempre pelo Maestro) existe, mas fica desligada
  (`LEARNING_WEB_RESEARCH=0`). Cotação, notícia, edital atualizado, nota de prova: é pedido para o web-agent.
- Não vê arquivos, fotos nem a tela: trabalha com o que o usuário escreve (dá para colar um texto para virar cards).
- Não é professor credenciado nem fonte oficial: pode errar; edital, regra de prova e legislação devem ser conferidos
  na fonte oficial.
- Não cria lembretes falados nem alarmes (isso é a **Cassandra**): mostra o que fazer quando a tela é aberta ou
  quando perguntam.
- Não se inscreve em cursos, não compra livros, não faz login em plataformas de ensino.
- **Efeito colateral**: um pedido que conta uma sessão, um módulo, uma matéria, uma meta ou dita um card **grava**
  isso; pedir um plano ou cards **cria** o plano/os cards. Perguntas sobre o conteúdo não gravam nada.
- Os dados ficam só na pasta `data/` do Lume, mas o conteúdo das conversas, dos planos, dos quizzes e dos cards
  gerados vai para o provedor de LLM escolhido (OpenAI ou DeepSeek).

## Parâmetros de despacho
Nenhum é necessário: o pedido em si vira uma mensagem no chat do Lume, que
responde com todo o contexto dos estudos e já anota o que o usuário contou. Mande o pedido com as palavras e os
números do usuário, sem resumir. Opcionais:
- `{"action": "add"}` — o pedido é **só** para anotar ("estudei 40 min de cálculo", "terminei o módulo de
  derivadas"): grava e devolve a confirmação curta (`POST /api/quick`).
- `{"action": "status"}` — a situação exata dos estudos agora, sem IA (`GET /api/status`, campo `text`).
