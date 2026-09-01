# Pendências (achados menores durante o processo)

> Diferente do `ARQUITETURA.md` (fonte de verdade, decisões e fila
> oficial): este arquivo é só uma lista curta de achados **reais**, mas
> pequenos demais pra virar item próprio da fila — objetivo é não
> esquecer, sem inchar o documento principal. Quando um item daqui for
> resolvido (ou virar grande o suficiente pra merecer registro completo),
> mover o resultado pra `ARQUITETURA.md` e apagar a entrada daqui.
>
> Não presumir que um item daqui já foi resolvido só porque não está mais
> "quente" na conversa — checar o código antes de assumir.
>
> **Limpeza de 2026-08-28**: todo achado que já estava `[x]` resolvido foi
> retirado daqui (17 itens — motor de busca, catálogo de arquivos,
> consulta estruturada/planilha, resumo, memória de conversa). Só sobrou o
> que ainda está genuinamente em aberto.

> **Ordem de trabalho definida pelo usuário em 2026-08-28:**
> 1. ✅ Reorganizar o `ARQUITETURA.MD` de verdade — feito.
> 2. ✅ Implementar as medidas de UI ainda faltando (busca de termo tipo
>    Ctrl+F com contagem/localização, link de abrir/indexar arquivo
>    catalogado — feito, ver item abaixo).
> 3. ✅ Decidir o método que vai ser usado pra **apresentar o Jarvis** —
>    definido (Chrome Remote Desktop, ver item abaixo).

- [x] **Tutorial "Implementar em outro PC" revisado + `.gitignore` criado —
  FEITO em 2026-08-29** (usuário perguntou se estava atualizado antes de
  levar o projeto pra outra máquina). O tutorial (seção no
  `ARQUITETURA_V2.MD`) tinha **erro que quebraria a instalação**: mandava
  `ollama pull nomic-embed-text`, substituído por `mxbai-embed-large` em
  2026-08-25 — dimensão de vetor diferente, ChromaDB rejeita a coleção.
  Também faltava: LibreOffice nos pré-requisitos (sem ele todo `.docx` volta
  a ser "página 1"), versão do Python (3.14.2), o passo do
  `credentials.toml` (senão o Streamlit trava pedindo e-mail e o servidor
  nunca sobe — achado do mesmo dia), `iniciar_jarvis.bat`, `tests/`/`pytest`,
  a nota de VRAM do `NUM_CTX`, e referência ao `ARQUITETURA.MD` antigo (é
  V2 agora). Adicionada a rota **GitHub**, que não existia.

  **`.gitignore` criado (não existia)**: sem ele, subir a pasta pro GitHub
  publicaria `catalogo_arquivos.db` (56 MB — listagem de TODOS os arquivos
  do PC, com caminho), `historico_temp.db` (11 MB — histórico de navegação),
  `Docs/` (77 MB — documentos pessoais) e `banco_vetorial/` (158 MB —
  embeddings de onde o conteúdo é recuperável). **Ressalva honesta**: o
  `.gitignore` NÃO pôde ser testado de verdade — não há Git instalado nesta
  máquina. Por isso o tutorial manda conferir `git status` antes do primeiro
  commit. (Um bug de sintaxe já foi corrigido na escrita: comentário na
  mesma linha do padrão não funciona em `.gitignore`, o `#` só vale no
  início da linha — na 1ª versão os padrões teriam virado literais e não
  ignorariam nada.)

  **`requirements.txt`: conferido, está correto.** Comparado com
  `pip freeze` real: as ausências são só dependências transitivas que o
  spaCy/pytest instalam sozinhos, mais o `playwright` (deliberadamente fora
  — ferramenta de teste, não do app). O modelo gramatical usado pelo código
  é o `pt_core_news_lg`, que está declarado por URL.

- [x] **Régua de fusão de sub-perguntas trocada de PONTO para CONJUNTO —
  FEITO em 2026-08-29.** Causa da resposta duplicada relatada pelo usuário
  ("qual a motivação da revolução?"). A rede de proteção já existia e estava
  bem desenhada (mede em vez de perguntar pra IA), mas media o chunk
  CAMPEÃO de cada sub-pergunta — um ponto só. Medido: `"quais as causas que
  levaram à revolução?"` campeia no chunk **409** e `"quais FORAM as causas
  que levaram à revolução?"` no **21** — uma palavra de diferença, 388
  chunks de distância. Quando 1º e 2º lugar estão quase empatados (os dois
  conjuntos contêm 21 E 409), qualquer palavrinha vira a disputa e a decisão
  de fundir vira junto.

  **Duas alternativas medidas antes de escolher** (pesquisa na web primeiro,
  a pedido do usuário — sobre-decomposição é problema conhecido e
  documentado da técnica, e a literatura confirma que comparar conjuntos
  recuperados é mais confiável que o top-1):
  - **similaridade de TEXTO entre as sub-perguntas — REPROVADA.** Não
    separa: par redundante (motivação × causas) = 0,79, par legítimo
    ("tema do livro" × "quantas páginas") = **0,86**, mais alto. Qualquer
    corte quebraria um dos dois. Era a minha primeira sugestão; medi e
    descartei em vez de escolher um limiar a dedo.
  - **sobreposição de conjunto (Jaccard) — APROVADA.** Devem fundir: 0,304 /
    0,333 / 0,310. Não podem fundir: 0,071 / 0,048 / 0,000. Vão de 4x.
    `LIMIAR_SOBREPOSICAO_SUBPERGUNTAS = 0.15` fica no meio.

  Implementado NO LUGAR da régua antiga (não em cima):
  `melhor_posicao_semantica()` virou `conjunto_ativado_por_subpergunta()` +
  `sobreposicao_de_conjuntos()`; a decisão passou de "maioria perto da
  mediana das posições" pra "mediana das sobreposições par a par ≥ limiar"
  (mediana mantém a tolerância a uma sub-pergunta malformada, que era o
  motivo original de usar maioria). Custo idêntico — os candidatos já eram
  buscados, só era descartado tudo menos o primeiro colocado.
  `RAIO_FUSAO_SUBPERGUNTA_*` continua existindo porque tem OUTRO uso vivo
  (refino da busca literal); o nome ficou herdado e está anotado como tal.

  Verificado: a pergunta original agora funde (uma busca só, com o texto
  inteiro do usuário). Suíte completa sem regressão — 25 rápidos + **9
  lentos** (6min29). Os dois casos que essa mudança poderia quebrar passaram,
  e são opostos entre si: `test_datasheet_tabela_verdade_canal_5` (4
  sub-perguntas que PRECISAM fundir) e
  `test_mcmv_e_agrobrasil_combinados_nao_contaminam_um_ao_outro` (2 que NÃO
  podem fundir).

  **Efeito medido no CONTEÚDO (3 repetições da pergunta original, a pedido
  do usuário)**: os 5 erros factuais originais sumiram nas 3 rodadas —
  incluindo o grave "Major, um velho cavalo". Resposta caiu de ~2.600
  caracteres duplicados pra ~1.200 focados; rodadas 2 e 3 idênticas, a 1
  varia um pouco (efeito de modelo recém-carregado, já visto no resumo).
  As citações centrais foram conferidas contra o documento e são reais e do
  dono certo (discurso do Major). Confirma a suspeita do usuário de que a
  duplicação alimentava a alucinação: a 2ª busca caía no fim do livro e
  trazia material solto que o modelo costurava em narrativa.
  **Cuidado ao conferir**: o PDF quebra palavras com hífen ("te- mos"), então
  busca por citação exata dá falso "não encontrei" — 3 de 6 citações foram
  dadas como inexistentes por esse motivo e depois confirmadas como reais.

- [x] **Verificação da resposta contra a fonte — FEITO em 2026-08-29**
  (`verificar_resposta.py`, novo). Ataca o problema (b) do item abaixo: o
  modelo afirmar além do que o trecho sustenta. Pesquisa na web ANTES de
  escolher, conforme diretriz do usuário — sobre-decomposição, groundedness
  e "Deterministic Quoting" são todos problemas com literatura própria.

  **Duas checagens MECÂNICAS, ligadas (custam ~40 ms, sem modelo nenhum):**
  - `citacoes_nao_encontradas()` — o que a resposta põe entre aspas existe
    literalmente na fonte? É o "Deterministic Quoting" da literatura
    (conferência por comparação direta com o texto, sem IA).
  - `atribuicoes_suspeitas()` — "Fulano disse que X": acha X na fonte e
    procura marcação de fala explícita na vizinhança. **Só acusa quando acha
    OUTRO falante**, nunca pela mera ausência do nome esperado — distinção
    que veio de um falso positivo real: a citação "O Homem é o único e
    verdadeiro inimigo" é mesmo do Major, mas naquele ponto o texto está no
    meio do discurso dele e o nome não se repete (num discurso longo o
    falante é nomeado uma vez, no começo).

  Medido contra os 2 erros reais desta investigação + 3 respostas corretas:
  **5 de 5**, em ~40 ms. No erro de autoria ele ainda identifica o falante
  verdadeiro ("bola de neve") e mostra isso no aviso. Os avisos NUNCA
  reescrevem nem apagam a resposta — só sinalizam (mesmo princípio do aviso
  de colagem em planilha).

  **Verificação por NLI (mDeBERTa multilíngue): CONSTRUÍDA e DESLIGADA**
  (`VERIFICAR_RESPOSTA_ATIVO = False`), com o código mantido. Por quê, em
  números medidos:
  - custo real: **+100 a 250s por resposta** (decomposição em afirmações
    atômicas pelo LLM + NLI na CPU sobre trechos grandes);
  - pega a contradição escancarada ("O Major é um cavalo" → contradiction
    0,995) — mas só se a afirmação for ATÔMICA: na frase composta em que ela
    apareceu de verdade, deu neutral 0,580 (as partes verdadeiras diluem a
    falsa);
  - **passou batido nos dois erros que realmente aconteceram**: autoria
    trocada (entailment 0,915, quase igual à versão correta) e citação
    inventada ("Vamos criar uma sociedade de animais livres da fome e do
    chicote" — o trecho existe, mas é NARRAÇÃO sobre a expectativa da égua
    Quitéria, capítulos depois, e o "Vamos criar" é invenção). NLI julga
    CONTEÚDO e é cego pra autoria e literalidade.
  - calibragem: com limiar 0,98, zero falso positivo e 6 de 7 acertos em ~17
    medições — mas os falsos positivos vinham todos de frase CONDICIONAL
    ("Livrem-se apenas do Homem, e..."), fraqueza conhecida de NLI.
  Dependências novas (`transformers`, `torch`) ficaram instaladas e
  registradas; conferido antes que nada seria rebaixado a ponto de quebrar
  (`chromadb` exige `tokenizers>=0.13.2`, satisfeito).

  **Prompt de citação** (`montar_prompt`): trocada a proibição ("nunca cite
  a menos que...") por EXIGÊNCIA ("cite a origem de cada afirmação"), mais
  instrução explícita de conferir a autoria antes de escrever "fulano disse
  X". Técnica com eficácia medida na literatura (queda de 17,4% → 4,9% de
  alucinação num estudo). **Ressalva honesta**: nos testes desta sessão as
  respostas continuaram SEM trazer "(página N)" — a instrução não pegou
  visivelmente. Fica registrado como não-comprovado aqui.

  **Custo real medido, sem regressão**: suíte lenta 9/9 passando. Tempo:
  6min29 antes → **7min00** depois (+8%), sendo 1 a 2s a mais em cada teste
  de RAG (o prompt ficou mais longo) e +23s no teste de resumo, que nem usa
  esse prompt — variação normal do teste mais longo da suíte. Resposta
  isolada: ~22s → 28s.
  **Armadilha de medição registrada**: uma rodada intermediária deu 17min50
  e quase virou "o código triplicou o custo". Era ambiente — dois servidores
  Streamlit esquecidos rodando, cada um com o batimento cutucando os modelos
  a cada 4 min, disputando GPU durante o teste inteiro. Eu tinha INFERIDO
  que era isso a partir de uma medição isolada; o usuário exigiu refazer a
  medição de verdade, e só aí ficou provado. Lição: matar processos de teste
  antes de medir tempo, e nunca registrar número inferido como se fosse
  medido.

- [ ] **`dividir_em_subperguntas()` INVENTA pergunta que o usuário não fez**
  (achado real 2026-08-29, verificando a resposta de "qual a motivação da
  revolução?" no `revolucao-dos-bichos.pdf`). Medido direto:
  - `"qual a motivacao da revolucao?"` → 2 sub-perguntas, a 2ª é paráfrase
    da 1ª (`"quais as causas que levaram à revolução?"`) → duas respostas
    completas emendadas, dizendo quase a mesma coisa duas vezes.
  - `"quem e o Major?"` → 2, sendo a 2ª `'O que significa "Major"?'` —
    pergunta que ninguém fez, e que empurra o modelo pro conhecimento geral
    dele (o significado da PALAVRA), para longe do documento. **Ressalva:
    este caso foi um teste MEU, não a pergunta do usuário** — serve como
    evidência de que o divisor inventa pergunta em geral, mas NÃO é a causa
    do erro do "cavalo" descrito abaixo (a pergunta real dele não gerou
    nenhuma sub-pergunta sobre o Major).
  - Acerta quando há duas partes de verdade (`"quem é o Major E o que
    acontece com ele?"` → 2) e em pergunta simples (`"qual o tema do
    livro?"` → 1). Ou seja, o defeito é nos casos intermediários.

  **Problema SEPARADO, medido na mesma resposta**: 5 erros factuais, sendo
  o mais grave "Major, um velho cavalo" — o documento (pág. 3) diz *"o
  velho Major, um porco da raça middle white"*. Diagnóstico com o contexto
  instrumentado: o trecho que identifica o Major como porco **nunca foi
  recuperado** (nenhuma das 2 buscas trouxe "middle white"), mas o contexto
  continha a palavra "cavalo" (do Sansão) — sem a identificação na fonte, o
  modelo preencheu o buraco com narrativa plausível. Note que as duas
  sub-perguntas geradas eram AMBAS sobre a revolução (motivação/causas);
  nenhuma pedia identificar o Major — ele entrou na resposta porque o
  modelo julgou que fazia parte de explicar a motivação, e aí errou. Outros erros: revolta
  descrita como liderada por Napoleão (foi espontânea — pág. 21-22, Jones
  bêbado não alimentou os animais, uma vaca quebrou a porta do celeiro);
  "proteger a fazenda dos humanos que ainda estavam lá" (pág. 23: "Jones foi
  expulso"); Sete Mandamentos descritos como "igualdade, justiça e
  cooperação" quando pág. 27 lista proibições concretas.

  **NÃO é temperatura** — `perguntar.py` já usa `temperature=0` em todas as
  chamadas, inclusive a resposta final. São dois problemas separados:
  (a) o divisor inventando pergunta, (b) o modelo não se limitando ao que
  o contexto traz quando falta a informação. **Nada decidido ainda sobre a
  correção** (usuário não se pronunciou; e vale a regra registrada de não
  sair reescrevendo prompt por reflexo — o (a) é definição de trabalho do
  divisor, não redação).

  **Atualização 2026-08-29, depois da troca da régua de fusão**: o (b)
  DIMINUIU mas NÃO acabou. Com a duplicação corrigida, os 5 erros graves
  sumiram, mas nas 3 rodadas de verificação o modelo continua atribuindo ao
  Major falas que são de **Bola de Neve** ("não temos os meios necessários
  para fazer açúcar nesta fazenda" e "você terá toda a aveia e feno que
  quiser" — ditas a Mollie, DEPOIS da revolução; e "trabalhar apenas três
  dias por semana" — sobre o moinho de vento, capítulo V). As frases são
  reais, o dono é outro. Mesma doença do "cavalo", em escala menor: o modelo
  costura fragmentos verdadeiros e atribui ao personagem sobre quem a
  resposta fala. A duplicação era amplificador, não causa.
  **Nota de método**: a checagem automática que eu escrevi não pegou isso —
  ela só procurava os erros JÁ conhecidos. Só apareceu lendo o conteúdo.

- [ ] **Transcrição não entende "capítulo"/"seção" quando o PDF não tem
  sumário embutido** (achado real 2026-08-29: usuário pediu "transcreva o
  primeiro capitulo" do livro amarelo). Duas coisas separadas aqui:

  **(a) O silêncio — CORRIGIDO.** `extrair_recorte_transcricao()` só
  entende intervalo de página e termo literal. "primeiro capitulo" virou
  `PAGINA_INICIO=1, PAGINA_FIM=None` (= página 1 até o fim = tudo), e
  "capitulo 2" virou recorte vazio (= tudo também). Ou seja: o pedido MENOS
  compreendido virava a MAIOR ação possível, sem avisar — 139.554
  caracteres salvos em arquivo, sem o usuário saber que o recorte tinha
  sido ignorado. Agora `recorte_pede_documento_inteiro()` (jarvis.py)
  detecta "recorte não restringe nada" e a interface **pergunta antes**,
  com botão ("Transcrever documento inteiro"), dizendo o tamanho aproximado
  e quais recortes funcionam de verdade. Decisão do usuário entre 3 opções
  (perguntar / avisar e fazer / recusar): perguntar antes. Verificado no
  navegador: pedido de capítulo → mensagem de confirmação + botão; ao
  confirmar → transcrição sai normal com o botão de abrir o arquivo.

  **(b) A capacidade em si — AINDA EM ABERTO.** O projeto JÁ tem máquina de
  seção (`_secoes_disponiveis`/`_casar_secao`/`_limite_da_secao` em
  resumir.py, feitas em 2026-08-25 justamente pra "transcreva o capítulo
  1"), mas ela depende do sumário EMBUTIDO do PDF, e este livro não tem
  nenhum: `_secoes_disponiveis()` devolve lista vazia. Então mesmo roteando
  o pedido pra lá não resolveria neste documento. Para funcionar, precisaria
  detectar capítulo pelo TEXTO (títulos numerados, quebras de página,
  formatação) em vez de só pelo sumário — mudança de tamanho real, não
  ajuste de prompt. **Não decidido ainda se vale fazer** (usuário não se
  pronunciou).

- [x] **Botão pra abrir o arquivo gerado pela transcrição — FEITO em
  2026-08-29** (pedido do usuário no mesmo teste acima: "mais vale ter um
  botão que te leve àquela pasta"). Escolhido apontar pro ARQUIVO
  recém-criado (não só pra pasta `transcricoes/`, que acumula transcrições
  antigas e não diz qual é a nova). Reaproveita o mesmo mecanismo de botão
  ↗ da busca de arquivo (`executar_acao_abrir`, Explorer com o arquivo
  selecionado). `formatar_saida_transcricao()` continua existindo pro
  terminal; a interface usa `transcrever_documento_estruturado()`, que
  devolve `(mensagem, caminho)`.

- [x] **Suite de teste automatizado criada — IMPLEMENTADO em 2026-08-28**
  (pasta `tests/`, `pytest`). Motivado por auto-avaliação do estado do
  projeto pra apresentação (ausência de teste automatizado era o ponto
  fraco mais concreto apontado). 34 testes, todos passando: 25 rápidos
  (sem Ollama — `pytest -m "not slow"`, ~5s) cobrindo os bugs de
  `catalogar_arquivos.py` (LIKE/coringa, barra dupla) e
  `consultar_dados.py` (tipo numérico, PS/PSD, agrupar_por, detecção de
  colagem, blocos da planilha real) e a gramática de `reformular_pergunta()`;
  9 lentos (`@pytest.mark.slow`, chamam Ollama de verdade e/ou dependem
  de documento indexado — ~7,5min no total, maioria é 1 rodada do resumo
  do livro amarelo) cobrindo consulta real de planilha/histórico, os 4
  cenários de RAG (MCMV+AgroBrasil, MCMV sozinho, datasheet, Uauá) e a
  checagem de alucinação do resumo. `pytest`/`scipy` adicionados ao
  `requirements.txt` (scipy já estava em uso desde a detecção de blocos
  de planilha, nunca tinha sido registrado). **Lacuna conhecida**: falta
  o cenário do Polifemo (Odisseia) — o PDF fonte só existe numa coleção
  de teste temporária fora do projeto, não em `Docs/`; não reproduzível
  sem adicionar o livro ao projeto de verdade.

- [x] **Método de apresentação do Jarvis — DEFINIDO em 2026-08-29.**
  Terceiro passo da ordem de trabalho. Restrição real que definiu a
  escolha: o usuário vai apresentar de um PC que **não é** o que roda o
  Jarvis e onde **não pode instalar programa de terceiros** (só usar
  site/navegador).

  **Decisão: acesso remoto via Chrome Remote Desktop** (gratuito, conta
  Google). Instala o host **só no PC do Jarvis**; no PC da apresentação é
  só abrir `remotedesktop.google.com/access` no Edge (Chromium, já vem no
  Windows — nada a instalar) e logar na conta do usuário. Transmite a
  ÁREA DE TRABALHO inteira, não só o navegador — importante porque o botão
  "abrir" do Jarvis abre o Explorer, e isso precisa ser visível na demo.
  Configuração é permanente (não expira, não precisa recriar link no dia).

  **Alternativa descartada: expor o Streamlit via túnel** (ngrok/Cloudflare)
  — o Jarvis tem ações que mexem de verdade no PC (abrir Explorer, copiar/
  indexar arquivo, varrer o disco), e uma URL pública daria essas ações a
  qualquer um com o link. Com tela espelhada, quem assiste só vê pixels.

  **Cuidados anotados pro dia**: desligar suspensão automática do PC (senão
  dorme e cai a conexão); tela inteira fica visível (notificação, aba
  aberta, nome de arquivo no Desktop); logar no Google em janela anônima no
  PC alheio e deslogar depois.

  **Recuperação se o Streamlit cair**: criado `iniciar_jarvis.bat` na raiz
  (duplo clique, ativa o venv e sobe a interface; a janela do terminal
  precisa ficar ABERTA). Motivado por caso real — o processo caiu sozinho
  uma vez durante esta sessão, sem erro no log. **Achado ao testar o .bat
  (teria travado a demo)**: numa execução nova o Streamlit pede um e-mail
  ("Welcome to Streamlit!") e fica esperando input — o servidor nunca
  sobe. Resolvido criando `C:\Users\<user>\.streamlit\credentials.toml`
  com `email = ""` (o arquivo que ele checa; `.streamlit/config.toml` do
  projeto, criado antes, NÃO resolve isso — só desliga a telemetria).
  Re-testado depois da correção: sobe sozinho e responde em ~15s.

  **Achado grave pra demo (2026-08-29) — resposta de 260s por modelo frio,
  não por bug de código.** Usuário reportou que "poderia me falar sobre
  bomba atômica?" (livro amarelo) ficou ~3min "Pensando...". Medido: a
  MESMA pergunta levou **260s na 1ª vez e 14,5s na 2ª**, sem mudar nada.
  Minha 1ª hipótese estava ERRADA (achei que pergunta fora do assunto
  ativaria material demais e cairia na rota ampliada) — instrumentado e
  desmentido: rota "direta", só 14.465 caracteres, e o pipeline inteiro
  (busca + sub-perguntas + corte) soma ~16s. A resposta em si estava
  CORRETA (disse que não achou menção a bomba atômica; usuário confirmou
  que o livro não menciona). Causa real: o Ollama descarrega o modelo da
  VRAM após **5 minutos sem uso** (`keep_alive` padrão) — `ollama ps`
  mostrava "UNTIL 3 minutes from now". Numa demo o apresentador fala vários
  minutos entre perguntas, então a pergunta seguinte paga o recarregamento
  dos 7 GB. **Por que nunca apareceu nos testes**: teste roda em sequência,
  sem pausa — o modelo nunca esfriava. Só o padrão de uso REAL (pausas de
  conversa) expõe isso; ponto cego dos meus testes.

  **Solução: batimento periódico** (`manter_modelo_quente.py`, novo). Uma
  thread daemon dentro do processo do Streamlit cutuca os modelos a cada
  4 min (menos que os 5 do prazo), com `keep_alive: 10m`. Ligada em
  `interface.py` via `st.cache_resource` (garante UMA thread por processo,
  não uma por rerun de tela). Efeito: Jarvis aberto = sempre rápido;
  fechou o `.bat` = thread morre junto e a GPU se libera sozinha no prazo
  padrão — sem precisar lembrar de desativar nada.
  **Alternativa descartada**: `OLLAMA_KEEP_ALIVE=-1` no sistema — global e
  permanente, prenderia ~7,6 GB de VRAM o tempo todo (usuário joga na
  mesma máquina). Também descartado ajustar `keep_alive` nas ~48 chamadas
  do projeto: `keep_alive` vale por requisição e a ÚLTIMA é que manda, então
  cobertura parcial não resolveria — qualquer chamada esquecida reporia os
  5 min. O batimento contorna isso por outro caminho (chega sempre antes de
  expirar), sem tocar nas 48 chamadas.
  **Achado ao testar**: modelo de embedding recusa `/api/generate` (erro
  400 "does not support generate") e só carrega por `/api/embeddings` — sem
  isso o aquecimento parecia funcionar (o principal subia) mas o embedding
  ficava de fora em silêncio, e ele também custa recarregamento na busca.
  Verificado com VRAM zerada (`ollama stop` nos dois): subir o `.bat` e
  abrir a página carrega os DOIS modelos sozinho.

- [x] **Reorganizar `ARQUITETURA.MD` de verdade — FEITO em 2026-08-28.**
  Primeiro passo da ordem de trabalho do dia. Reescrito em 5 partes
  (Estado atual / Perfil / Fila / Visão de longo prazo / Log histórico),
  como `ARQUITETURA_V2.MD` — comparado com o original (inclusive por uma
  segunda IA, achou 2 perdas reais já corrigidas: 2 arquivos sumidos da
  árvore de estrutura, 2 frases de contexto da pasta `Planos/`) — usuário
  vai apagar o `ARQUITETURA.MD` original e ficar só com o V2.

- [x] **UI de "Consultar+Documento" + ações na listagem/busca de arquivo —
  IMPLEMENTADO e VERIFICADO NO NAVEGADOR em 2026-08-29.** Segundo passo da
  ordem de trabalho de 2026-08-28. Estado final (depois de descartar duas
  abordagens intermediárias — ver histórico abaixo):
  1. Botão "Resumo" — já existia.
  2. Remoção de `classificar_consulta_documento()` — já tinha sido feita.
  3. `contar_termo_por_pagina()` (`resumir.py`) — usa o metadado `pagina`
     via `buscar_pares_chunk_metadata()`. Termo em mais de 20 páginas → só
     a quantidade; 20 ou menos → lista as páginas.
  4. Caixa de termo + botão "Procurar" na interface, abaixo do Resumo.
  5. Listagem de pasta (`Procurar → Por pasta`) e busca por nome
     (`Procurar → Por nome de arquivo`) mostram cada arquivo com dois
     BOTÕES DE VERDADE do Streamlit (`st.button`, não link): ↗ abrir a
     pasta no Explorer (`explorer /select,"caminho"`), ⬆ indexar (só em
     formatos de `EXTENSOES_INDEXAVEIS` — copia pra `Docs/` se ainda não
     estiver lá, recusa em vez de sobrescrever se já existir um arquivo
     DIFERENTE com o mesmo nome). Clique dá feedback via `st.toast()`.

  **Por que botão e não link markdown/HTML** (histórico, pra não repetir o
  caminho errado): a primeira versão usava link markdown
  `[abrir](?acao=abrir&arquivo=...)`, processado por um bloco de
  `st.query_params` no topo de `interface.py`. Funcionava, mas testado com
  clique de verdade (não só leitura de código) revelou 2 problemas sem
  solução limpa nesse formato: (1) link do Streamlit sempre abre em ABA
  NOVA (`target="_blank"` automático, sem parâmetro pra desligar) — forçar
  HTML bruto com `target="_self"` tira a aba extra mas causa RECARGA
  COMPLETA da página, que reseta toda a sessão (funil, busca em
  andamento) — troca ruim por ruim; (2) fazer a aba extra se fechar
  sozinha via JS não é possível — testado que nem `<script>` nem atributos
  de evento (`onerror=`) rodam via `unsafe_allow_html`, o Streamlit
  bloqueia os dois. Também rodou por um tempo com emoji colorido (↗️/⬆️)
  como ícone do link, que no Windows renderiza com fundo azul chapado tipo
  placa de trânsito (embutido na fonte de emoji) — feio e destoante do
  tema escuro do site. Botão de verdade (`st.button`) resolve tudo de
  uma vez: sem URL, sem aba, sem navegação, sem perda de sessão, e a
  aparência já é nativa do tema (sem precisar de CSS nem escolha de
  ícone/emoji) — decisão do usuário, 2026-08-29 ("porque nao reescrever
  como botao?"), depois de eu explicar o trade-off (mais código: os
  resultados agora são dado estruturado — `arquivos_diretos_de()` em
  `catalogar_arquivos.py`, `localizar_arquivo_estruturado()` em
  `jarvis.py` — não mais texto pronto, então cada linha vira widget de
  verdade com key única por arquivo/mensagem).

  O bloco de `st.query_params`, o CSS de estilo de link e a função
  `exibir_mensagem()` (que ligava `unsafe_allow_html` condicionalmente)
  foram REMOVIDOS por completo — nada mais gera link `?acao=...`.
  `localizar_arquivo()`/`listar_pasta_por_caminho()` (texto puro, ainda
  usadas pelo terminal via `processar_mensagem()`) voltaram a não ter
  link nenhum, coerente com o que já valia pra `listar_pasta()`.

  Verificado com Playwright (Chromium real, clique de verdade — não só
  navegação direta por URL nem leitura de código): busca por nome e
  listagem de pasta renderizam os botões certos (`.xlsx` sem o de
  indexar); clicar em "abrir" mostra o toast certo
  ("Abrindo pasta de '...'..."), mantém 1 única aba/página no contexto do
  navegador, e o funil/resultado da busca continuam visíveis (sessão não
  resetou); clicar em "indexar" num arquivo já indexado mostra o toast com
  a mensagem real de `indexar_arquivo()` ("sem alterações, pulando").
  Suíte de teste rápida (`pytest -m "not slow"`) rodada depois do refactor:
  25 passed, sem regressão.

  **Bug real encontrado pelo usuário (2026-08-29, testado com busca "Alan
  Wake" — caminho com espaço no nome da pasta) e corrigido**: o botão
  "abrir" caía sempre em "Documentos", não na pasta certa. Eu só tinha
  conferido o TEXTO do toast antes (que é montado igual não importa se o
  Explorer funcionou ou não) — nunca se a pasta certa abria de verdade,
  então o bug passou pelos meus testes anteriores (que só usaram caminhos
  sem espaço, tipo Desktop\sexo.txt). Causa: `subprocess.run(["explorer",
  f"/select,{caminho}"])` como LISTA — quando o caminho tem espaço, o
  Windows envolve o argumento INTEIRO (`/select,` + caminho) numa aspa só,
  e o Explorer não reconhece `/select,` colado dentro da aspa, caindo no
  fallback dele (Documentos). Reproduzido e corrigido com verificação real
  (automação COM `Shell.Application`, lendo `LocationURL` da janela do
  Explorer que abriu — não só o texto do toast): trocado por
  `subprocess.run(f'explorer /select,"{caminho}"')` (string montada na
  mão, aspas só ao redor do caminho, do jeito que o Explorer espera).
  Confirmado com o caminho real do Alan Wake (pasta com espaço): abriu a
  pasta certa (`...\Alan Wake\bonus_material\pdf`), não mais Documentos.

- [ ] **Limpar e organizar o código, arquivo por arquivo.** Passar por cada
  `.py` do projeto (não só `perguntar.py`/`consultar_dados.py`, que tiveram
  mais mudança recente) procurando: código morto (função/import que nada
  mais chama), trecho truncado ou deixado pela metade de alguma
  implementação anterior, lógica duplicada que deveria virar uma função só,
  e comentário/docstring que ficou incoerente com o código atual. Pedido
  explícito do usuário: não é só apagar o obviamente morto, é também
  **resumir/juntar** onde fizer sentido — reduzir a poluição acumulada de
  sessões de tentativa-e-erro, não só remover o que já foi identificado
  como não usado.

- [ ] **Transcrição de PDF/DOCX/TXT nunca preserva o formato original da
  fonte** (registrado 2026-08-25). Hoje só planilha (Excel) devolve algo
  parecido com sua estrutura original (linha/coluna) — mas não é porque
  decidimos preservar formato, é porque `consultar_dados.py:
  transcrever_planilha()` lê o `.xlsx` direto via pandas, sem passar pela
  indexação. PDF/DOCX/TXT passam por `extrair_texto_*()` na hora de
  indexar, que já ACHATA tudo em texto corrido antes de qualquer chunk
  existir — a estrutura original já foi perdida ali, não na transcrição
  depois. Pra "sempre devolver no formato da fonte" valer pra esses 3
  formatos também, precisaria mudar a INDEXAÇÃO pra guardar estrutura, não
  só texto achatado — mudança bem maior que qualquer bug de transcrição,
  mexe na base do pipeline. Não é bug — é ideia de feature registrada, sem
  desenho ainda. Não bloqueia nada da ordem de trabalho atual.
