# Jarvis Pessoal — Arquitetura do Projeto

> **V2 — reorganizado em 2026-08-28.** Este documento tinha virado uma
> narrativa cronológica de 2.800 linhas, difícil de navegar (tópicos
> misturados, mesma informação repetida em lugares diferentes, seção
> "estado atual" enterrada depois de 800 linhas de histórico). Reescrito
> em 5 partes, nesta ordem:
> 1. **Estado atual do sistema** — referência enxuta, sem narrativa: o que
>    o sistema É hoje, não como se chegou lá.
> 2. **Perfil do usuário e forma de trabalho**.
> 3. **Fila / próximos passos** — uma lista só, a ordem de trabalho real.
> 4. **Visão de longo prazo (escala corporativa)**.
> 5. **Log histórico de decisões e achados** — todo o histórico detalhado
>    de bug/investigação/decisão, preservado por completo, só reorganizado
>    e sem repetir o mesmo tópico em 3 lugares. Não precisa reler em toda
>    sessão nova — é material de referência, não leitura obrigatória.
>
> REGRA PARA O CLAUDE: sempre que uma decisão de arquitetura, mudança de
> plano, ou novo componente relevante for definido na conversa, avisar
> explicitamente o usuário perguntando se isso deve ser adicionado a este
> documento. Não assumir que o usuário vai lembrar de pedir — a iniciativa
> de avisar é do Claude. Atualização de decisão vigente: editar a Parte 1
> no lugar (nunca só acrescentar nota "~~resolvido~~, ver seção X"). Achado
> novo de investigação/bug: vai pra Parte 5 (Log histórico), na seção do
> tópico a que pertence.

## Parte 1 — Estado atual do sistema

### Objetivo
Assistente pessoal local, que consulta fontes de dados do próprio PC
(documentos, histórico de navegação, arquivos no disco, programas
instalados, dados estruturados) e responde perguntas com base nelas — sem
inventar informação.

Filosofia herdada do projeto original (versão corporativa): IA identifica →
apresenta evidências → humano decide → IA executa. Nunca decide sozinha.

### Princípio central de arquitetura #1
O sistema não é "baseado em RAG" — é um roteador de tarefas que usa a
ferramenta certa para cada tipo de pedido. RAG (busca semântica) é ótimo
para perguntas pontuais sobre conteúdo de texto, mas é a ferramenta errada
para: contagem exata (código Python direto sobre o texto completo), resumo
de documento inteiro (map-reduce), localizar arquivo (catálogo SQLite por
nome, sem embedding), ou listar/filtrar dados estruturados como histórico
cronológico ou planilhas (consulta direta aos dados brutos, não busca
vetorial). O `jarvis.py` classifica o pedido e decide qual ferramenta
interna usar — RAG é uma peça do sistema, não o sistema inteiro.

### Princípio central de arquitetura #2
A IA nunca ESCOLHE entre opções — só RACIOCINA/EXECUTA sobre uma entrada
já desambiguada. Sempre que uma interação envolver seleção entre um
conjunto conhecido e finito de opções (qual arquivo, qual aba de planilha,
qual pasta, qual categoria), essa escolha é responsabilidade da
**interface** (botão, dropdown, lista pra clicar) — nunca da IA
adivinhando/inferindo a partir de texto livre, por mais "óbvia" que a
escolha pareça pra um humano lendo a conversa. A IA fica reservada só pro
que exige raciocínio de verdade sobre uma entrada já resolvida: resumir,
explicar, transcrever, somar, tirar média, comparar, identificar
padrão/erro, etc.

**Exceção legítima**: quando o próprio objetivo de uma funcionalidade é
ACHAR algo que o usuário não sabe identificar com precisão (ex: localizar
arquivo por nome parcial) — aí a busca fuzzy É o propósito da
funcionalidade, não uma escolha que deveria ter sido mecânica.

*(Motivação e histórico de como esses 2 princípios foram descobertos: ver
Parte 5, seção "Origem dos princípios centrais".)*

### Modelos em uso (atualizado 2026-08-28)
- `llama3.1:8b` (`MODELO_LLM`) — modelo principal: geração de resposta
  final, classificação/extração em geral, e (desde 2026-08-28) **as 3
  etapas do resumo de documento** (`resumir_bloco`,
  `sintetizar_grupo_intermediario`, `sintetizar_resumo_final` — as duas
  primeiras rodavam no auxiliar antes, ver Log histórico "Mitigação de
  alucinação no resumo").
- `llama3.2:3b` (`MODELO_LLM_AUXILIAR`) — modelo auxiliar: hoje usado só
  em `condensar_para_historico()` (`resumir.py`, resumo curto pra memória
  de conversa). Não é mais usado no resumo de documento.
- `mxbai-embed-large` (`MODELO_EMBEDDING`) — modelo de embeddings (trocou
  de `nomic-embed-text` em 2026-08-25, ver Log histórico "Status da
  Camada 1").

Os três precisam estar baixados simultaneamente. VRAM não cabe
principal+auxiliar ao mesmo tempo em `num_ctx` grande (medido: 9,1+4,1 =
13,2 GB > 12,28 GB disponíveis) — custa uma recarga de modelo quando as
duas tarefas acontecem em sequência próxima, não é bug.

**Princípio: modelo certo pra tarefa certa.** Tarefas mecânicas/objetivas
podem usar o auxiliar. Tarefas que exigem nuance, síntese final, ou que o
usuário vai ler diretamente, usam o principal. Nunca comprometer qualidade
da resposta final por velocidade.

### Setup do ambiente
- SO: Windows
- Hardware: Ryzen 7 3800X, RTX 4070 (12GB VRAM), 32GB RAM, SSD D: 2TB, SSD C: 200GB
- Python: ambiente virtual em `D:\jarvis-pessoal\venv`
- Ollama: instalado, modelos salvos em `D:\Ollama-Models` (fora do C:, por espaço)
- LibreOffice: instalado via `winget` (`TheDocumentFoundation.LibreOffice`) —
  usado só pra renderizar `.docx` com paginação real (`indexar.py`)
- Custo: 100% gratuito — modelos locais via Ollama, sem "cloud" pago

### Estrutura de arquivos do projeto
```
jarvis-pessoal/
├── venv/ → ambiente virtual Python (não mexer manualmente)
├── Docs/ → arquivos fonte da zona controlada (indexados/consultados)
├── banco_vetorial/ → banco ChromaDB (documentos + histórico, gerado
│   automaticamente, não editar à mão)
├── Planos/ → ARQUITETURA.MD (este arquivo, fonte de verdade do projeto:
│   decisões e fila oficial) e PENDENCIAS.md (achados menores, pequenos
│   demais pra virar item de fila — quando resolvido, o resultado se
│   move pra cá e a entrada de lá é apagada). Centralizados aqui pra
│   facilitar transferência entre PCs via pen drive
├── transcricoes/ → saída de transcrição grande (.txt com carimbo de
│   data/hora, gerada automaticamente) — pasta ignorada pelo catálogo
├── catalogo_arquivos.db → catálogo SQLite de localização de arquivos
│   (zona geral, gerado automaticamente)
├── pastas_catalogadas.json → pastas que a zona geral pode varrer,
│   editável pela interface (config.py é só o padrão da 1ª execução)
├── config.py → configurações centralizadas (caminhos, modelos, parâmetros)
├── jarvis.py → PORTA ÚNICA DE ENTRADA: classifica pedido e roteia
│   (`processar_mensagem` = terminal; `processar_mensagem_guiada` = funil
│   da interface)
├── interface.py → interface Streamlit (funil de decisão em etapas +
│   upload + configuração de pastas catalogadas)
├── perguntar.py → busca semântica (RAG) + memória de conversa
├── resumir.py → resumo map-reduce, contagem exata de termos e transcrição
├── consultar_dados.py → consulta estruturada genérica (histórico,
│   programas, planilha Excel) — filtro/contagem/soma/média/agrupamento
│   sobre dados tabulares
├── programas_instalados.py → lê programas instalados do Registro do Windows
├── indexar.py → extrai PDF/TXT/DOCX, gera chunks, gera embeddings
├── indexar_historico.py → indexa histórico de navegação do Brave
├── catalogar_arquivos.py → catálogo de arquivos (zona geral, sem RAG)
├── teste_historico.py → teste isolado de leitura do histórico (debug)
├── Teste_Ollama.py → teste isolado de conexão com Ollama (debug)
└── requirements.txt → dependências pra recriar o venv em outro PC
```

### Pipeline atual (como os dados fluem)
1. Documento em `Docs/` → texto extraído, despachado por extensão
   (`EXTRATORES_POR_EXTENSAO` em `indexar.py`): `.pdf` via PyMuPDF (com
   detecção de tabela e offsets de página reais), `.docx` renderizado via
   LibreOffice pra paginação real (cai pro extrator sem página se
   LibreOffice não estiver disponível), `.txt` sem paginação real (não é
   possível sem renderizar). **Excel (`.xlsx`) não passa por aqui** — é
   lido direto do arquivo a cada consulta, sem chunk/embedding.
2. Texto dividido em chunks de ~500 caracteres, com 50 de sobreposição,
   respeitando limite de palavra.
3. Cada chunk vira um embedding (`mxbai-embed-large`) e é salvo no
   ChromaDB, com metadados: `arquivo`, `chunk_num`, `hash_conteudo`,
   `pipeline_versao`, `fonte`, `pagina`.
4. Indexação é **incremental**: hash MD5 do arquivo + `pipeline_versao`
   são comparados a cada execução. Se ambos batem, pula. Se algum diverge,
   reprocessa e substitui os chunks antigos daquele arquivo.
5. Na consulta: pergunta → reformulada (troca de pronome por termo
   concreto — **hoje só DENTRO de sub-perguntas da mesma mensagem**, ver
   nota logo abaixo) → dividida em sub-perguntas se tiver múltiplos
   tópicos distintos (medição de convergência semântica decide se a
   divisão é real ou deveria ser fundida de volta) → cada sub-pergunta
   busca chunks relevantes em 3 camadas (busca ampla + corte por
   relevância + busca literal por análise gramatical + filtro de
   isolamento + vizinhança adaptativa + agrupamento contíguo) → roteamento
   por volume decide se cabe numa leitura direta, numa leitura ampliada,
   ou se excede o limite e recusa com honestidade → resposta final via LLM
   principal, com `temperature=0`.

**Resolução de pronome ENTRE MENSAGENS desativada (`config.py:
HISTORICO_PRONOME_ATIVO = False`, decisão do usuário, 2026-08-27)**: o uso
real do Jarvis hoje é mais consulta independente do que chat corrido, e
essa resolução foi a origem de vários bugs de referência cruzada (spaCy
classifica errado certas expressões temporais como pessoa). Reversível —
só virar a chave. Não afeta a resolução de pronome DENTRO de uma mensagem
dividida em sub-perguntas (usa histórico local fabricado da própria
mensagem, sempre ativa) nem os outros 2 usos de histórico ("detalhar
mais", e contexto passivo no prompt da resposta). Ver Log histórico,
"Desativação da resolução de pronome entre mensagens", pro raciocínio
completo.

### Decisões técnicas vigentes (resumo — motivação completa de cada uma no Log histórico)
- Chunking simples por caractere (sem LangChain/LlamaIndex), tamanho 500,
  sobreposição 50.
- `num_ctx` em 3 níveis: 16384 (direto), 32768 (ampliado), acima disso
  recusa e redireciona pra resumo/refinar pergunta — nunca fatia material
  pra cobertura parcial.
- `temperature=0` em toda chamada de classificação/extração e na resposta
  final de pergunta — não nas 3 chamadas do resumo de documento
  (`resumir_bloco`/`sintetizar_grupo_intermediario`/`sintetizar_resumo_final`,
  que passaram a usar `temperature=0` também desde 2026-08-28, ver Log
  histórico).
- LLM sempre traduz pedido em JSON estruturado (filtros, operação,
  coluna) que o código interpreta com operadores fixos — nunca gera/roda
  código livre (`eval`, SQL/pandas gerado pela IA).
- Filtro de texto em consulta estruturada usa sempre "contém", nunca "==",
  exceto quando o valor pedido bate EXATO com um valor real e distinto da
  coluna (aí prefere "==" pra não confundir prefixo com valor, ex: "PS" vs
  "PSD").
- Histórico de conversa: 3 trocas, resposta longa condensada
  (cabeça literal + resumo do fecho) antes de entrar na memória — nunca a
  resposta que o usuário vê na tela.
- Capacidade de alterar/apagar arquivo está FORA de escopo (risco de dano
  irreversível sem desfazer) — sistema só identifica/diagnostica, humano
  executa a correção. Criar arquivo NOVO está dentro de escopo (não
  sobrescreve nada existente).
- Catalogador de arquivos (zona geral) revarre a cada busca, sem
  embedding — custo desprezível hoje, registrado como possível gargalo
  futuro (item na Fila).

## Parte 2 — Perfil do usuário e forma de trabalho

- Não é programador — é "executor": aprende fazendo, não estudando teoria
  antes. Planeja e organiza bem, mas o aprendizado técnico acontece na
  prática, durante a implementação.
- Apesar de se descrever como "não programador", demonstra forte intuição
  arquitetural quando o assunto é discutido a fundo — já puxou sozinho
  soluções estruturais reais (ex: resolver pronome via árvore de
  dependência gramatical em vez de LLM; insistir em cobrir plural sem
  esperar teste falhar; apontar que "entidade prioriza e descarta o
  resto" devia ser "entidade prioriza e REFINA por proximidade").
  Repetidamente identifica quando uma solução proposta resolve o sintoma
  mas não a causa raiz. Tratar as ideias dele sobre arquitetura/design com
  peso real — ele está ativamente co-desenhando a solução, não só
  validando o que é proposto.
- Prefere trabalhar em passos pequenos, um de cada vez, pra poder
  interromper e corrigir sem perder o fio do raciocínio.
- Ao pedir correção de código, sempre enviar o **arquivo inteiro**, não só
  o trecho a colar — ele não tem a intuição de programador para saber onde
  exatamente um trecho solto se encaixa, e isso já causou bugs de colagem
  errada.
- Gosta de entender o "porquê" técnico por trás de cada decisão, não só o
  "o quê" — mas durante a implementação, não como aula teórica antecipada.
- Prefere explicação em linguagem abstrata/simbólica (metáfora, conceito)
  primeiro, com nome de função/código só como referência lateral, não como
  corpo principal da explicação.
- Para qualquer bug/decisão de arquitetura de verdade (não só ajuste de
  limiar): explicar o problema com exemplo concreto E o plano de correção
  ANTES de implementar, pra ele concordar ou propor algo melhor.
- Nunca marcar um bug/limitação como "aceito"/"resolvido o suficiente"
  sozinho — só ele decide quando uma limitação é aceitável. Isso vale
  mesmo como precedente pra decisão futura parecida.
- Não é obrigação/trabalho — é interesse genuíno e imersivo (compara a
  hobby, sessões de centenas de horas). Sessões longas não são sinal de
  esgotamento nem devem ser tratadas como preocupação de bem-estar.
- Confia no Claude para apontar proativamente quando algo deveria ser
  registrado neste documento — não assume que vai lembrar de pedir
  sozinho.
- Ao pedir "verificar tudo" ou "conferir se bate", isso inclui SEMPRE este
  documento e o `PENDENCIAS.md`, não só os arquivos `.py` — nunca presumir
  alinhamento sem de fato reler o conteúdo real.
- Quer um sistema **completo e útil**, usando a melhor ferramenta pra cada
  tarefa (RAG, map-reduce, consulta estruturada, código direto), sem apego
  a nenhuma técnica específica nem à opção mais leve/conveniente. Único
  limite real: nada deve demorar de forma absurda — mas escolher a
  ferramenta certa quase sempre já resolve isso.
- **Pesquisar na web ANTES** de resolver um problema específico ou
  implementar uma ideia (diretriz do usuário, 2026-08-29): verificar se o
  problema já tem nome/documentação e se existe método estabelecido, ou
  melhor que o pensado. Trazer o que achou (com links) junto da proposta,
  dizendo explicitamente se há alternativa superior. Se nada melhor
  aparecer, seguir com a ideia própria — mas tendo verificado, não
  presumido. Motivo concreto: investigando a resposta duplicada do RAG
  (2026-08-29), a pesquisa revelou que "sobre-decomposição de pergunta" é
  problema conhecido da técnica, que a arquitetura proposta pelo usuário já
  tem nome (Router/Adaptive-RAG), e que comparar CONJUNTOS recuperados é
  mais confiável que comparar o primeiro colocado — o que virou a correção
  adotada, no lugar da minha primeira ideia (que a medição depois reprovou).

*(Perfil também mantido como memória persistente do Claude entre sessões —
`user_perfil_executor.md` — as duas versões devem ficar consistentes; essa
aqui é a completa/canônica.)*

## Parte 3 — Fila / próximos passos

> Ordem de trabalho definida pelo usuário em 2026-08-28 (também registrada
> no `PENDENCIAS.md`, que é onde novos achados pequenos entram primeiro):

1. **Reorganizar este documento** — em andamento (esta própria reescrita).
2. **UI de "Consultar+Documento" + ações na listagem de pasta** — botão
   Resumo, `st.query_params` pra ações de link, link `[abrir]`/`[indexar]`
   em cada linha de pasta listada, contagem de termo por página, caixa de
   termo + botão Procurar. Ordem interna e detalhe de cada passo: ver
   `PENDENCIAS.md`.
3. **Método de apresentação do Jarvis** — formato da demonstração
   (prazo: retorno 18/mês, demo 30/mês). Ainda não discutido/desenhado.

**Outros itens pendentes, prioridade baixa (pós-prazo de demo)** — detalhe
completo de cada um na Parte 5, seção "Fila numerada original (histórico)":
- Leitura de tabela dinâmica (pivot table) em Excel — investigado,
  viável com `openpyxl`, não implementado.
- Memória ensinável ("lembre que X").
- Camada de revisão da própria resposta (self-check) / auditoria formal.
- Capacidade de criação de arquivo (Excel/PDF a partir de dado indexado).
- Indexação configurável (3 modos: ao iniciar, agendado, sob comando).
- `garantir_catalogo()` revarrer por intervalo/comando em vez de sempre.
- Limpeza de prints de debug, checklist de erros conhecidos, documentação
  de handoff.
- Limpar e organizar o código, arquivo por arquivo (ver `PENDENCIAS.md`).
- Transcrição de PDF/DOCX/TXT preservar formato original da fonte (ideia
  de feature, não desenhada — ver `PENDENCIAS.md`).

## Parte 4 — Visão de longo prazo (escala corporativa)

> Os itens abaixo são lacunas estruturais que separam "sistema funcional
> pra uma pessoa" de "ferramenta pronta pra escritório de multinacional" —
> não fazem parte do prazo pessoal de demonstração, ficam registrados como
> visão de médio/longo prazo. Detalhe de cada um: Parte 5, seção "Buracos
> identificados para escala corporativa".

- Multiusuário com permissão diferenciada.
- Log de auditoria de uso geral (quem perguntou o quê, quando).
- Fontes de dados corporativas típicas (e-mail, Teams/Slack, ticket, ERP).
- Backup e recuperação do banco vetorial.
- Escalabilidade de hardware além de um PC local.
- Classificação de dado sensível por nível de sigilo.

## Parte 5 — Log histórico de decisões e achados

> Material de referência — não precisa reler em toda sessão nova. Preserva
> o raciocínio completo (o quê foi tentado, o que falhou, por que a
> decisão final foi essa) por trás de cada item das Partes 1-4. Organizado
> cronologicamente, por tópico. Se uma decisão aqui contradizer a Parte 1,
> a Parte 1 é que vale — avisar o usuário pra corrigir a divergência.

### Onde o projeto está (registro de 2026-08-25, ver Parte 1 pro estado atual real)

Sistema **funcionando** e usável (`streamlit run interface.py`). Itens 1 a 12 da
fila concluídos — o funil de decisão em etapas está completo, com escolha de
arquivo/aba/pasta por dropdown (item 12). **Rework da busca e resposta
(Camadas 1, 2 e 3) concluído em 2026-08-25** — ver "Status da Camada 1" e
"Status da Camada 2/3" mais abaixo pros achados e decisões. Próximo passo
disponível: UI de "Consultar+Documento" (botão Resumo + caixa de termo, ver
"Próximo passo planejado" abaixo).

**Sessão 2026-08-24/25: rework completo, testado contra Odisseia (267 páginas)
e Os Sertões (373 páginas), ambos lidos por completo antes de testar.**
Resumo do que mudou (detalhes nas seções "Status da Camada 1" e "Status da
Camada 2/3" abaixo, não repetir aqui):
- Camada 1: filtro de isolamento semântico, busca literal com stopwords do
  spaCy, limiar de vizinhança por fração do documento.
- Camada 2/3: map-reduce fragmentado abandonado, substituído por roteamento
  de 3 rotas (direta / direta ampliada / avisa limite excedido) — nunca mais
  fatia material pra interpretar em pedaços separados.
- `temperature=0` adicionado na resposta final (`perguntar_ao_modelo()`).
- Limites de modelo aceitos e documentados (não perseguidos mais): leitura de
  verso arcaico (Odisseia) e omissão de item em enumeração densa (Os Sertões).
- **Item 21 da fila (localizar seção de um documento sobre um tema) resolvido
  de quebra** — não era objetivo do rework, mas o pipeline novo (busca
  semântica + contiguidade) era exatamente o método que já tinha sido
  identificado como promissor pra esse item em 2026-08-22. Reconfirmado
  contra o caso canônico, ver item 21 na fila numerada.

**Sessão anterior (2026-08-22): 1ª bateria de testes humanos do usuário.** Ele
usou a interface de verdade e trouxe achados. Todos os bugs foram corrigidos:

| | Bug | Estado |
|---|---|---|
| B1 | Crash `openpyxl` ao trocar de formato com alvo escolhido (`.docx` ia para rota de planilha) | ✅ `limpar_alvo()` em `trocar_formato()` + validação de extensão |
| B2 | Recusa da transcrição sugeria ação impossível no caminho atual (loop fechado) | ✅ o chamador informa a saída alcançável (`sugestao_alternativa`) |
| B3 | Filtro aplicado na coluna errada (`origem` em vez de `url`) | ✅ procura o valor nas outras colunas + `PRIORIDADE_COLUNAS_POR_FONTE` |
| B4 | Dúvida sobre veracidade das "13 propostas" | ✅ **conferido lendo o livro** — ver veredito abaixo |

Também nessa sessão: `NUM_CTX` 8192 → **16384** (medido, ver tabela), catálogo
ganhou exclusão de lixo técnico, e `condensar_para_historico()` foi criada.

## A decisão que já foi executada: REWORK DA BUSCA E RESPOSTA

**Concluído em 2026-08-25** (Camadas 1, 2 e 3 implementadas e testadas contra
livro amarelo, Odisseia e Os Sertões). Seção mantida como registro do desenho
original e das decisões tomadas — ver "Status da Camada 1" e "Status da
Camada 2/3" abaixo pro estado final.

### Por que (três evidências medidas, não suposições)

1. **Fusão de trechos — confirmada lendo o livro.** A resposta juntou "20 bilhões
   ao longo de uma década" (pág. 40) com "candidatura de Arthur do Val à
   prefeitura de São Paulo" (pág. 28) numa frase só. Nada foi inventado: pedaços
   verdadeiros de páginas distantes foram costurados. **Causa:** os trechos
   chegam ao modelo colados, fora da ordem do documento e sem identificação de
   origem — parecem texto contínuo.
2. **Falta de cobertura.** Perguntado "quais as propostas do livro", o sistema
   afirmou que *"o livro não menciona propostas específicas para educação"* — e
   o mesmo sobre segurança — quando há **capítulos inteiros** sobre os dois (IX e
   II). O RAG olha 15 de 311 trechos: **5% do documento**, e responde com cara de
   completo.
3. **Aumentar o trecho NÃO resolve** (medido, ver tabela): chunk de 1500
   **piorou** a recuperação. Trecho grande vira a média de vários assuntos no
   embedding e deixa de casar com precisão.

**Conclusão que orienta o rework:** busca quer trecho **pequeno** (precisão);
leitura quer texto **contínuo** (compreensão). São exigências opostas, e hoje o
sistema atende só a primeira.

### O desenho aprovado (ideia central do usuário: camadas, não escolha)

Em vez de a IA escolher entre RAG / resumo / vizinhança, **aplicar tudo em
camadas, com a rota decidida por medição**:

1. **Busca ampla com distâncias** — muitos candidatos, não 15 fixos.
2. **Corte por relevância** relativo ao melhor — a quantidade varia: pergunta
   pontual ativa pouco, pergunta de cobertura ativa muito.
3. **Vizinhança ADAPTATIVA** — poucos trechos ativados = falta contexto, então
   vizinhança larga; muitos = já há cobertura, então estreita. Resolve a objeção
   do usuário: um trecho pode ser a *continuação* de uma proposta sem repetir a
   palavra.
4. **Agrupamento contíguo + ordem do documento + `[trecho da página N]`** — é o
   que ataca a fusão.
5. **Roteamento por volume, 3 rotas — REDESENHADO em 2026-08-24/25** (ver
   "Status da Camada 2/3" abaixo pro porquê): a ideia original de "map-reduce
   focado" (item 6 abaixo, como estava escrito) foi **abandonada e substituída**
   depois de testada de verdade e falhar em tarefa de extração factual densa.
   O desenho final: material cabe no teto normal (`NUM_CTX`) → resposta direta;
   não cabe mas cabe no teto ampliado (`NUM_CTX_AMPLIADO`, 32768) → mesma
   resposta direta, só com contexto maior, ainda numa ÚNICA leitura sem fatiar;
   não cabe nem ampliado → **não tenta cobertura parcial**, avisa e redireciona
   pra resumo do documento ou pra refinar a pergunta.
6. ~~**Teto obrigatório** com aviso honesto: corta em blocos e declara que
   analisou parte.~~ **Resolvido em 2026-08-25, ver "Status da Camada 2/3"**:
   a pendência abaixo (reabrir depois das camadas prontas, buscar alternativa
   à cobertura parcial) foi diretamente resolvida — a resposta final não é mais
   "analisei só uma parte", é uma leitura completa (rota ampliada) ou um aviso
   honesto de que a pergunta precisa ser mais específica (rota excedida), nunca
   uma cobertura fatiada arriscando misturar informação.

**Por que isso é melhor do que corrigir caso a caso:** elimina a decisão
"resumo ou pergunta?" em vez de melhorá-la. Não é a IA escolhendo a ferramenta —
é o código medindo quanto do documento é relevante. É o Princípio central #2
aplicado à camada que ainda não o seguia.

**Plano completo** (com scripts afetados, verificação e experimento do critério
de corte): `C:\Users\Foda\.claude\plans\pensar-na-posiibilidade-de-glowing-pony.md`

### Status da Camada 1 (2026-08-24) — implementada e calibrada

`reunir_contexto()` (`perguntar.py`) implementa os passos 1-4 acima
(`buscar_candidatos`, `cortar_por_relevancia`, `buscar_por_termo_literal`,
`calcular_janela_vizinhanca`, `agrupar_em_blocos_contiguos`).
`buscar_chunks_relevantes()` virou wrapper fino por cima, então
`responder_pergunta()`/`responder_com_detalhamento()` já se beneficiam sem
mudança de assinatura. Camadas 2 e 3 **implementadas e testadas em 2026-08-24/25**
— ver "Status da Camada 2/3" logo abaixo.

**Achados da calibração, todos medidos contra o livro amarelo (50 páginas
lidas por completo, não só trechos) e verificados linha por linha, nunca só
pelo caminho de busca:**

- **Busca híbrida por termo literal adicionada** (`buscar_por_termo_literal()`,
  novo passo entre o corte de relevância e a vizinhança). Achado que motivou:
  "quanto o Brasil gasta com o Minha Casa Minha Vida" falhava sempre (chunk
  certo existia mas nunca vencia a busca semântica — ver explicação detalhada
  abaixo) — busca por trecho literal de 3+ palavras da pergunta resolveu nos
  dois tamanhos de chunk testados, sem regressão nos casos que já funcionavam.
- **Por que a busca semântica sozinha falhava neste caso**: o chunk (pág. 48)
  fala majoritariamente de OUTRO assunto (fracasso histórico de políticas
  habitacionais) e só cita o programa de passagem — o embedding do chunk
  inteiro representa o assunto dominante, não o fato específico embutido nele,
  então não se destaca entre dezenas de chunks com assinatura semântica
  parecida ("crítica a política pública"). Fator de corte (`LIMIAR_RELEVANCIA_FATOR`)
  não resolve isso de forma confiável: apertar ajuda pergunta pontual diluída
  por ruído, mas pode EXCLUIR de vez um chunk que já está mal ranqueado (medido:
  chunk certo ficou na posição 13 de 60 — um corte agressivo o teria cortado
  fora). Busca semântica e busca literal erram em casos opostos; por isso
  ficam como camadas complementares, não uma substituindo a outra.
- **`mxbai-embed-large` adotado no lugar de `nomic-embed-text`** (335M vs 137M
  parâmetros, +400MB de VRAM). Decisão por avaliação externa (benchmarks),
  não por A/B testado no próprio acervo — dado o custo baixo, não valeu testar
  com/sem, só substituir. **Migração pra produção feita em 2026-08-25**
  (`config.py`, `MODELO_EMBEDDING`) — antes disso, só testado numa coleção
  separada (`banco_teste`) usada pra calibrar a Camada 1. Exigiu apagar e
  reconstruir a coleção `documentos_pessoais` inteira (documentos E histórico
  de navegação, mesma coleção): ChromaDB não aceita vetor de dimensão
  diferente misturado no mesmo índice, e `indexar_historico.py` não rastreia
  `pipeline_versao` como `indexar.py` rastreia — trocar o modelo sem
  reconstruir tudo teria misturado vetor antigo (nomic, 768 dim) com novo
  (mxbai, 1024 dim) e quebrado a busca. Reindexação combinada com a correção
  de extração de tabela (ver "Status da Camada 2/3" — achado do datasheet de
  CI, 2026-08-25) na mesma passada, pra não reindexar tudo duas vezes.
  `bge-m3` foi cogitado (também bom, multilíngue e
  nativamente híbrido) e **descartado por ora**: o modo híbrido dele exige a
  biblioteca `FlagEmbedding` (PyTorch) rodando fora do Ollama, e ChromaDB não
  entende a saída esparsa dele nativamente — trocaria motor de inferência E
  banco vetorial só pra usar uma capacidade que a busca por termo literal
  (acima) já cobre de forma mais simples pro caso observado. Mesmo raciocínio
  do episódio do Qwen2.5:14b: ferramenta maior nem sempre vale a troca de
  funcionamento. Registrado para reconsiderar **depois de muitos mais testes**,
  se a busca literal se mostrar insuficiente algum dia.
- **Tamanho de chunk: mantido em 500.** Testado contra 350 (ambos com mxbai +
  busca híbrida, 18 perguntas no total, pontuais e de cobertura, cada resposta
  conferida linha por linha contra o livro). Resultado sem vencedor limpo — os
  dois erraram e acertaram em casos diferentes — mas 500 mantido por já ser o
  padrão calibrado (chunk 500 também venceu o experimento de tamanho original,
  ver tabela "Tamanho de chunk" acima) e por evitar reindexar tudo sem ganho
  comprovado.
- **`JANELA_VIZINHANCA_LARGA` subiu de 4 para 8** (`config.py`). Achado real:
  com só 1 candidato ativado (pergunta "quais os cinco pilares do AgroBrasil
  2030", resolvida via busca literal), ±4 não foi longe o bastante — o bloco
  cortou NO MEIO DA FRASE do quarto pilar, e o modelo completou o corte com um
  chute e reaproveitou uma frase do pilar 1 fingindo ser o pilar 5. Causa: o
  ponto de ancoragem (chunk que menciona "AgroBrasil 2030" de passagem, na
  introdução) ficava ANTES de onde os pilares são listados, "gastando" metade
  da janela só pra chegar lá. Retestado com janela=8: bloco foi de 4.119 pra
  7.716 caracteres, resposta saiu com os 5 pilares corretos, incluindo
  detalhes finos que antes saíam errados ou inventados. Seguro de aumentar
  justamente por ser o caso de MENOS candidatos ativados — sobra orçamento de
  contexto de sobra, nenhum teste chegou perto do limite do `NUM_CTX`.
- **Correção de citação de fonte no prompt** (`montar_prompt()`,
  `perguntar.py`): o modelo às vezes inventava nome de capítulo
  ("CAPÍTULO XIII POLÍTICA EXTERNA") sem NENHUMA base no contexto recebido —
  nem a marcação `[trecho da página N]` inclui nome de capítulo, então era
  invenção pura, um padrão de "completar o estilo de resposta bem
  fundamentada" bem documentado em sistemas de RAG em geral. Corrigido com
  instrução explícita: nunca citar capítulo/seção/página que não esteja
  literalmente marcada no contexto. Efeito colateral bom observado depois: o
  modelo passou a **admitir mais quando não tem informação suficiente**, em
  vez de fundir capítulos com confiança — bug de segurança pública (fusão de
  3 capítulos, achado na bateria de 30 perguntas) apareceu bem mais raro nas
  baterias seguintes, quase sempre virando hedge honesto em vez de mistura.
- **Falso positivo corrigido no caminho**: uma citação "página 36" que parecia
  errada (fato esperado na página 35) na verdade não era erro — o livro repete
  o mesmo número em duas páginas de verdade (35 como problema, 36 na seção de
  solução, com uma gralha de digitação no original: "cerca de cerca de 6
  milhões"). Lição: sempre confirmar contra o texto fonte antes de classificar
  algo como bug.

**Segunda rodada de calibração da Camada 1 (2026-08-24), agora medida contra a
Odisseia (267 páginas, verso arcaico) e Os Sertões (373 páginas, prosa densa),
ambos lidos por completo antes de testar — não só livro amarelo:**

- **Filtro de isolamento semântico** (`filtrar_semanticos_isolados()`, novo
  passo em `reunir_contexto()`, roda ANTES de `calcular_janela_vizinhanca()`).
  Achado: pergunta sobre Polifemo (Odisseia) fundiu o episódio errado
  (Proteu/pele de foca) e inventou uma personagem ("Galateia") que não existe
  no texto. Causa dupla: (a) `cortar_por_relevancia()` não discrimina bem em
  texto narrativo/poético (distâncias ficam muito próximas, quase tudo passa
  no corte); (b) `buscar_por_termo_literal()` (na forma antiga, 6→3 palavras)
  caiu pra um fallback de conectivo sem sentido ("e o que") pra um nome próprio
  de uma palavra só, trazendo 15 trechos irrelevantes. Corrigido descartando
  candidato ativado SÓ pela busca semântica (sem âncora de termo literal por
  perto — dentro de `JANELA_VIZINHANCA_LARGA * 2` posições de um candidato
  literal) — testado contra a alternativa de "cluster mútuo" (candidato perto
  de OUTRO candidato qualquer, não só de âncora literal) e essa alternativa
  ficou bem mais fraca (~28% de ruído retido no melhor ajuste, contra 0% do
  ancoramento por termo literal).
- **`buscar_por_termo_literal()` reescrita com stopwords do spaCy**
  (`spacy.lang.pt.stop_words.STOP_WORDS`, importado como
  `PALAVRAS_FUNCIONAIS_PT`). Descartada lista de palavras funcionais escrita à
  mão (não generaliza pra outro idioma/domínio) e descartada frequência
  relativa ao corpus (quebra com termo técnico repetido ou termo funcional
  raro por acaso em documento pequeno). N-grama agora desce de 6 até 1 palavra
  (era 6→3), exigindo que pelo menos uma palavra do n-grama não seja stopword —
  resolve o caso de nome próprio de uma palavra só sem cair em conectivo.
- **Limiar de vizinhança virou fração do documento, não número absoluto**
  (`LIMIAR_ATIVADOS_VIZINHANCA_LARGA/MEDIA_PISO` + `_FRACAO`, `config.py`).
  Achado real (pergunta "quantos morreram em Uauá?", Os Sertões): os valores
  antigos (6 e 12) foram calibrados como absolutos no livro amarelo (311
  chunks) — em Os Sertões (2.253 chunks), 19 ativados (0,84% do livro,
  proporcionalmente escasso) já passava de 12 e caía em janela estreita (0),
  o que impediu a vizinhança de alcançar um fato a só 6 posições do candidato
  mais próximo — janela larga (8) teria alcançado, mas nunca foi escolhida
  porque o limiar não escalava com o tamanho do arquivo. Agora o limiar é
  `max(piso_absoluto, fração × total_de_chunks_do_arquivo)` — piso protege
  documento pequeno (mesmo comportamento de antes), fração protege documento
  grande. Frações (2%/4%) deliberadamente abaixo de 5%, pra não esvaziar a
  distinção entre pergunta pontual e de cobertura em documento muito grande.
  Ainda não testado contra documento múltiplas vezes maior que Os Sertões —
  pendência conhecida.
- **Teto de leitura arcaica do llama3.1:8b (Odisseia) — aceito como limite
  conhecido do modelo, não perseguido mais.** Mesmo com retrieval corrigido
  (verificado inspecionando o bloco entregue: cena do cegamento, truque do
  "Ninguém", fuga pelos carneiros — tudo presente e correto), o modelo ainda
  errava a narrativa (omitia o cegamento, invertia quem amaldiçoa quem).
  Testado Qwen2.5:14b como alternativa: leu dramaticamente melhor, mas sozinho
  já usa ~10-11,5 GB de VRAM, sem espaço pro auxiliar+embedding — descartado
  pelo mesmo motivo que já tinha descartado outras trocas de modelo maior
  (custo de VRAM inviabiliza os três modelos coexistindo). Decisão do usuário:
  aceitar como limite documentado, não é bug a perseguir.

### Status da Camada 2/3 (2026-08-25) — redesenhada e implementada

**Camada 3 original (map-reduce focado, item 5/6 do desenho aprovado) foi
testada de verdade e ABANDONADA — não é mais map-reduce nenhum.** Substituída
por um roteamento de 3 rotas em `decidir_rota_por_volume()` (`perguntar.py`),
decidido por MEDIÇÃO de caracteres ativados pela Camada 1, nunca por LLM
(Princípio central #2):

- **"direta"**: material cabe em `LIMITE_CARACTERES_CONTEXTO_DIRETO` (56000,
  calculado a partir de `NUM_CTX`=16384) → resposta de sempre.
- **"direta_ampliada"**: não cabe no teto normal mas cabe em
  `LIMITE_CARACTERES_CONTEXTO_AMPLIADO` (120000, calculado a partir de
  `NUM_CTX_AMPLIADO`=32768) → MESMA resposta direta, só com contexto maior —
  mais lenta (~40-50s vs ~10-20s), mas ainda uma leitura ÚNICA e contínua,
  sem fatiar o material.
- **"excede_limite"**: não cabe nem ampliado → `montar_mensagem_limite_excedido()`
  devolve um aviso honesto (mensagem fixa, não gerada por LLM) redirecionando
  pra `resumir_arquivo()` (resumo do documento inteiro) ou pra refinar a
  pergunta — **nenhuma tentativa de cobertura parcial fatiada**.

**Por que o map-reduce foi abandonado (achado real, testando "quantos morreram
em Uauá?" no Os Sertões — texto fonte lido por completo antes do teste):**
fatiar o material relevante em blocos e pedir pra IA extrair de cada um
separado (map) e depois juntar (reduce) produziu respostas erradas ou
incompletas em TODA combinação testada de modelo/prompt/temperature/tamanho de
bloco — porque a tarefa era de RETRIEVAL (relatar um número que já está
escrito), não deveria depender de interpretação de fragmento isolado fora de
contexto. Ao mandar o MESMO material inteiro, numa passada só, com
`num_ctx` maior (32768 e 49152 testados), o modelo leu certo e completo, de
forma reproduzível — confirmando que o problema era a fragmentação em si, não
o prompt. Ver [[feedback_evitar_prompt_como_reflexo]] na memória — essa
descoberta só apareceu depois de o usuário interromper uma sequência de
patches de prompt e pedir pra testar a hipótese estrutural.

**`temperature=0` adicionado em `perguntar_ao_modelo()` (achado real,
2026-08-25).** Faltava — só existia no map-reduce já removido. Sem isso, a
MESMA pergunta com o MESMO contexto dava respostas diferentes entre uma
chamada e outra (testado: uma chamada leu "150 sertanejos, dez mortes,
dezesseis feridos" certo; a chamada seguinte, idêntica, perdeu a distinção
jagunços/soldados e confundiu mortos com feridos). Com `temperature=0` a
resposta ficou estável e reproduzível entre chamadas — não corrige limite de
leitura do modelo, mas elimina a variação por sorte de amostragem.

**VRAM medida com as 3 rotas (RTX 4070, 12,28 GB, 2026-08-25):** principal
sozinho em `num_ctx=32768` usa 9,1 GB; junto com o embedding (nomic-embed-text,
0,3 GB) — os dois que uma pergunta em rota ampliada usa ao mesmo tempo — dá
11,0 GB, ~1,0 GB livre (justo, mas cabe). **NÃO cabe junto com o auxiliar**
(llama3.2:3b, 4,1 GB): 9,1+4,1 = 13,2 GB estoura os 12,28 GB — confirmado
testando na prática: o Ollama descarrega um modelo pra abrir espaço pro outro.
Como o auxiliar só é usado por `resumir_arquivo()`, isso só custa uma recarga
de modelo (mesmo tipo de custo que já existe ao trocar de tarefa) se um resumo
e uma pergunta de rota ampliada acontecerem em sequência próxima — não é
problema de correção da rota ampliada isolada.

**Limite conhecido aceito, não perseguido (achado real, 2026-08-25, mesmo
teste de Uauá):** mesmo com retrieval correto (verificado isolando o trecho
sozinho, fora do resto do contexto) e com `temperature=0`, o llama3.1:8b
consistentemente omite um item ("os dois guias") de uma enumeração de 4 itens
dentro de um trecho entre travessões duplos ("as dez mortes -- um alferes, um
sargento, seis praças e os dois guias -- e dezesseis feridos"). Investigado a
fundo antes de aceitar (não foi só "adicionar instrução e seguir"):
- Testado se era o trecho isolado vs. contexto cheio (diluição de atenção):
  **mesmo erro isolado** — não é diluição, é leitura mesmo.
  Testado se era o travessão OU o enquadramento binário da pergunta
  ("soldados e jagunços"): nenhuma combinação (com/sem travessão × pergunta
  binária/neutra) acertou TODOS os números da frase ao mesmo tempo — cada
  variação trocou qual número saía errado, sem eliminar erro nenhum.
- Testado instrução explícita no prompt ("preserve todos os itens da
  enumeração, não resuma") — **não corrigiu a omissão**, e piorou outro número
  na mesma resposta. Confirma que não é o modelo "decidindo" resumir por
  estilo (o que uma instrução resolveria) — é falha de leitura genuína numa
  frase com múltiplos números aninhados, teto de capacidade do modelo, mesma
  categoria do limite já aceito com a Odisseia acima.
- **Decisão do usuário (2026-08-25)**: aceitar essa omissão específica como
  preferível a arriscar errar o número maior/mais importante da resposta
  (150 jagunços) — não vale a pena continuar iterando prompt pra um teto de
  leitura que já foi isolado e não responde a instrução.

**Bug de fragmentação em `dividir_em_subperguntas()` (achado real, 2026-08-25,
testando um datasheet de CI — Texas Instruments CD4051B/52B/53B).** Função
pré-existente (não tocada no rework até então), separada da Camada 1-3:
decide se uma pergunta tem "mais de um tópico" por classificação de LLM
(padrão sintático: vírgula/"e" entre nomes). Pergunta "quais os estados de
INHIBIT, C, B e A para ativar o canal 5?" virou 4 sub-perguntas, uma por
sinal — cada uma perdendo o resto do contexto (INHIBIT sozinho nem menciona
mais "canal 5"), e nomes de sinal de uma letra (A, B, C) são genéricos demais
num datasheet cheio de tabela, então cada busca separada trouxe ruído. A
união das 4 buscas estourou o teto ampliado (149 mil caracteres), quando a
pergunta inteira, buscada de uma vez, ficava em 7.898 caracteres.

**Correção:** em vez de ensinar mais casos por exemplo de prompt (mesmo
padrão de patch-atrás-de-patch já evitado na Camada 3 — ver
[[feedback_evitar_prompt_como_reflexo]]), `responder_pergunta()` agora MEDE
se as sub-perguntas geradas apontam pro mesmo lugar do documento
(`melhor_posicao_semantica()`, nova função em `perguntar.py`: sonda leve,
só `buscar_candidatos` + `cortar_por_relevancia`, sem o resto do pipeline).
Se a MAIORIA das sub-perguntas ativa mais forte dentro de um raio-limite
umas das outras, a divisão é descartada e a pergunta original inteira é
buscada de uma vez — maioria, não unanimidade, porque uma sub-pergunta pode
sair malformada (foi exatamente o caso do "INHIBIT" sozinho) sem que isso
signifique que o tópico é realmente outro. Só se aplica quando todas as
sub-perguntas resolvem pro MESMO arquivo; sub-perguntas de fontes/arquivos
diferentes (ex: "Google e YouTube", o caso original que motivou a função)
continuam pelo caminho de sempre, sem posição comparável entre si.

**Correção do raio-limite (achado real, 2026-08-25, "quantos soldados e
quantos jagunços morreram em Uauá?" — Os Sertões, 2.253 chunks).** A
primeira versão usava raio fixo (`JANELA_VIZINHANCA_LARGA * 2` = 16,
calibrado só contra o datasheet, 176 chunks) — mesma classe de bug do
limiar de vizinhança já corrigido antes (`LIMIAR_ATIVADOS_VIZINHANCA_*`,
ver "Segunda rodada de calibração da Camada 1" acima), só que esquecido
aqui: as duas sub-perguntas do Uauá convergiam a 19 de distância, o raio
fixo errou por 3. **Corrigido com o mesmo padrão piso+fração** já
estabelecido (`RAIO_FUSAO_SUBPERGUNTA_PISO`=16, `RAIO_FUSAO_SUBPERGUNTA_FRACAO`=2%,
`config.py`) — reconfirmado com o caso do Uauá (raio calculado 45, cobre a
distância real de 19) e com os 4 casos conhecidos (Polifemo, MCMV, Uauá,
datasheet) sem regressão. Ver [[feedback_interrogar_contraponto_antes_de_fechar]]
— o usuário pegou esse erro (calibrar um número só contra o caso que
motivou a correção, sem perguntar "e se o documento for maior?") como um
padrão a evitar sistematicamente, não só aqui.

**Extração de PDF achatava tabela — achado real, mesmo teste do datasheet,
2026-08-25.** Depois de corrigir a fragmentação acima, a pergunta do canal 5
ainda saía ERRADA (`INHIBIT=0, C=0, B=1, A=0` em vez de `0, 1, 0, 1`) mesmo
com o bloco certo entregue por completo — confirmado inspecionando o bloco:
a Table 7-1 (tabela-verdade binária, 5 colunas × 26 linhas) estava lá,
correta, mas `extrair_texto_pdf()` (`indexar.py`) usava só `page.get_text()`,
que acha a tabela numa sequência LINEAR de números, sem estrutura de coluna
nem linha — o modelo não consegue reconstruir sozinho qual número pertence a
qual coluna. Testado e descartado como limite de modelo antes de aceitar:
- Mesma tabela em markdown (`page.find_tables().to_markdown()`) — **ainda
  errou**, formato de tabela per se não bastou.
- Mesma informação em prosa manual ("Se INHIBIT=0, C=1, B=0, A=1, então o
  canal ativado é o canal 5") — **acertou**.
- Formato genérico "Linha N: cabeçalho=valor" (não específico desta tabela,
  gerável de QUALQUER tabela detectada) — **acertou**, inclusive gerado
  automaticamente com cabeçalho imperfeito (coluna mesclada virou "col1")
  e numa pergunta diferente da testada antes (canal "cy" do CD4053B).

**Correção:** `extrair_texto_pagina_pdf()` (nova, `indexar.py`) roda
`pagina.find_tables()` por página; região identificada como tabela (mínimo
2 colunas × 3 linhas de dado, pra reduzir falso-positivo em lista com
marcador/recuo) vira prosa "Linha N: campo=valor" via `tabela_para_prosa()`
— linha com um só valor preenchido vira `[Seção: X]` (preserva contexto de
sub-cabeçalho, ex: qual variante do chip aquele bloco de linhas descreve).
Resto da página (texto fora da bbox da tabela) continua por `get_text()`
normal — testado que prosa comum (parágrafo técnico, lista de bullets) não
regride. **Diferente do limite aceito do Uauá acima**: aquele é prosa corrida
mal-lida (frase densa entre travessões, sem tabela nenhuma pra `find_tables()`
achar); este é tabela de verdade mal-extraída — categorias diferentes, uma
foi aceita como teto de modelo, a outra tinha correção estrutural real.

**`VERSAO_PIPELINE` subiu pra "v5-com-tabela"** pra forçar reindexar todo PDF
já catalogado com a extração nova — não só o datasheet que motivou o achado.

**Limpeza de código:** `extrair_resposta_do_bloco()`, `consolidar_extracoes()`,
`consolidar_grupo_intermediario_cobertura()`, `selecionar_blocos_com_teto()` e
`responder_por_cobertura()` (map-reduce original) foram DELETADAS de
`perguntar.py`, não só desativadas. Import de `MODELO_LLM_AUXILIAR` também
removido de `perguntar.py` (não é mais usado ali — só `resumir.py` usa o
auxiliar).

### Filtro de isolamento: tentativa de afrouxar por tamanho, TESTADA e REVERTIDA (2026-08-25)

**Achado que motivou:** pergunta ampla ("os animais da fazenda", Revolução
dos Bichos) ativava candidatos genuinamente espalhados pelo livro inteiro
(tema pervasivo, sem "lugar certo" pra ancorar), mas o filtro de isolamento
(que só confia em candidato semântico perto de âncora literal) descartava
75% deles — sobrava um recorte pequeno e enviesado (só o início do livro,
fase feliz pós-revolução), e o modelo respondia com confiança total uma
narrativa **factualmente invertida** ("os animais estavam felizes e
prósperos" — o oposto do final real do livro).

**Investigação (nível a nível, com dado real, não suposição):** rastreei a
pipeline inteira pra achar onde a perda acontecia — foi o filtro de
isolamento mesmo, não outro passo. Tentei achar uma métrica geométrica
("convergência" entre âncora literal e melhor candidato semântico) pra
distinguir esse caso do caso Polifemo (onde o mesmo filtro funciona
corretamente, isolando o episódio certo). **Testei com 60 perguntas reais
em 4 documentos diferentes** (livro amarelo, Revolução dos Bichos, Os
Sertões, datasheet de CI — 15 perguntas cada, rotuladas "estreita"/"ampla"
por construção): nenhuma métrica testada (âncora-no-pool-bruto, dispersão
das âncoras entre si, taxa de descarte) separou os dois grupos de forma
confiável — médias praticamente idênticas entre estreita e ampla. **Não
propor de novo essa linha de classificação geométrica** sem um sinal novo
que ainda não foi tentado.

**Tentativa de correção sem classificar:** em vez de prever se uma pergunta
é estreita ou ampla, tentei sempre construir o contexto SEM o filtro de
isolamento primeiro; só aplicar o filtro quando o material sem filtrar não
coubesse nem no teto ampliado (Camada 2) — cortar só por necessidade de
tamanho, nunca por suposição de que o candidato solto é ruído.

**Testado ponta a ponta contra os 4 casos conhecidos e REVERTIDO**: Bichos
melhorava de fato (parou de inventar o final feliz), mas **Polifemo
regrediu** — sem o filtro, a resposta passou a incluir "Ulisses dá uma
poção que transforma os companheiros em porcos" (contaminação da Odisseia
real, mas do episódio da Circe, não do Polifemo) — exatamente o tipo de
mistura entre episódios parecidos que o filtro foi criado pra evitar (caso
original: contaminação com o episódio de Proteu). Medir só TAMANHO não
captura esse risco de CONTEÚDO relacionado. Revertido pro comportamento
original (filtro sempre aplicado) — `reunir_contexto()` voltou a ser como
estava antes desta tentativa.

**Estado atual: Bichos RESOLVIDO como efeito colateral (2026-08-25),
reconfirmado com 6 rodadas.** A tentativa de afrouxar o filtro por tamanho
(acima) foi revertida e NÃO foi o que resolveu — a correção real veio de
outra frente, feita depois: as correções de busca gramatical/entidade (NER,
prioridade de entidade, refino por proximidade, ver seções abaixo). Testado
com 3 rodadas idênticas de "como os animais da fazenda estão vivendo depois
da revolução?" (determinístico, sempre o final real — tirania crescente,
cooperação com humanos) + 3 reparafraseações (nenhuma inverteu o fato,
mesmo variando em completude). Ver `PENDENCIAS.md` pro detalhe.

**Achado colateral, mesmo Uauá usado pra testar isso**: no processo, achei
e corrigi um bug real e separado — o raio de fusão de sub-perguntas usava
limiar fixo em vez de escalar com o tamanho do documento (ver correção
registrada acima, na seção do bug de fragmentação). Mesmo com isso corrigido,
a pergunta do Uauá pelo pipeline completo continuou quebrada por mais uma
rodada de causas próprias — ver "Prioridade de entidade nomeada (NER) e
refino por proximidade" logo abaixo, que fecha essa história.

### Busca literal por análise gramatical (achado real, 2026-08-25)

**O que motivou:** rastreando a pergunta combinada "quanto o Brasil gasta
com o MCMV e quais são os cinco pilares do AgroBrasil 2030?" (ver achado
acima), a parte do AgroBrasil vinha sempre errada — mesmo sozinha, sem
combinar com nada. Rastreio nível a nível achou a causa: `cortar_por_relevancia`
mantinha só 1 candidato (chunk certo, margem semântica enorme — 0,295 vs
0,466 do segundo colocado); `buscar_por_termo_literal()` achava "pilares do"
como âncora em DOIS trechos sem nada a ver (mesma construção retórica
"pilares do X" reaproveitada em outros capítulos: "pilares do pensamento
liberal", "pilares do direito à saúde"); o filtro de isolamento então
descartava o chunk CERTO (longe dessas âncoras erradas) e mantinha os dois
ERRADOS (literal nunca é descartado). Resultado: a resposta final nunca via
a página certa.

**Causa raiz do "pilares do" ser uma âncora ruim**: a busca literal por
n-grama de tamanho fixo não sabe se o pedaço que bateu é uma frase de
verdade ou um fragmento cortado no meio — "do" fica solto de "AgroBrasil"
só por causa de onde o corte de N palavras caiu, não porque a gramática
manda. "Cinco pilares" e "AgroBrasil 2030" são frases completas; "pilares
do" sozinho não é.

**Correção — análise de dependência gramatical de verdade**, não mais corte
por tamanho: `frases_ancora_por_dependencia()` (nova, `perguntar.py`) usa
`spacy` com o modelo `pt_core_news_lg` pra montar a árvore gramatical da
pergunta e gerar candidatos a âncora a partir dos substantivos/nomes
próprios e suas combinações de modificadores reais (nunca separando uma
preposição do que ela liga — "do" nunca fica solto de "AgroBrasil" numa
árvore de dependência, mesmo que fique solto numa janela de N palavras).
`buscar_por_termo_literal()` tenta isso primeiro; só cai pro método antigo
de n-grama se a árvore não fechar numa raiz só (pergunta mal formada/
fragmento sem verbo, ex: "uauá quantos jagunços mortos") ou não achar nada
— nunca perde a rede de segurança antiga, só usa uma melhor primeiro.

**Por que `lg` e não `sm`** (o modelo pequeno, já usado antes só pra
stopwords): testado contra pergunta mal formada de propósito — `sm` quebrou
2 de 3 casos difíceis (árvore com mais de uma raiz), `lg` só 1 (e esse 1 é
uma frase genuinamente sem verbo, nenhum modelo resolveria isso). Custo:
568MB de download (não disputa VRAM da GPU, roda em CPU) e ~7s de
carregamento na inicialização (não por pergunta — o modelo carrega uma vez
só). Registrado em `requirements.txt`.

**Reconfirmado sem regressão** contra os casos já validados: MCMV sozinho
(sem mudança), Polifemo (mesmo teto de leitura já aceito, não piorou),
datasheet canal 5 (retrieval confirmado correto via inspeção direta do
bloco — erro que apareceu é do mesmo teto de leitura do modelo já
documentado, não da busca literal). A pergunta combinada MCMV+AgroBrasil
agora sai completa e correta nos dois.

### Prioridade de entidade nomeada (NER) e refino por proximidade (achado real, 2026-08-25)

**O que motivou:** mesmo depois da correção gramatical acima, "quantos
soldados morreram e quantos jagunços morreram no primeiro combate, em
Uauá?" continuava errando — de um jeito NOVO. "no combate" (preposição +
substantivo comum) e "primeiro combate" (adjetivo + substantivo) empatavam
em tamanho e entravam JUNTOS no mesmo nível gramatical; a união dos dois
batia em 3 trechos de OUTRAS batalhas do livro, nenhuma delas Uauá — mesma
classe de erro do "pilares do" (frase genérica reaproveitada em vários
lugares), só que desta vez pelo lado do empate de nível, não do corte por
tamanho.

**Correção 1 (densidade de conteúdo)**: `_densidade_conteudo()` desempata
por fração de palavras não-stopword — "primeiro combate" (100% conteúdo)
vence "no combate" (50%, "no" é stopword). Resolveu o empate, mas expôs o
problema seguinte.

**Correção 2 (nível de entidade nomeada)**: mesmo com densidade certa,
"primeiro combate" (substantivo comum, se repete em várias batalhas do
livro) e "Uauá" (nome de lugar, único no livro — spaCy reconhece via NER,
`doc.ents`) tinham tamanho/densidade parecidos e podiam entrar no mesmo
nível. Um nome próprio reconhecido é sempre mais específico que substantivo
comum do mesmo tamanho — `frases_ancora_por_dependencia()` passou a ordenar
`eh_entidade` como critério MAIS alto, antes de tamanho e densidade.

**Bug introduzido por essa correção 2 (pego antes de fechar, não pelo
usuário em produção)**: como a busca para no primeiro nível não-vazio, e o
nível de entidade agora vem sempre primeiro, "Uauá" sozinho (25 menções
espalhadas pelo livro inteiro, a maioria sem relação com o combate) passou
a bastar pra parar a busca — "primeiro combate" nunca chegava a ser
considerado. Resultado: contexto grande demais (`excede_limite`, recusa
honesta) em vez de resposta errada — mais seguro que antes, mas ainda
incorreto.

**Correção final — hierarquia entidade-primeiro, conteúdo-como-refino**
(desenho do usuário): entidade nomeada (Uauá = ONDE) decide o universo de
busca; termo de conteúdo comum (combate = O QUE aconteceu) NUNCA vira
âncora independente quando existe entidade na pergunta, mas REFINA os
achados da entidade por proximidade — um chunk de Uauá perto de um chunk de
"combate" é estritamente melhor que um chunk de Uauá isolado. Implementado
em `buscar_por_termo_literal()`: acha o nível de entidade primeiro; se
achar, tenta refinar pelos níveis de conteúdo (raio de proximidade
reaproveita `RAIO_FUSAO_SUBPERGUNTA_PISO/FRACAO`, já calibrado neste mesmo
livro pra distância de convergência entre termos relacionados); se o refino
achar algo, é o resultado ideal; se não achar nada perto, cai pra entidade
pura sem refino (aceitável); conteúdo comum só volta a valer como âncora
independente quando NÃO há nenhum nível de entidade na pergunta (mesmo
quando a entidade existe mas não bate em nada literalmente — caso raro,
variação ortográfica — ainda assim não usa conteúdo sozinho, cai pro
n-grama antigo).

**Resultado no caso Uauá**: de 25 chunks (entidade sozinha, `excede_limite`)
pra 10 chunks (refinados por proximidade a "no combate"/"primeiro combate"),
resposta final correta e verificada contra o texto fonte: "150 sertanejos
(jagunços) foram mortos e dezesseis feridos da expedição... um alferes, um
sargento, seis praças e os dois guias também morreram."

**Reconfirmado sem regressão** contra os 4 casos de sempre (MCMV+AgroBrasil
combinado, Polifemo, datasheet canal 5) — todos corretos, nenhuma mudança
de comportamento. **MCMV sozinho continua caindo em `excede_limite`** ("Minha
Casa Minha Vida" é entidade única, sem termo de conteúdo pra refinar —
mesmo comportamento de antes desta correção, não é regressão nova, é
característica já conhecida do tema ser discutido no livro inteiro sem um
recorte natural; registrado como pendência separada, não bloqueia isto).

**Correção seguinte, mesma rodada (achado real, "quantos morreram dos dois
lados no combate de Uauá?" — reparafraseando a mesma pergunta pra bateria de
confirmação, não repetindo literal): o nível de entidade tinha o MESMO
problema que motivou toda essa seção. `_variantes_do_token()` gerava "de
Uauá" (com a preposição da pergunta) como candidato mais específico que
"Uauá" sozinho; "de Uauá" bateu, por coincidência, em UM trecho sem relação
com o combate ("...jagunço, que vinha pela estrada de Uauá...") e parou a
busca ali, descartando os 25 trechos reais. Causa: pra nome próprio, a
preposição que o liga ao resto da frase é acidente de como a PERGUNTA foi
escrita, nunca parte do nome da entidade — diferente de adjetivo/numeral em
substantivo comum, que É parte do que restringe o sentido ("cinco pilares"
vs "pilares" quaisquer). Corrigido: entidade nomeada exclui a relação `case`
(preposição) dos modificadores considerados; substantivo comum continua
igual.**

**Bateria de confirmação (2026-08-25, pedida pelo usuário antes de aceitar
"resolvido")**: 4 rodadas com a pergunta original idêntica — mesma resposta
nas 4, sem intermitência. 3 reparafraseações do Uauá — 2 corretas
("quantas mortes houve entre soldados e jagunços" / "fale sobre as baixas
do primeiro combate"), 1 ainda falha ("quantos morreram dos dois lados no
combate de Uauá?", sem a palavra "primeiro"). Investigado a fundo: nem o
refino por conteúdo literal (a frase-âncora de conteúdo dessa reparafraseação
não bate perto do trecho certo) nem a posição semântica pura (testado
diretamente com `melhor_posicao_semantica()` nas 3 variantes — nenhuma
aponta pro cluster 863-887) acham o trecho certo. **Não é regressão nem
falta de teste — é limite estrutural** da mesma família do bug do Bichos
(pergunta ampla/temática): busca mecânica sem julgamento semântico de
verdade tem teto. Decisão do usuário: aceitar como limitação documentada,
não perseguir com mais heurística (a calibração das 60 perguntas já provou
que esse caminho não generaliza). **Regressões reparafraseadas também
testadas** (AgroBrasil, MCMV, datasheet canal 5, Polifemo — frases
diferentes das originais, não repetidas literalmente): todas corretas.

**Ideias registradas pra explorar depois, não implementadas ainda:**
- Usar a mesma limpeza gramatical (tirar a armação de pergunta — "quais
  são", "o que" — manter só o conteúdo) pra gerar um texto mais limpo pra
  embeddar na busca SEMÂNTICA também, não só na literal.
- Usar a árvore de dependência pra decidir mecanicamente se
  `dividir_em_subperguntas()` deveria separar duas cláusulas de verdade
  (sujeitos/verbos diferentes, ex: "quanto gasta com X e quais são os
  pilares de Y") de uma coordenação de substantivos dentro da MESMA cláusula
  (ex: "estados de INHIBIT, C, B e A") — substituindo a classificação por
  LLM que existe hoje (`dividir_em_subperguntas()`) por medição gramatical,
  Princípio central #2 aplicado a mais um ponto do funil.

### Próximo passo planejado, depois das 3 camadas (não começar antes)

**Achado durante a calibração da Camada 1 (usuário, 2026-08-24)**: "resumo vs
contagem vs pergunta" dentro de "Consultar+Documento" ainda é decidido por LLM
(`classificar_consulta_documento()`) — o mesmo padrão de "IA escolhendo entre
opções conhecidas" que o Princípio central #2 já baniu em outros pontos do
funil (arquivo/aba/pasta, item 12). Já estava registrado como pauta pendente
("Ideias do usuário", mais abaixo neste documento), mas ficou desconectado da
conversa do rework até esse momento.

**Desenho aprovado pelo usuário** para a sub-etapa de "Consultar+Documento"
(depois que o dropdown de arquivo já escolheu o documento):
- **Botão "Resumo"**, ao lado do dropdown — chama `resumir_arquivo()` direto,
  sem LLM decidindo se é isso que o usuário quer.
- **Caixa de termo/frase completa + botão "Procurar"**, abaixo — base é
  `contar_termo_no_arquivo()` (já existe), mas precisa de capacidade nova:
  contar por CHUNK (que já carrega `pagina` no metadado) em vez de no texto
  inteiro concatenado, pra poder informar **onde** o termo foi encontrado, não
  só quantas vezes.
  **Formato de saída decidido**: se o termo aparecer em **mais de 20 páginas
  diferentes**, informa só a quantidade de páginas; se forem **20 ou menos**,
  lista as páginas. Evita despejar uma lista longa pra termo comum, mas dá
  localização de verdade pra termo raro/específico.
- **Chat livre passa a significar só "pergunta"** — com resumo e contagem
  tirados pra controle mecânico, `classificar_consulta_documento()` deixa de
  ser necessário nessa combinação inteira: zero chamada de LLM só pra decidir
  rota.

**Por que depois das 3 camadas, não antes**: essa mudança é sobre a
INTERFACE (como o usuário chega até `responder_pergunta()`), não sobre o
motor de busca em si. Terminar Camada 2/3 primeiro evita retrabalho — melhor
desenhar a UI em cima do motor já completo do que precisar ajustar depois de
Camada 2/3 mudarem a assinatura de `responder_pergunta()`.

**Câmadas 2/3 concluídas em 2026-08-25 (ver "Status da Camada 2/3" acima) —
este item de UI está DESBLOQUEADO, é o próximo passo disponível.** A
assinatura de `responder_pergunta()` não mudou nesse redesenho (mesmos
parâmetros de antes), então nada aqui precisa ser revisto por causa da
mudança de motor.

**Ressalva técnica registrada na discussão**: "resumir o documento inteiro" e
"pergunta ampla que precisa de muita cobertura" não são a mesma coisa por
baixo, mesmo que as duas possam um dia passar pelo mesmo mecanismo de
map-reduce quando não cabem no contexto (Camada 3) — resumo quer o documento
**inteiro, sem filtro de relevância nenhum**; pergunta, mesmo ampla, continua
sendo filtrada por relevância à pergunta (mesmo que frouxa). Por isso
`resumir_arquivo()` continua como caminho próprio, não vira um caso particular
de `reunir_contexto()`.

### Ordem definida pelo usuário

1. ✅ Levantar o que é independente do rework — **nada bloqueia**
2. ✅ Registrar tudo aqui, antes de codar
3. Revisitar os scripts afetados, arquivo por arquivo
4. Implementar camada por camada, **testando a resposta real** a cada etapa

## Números medidos nesta sessão (NÃO refazer estes experimentos)

**Janela de contexto** (RTX 4070, 12GB) — adotado 16384:

| `num_ctx` | tempo | VRAM do principal | livre |
|---|---|---|---|
| 8.192 | 9,0s | 5,53 GB | 4.178 MB |
| 16.384 | 11,2s | 6,54 GB | 3.142 MB |
| 32.768 | 13,9s | 8,44 GB | 1.213 MB |

32k funciona (coube o `steam.pdf` inteiro), mas com os 3 modelos carregados dá
~11,6 GB de 12,28 GB — mesma armadilha que descartou o Qwen2.5:14b.

**Tamanho de chunk** (livro amarelo, acerto em 7 fatos de gabarito) — **manter 500**:

| chunk | trechos | acerto |
|---|---|---|
| 500 | 311 | 4/7 |
| 1000 | 148 | 4/7 |
| 1500 | 97 | **2/7** |
| 2000 | 72 | 4/7 |

**Vizinhança** (o que ataca a fusão) — o número que importa é **blocos**:

| config | fatos | blocos | caracteres |
|---|---|---|---|
| 15 × ±0 (atual) | 6/8 | **11** | 7.600 |
| 15 × ±2 | 7/8 | 6 | 25.774 |
| **8 × ±2** | **7/8** | **4** | 15.358 |
| 6 × ±4 | 7/8 | 3 | 18.712 |

**Custo de map-reduce:** ~9s por bloco (base: resumo do `steam.pdf`, 9 blocos em
80s).

## Item 21 (M1) — localizar a seção de um documento sobre um tema

**✅ Resolvido em 2026-08-25, como efeito colateral do rework de Camada 1-3 —
ver o registro completo (caso, experimentos, medições) na seção "M1" dentro de
"Achados da auditoria de coerência" mais abaixo.** Não repetir os experimentos
já registrados lá (densidade/concentração, índice de PDF, estilo de título de
DOCX, sumário em texto — todos testados e descartados em 2026-08-22). O método
que resolveu é justamente a direção que já tinha sido identificada como
promissora então ("busca semântica + contiguidade") e que o rework de Camada
1-3 implementou por completo, sem ter sido desenhado especificamente pra isso.
Reconfirmado em 2026-08-25 contra o caso canônico (`livro-amarelo-resumo-2026.pdf`,
capítulo "PRENDEU, MATOU?"): tanto a pergunta pelo **rótulo** ("o que o livro
conta sobre segurança pública?") quanto pelo **conteúdo** ("o que o livro diz
sobre violência e crime organizado?") agora acertam o capítulo certo — o caso
que falhava antes (rótulo) passou a funcionar sem nenhuma mudança feita
especificamente para ele.

## Veredito do B4 (conferido contra o livro)

Todos os 13 temas citados **existem** no livro — nada foi inventado do nada. Mas
**duas afirmações estão distorcidas** por fusão de trechos verdadeiros de páginas
diferentes (detalhe completo na seção "Achados da 1ª bateria de testes humanos").
Isso promoveu o **item 14 (self-check)** a prioritário, junto com o item 21.

*(Perfil do usuário e forma de trabalho: ver Parte 2, no topo do
documento — removido daqui pra não duplicar.)*

### Origem dos princípios centrais, objetivo original, e primeira versão do pipeline

*(Objetivo, os 2 princípios centrais, modelos, setup, estrutura de
arquivos e pipeline atuais já estão na Parte 1 — o que segue aqui é só o
**raciocínio histórico** de como o Princípio central #2 nasceu, preservado
porque explica o PORQUÊ por trás da regra.)*

**Como o Princípio central #2 nasceu**: tentativas de fazer a IA
"entender" qual arquivo/aba o usuário queria a partir de texto livre
(mesmo com histórico da conversa disponível) geraram uma sequência de
bugs no mesmo dia (2026-08-20) — nome de arquivo com palavra de conexão a
mais não batendo ("tarefa de matemática" vs "TAREFA MATEMATICA.xlsx"),
nome de aba confundido com nome de planilha, filtro confundindo o termo
da pergunta com nome de coluna auxiliar — e cada tentativa de correção
(few-shot, prompt mais genérico, modelo maior) só trocava o bug de lugar,
nunca eliminava a classe inteira do problema. Também testado trocar pra
um modelo maior (Qwen2.5:14b) especificamente pra essa tarefa de
reformulação por histórico — melhorou parcialmente a qualidade em alguns
casos, mas nem chegou a resolver o bug mais grave (confusão de coluna),
ficou 2-9x mais lento por chamada, e ocupou a VRAM inteira da GPU (12,4GB
de 12,28GB), inviabilizando os outros modelos do projeto (auxiliar +
embedding) rodarem juntos. Ou seja: nem o modelo maior resolveu de
verdade — reforça que o problema é estrutural (deixar a IA escolher), não
de capacidade do modelo.

## Decisões técnicas importantes (e por quê)

- **Chunking simples por caractere, não por biblioteca pronta**: decisão
  deliberada de não usar LangChain/LlamaIndex no início, pra entender o
  funcionamento sem abstração escondida. Pode migrar depois se o projeto
  crescer e ficar repetitivo.
- **`num_predict: 1024` e `num_ctx: 8192`**: valores padrão do Ollama cortavam
  respostas no meio. Ajustado para respostas completas.
- **Histórico limitado a 3 trocas**: evita que o prompt fique gigante e lento
  a cada pergunta. Pode ajustar se necessário.
- **Reformulação de pergunta antes da busca**: sem isso, perguntas de
  acompanhamento ("e ele, o que mais?") buscavam errado no banco vetorial,
  porque a busca usava só a última frase, sem saber a quem "ele" se referia.
  Instrução reforçada para só trocar pronomes, sem elaborar/adicionar
  informação nova (evita "contaminar" a busca com contexto irrelevante da
  troca anterior).
- **Prompt instrui a IA a nunca opinar, só responder com base no contexto**:
  proposital, para não confundir opinião gerada com fato do documento
  (relevante especialmente para o PDF de propostas políticas).
- **Resumo de documento inteiro via map-reduce, não RAG**: buscar top-N
  chunks não é adequado para "resuma o documento inteiro", porque N chunks é
  uma fração pequena do total. Solução: resumo hierárquico — agrupar chunks
  em blocos (15 chunks por bloco), resumir cada bloco, depois sintetizar os
  mini-resumos num resumo final. Agrupamento maior escolhido para reduzir
  número de chamadas ao modelo, mantendo o mesmo modelo principal.
- **Documentação centralizada dentro do projeto, em subpasta própria**:
  `ARQUITETURA.md` fica em `jarvis-pessoal/Planos/` — facilita levar tudo
  junto (código + documentação) numa única cópia da pasta pra pen
  drive/outro PC. Deve continuar sendo subido ao Project Knowledge do
  Claude também, não só salvo localmente, pra persistir entre conversas.
- **Extração de PDF migrada de `pypdf` para `PyMuPDF` (fitz)**: `pypdf`
  falhava em PDFs com fontes de codificação não-padrão (ex: Odisseia,
  retornava `/uni0048/uni004F...` em vez de texto legível). PyMuPDF
  resolveu sem necessidade de OCR — o problema era de decodificação de
  fonte, não de ausência de texto.
- **Indexação incremental versiona o pipeline, não só o conteúdo**: hash de
  arquivo sozinho não detecta quando o *método* de processamento muda (nova
  biblioteca, chunking diferente, novo campo de metadado). Campo
  `pipeline_versao` nos metadados — reprocessa se hash OU versão
  divergirem. Ao mudar algo estrutural no pipeline, incrementar essa
  constante força reindexação automática sem apagar o banco manualmente.
- **Embeddings gerados em lote (batch), não um por um**: chamada HTTP
  individual por chunk criava overhead alto em documentos grandes (ex:
  Odisseia, ~1000 chunks). Migrado para o endpoint `/api/embed` do Ollama,
  que aceita lista de textos por chamada. Lote atual: 50 chunks/requisição.
- **Fontes estruturadas usam campo `fonte` nos metadados**: reaproveita o
  mesmo pipeline de chunk→embedding→ChromaDB já validado com PDFs, em vez
  de sistema paralelo. Cada chunk ganha `fonte` (ex: "documento",
  "historico_navegacao") pra permitir filtrar buscas por tipo.
- **Histórico de navegador (Chromium-based) lido via cópia do arquivo
  SQLite**: o arquivo `History` fica travado enquanto o navegador está
  aberto, por isso o script copia pra um arquivo temporário antes de ler.
  Navegador: Brave, caminho em
  `~\AppData\Local\BraveSoftware\Brave-Browser\User Data\Default\History`.
  Timestamps usam formato não-padrão (microssegundos desde 1601) —
  conversão implementada em `converter_timestamp_chrome()`.
- **Config centralizado em `config.py`, importado pelos scripts**:
  `indexar.py`, `perguntar.py` e `resumir.py` migrados (usam
  `from config import (...)` em vez de duplicar constantes).
- **Limitação identificada: RAG depende do tipo de texto da fonte**: testado
  com a Odisseia — perguntas do tipo "quem é X" falham não por erro do
  sistema, mas porque textos narrativos clássicos ("in medias res") não
  contêm trechos definicionais explícitos sobre personagens, só menções em
  cena. Documentos expositivos não sofrem desse problema. Solução possível
  (não implementada): indexar fonte complementar (sinopse/verbete).
- **Prompt principal generalizado para multi-fonte**: rótulo genérico
  "CONTEXTO" (em vez de "CONTEXTO DOS DOCUMENTOS"), explicando que pode vir
  de documentos ou atividade do usuário, e instruindo a interpretar com bom
  senso (sinônimos/paráfrases), sem exigir correspondência exata de
  palavras. Trade-off: abre espaço para inferência do modelo — segue
  transparente ao marcar como suposição, mas vale monitorar.
- **Filtro de busca por fonte (`fonte: documento` vs
  `fonte: historico_navegacao`)**: sem esse filtro, perguntas sobre
  histórico podiam recuperar chunks de PDF por coincidência de
  palavra-chave. Resolvido com classificação via LLM antes da busca
  (`detectar_fonte`), aplicando `where` no ChromaDB. Classificação via
  modelo escolhida em vez de lista de palavras-chave fixas, por ser mais
  robusta a erro de digitação e formas variadas de perguntar.
- **RAG não serve para tarefas de contagem/agregação exata**: perguntas como
  "quantas vezes X aparece" exigem cobertura total do texto. Solução:
  função separada que conta ocorrências via código Python direto sobre o
  texto completo do arquivo, sem passar pelo LLM. Ressalva: sobreposição
  entre chunks pode causar pequena contagem duplicada nas bordas.
- **Contagem exata exige termo exato, por design**: `contar_termo_no_arquivo`
  não interpreta sinônimos/variações do termo buscado ("jones" ≠ "sr
  jones") — decisão deliberada, pra não comprometer a confiabilidade do
  número exato. Flexibilidade fica restrita à localização do arquivo
  (nome), não ao termo contado.
- **`jarvis.py` criado como porta única de entrada**: unifica `perguntar.py`,
  `resumir.py` e `catalogar_arquivos.py` num único chat. Classifica o
  pedido via LLM e roteia automaticamente para a função certa — usuário
  nunca escolhe manualmente script/modo.
- **Bug corrigido: `resumir_arquivo()` quebrava com fontes mistas no
  banco**: `colecao.get()` sem filtro trazia também histórico de navegação
  (sem campo `arquivo`), causando `KeyError`. Corrigido filtrando
  `where={"fonte": "documento"}`.
- **Escopo final do projeto (revisado — sem alteração de arquivos)**:
  assistente virtual único (via `jarvis.py`), com três capacidades centrais:
  1. **Zona geral** (todo o PC): localizar arquivos por nome/caminho/tipo,
     nunca ler conteúdo.
  2. **Zona controlada** (pasta específica): ler, consultar e resumir
     arquivos — PDF, TXT, Word, Excel, SQL/banco de dados (leitura apenas).
     Imagens fora de escopo (complexidade).
  3. **Consultas agregadas/analíticas sobre dados estruturados** (ex:
     "faturamento dos últimos 6 meses") — leitura e cálculo sobre
     planilha/SQL, não busca por similaridade.

  **Decisão revisada**: a capacidade de **alterar/apagar arquivos foi
  removida do escopo por ora**, para eliminar o risco de dano irreversível
  (ex: um `UPDATE`/`DELETE` mal interpretado em SQL de produção não tem
  "desfazer"). Compensação: a IA deve ser excelente em **identificar
  possíveis erros/inconsistências e apontar a localização exata** (arquivo,
  linha, célula, trecho) para que o usuário mesmo faça a correção. Trocamos
  "poder de execução" por "precisão de diagnóstico" — mais alinhado à
  filosofia original (IA identifica → humano decide → **humano executa**).
  Poder de escrita pode ser reconsiderado no futuro, com salvaguardas
  robustas (permissão só-leitura no banco, confirmação reforçada).
- **Capacidade de criação de arquivos (mantida)**: gerar arquivo **novo**
  (ex: tabela Excel a partir de dados indexados) não é "alterar" um arquivo
  existente — é saída nova, sem risco de sobrescrever dado já existente.
- **`LIMITE_ENTRADAS` do histórico aumentado de 500 para 4000**: cobertura
  anterior deixava de fora vídeos do YouTube mais antigos. Valor vive em
  `indexar_historico.py` (não centralizado no `config.py`).
- **Limitação: buscas por site nem sempre têm URL específica o suficiente**:
  YouTube inclui identificador do vídeo na URL, mas sites tipo Crunchyroll
  (aplicativo de página única) mantêm a mesma URL/título genérico
  independente do conteúdo assistido — limitação da fonte, não do sistema.
- **`indexar_historico.py` é incremental (evita duplicatas)**: antes de
  gerar embeddings, verifica quais IDs já existem no ChromaDB
  (`colecao.get(ids=...)`) e processa só entradas genuinamente novas.
- **Capacidade de transcrição de documento (planejada)**: hoje o sistema só
  resume (map-reduce) ou busca trechos (RAG) — falta devolver texto
  completo e literal, sem resumir. Peça técnica já existe parcialmente
  (`buscar_todos_chunks_do_arquivo()`).
- **Compactação de resposta longa na memória de conversa** — ✅ implementado em
  2026-08-20 (estava previsto desde cedo como "resumo de histórico em escala",
  com a nota "não relevante hoje"; virou relevante ao medir o tamanho real das
  respostas de listagem). `condensar_para_historico()` (`resumir.py`).

  **Vale para QUALQUER resposta longa do chat** — resumo de documento, resposta
  de pergunta (RAG), listagem de planilha ou de histórico. Não é uma solução
  para um formato específico.

  **Formato fixo (definido pelo usuário)**: resposta até 1000 caracteres é
  guardada **inteira**; acima disso vira **500 caracteres literais do início +
  até 500 de resumo da conclusão**. O que o usuário vê na tela nunca muda — a
  condensação afeta só o que vai dentro do prompt.

  **Por que "conclusão" e não "resumo genérico"** (razão do usuário, registrada
  porque foi mal-entendida uma vez): numa resposta longa — o exemplo dele foi o
  resumo de um livro — as duas pontas são o que importa, como o texto começa e
  a que conclusão chegou. O miolo é o que pode ser perdido. O formato serve aos
  dois extremos: em texto corrido, começo + desfecho; em listagem, cabeçalho +
  fecho.

  Medido em quatro formatos reais: parágrafo único de 2.803 → 582; vários
  parágrafos 2.807 → 582; listagem de navegação 3.772 → 717; resumo real do
  `steam.pdf` 2.234 → 642.

  **Janela mantida em 3 trocas, deliberadamente**: chegou a ser aumentada pra 6
  aproveitando a compactação, e o usuário reverteu com o argumento certo — não
  se aumenta a memória apoiando-se numa peça que erra (ver limitação abaixo).
  Janela curta + compactação como exceção é mais seguro que janela longa
  dependendo de resumo automático.

  **Por que resumir em vez de cortar nos primeiros N caracteres**: corte cego
  decapita justamente a parte que costuma importar (o fim de uma listagem, a
  conclusão de uma resposta). Daí o formato híbrido: início literal + fecho
  resumido, que cobre as duas pontas.

  **Por que a cabeça NÃO passa pelo modelo (correção determinística)**: a
  primeira versão mandava o texto inteiro pro modelo auxiliar com a instrução
  "PRESERVE o número exato". Ele perdeu o total ("Encontrei 853 entrada(s)") e
  **inventou "39 itens"**, contando as linhas visíveis — e como o histórico
  alimenta a resposta seguinte, esse número falso seria repetido como fato numa
  pergunta de acompanhamento. Corrigido tirando o começo do alcance do modelo,
  não com mais instrução: `separar_cabeca_literal()` copia o início palavra por
  palavra. O teto do trecho gerado também é aplicado **em código**, não só
  pedido no prompt. (Vale além de número: preserva literalmente a abertura de
  qualquer resposta.)

  **Bug corrigido no mesmo dia — a primeira versão não condensava texto
  corrido**: `separar_cabeca_literal()` cortava **só** em quebra de linha, o que
  funcionava em listagem (muitas linhas curtas) e falhava em silêncio
  justamente no caso que o usuário tinha em mente, o resumo de livro: num
  parágrafo único de 3.000 caracteres não havia quebra de linha dentro do
  limite, o parágrafo inteiro virava "cabeça", o corpo saía vazio e a função
  **devolvia o texto inteiro sem condensar nada** — sem erro, com o contexto
  seguindo estourado. Em texto de dois parágrafos, a "cabeça de 500" saía com
  1.500 caracteres. Corrigido com três níveis de fronteira de corte (quebra de
  linha > fim de frase > espaço entre palavras) e teto duro de 500. **Lição
  repetida**: implementar e testar só com o formato que motivou o bug (aqui,
  listagem) deixa passar o formato mais comum do sistema (texto corrido) — o
  mesmo padrão do episódio das capacidades apagadas.

  **Aviso do sistema não entra na memória (2026-08-20)**: avaliando a qualidade
  do texto gerado (e não só o tamanho), apareceu um erro real — o modelo fundiu
  um aviso do sistema com o conteúdo dos dados e gravou na memória *"a Datafolha
  divulga a primeira pesquisa cobrindo todos os 4000 registros da fonte"*. O
  "cobre todos os 4000 registros" era o aviso de consulta-sem-filtro, não algo
  dito por nenhuma fonte. Causa: resposta e aviso viravam uma string só, então
  metadado voltava como se fosse dado. Corrigido com `PREFIXO_AVISO` (`⚠`, em
  `texto.py`) marcando as linhas de aviso na formatação, e
  `remover_avisos_do_sistema()` tirando-as **antes** da condensação — os avisos
  nem chegam ao modelo, nem entram na cabeça literal. Na tela continuam
  aparecendo normalmente (e o marcador ainda serve de destaque visual).
  Colocado em `texto.py`, não em `consultar_dados.py`, pra não criar dependência
  de `resumir` → `consultar_dados`.

  **Cortar o preâmbulo do modelo foi proposto e RECUSADO pelo usuário**: o
  modelo às vezes prefixa o resumo com "Aqui está um resumo em 2 frases:",
  ocupando espaço numa memória de 500 caracteres. A correção sugerida era
  descartar em código a primeira linha quando ela termina em `:`. O usuário
  vetou, com razão: a regra casaria com conteúdo legítimo no futuro — um resumo
  que devolva "Total de vendas:\nR$ 5.000" perderia o rótulo e a memória
  guardaria o número sem dizer do quê. Troca ruim: o preâmbulo é ruído visível e
  barato (~30 caracteres), o corte errado é perda **silenciosa** de informação —
  exatamente a categoria de falha que o projeto evita. Fica como está.

  **Limitação residual conhecida**: o resumo do fecho ainda pode conter número
  contado pelo modelo. Pedir "a conclusão" em vez de "um resumo" reduziu muito
  o problema nos testes (parou de totalizar), mas não é garantia. O número que
  importa está protegido na cabeça literal, e o trecho gerado vem rotulado como
  `[resumo da conclusão]`. Validar os números do resumo contra o texto original
  foi considerado e **descartado**: não resolveria o caso observado, porque o
  "39" existe no texto — o errado é o significado, não o algarismo. Candidato
  natural ao item 14 (self-check).

  **Não confundir com o resumo que o usuário pede**: `resumir_arquivo()` →
  `resumir_bloco` (600) → `sintetizar_grupo_intermediario` (700) →
  `sintetizar_resumo_final` (1500, modelo **principal**) não tem teto de
  caracteres e não foi tocado — o limite de 500 vale **só** pra esta memória
  interna, que o usuário nunca lê. Há teste travando isso pra evitar que
  alguém aplique o teto no lugar errado no futuro.
- **Catalogador de arquivos (zona geral) implementado**: `catalogar_arquivos.py`
  usa SQLite (não ChromaDB) — busca por nome é comparação de texto direta
  (`LIKE` com normalização de acento/espaço/hífen/underscore), não busca
  semântica. Gerar embedding para todo arquivo do disco seria caro e
  desnecessário, já que a maioria das buscas de arquivo é por nome. Busca
  semântica fica reservada como possível fallback futuro.
- **Catalogação sempre revarre, sem apagar banco manualmente**:
  `garantir_catalogo()` roda a varredura das pastas configuradas toda vez
  que o usuário pede uma localização, usando `INSERT OR REPLACE` — atualiza
  o que mudou, sem duplicar. Custo baixo (só metadado, sem conteúdo).
- **Catalogador remove arquivos apagados/movidos (fantasmas)**: antes, só
  adicionava/atualizava, nunca removia — um arquivo apagado continuava
  aparecendo como resultado. Corrigido: `catalogar_pasta()` compara o que
  foi encontrado na varredura atual com o que já estava no banco para
  aquela pasta, e remove (`DELETE`) o que não foi reconfirmado.
- **`extrair_termo_arquivo` precisou de exemplo explícito no prompt**: sem
  exemplo, o modelo às vezes traduzia o termo pro inglês (ex: "revolução" →
  "Revolution") ao extrair da mensagem. Mesmo padrão de correção (few-shot)
  já usado em `extrair_termo_e_arquivo`.
- **`PASTAS_CATALOGADAS` centralizado no `config.py`**: lista de pastas que
  a zona geral tem permissão de varrer (hoje: Área de Trabalho e `Docs`).
  Zona geral nunca lê conteúdo, só metadado.
- **Campo `origem` adicionado ao histórico de navegação**: cada entrada
  guarda de qual PC/máquina veio (`IDENTIFICADOR_MAQUINA` no `config.py`,
  ex: "pc-casa"). Objetivo: permitir múltiplos PCs indexando no mesmo banco
  sem misturar irreversivelmente a origem. Entradas indexadas *antes* dessa
  mudança não têm o campo — histórico existente foi apagado e reindexado
  do zero para garantir consistência.
- **Tag de origem precisou ser explicada no prompt pra ser usada**: só
  anexar `[origem: pc-casa]` no texto do chunk não bastou — o modelo
  ignorava a tag sem instrução explícita em `montar_prompt`.
- **`indexar_historico.py` nunca apaga entradas antigas, só adiciona**: se
  rodado em PCs diferentes ao longo do tempo, o histórico de todos os PCs
  se acumula no mesmo banco, sem remoção automática (evita apagar dados
  válidos só por estarem fora do recorte de `LIMITE_ENTRADAS`).
- **`QUANTIDADE_CHUNKS` aumentado de 10 para 15**: mais contexto por busca,
  custo de lentidão pequeno e proporcional (mesmo modelo, só mais texto de
  entrada).
- **Limite real de "cobertura tipo livro inteiro" em hardware local**: RAG
  com contexto grande (estilo API Google/VPS) não é o caminho local — VRAM
  (12GB) é o teto físico de modelo+contexto simultâneo. Para documento
  inteiro, a ferramenta certa é o map-reduce, não aumentar
  `QUANTIDADE_CHUNKS` ao extremo. Reranking (buscar mais candidatos,
  filtrar os melhores) fica como possível melhoria futura.
- **Limitação: perguntas de listagem/cronologia sobre histórico falham com
  RAG por similaridade**: perguntas como "o que assisti no YouTube" ou "o
  que vi no dia X" não são bem servidas por busca semântica — RAG recupera
  só os N chunks "mais parecidos", sem noção de ordem cronológica real nem
  garantia de cobertura completa de um período. Mesma categoria de
  limitação já identificada com contagem exata e resumo — ferramenta
  errada, não falha do modelo. Solução: estender consultas estruturadas
  (fila) para cobrir também histórico de navegação — consulta direta ao
  SQLite/dados brutos, filtrando por data/fonte e ordenando
  cronologicamente, em vez de busca vetorial.
- **Estratégia de indexação: configurável pelo usuário, três modos
  possíveis (planejado)**: hoje, `indexar.py` e `indexar_historico.py`
  precisam ser rodados manualmente. Já são incrementais (pulam o que não
  mudou), mas ainda exigem ação do usuário. Nenhum modo único serve bem a
  todos os cenários de uso, então a decisão é deixar **configurável no
  `config.py`**, com três modos possíveis:
  1. **Ao iniciar** (`sempre_reindexar_ao_abrir`): roda a checagem toda vez
     que `jarvis.py` inicia — simples, bom para uso pessoal esporádico, mas
     soma um pequeno atraso a cada abertura (precisa ler cada PDF pra
     calcular hash).
  2. **Agendado** (`horario_indexacao_diaria`): roda uma vez por dia, em
     horário fixo configurável — melhor para cenário de servidor ligado
     continuamente (uso corporativo). Não é tempo real, mas evita
     reprocessamento a cada abertura e mantém custo previsível. Exigiria um
     mecanismo de agendamento rodando em paralelo ao `jarvis.py` (ex: tarefa
     agendada do Windows, ou um loop com verificação de horário).
  3. **Sob comando manual no chat** (ex: "atualize o índice agora" /
     "reindexe"): categoria nova no roteador do `jarvis.py`, chamando
     `indexar.py`/`indexar_historico.py` diretamente na hora. Mais simples
     de implementar que o modo agendado (não precisa de scheduler
     separado), dá controle total e imediato ao usuário, mas depende dele
     lembrar de pedir.

  Nenhum desses modos é mutuamente exclusivo — o sistema pode, por exemplo,
  ter um modo padrão (ex: agendado) **e** ainda aceitar o comando manual
  como forma de forçar atualização fora do horário programado. Nenhum dos
  três está implementado ainda; ordem de implementação sugerida: comando
  manual primeiro (mais simples, maior controle imediato), agendamento
  depois (mais relevante quando o uso for mais contínuo/corporativo).

  **Importante**: essa necessidade não se aplica ao catalogador de arquivos
  (`catalogar_arquivos.py`), que já revarre a cada pedido de localização —
  por ser só metadado (sem embedding), o custo é desprezível, diferente de
  `indexar.py`/`indexar_historico.py` (que geram embedding, custo real).
- **Interface híbrida em Streamlit implementada (`interface.py`)**: chat
  livre (reaproveita `processar_mensagem()`, extraído do `jarvis.py` pra ser
  chamável tanto pelo terminal quanto pela interface) + barra lateral com 4
  ações rápidas (resumir documento, localizar arquivo, contar termo, ver
  histórico recente) que chamam as funções direto, sem passar pelo
  classificador. Upload de arquivo pra zona controlada ainda não
  implementado.
- **Consulta estruturada genérica implementada (`consultar_dados.py`)**:
  substitui o padrão de "uma função pontual por tipo de pergunta sobre dado"
  (ex: `contar_termo_no_arquivo`, que só conta string literal em texto) por
  uma ferramenta única — `consultar_dado_estruturado(pergunta, fonte,
  colecao)` — cobrindo contagem, listagem, soma e média sobre dados
  tabulares, com filtro/ordenação/limite. Escopo inicial: só
  `historico_navegacao` (única fonte genuinamente estruturada que existe
  hoje — planilha/SQL da zona controlada, itens da fila, ainda não
  implementados). Corresponde ao item "consultas estruturadas/agregadas"
  já previsto na fila, generalizado numa ferramenta só em vez de uma função
  por caso.
- **LLM traduz a pergunta num JSON de especificação, nunca gera/roda código
  livre**: `extrair_especificacao_consulta()` pede ao modelo um JSON
  (operação, filtros, coluna-alvo, ordenação, limite) que o código Python
  interpreta com uma lista fixa de operadores — nunca `eval` de pandas/SQL
  gerado pela IA. Mesmo padrão já usado em `extrair_termo_e_arquivo` (LLM
  extrai campos estruturados, código decide/executa) — mantém a filosofia
  "IA identifica, sistema executa com precisão" e evita alucinação de
  número.
- **Metadados do histórico de navegação ganharam `titulo` e
  `timestamp_chrome`**: a `data_visita` existente é uma string já formatada
  (`dd/mm/aaaa`), que ordena errado como texto (ordenação alfabética ≠
  ordenação cronológica — ex: "01/12" viria antes de "15/01"). O
  `timestamp_chrome` (int bruto do Chrome, cronologicamente crescente)
  resolve isso pra qualquer consulta que precise de ordem cronológica real.
  Precisou de migração (apagar + reindexar `fonte=historico_navegacao`),
  mesmo padrão já usado pra adicionar o campo `origem`.
- **Classificador de pedidos precisou de exemplo de contraste explícito
  pra separar "consulta_estruturada" de "pergunta"**: sem isso, perguntas
  sobre ASSUNTO/tema pesquisado no histórico (ex: "o que eu pesquisei sobre
  X") caíam erroneamente na consulta estruturada (que faz filtro literal,
  não busca semântica) e voltavam "não encontrado" mesmo quando a
  informação existia via RAG. Resolvido com exemplos few-shot mostrando os
  dois casos lado a lado — mesmo tipo de correção já visto em outros
  extratores do projeto (ex: `extrair_termo_arquivo`).
- **Uso de modelo auxiliar/segunda IA reforçado como princípio permanente,
  não só pra tarefas mecânicas**: além de resumo intermediário e
  classificação (já documentado acima), o usuário reforçou (2026-08-18,
  duas vezes) que uma segunda chamada de IA — mesmo modelo ou modelo
  auxiliar — deve ser considerada sempre que ajudar na **velocidade OU na
  veracidade** de uma operação. Isso inclui, por exemplo, uma camada de
  auditoria que verifica se a própria resposta do sistema faz sentido antes
  de entregá-la ao usuário (ver item "self-check" na fila). Mesmo com o
  sistema tendo alguns erros, camadas de auditoria ajudam a reduzir o
  impacto deles — esse valor não deve ser descartado só por ser pouco
  visível numa demonstração rápida.
- **Bug corrigido: síntese final do resumo estourava o contexto do modelo em
  livros grandes**: com `revolucao-dos-bichos.pdf` (28 blocos), a síntese
  final às vezes voltava dizendo "não há um resumo final, parecem ser
  fragmentos" — o modelo recebia os 28 mini-resumos concatenados (bem acima
  de `num_ctx=8192`) e perdia parte do material. Corrigido com uma segunda
  camada de síntese: acima de `LIMITE_RESUMOS_POR_SINTESE` (10) mini-resumos,
  eles são agrupados e sintetizados em grupos intermediários primeiro
  (`sintetizar_grupo_intermediario`, modelo auxiliar) — só os resumos de
  grupo (sempre poucos) chegam na síntese final. Mantém o contexto sempre
  dentro do limite, não importa o tamanho do livro (ex: Odisseia, ~67
  blocos, teria o mesmo problema sem essa camada). De caminho, também
  corrigido `resumir_bloco()` cortando resumos no meio da frase
  (`num_predict` de 400 para 600).
- **Limitação residual observada: alucinação pontual em resumo de livro
  grande, mesmo após a correção acima**: no mesmo teste, o resumo final
  ainda inventou detalhes (nomes de cadelas que não existem no livro, trocou
  a espécie de uma personagem) — efeito colateral esperado de sintetizar
  resumo-de-resumo em duas camadas. O bug de estouro de contexto (resposta
  vazia/recusa) está corrigido; a acurácia fina do conteúdo em documentos
  grandes ainda depende de uma camada de verificação (ver item "self-check"
  — reforçado pela 3ª vez pelo usuário logo após esse caso concreto).
- **RAG passa a suportar detalhamento item-por-item, com busca separada
  para cada item (`perguntar.py`)**: perguntas do tipo "quais as propostas
  de X, com detalhes de cada uma" (ou follow-up vago "seja mais específico
  em cada uma") agora disparam `responder_com_detalhamento()` — descobre a
  lista de itens distintos (via resposta anterior no histórico, ou uma
  busca inicial se não houver), e faz uma busca RAG **separada** pra cada
  item, concatenando as respostas sem uma segunda síntese (evita o mesmo
  tipo de alucinação-por-resumo-de-resumo do bug do `resumir.py` acima).
  Detectado via `pede_detalhamento_de_itens()` (classificador few-shot, novo
  padrão já visto em outros extratores do projeto). Trava de segurança:
  `LIMITE_ITENS_DETALHADOS = 12`. Custo: ~4-6x mais lento que uma resposta
  RAG normal (cada item = 1 busca + 1 chamada ao modelo principal), na
  faixa de 2-3 min pro pior caso — aceito pelo usuário (limite de "uns 3 a
  5 minutos").
- **Bug corrigido: detalhamento por item vazava conteúdo de outro
  documento**: no follow-up vago ("seja mais específico"), a detecção de
  fonte usava só o texto do follow-up (sem "livro" nem contexto), caindo em
  busca sem filtro e puxando trechos de outro livro/histórico por
  coincidência semântica. Corrigido usando a **pergunta original** do
  histórico (que nomeia o documento) pra detectar fonte, não o follow-up.
- **Bug maior corrigido: busca RAG nunca filtrava por documento específico,
  só por tipo de fonte**: `resumir.py`/`contar_termo_no_arquivo` já sabiam
  identificar e filtrar por um arquivo específico havia tempo —
  `perguntar.py` nunca teve essa capacidade, mesmo sendo o mesmo padrão.
  Isso permitia que uma pergunta claramente sobre um livro específico (ex:
  "resuma a história de Napoleão em Revolução dos Bichos") buscasse em
  **todos** os documentos indexados, arriscando puxar chunks de outro
  livro. Corrigido com `identificar_arquivo_na_pergunta()` (reaproveita
  `listar_arquivos_disponiveis`/`normalizar` de `resumir.py`, mesmo
  casamento fuzzy de nome já usado lá) — quando um documento é nomeado
  explicitamente, `buscar_chunks_relevantes()` agora filtra por
  `fonte` **e** `arquivo` juntos (`$and` no ChromaDB). Aplicado tanto no
  fluxo normal de pergunta quanto no detalhamento por item. **Lição**:
  quando uma capacidade central existe numa ferramenta do sistema, checar
  proativamente se as outras ferramentas que deveriam ter a mesma
  capacidade realmente a têm, em vez de esperar o usuário achar o buraco
  testando.
- **Classificador de `jarvis.py` ajustado: "resumir uma parte específica"
  não é "resumo do livro inteiro"**: "resuma a história de Napoleão no
  livro X" usa a palavra "resumir", mas pedia coisa errada
  (`resumir_arquivo`, que sempre processa o livro inteiro via map-reduce).
  Categoria "resumo" agora exige que o pedido seja do documento inteiro,
  de ponta a ponta — um personagem/tema/trecho específico cai em
  "pergunta" (RAG, que já tem o filtro por documento acima).
- **Decisão (2026-08-20): classificação única de 7 vias substituída por
  funil de decisão em etapas (Streamlit), ver fila item 10 — PLANEJADO,
  ainda não implementado**. Motivo: um teste real com os documentos do
  próprio usuário (não sintéticos) achou 4 bugs, e 2 deles têm a mesma
  causa raiz — `classificar_pedido()` pede pro modelo escolher entre 7
  categorias numa chamada só, e a superfície de erro cresceu a cada
  categoria nova adicionada (transcrição, consulta estruturada com 3
  fontes, listar pasta...). Corrigir cada confusão nova com mais um
  exemplo few-shot (já feito 3x nesta sessão) é remendo pontual, não
  solução estrutural — ver também a discussão registrada sobre "tipo 1
  (correção estrutural/determinística)" vs "tipo 2 (patch de prompt)"
  logo abaixo desta decisão. A alternativa estrutural escolhida: interface
  guia o usuário em 2 etapas de botão (Categoria → Formato/Fonte, zero
  LLM, zero chance de erro de rota) antes de qualquer texto livre — o
  modelo só entra em cena já dentro de um escopo estreito (no máximo 2-3
  opções, em vez de 7), e várias combinações nem precisam de classificação
  alguma. **Importante para não confundir sessões futuras**: isso NÃO
  substitui `classificar_pedido()`/`processar_mensagem()` em `jarvis.py` —
  essas funções continuam existindo sem alteração, usadas pelo `__main__`
  do terminal (`python jarvis.py`). O funil é específico da interface
  Streamlit (`interface.py`), que passa a chamar um orquestrador novo
  (`processar_mensagem_guiada`) em vez de `processar_mensagem`. Também não
  muda nenhuma função de execução já validada (`resumir_arquivo`,
  `responder_pergunta`, `consultar_dado_estruturado`,
  `transcrever_arquivo`, `localizar_arquivo`, `listar_pasta` etc.) — o
  funil só muda **como se chega** até elas.
- **Metodologia de correção de bug reforçada pelo usuário (2026-08-20)**:
  ao corrigir um erro de classificação/extração da LLM, distinguir sempre
  entre correção **estrutural/determinística** (ex: pré-filtro de palavra-
  chave antes de chamar o modelo, reduzir o número de opções que o modelo
  precisa escolher, mover uma decisão pra código Python direto) e
  correção **via exemplo few-shot no prompt** (ensinar o modelo a não
  errar de novo naquele caso específico). A segunda é às vezes necessária
  e válida, mas não escala sozinha — cada exemplo novo só cobre o caso que
  já foi visto, não a próxima variação. Preferir sempre a estrutural
  quando ela existir; usar few-shot como complemento pontual, não como
  único mecanismo de correção repetido indefinidamente.
- **Reescrever um arquivo inteiro pode apagar capacidade validada sem
  ninguém perceber — e o ✅ da fila continua lá, mentindo (achado
  2026-08-20)**: a reescrita da `interface.py` pelo funil (item 23) removeu
  em silêncio 3 capacidades que estavam marcadas como concluídas nos itens
  4, 5 e 7 (barra de progresso do resumo, configuração de pastas
  catalogadas, listagem direta de programas). Nenhuma quebrou com erro —
  todas simplesmente **deixaram de existir**, que é a categoria mais
  perigosa (mesma família da falha silenciosa do DOCX sem paginação): o
  sistema continua respondendo, só que pior, e o documento segue afirmando
  que a capacidade existe. Duas delas viraram literalmente código morto
  (`salvar_pastas_catalogadas()` sem nenhum chamador; `progresso_callback`
  sem ninguém que passasse o argumento).

  **Causa**: o plano do item 10 dizia "a barra lateral fica só com Upload,
  as outras seções saem" — descrição correta do que fazer com a
  *interface*, mas ninguém checou o que aquelas seções eram a **única porta
  de entrada** para dentro do sistema. Um botão não é só um botão quando é
  o único chamador de uma função.

  **Regra adotada**: ao reescrever ou substituir um arquivo inteiro, antes
  de considerar a troca concluída, listar as funções que o arquivo antigo
  chamava e confirmar uma a uma quem passou a chamá-las — uma busca por
  chamadores (`grep` do nome da função no projeto inteiro) resolve em
  segundos e teria pego as três. Função pública sem nenhum chamador é
  sinal de capacidade perdida, não de código a apagar. Ver também
  [[feedback_revisar_consistencia_periodicamente]] e
  [[feedback_completude_proativa_capacidades]] na memória — este episódio é
  o caso concreto que as duas diretrizes previam.
## Prazo e objetivo de demonstração (contexto importante)
Usuário viaja e retorna em 18/mês, com objetivo de ter um **protótipo
demonstrável para pessoas leigas em tecnologia até dia 30/mês** (~12 dias
intensos de trabalho). Isso muda a priorização da fila temporariamente:
funcionalidades **visíveis numa demo** (interface, múltiplas fontes de
dados, ações centrais funcionando de forma confiável) sobem de prioridade;
funcionalidades **tecnicamente importantes mas invisíveis numa demo rápida**
(self-check, auditoria formal, documentação de handoff) descem, sem prejuízo
— ficam para depois do prazo, não são descartadas.

Receio identificado: chat de linguagem natural pura pode gerar respostas
"não encontrei" que pareçam falha de sistema para um público leigo, além de
não deixar claro pra esse público o que o sistema é capaz de fazer.
Decisão: interface **híbrida** (botões para ações centrais validadas +
chat livre por baixo para perguntas abertas).

**Evolução dessa decisão (2026-08-20)**: o funil de decisão em etapas
(fila item 10) não contradiz essa escolha — é a mesma lógica levada
adiante. Em vez de "botões soltos ao lado de um chat 100% livre", a
interface guia o usuário por botões (Categoria → Formato/Fonte) **antes**
do texto livre, então o chat nunca fica totalmente sem guarda-corpo — ele
já nasce escopado pela combinação escolhida. Reduz ainda mais o risco de
"não encontrei" parecendo falha de sistema pra um público leigo.
- **Upload de arquivo pela interface valida formato antes de aceitar** — ✅
  feito. A validação de extensão (`EXTENSOES_PERMITIDAS`) acontece **antes**
  de salvar o arquivo em disco, não depois — evita que
  um arquivo de formato não suportado (ou potencialmente perigoso, tipo
  `.exe`) chegue a ser gravado na pasta controlada mesmo que só
  temporariamente. **Estado atual** (depois do item 8, "zona controlada de
  leitura"): `EXTENSOES_INDEXAVEIS = (".pdf", ".txt", ".docx")` — viram
  chunk+embedding e entram no RAG — mais `EXTENSAO_PLANILHA = ".xlsx"`, que é
  salva mas **não** indexada (relida direto do arquivo a cada consulta). Os
  dois grupos juntos formam `EXTENSOES_PERMITIDAS`. Formatos antigos
  (`.doc`/`.xls`) continuam fora de propósito.
## Roadmap (visão geral)
1. ✅ Motor: Python + Ollama + GPU
2. ✅ Conexão Python ↔ Ollama via API local
3. ✅ Primeira fonte de dados (PDFs)
4. ✅ Embeddings + Vector Store (ChromaDB)
5. ✅ RAG básico (busca + resposta)
6. ✅ Memória de conversa + reformulação de pergunta
7. ✅ Indexação incremental (hash de conteúdo + versão de pipeline)
8. ✅ Resumo de documento inteiro (map-reduce, versão híbrida)
9. ✅ Expansão de fontes: histórico de navegação (Brave)
10. ✅ `jarvis.py` como porta única de entrada (roteador de pedidos)
11. ✅ Contagem exata de termos em documento
12. ✅ Corrigir busca em perguntas compostas (divisão em sub-perguntas + fonte)
13. ✅ Catalogador de arquivos — zona geral (SQLite, busca por nome)
14. ✅ Interface híbrida Streamlit — chat + 4 ações rápidas, dropdown de arquivo e upload de PDF (`interface.py`) — **substituída pelo funil de decisão em etapas, ver item 10 (2026-08-20)**: maioria dos botões e o chat 100% livre foram trocados pelo funil
15. ✅ Consulta estruturada genérica sobre histórico de navegação (`consultar_dados.py`)
16. ✅ Modelo auxiliar (`MODELO_LLM_AUXILIAR`) para resumo de bloco — ~24% mais rápido
17. ✅ Comando `/comandos` (intercepta antes do classificador, sem custo de LLM)
18. ✅ Nova fonte estruturada: programas instalados (`programas_instalados.py`, Registro do Windows)
19. ✅ Transcrição de documento — completa, por página e por trecho de conteúdo (`transcrever_arquivo()`)
20. ✅ Listar conteúdo de pasta + pastas catalogadas configuráveis pela interface
21. ✅ Zona controlada de leitura — TXT, Word e Excel (leitura via RAG pra TXT/Word, consulta estruturada pra Excel)
22. ✅ Temperatura fixa (determinística) em todas as chamadas de classificação/extração do projeto
23. ✅ Funil de decisão em etapas na interface — substitui a classificação livre de 7 vias por botões + texto escopado (`jarvis.py`: `processar_mensagem_guiada`; `interface.py` reescrito)
24. ✅ Escolha de arquivo/aba/pasta por dropdown antes do chat (item 12 da fila) — a IA deixa de adivinhar QUAL alvo, e passa a cuidar só do conteúdo da pergunta
25. ✅ Auditoria de coerência código × documento (2026-08-20) — achou 3 capacidades
    marcadas ✅ que a reescrita do item 23 tinha apagado silenciosamente, todas
    restauradas e testadas; mais 4 bugs/fragilidades ainda em aberto (ver seção
    "Achados da auditoria" no fim deste documento)

## Fila de prioridades (próximas implementações)

> Ordem atual priorizada pelo prazo de demonstração (retorno 18/mês, demo
> 30/mês) — ver seção "Prazo e objetivo de demonstração" acima. Ordem dos
> itens novos (dropdown, resumo mais rápido) definida a critério do Claude,
> a pedido do usuário (2026-08-18).

### ⚡ Ordem de execução vigente (revista em 2026-08-22)

> **A numeração da fila abaixo NÃO é a ordem de trabalho.** Ela foi mantida
> porque várias seções deste documento referenciam "item 10", "item 12", "item
> 14" etc., e renumerar quebraria essas referências em silêncio. A ordem real é
> esta, revista quando o usuário observou — com razão — que "localizar seção"
> não podia estar no fim da fila:
>
> 1. **Bugs da 1ª bateria de testes humanos** (B1 ✅, B2, B3, B4) — ver seção
>    "Achados da 1ª bateria de testes humanos".
> 2. ~~Item 21 — Localizar a seção de um documento sobre um tema (M1).~~ **✅
>    Resolvido em 2026-08-25** (efeito colateral do rework de Camada 1-3, ver
>    item 21 na fila numerada abaixo) — não ocupa mais posição na ordem.
> 3. **Decisões de interface em discussão** — subcategorizar transcrição em
>    botões, esconder fonte vazia, QOL do catálogo. São **visíveis numa demo** e
>    reduzem a superfície de erro (menos LLM decidindo rota). A discutir com o
>    usuário antes de implementar.
> 4. **Item 11 — pivot table em Excel**: relevante se a demo passar por planilha
>    (3 das 6 abas de `TAREFA MATEMATICA.xlsx` aparecem vazias hoje).
> 5. **Itens 13 a 20**, na ordem em que estão — todos são ou invisíveis numa
>    demonstração (self-check, auditoria formal), ou de encerramento de projeto
>    (limpeza de debug, checklists, handoff), ou conveniências que não bloqueiam
>    nada (memória ensinável, formatos de saída, indexação agendada).

1. **Interface híbrida (Streamlit)** — ✅ completo. Chat + 4 ações rápidas
   (resumir, localizar, contar termo, ver histórico) + upload de PDF
   (`st.file_uploader`, restrito a `EXTENSOES_PERMITIDAS = (".pdf",)`,
   validando extensão **antes** de salvar em `Docs/`). Upload já indexa o
   arquivo na hora, reaproveitando `indexar_arquivo()` — extraída de
   `indexar.py` pra ser chamável tanto pelo loop do `__main__` quanto pela
   interface, mesmo padrão de refactor já usado em `jarvis.py`. Testado com
   PDF real (manual de cortador de grama) — apareceu no dropdown e o resumo
   funcionou. Campo de upload volta ao estado vazio após sucesso (troca de
   `key` do widget, força o Streamlit a recriá-lo do zero) e mostra
   confirmação visual — sem isso, o campo ficava com o arquivo antigo
   visível, dando impressão de que o envio não tinha funcionado.
   Word/Excel/TXT continuam fora de `EXTENSOES_PERMITIDAS` até o item "zona
   controlada de leitura" existir. *(Desatualizado: o item 8 foi concluído e
   os quatro formatos são aceitos hoje — ver o estado atual logo acima do
   Roadmap.)*

   **Substituído pelo funil de decisão em etapas (2026-08-20, ver item
   10)**: as 4 ações rápidas (resumir, localizar, contar termo, ver
   histórico) e o chat 100% livre descritos acima foram removidos de
   `interface.py` e substituídos por um funil de decisão em etapas — só o
   upload continua exatamente como estava. Este bloco de texto permanece
   como registro histórico do que foi construído e validado primeiro, não
   reflete mais o estado atual da interface — ver item 10 pro estado
   vigente.

   **Dropdown de arquivo em vez de digitar o nome** — ✅ feito. Campos
   "Resumir documento" e "Contar termo em arquivo" da barra lateral agora
   usam `st.selectbox`, populado por `listar_arquivos_disponiveis()`
   (extraída de dentro de `resumir_arquivo`/`contar_termo_no_arquivo` pra
   virar função reutilizável). Não usa LLM — é consulta direta ao ChromaDB,
   então não compromete velocidade, só reduz erro de digitação/nome errado.
2. **Resumir mais rápido — modelo auxiliar pros resumos de bloco** — ✅
   feito. `resumir_bloco()` em `resumir.py` agora usa `MODELO_LLM_AUXILIAR`
   (`llama3.2:3b`, novo em `config.py`) só pro resumo de cada bloco (etapa
   mecânica/intermediária); a síntese final continua no modelo principal
   (`llama3.1:8b`, `MODELO_LLM`) — resposta que o usuário lê não perde
   qualidade. Medido com o mesmo bloco de texto, modelo já "aquecido" (sem
   contar tempo de troca de modelo na VRAM): 8.6s (8B) → 6.5s (3B), **~24%
   mais rápido** — abaixo dos 30% pedidos, mas ganho real sem mexer em mais
   nada. Se quiser chegar mais perto de 30%, próximo passo seria aumentar
   `CHUNKS_POR_BLOCO` (menos chamadas ao modelo) ou testar um modelo
   auxiliar ainda menor.
3. **Comando `/comandos` (ou `/ajuda`, `/help`)** — ✅ feito. `jarvis.py`
   intercepta a mensagem em `processar_mensagem()` antes de chamar
   `classificar_pedido()` (lista `COMANDOS_DE_AJUDA`), retornando
   `texto_de_ajuda()` direto — testado sem nenhuma chamada de LLM (4
   variações, incluindo espaço/maiúscula, em ~2.3s no total). **Lembrete
   deixado como comentário no código**: toda vez que uma categoria nova for
   adicionada a `classificar_pedido()`/`processar_mensagem()`,
   `texto_de_ajuda()` e este documento precisam ser atualizados junto.
4. **Feedback visual de progresso durante processamento** — ✅ feito.
   Localizar/contar/histórico/chat já usavam `st.spinner()` desde a
   implementação original da interface (item 1). Resumir ganhou uma barra
   real (`st.progress`) em vez de spinner indeterminado: `resumir_arquivo()`
   agora aceita um `progresso_callback(texto, fracao)` opcional, chamado a
   cada bloco resumido (testado com 28 blocos, progresso de 0.0 a 1.0
   corretamente) e mais uma vez antes da síntese final.
   **Catalogação** (dentro de "Localizar") continua com spinner
   indeterminado — `catalogar_pasta()` não tem hoje um sinal de progresso
   incremental (loop de `os.walk` sem callback), e é rápida o suficiente
   pra não valer o refactor agora.

   **⚠ Regressão silenciosa e restauração (2026-08-20, auditoria)**: a barra
   de progresso foi **perdida** na reescrita da `interface.py` pelo funil
   (item 23/10) e ficou semanas marcada como ✅ sem existir. `resumir_arquivo()`
   nunca perdeu o `progresso_callback` — o que quebrou foi o **caminho até
   ele**: a interface passou a chamar `processar_mensagem_guiada()`, que não
   tinha parâmetro pra repassar callback nenhum, então resumir um livro grande
   virou um `st.spinner` mudo por minutos (justamente o pior caso pra uma demo
   com público leigo: parece que travou). Restaurado com `progresso_callback`
   opcional em `processar_mensagem_guiada()` (repassado **só** na rota de
   resumo — as outras não têm progresso incremental real) e uma barra criada
   via `st.empty()` na interface, que só aparece quando o callback é de fato
   chamado. Parâmetro opcional de propósito: o `__main__` do terminal continua
   chamando sem ele.
5. **Nova fonte de dados: programas instalados** — ✅ feito, mas com desenho
   diferente do que o texto original sugeria. **Não** reaproveita o padrão
   do histórico (indexar no ChromaDB com embedding) — é dado tabular
   pequeno (~76 programas neste PC), então segue o padrão do catalogador de
   arquivos: sempre relê na hora, sem embedding, sem custo de indexação
   (`programas_instalados.py`, lê o Registro do Windows — chaves
   `Uninstall` em `HKLM`/`HKLM WOW6432Node`/`HKCU`, filtrando componentes de
   sistema e duplicatas). Plugado na engine de `consultar_dado_estruturado`
   já existente: `carregar_dataframe_por_fonte()` despacha entre
   `historico_navegacao` e `programas_instalados`, e `detectar_fonte_estruturada()`
   (novo, em `consultar_dados.py`) decide qual fonte consultar por LLM.
   **Formatação generalizada**: `formatar_resultado`/`formatar_linha` eram
   hardcoded pras colunas do histórico (`titulo`/`data_visita`/`url`) —
   agora formatam qualquer coluna genericamente, incluindo detectar se um
   timestamp tem hora real (histórico) ou só data (instalação de programa).
   **Ação rápida "Ver programas instalados"** adicionada na interface
   (lista tudo direto, sem LLM) — diferente do catálogo de arquivos geral,
   a lista de programas é pequena o suficiente pra listar tudo de uma vez
   sem virar ruído (ideia do usuário, ver decisão sobre "listar pasta").
   **Bug encontrado e corrigido nos testes**: o extrator de especificação
   usava `"=="` (igualdade exata) pra filtro de texto por padrão (ex:
   "Apple" não batia com "Apple Inc." no dado real) — reforçado no prompt
   com regra explícita + exemplo: filtro de texto usa sempre `"contem"`,
   `==`/`>`/`<` ficam reservados pra número/data.
   **Campo `caminho_instalacao` adicionado** (lido de `InstallLocation` no
   registro) — nem todo programa preenche esse campo (alguns instaladores
   não gravam), limitação da fonte, não bug. Botão "Ver programas
   instalados" da interface reaproveita `carregar_programas_dataframe()` +
   `formatar_linha()` (já genéricos) em vez de montar texto na mão —
   corrigiu de quebra um esquecimento (a primeira versão do botão não
   mostrava data de instalação nenhuma).

   **⚠ Regressão silenciosa e restauração (2026-08-20, auditoria)**: o botão
   sumiu junto com as outras seções da barra lateral na reescrita pelo funil
   (item 23/10), deixando "Consultar + Programas" só com texto livre — ou seja,
   um pedido puramente mecânico ("me mostre tudo") passava por
   `extrair_especificacao_consulta()` à toa, mais lento e com chance de erro de
   interpretação. Restaurado **dentro do funil** (ideia do usuário), não na
   barra lateral: botão "Listar todos os programas instalados" aparece na Etapa
   3 só na combinação Consultar+Programas. A lógica virou
   `listar_todos_programas()` em `consultar_dados.py` (em vez de montar texto na
   interface), reaproveitando as mesmas funções genéricas de antes. Medido: 76
   programas em 0,03s, zero chamada de modelo. A listagem **não** entra em
   `st.session_state.historico` — é longa e mecânica, só inflaria o contexto da
   reformulação seguinte. Aplicação direta do Princípio central #2 (escolha
   mecânica é da interface, não da IA).
6. **Transcrição de documento** — ✅ feito, mais flexível do que o texto
   original previa. `transcrever_arquivo()` (`resumir.py`) reaproveita
   `buscar_todos_chunks_do_arquivo` (refatorada pra
   `buscar_pares_chunk_metadata`, expondo metadados junto). Concatenação
   remove a sobreposição entre chunks (`remover_sobreposicao()`) — sem
   isso, o texto "completo" saía com pedaços duplicados a cada ~450
   caracteres.

   **Recorte por página**: `indexar.py` rastreia em qual página do PDF
   cada chunk começa (`pagina_do_offset()`, offsets reais do PyMuPDF) —
   campo `pagina` novo nos metadados. Exigiu bump de `VERSAO_PIPELINE`
   (`v3-com-fonte` → `v4-com-pagina`), reindexação automática via
   mecanismo já existente.

   **Recorte por conteúdo (não estava no plano original)**: usuário
   levantou um caso real — documento sequencial (ex: relatório mensal)
   onde o recorte que importa está no CONTEÚDO ("a parte de março"), não
   na estrutura. "Capítulo de livro" foi descartado (não dá pra detectar
   com confiança sem risco de erro silencioso), mas o caso geral (filtro
   por termo) é resolvível sem inventar: acha o primeiro e o último chunk
   onde o termo aparece, transcreve o trecho contíguo entre eles — assume
   documento sequencial/cronológico. Busca normaliza pontuação
   (`normalizar_busca_conteudo`, diferente da normalização exata e
   proposital de `contar_termo_no_arquivo`) — sem isso "Sr. Jones" não
   batia com "sr jones" que o extrator de LLM devolvia sem pontuação.
   **Trava de sanidade**: se o termo cobre >50% do documento (testado com
   "Sr. Jones" em Revolução dos Bichos — personagem recorrente do início
   ao fim, 75% do livro), a função recusa e sugere pergunta normal (RAG)
   em vez de transcrição — "do primeiro ao último" só serve pra
   tema/período localizado, não pra personagem que aparece o livro
   inteiro. Excel (colunas) fica fora de escopo até a "zona controlada"
   (item 8) ler Excel. Pedido combinando página+termo ao mesmo tempo:
   termo tem prioridade (comportamento determinístico, testado, não
   quebra nem mistura os dois filtros).

   **Saída vira arquivo, não texto cru no chat**: usuário apontou que
   despejar transcrição grande no chat não é usável — ligado ao item
   "criação de arquivos" (15) da fila, resolvido aqui de forma mínima sem
   esperar aquele item. Acima de `LIMITE_TRANSCRICAO_INLINE` (2000
   caracteres), `jarvis.py` salva em `transcricoes/*.txt` (carimbo de
   data/hora no nome) e devolve só o caminho. Transcrições curtas (ex: 1
   página) continuam aparecendo direto no chat.

   **Bug de completude encontrado testando limites**: `encontrar_arquivo()`
   (usada por resumo, contagem e transcrição) não tinha a mesma trava de
   termo curto que corrigi no `listar_pasta` — um nome de arquivo vago
   ("o e") só não deu erro por sorte (bateu em vários arquivos ao mesmo
   tempo, caindo na branch de ambiguidade). Corrigido com a mesma trava de
   3 caracteres mínimos, replicada pra essa função central também.
7. **Listar conteúdo de uma pasta (catalogador)** — ✅ feito. `listar_pasta()`
   em `catalogar_arquivos.py` lista os arquivos **diretos** de uma pasta
   (não recursivo) — `listar_pastas_disponiveis()` deriva as pastas a
   partir dos arquivos já catalogados, já que o catalogador só indexa
   arquivos, não pastas em si. Categoria nova `listar_pasta` no
   classificador, distinta de "localizar" (busca arquivo por nome sem
   saber a pasta). **Bug encontrado testando limite**: termo de 1
   caractere ("a") casava por acaso com uma pasta ("Jogos e Games" contém
   "a") e devolvia a listagem inteira sem avisar que o termo era vago
   demais — corrigido com trava de tamanho mínimo (3 caracteres
   normalizados; mesma trava depois replicada em `encontrar_arquivo`,
   ver item 6). **Acréscimo do usuário (QOL, mesmo item)**: pastas
   catalogadas (`PASTAS_CATALOGADAS`) viram configuráveis pela própria
   interface — `pastas_catalogadas.json` (gerado pela interface;
   `config.py` vira só valor padrão da primeira execução),
   `carregar_pastas_catalogadas()`/`salvar_pastas_catalogadas()` em
   `catalogar_arquivos.py`, usados por `jarvis.py` e por uma seção
   "Configurar pastas catalogadas" dentro de "Localizar arquivo" na
   interface. Evita reescrever `config.py` programaticamente (risco de
   corromper o arquivo).

   **⚠ Regressão silenciosa e restauração (2026-08-20, auditoria)**: essa
   seção era a **única porta de escrita** do `pastas_catalogadas.json`, e saiu
   junto com as outras 5 seções da barra lateral na reescrita pelo funil (item
   23/10). Efeito: `carregar_pastas_catalogadas()` continuou sendo usada
   (`jarvis.py` chama antes de qualquer "Procurar"), mas
   `salvar_pastas_catalogadas()` ficou **órfã, sem nenhum chamador** — o
   sistema seguia funcionando com as pastas que já estavam no JSON, só que
   congelado: adicionar uma pasta nova exigia editar o JSON à mão, exatamente
   o que este item existia pra evitar. Restaurada na barra lateral, com as
   travas testadas: caminho inexistente é recusado **antes** de gravar (mesmo
   princípio da validação de extensão no upload), pasta repetida avisa em vez
   de duplicar, e lista vazia mostra aviso explícito de que "Procurar" não vai
   encontrar nada. Escolha 100% mecânica, sem LLM.
8. **Zona controlada de leitura** — ✅ feito pra TXT, Word e Excel (SQL
   genérico continua fora, é o item de maior risco, fica pra depois). Só
   formatos modernos: `.docx`/`.xlsx` — `.doc`/`.xls` antigos não são lidos
   (avisado no `/comandos` e na interface; usuário converte no Word/Excel
   antes de enviar).

   **Decisão de arquitetura central: Excel não entra no pipeline de RAG**.
   TXT e Word são texto corrido — `indexar.py` ganhou
   `extrair_texto_txt()`/`extrair_texto_docx()` e `indexar_arquivo()` passou
   a despachar a extração por extensão (`EXTRATORES_POR_EXTENSAO`) em vez
   de chamar `extrair_texto_pdf` direto — reaproveitam automaticamente
   resumo/pergunta/contagem/transcrição sem nenhuma rota nova (mesmo padrão
   de PDF). Excel é dado tabular, não texto corrido — plugado na engine de
   `consultar_dado_estruturado()` já existente como nova fonte `"planilha"`
   (`carregar_planilha_dataframe()` via `pd.read_excel`, relido direto do
   arquivo a cada pergunta, sem embedding/ChromaDB — mesmo padrão já usado
   pra programas instalados). Colocar Excel no pipeline de RAG seria a
   ferramenta errada pro tipo de pedido que se faz numa planilha (soma,
   filtro, contagem exata) — o mesmo erro que o projeto já evitou
   deliberadamente com histórico/programas.

   **Transcrição de planilha reaproveita o extrator de consulta**: em vez
   de um "modo burro" que só despeja tudo, `transcrever_planilha()`
   reaproveita `extrair_especificacao_consulta()` (reconhece coluna/termo
   mencionados, ex: "transcreva a coluna preço da planilha X"), só forçando
   `operacao="listar"` e removendo o teto padrão de 20 linhas (transcrição
   é completa por definição). "Transcreva a planilha X" sem filtro vira uma
   consulta "listar tudo" — decisão do usuário, evita um caminho de erro
   confuso (antes, `transcrever_arquivo` procurava a planilha só na lista de
   documentos indexados no ChromaDB, onde ela nunca estaria).

   **Suporte a "mostrar só uma coluna" adicionado ao motor de consulta**
   (não só transcrição — beneficia `consulta_estruturada` normal também):
   `coluna_alvo` agora também funciona em `"listar"` pra projetar o
   resultado numa única coluna, não só em `"somar"/"media"` como antes.

   **Três bugs reais encontrados testando com arquivos de verdade** (TXT,
   DOCX, XLSX sintéticos — não só os PDFs já validados):
   1. Pergunta simples sobre um DOCX ("quem treina funcionários segundo
      o manual X") disparava o classificador de detalhamento por engano,
      citando o próprio nome do arquivo como se fosse um "item" a
      detalhar — resposta confusa e auto-referente. Corrigido com exemplo
      de contraste explícito em `pede_detalhamento_de_itens`
      (`perguntar.py`).
   2. Filtro de planilha ("quantas linhas de milho") ignorado
      silenciosamente — o LLM extraía o nome da coluna em caixa diferente
      da real (`"produto"` vs `"Produto"`), e a comparação era sensível a
      caixa. Corrigido com `resolver_coluna()` (novo, case-insensitive),
      usado em filtro, `coluna_alvo` e `ordenar_por`.
   3. "Transcreva a planilha X" não achava o arquivo — o extrator incluía
      a palavra "planilha" junto do nome (`"planilha teste_vendas.xlsx"`).
      Corrigido estendendo `normalizar()` (`resumir.py`, compartilhada por
      vários módulos) pra também remover palavras qualificadoras no início
      do termo (`"planilha "`, `"documento "`, `"arquivo "`, `"livro "`),
      além dos artigos que já removia.

   **Causa raiz mais ampla identificada e corrigida**: nenhuma chamada de
   classificação/extração do projeto fixava a temperatura do modelo —
   Ollama usa um valor padrão alto (bastante aleatoriedade), o que causa
   variação entre execuções idênticas (isso explicou uma reprodução
   inconsistente de um dos bugs acima). Adicionado `"temperature": 0` em
   **todas** as chamadas de classificação/extração do projeto
   (`jarvis.py`, `perguntar.py`, `consultar_dados.py` — 15 chamadas ao
   todo) — nunca nas chamadas de geração de resposta final/resumo, que
   continuam com a temperatura padrão (naturalidade importa mais que
   determinismo quando é texto pro usuário ler).

   **Melhoria futura registrada (não implementada agora, ver item 15)**:
   usuário quer poder escolher o formato de saída de uma transcrição
   grande (hoje sempre `.txt`) — PDF e Excel além de TXT.
9. **Consultas estruturadas/agregadas sobre dados** — ✅ feito para
   histórico de navegação e planilha Excel (`consultar_dado_estruturado()`
   em `consultar_dados.py`). Falta só SQL genérico (parte do item 8 ainda
   não implementada, item de maior risco). **Bug encontrado depois, ver
   item 10**: planilha com múltiplas abas lê sempre a primeira, sem
   avisar — corrigido junto com o item 10, não aqui.
10. **Funil de decisão em etapas (chat guiado, Streamlit) + 3 bugs
    restantes do stress test** — ✅ completo (2026-08-20, plano aprovado e
    implementado no mesmo dia). Motivo e desenho geral já registrados
    acima em "Decisões técnicas importantes". Resumo do funil:

    **Etapa 1 — Categoria** (botões, zero LLM): Consultar / Criar / Procurar

    **Etapa 2 — Formato/Fonte** (botões, zero LLM, depende da categoria):
    - Consultar → Documento (PDF/TXT/Word) | Planilha Excel | Histórico de
      navegação | Programas instalados
    - Criar → Documento (PDF/TXT/Word) | Planilha Excel
    - Procurar → Por nome de arquivo | Por pasta

    **Etapa 3 — texto livre**, já escopado pela combinação escolhida —
    só duas combinações ainda precisam de classificação por LLM, e nunca
    mais que 3 opções por vez: Consultar+Documento (pergunta/resumo/
    contagem) e Consultar+Histórico (pergunta RAG/consulta estruturada).
    Todas as outras combinações vão direto pra função certa, sem LLM
    decidindo rota nenhuma.

    **`jarvis.py`**: novas funções `classificar_consulta_documento()` (3
    vias), `classificar_consulta_historico()` (2 vias),
    `extrair_nome_aba()` (pra multi-aba), e um orquestrador novo
    `processar_mensagem_guiada(mensagem, categoria, formato, historico,
    colecao)` — reaproveita todos os extratores/funções que já existem,
    nenhum muda. `classificar_pedido()`/`processar_mensagem()` continuam
    intactas, servindo só o `__main__` do terminal.

    **`interface.py`**: barra lateral fica só com Upload; as outras 4
    seções (Resumir, Localizar, Contar termo, Histórico, Programas,
    Configurar pastas) saem. Área principal ganha o funil, controlado por
    `st.session_state`. Reformulação visual mais ampla fica pra depois
    (usuário já sinalizou que vai reformular design/interface mais pra
    frente, fora do escopo desta leva).

    **Bug 1 (`consultar_dados.py`) — planilha multi-aba lida errado, sem
    avisar** — ✅ corrigido (2026-08-20). Achado real no teste:
    `Soulstone Survivor Megasheet.xlsx` tem 33 abas, `TAREFA MATEMATICA.xlsx`
    tem 6, e `pd.read_excel()` sempre lia só a primeira, silenciosamente.
    Ex: pergunta sobre a aba "Enemy stat" devolvia "45 entradas" — que era
    a contagem da aba errada (primeira aba), não da pedida. Corrigido com
    `listar_abas_planilha()` (nomes via `openpyxl`, leitura leve, sem
    carregar dados) e `carregar_planilha_dataframe(nome_arquivo,
    nome_aba=None)` reescrita: se só tem 1 aba, comportamento igual a
    antes; se tem várias e `nome_aba` não veio, **não adivinha** — lista as
    abas disponíveis e pede pra especificar; se veio, resolve por nome via
    `resolver_aba()` (match exato ignorando caixa tem prioridade sobre
    match parcial — sem isso "enemy stat" ficava ambíguo entre "Enemy stat"
    e "Enemy stat (9g3)", duas abas reais do arquivo com nome parecido de
    propósito). Também cobre arquivo corrompido/formato antigo com extensão
    trocada (try/except claro em vez de travar, testado com um `.xlsx`
    falso). `nome_aba` agora é parâmetro opcional em
    `carregar_dataframe_por_fonte()`, `consultar_dado_estruturado()` e
    `transcrever_planilha()`, todas retornando/propagando `(resultado,
    erro)` em vez de só o valor — mesmo padrão já usado em
    `identificar_planilha()`. Ainda falta o `jarvis.py`/`interface.py`
    perguntarem qual aba o usuário quer quando a mensagem não especifica
    (isso virou o item 12 da fila — escolha por botão, não mais por texto
    livre) — por enquanto, sem aba especificada, o sistema corretamente
    recusa a adivinhar em vez de
    responder errado.

    **Bug extra encontrado testando com dado real, não previsto no plano
    original**: a aba "Enemy stat" da Megasheet tem cabeçalho de coluna
    não-textual (número, não string) — `extrair_especificacao_consulta()`
    quebrava com `TypeError` ao montar a lista de colunas pro prompt
    (`", ".join(colunas)` exige string). Corrigido convertendo cada nome de
    coluna pra string antes de juntar (`str(c) for c in colunas`). Só
    apareceu porque essa aba nunca tinha sido lida de verdade antes (bug 1
    sempre lia a primeira aba) — reforça o valor de testar com dado real do
    usuário, não só dado sintético.

    **Bug 2 — classificador confunde "tabela" (Word) e perguntas técnicas
    genéricas com consulta estruturada**: achado no teste com documentos
    reais do usuário (`LADDER_MPS_TIA_PORTAL.docx`,
    `TECHNICAL_REPORT_CORRECTED.docx`). "Quantas entradas digitais estão
    na tabela de tags do documento X?" (tabela é texto dentro de um Word,
    não planilha) caiu em `consulta_estruturada` e devolveu "Encontrei 0
    entrada(s)" — resposta confiante e errada, deveria ter sido `pergunta`
    (RAG). Mesmo problema com "quais as coordenadas de latitude e
    longitude usadas no relatório X" — devolveu "Nenhum resultado
    encontrado" em vez de buscar no texto do documento. **Resolvido
    estruturalmente pelo funil**: dentro de "Consultar + Documento", as
    únicas 3 opções são pergunta/resumo/contagem — `consulta_estruturada`
    nem existe mais como possibilidade nesse caminho, então essa classe
    inteira de erro deixa de ser possível, não só menos provável.

    **Bug 3 (`perguntar.py`) — vazamento de documento com nome técnico** —
    ✅ corrigido (2026-08-20). `TECHNICAL_REPORT_CORRECTED.docx`
    (maiúsculas/underscore) não era reconhecido por
    `extrair_nome_documento_mencionado()` — a busca ficava sem filtro de
    arquivo e trazia conteúdo da Odisseia junto na resposta, mesmo bug já
    corrigido antes pra outros formatos de nome (ver "Bug maior corrigido"
    no item 6). Corrigido com novo exemplo few-shot (Exemplo 3) usando nome
    de arquivo nesse formato — antes só havia exemplo tipo "livro amarelo".
    **Bug irmão achado no caminho**: o modelo às vezes ecoava o próprio
    rótulo do prompt (`"DOCUMENTO: NENHUM"` em vez de só `"NENHUM"`), e esse
    texto era tratado como se fosse nome de arquivo real — corrigido
    removendo o prefixo `"DOCUMENTO:"` antes de comparar. Retestado com a
    pergunta original das coordenadas (resposta vem só do relatório certo,
    sem Odisseia) **e** com 8 reformulações/nomes de arquivo nunca vistos
    no prompt (`SPEC-2024-v3.docx`, `REPORT2024.xlsx`, frases reescritas
    tipo "isso é mencionado no relatorio-tecnico-corrigido.docx?") — todas
    corretas, confirmando generalização pelo padrão, não decoreba da frase
    testada (ver [[feedback_stress_test_reparafrasear]] na memória).

    **Bug 4 (`perguntar.py`) — `pede_detalhamento_de_itens` disparando à
    toa, piorou em vez de melhorar** — ✅ corrigido (2026-08-20). Já
    corrigido uma vez nesta sessão com exemplo de contraste (ver item 6),
    mas recorreu — em "o documento X menciona alguma coisa sobre facas
    (melee knives)?" (pergunta simples de sim/não), o classificador
    disparou detalhamento e **inventou um item que não existe no documento
    nem na pergunta** ("Terra Blade Schematic"), citando-o como se fosse
    algo a detalhar. Prova concreta de que só empilhar exemplo few-shot não
    escala. Corrigido com pré-checagem determinística **antes** de chamar o
    classificador (`PALAVRAS_SINAL_DETALHAMENTO = ("cada", "todos os",
    "todas as")`) — se a pergunta não contiver nenhum desses sinais,
    `pede_detalhamento_de_itens` devolve `False` direto, **sem nenhuma
    chamada ao modelo**.

    **Round 2, pedido explicitamente pelo usuário ("resolveu mesmo ou só o
    caso específico?")** — achou 2 problemas reais adicionais, ambos
    corrigidos de forma determinística, **sem adicionar nenhum exemplo
    few-shot novo**:
    - "quantas vezes cada termo aparece no texto?" (contagem por item, não
      detalhamento) passava o pré-filtro (contém "cada") e o classificador
      também errava. Primeira tentativa de correção foi um exemplo
      few-shot (Exemplo 5) — **e esse exemplo quebrou um caso vizinho que
      já funcionava** ("cada vez que eu abro esse arquivo dá erro, por
      quê?" passou a dar `True` errado), provando na prática, dentro do
      próprio projeto, o risco de empilhar few-shot que o usuário já
      suspeitava. **Decisão tomada com o usuário**: reverter o Exemplo 5 e
      resolver com exclusão determinística — se "cada" é o único sinal
      encontrado E a pergunta contém verbo de contagem ("quantas vezes",
      "quantos", "quantas", "conte"), não é candidato a detalhamento,
      retorna `False` sem chamar o modelo. Cobre a família toda do padrão
      "contagem + cada" (testado com variações nunca vistas: "quantos
      exemplos de cada categoria existem", "conte quantas vezes cada
      personagem aparece"), não só a frase relatada.
    - Mesmo padrão aplicado pra "cada vez que..." (expressão temporal,
      "toda vez que"): exclusão determinística separada, só desconta o
      sinal "cada" quando aparece como "cada vez" e é o único sinal da
      pergunta.
    - **Por que isso importa mais do que parece**: o próprio incidente do
      Exemplo 5 virou a prova de conceito de uma diretriz nova de processo
      — ver [[feedback_avisar_remendo_antes_de_resolver]] (parar e avisar
      antes de aplicar remendo específico, não só resolver o sintoma) e
      [[feedback_stress_test_reparafrasear]] (ao reexecutar stress test,
      repetir igual os casos que falharam, mas reformular os que já
      passavam — não repetir literal, porque com `temperature: 0` repetir
      a frase exata não prova nada de novo).
    - Retestado com bateria reformulada completa (regressão idêntica nos 3
      casos que já tinham falhado + paráfrases em todos os casos que já
      passavam, incluindo os do Bug 3): **zero falhas**.

    **Pergunta genérica demais (ex: "quantas vezes cada termo aparece") —
    registrada como ideia futura, não implementada agora**: discussão com o
    usuário levantou que perguntas sem alvo identificável (equivalente a
    perguntar pro Google "pra que serve isso" sem dizer o que é "isso")
    talvez merecessem o sistema responder "pode ser mais específico?" em
    vez de tentar adivinhar ou cair num fallback aproximado. Não
    implementado deliberadamente — é capacidade nova (detector de
    ambiguidade), não correção do bug relatado, e o caso que motivou a
    ideia foi um teste hipotético do Claude, não um uso real reportado.
    Registrado como nota dentro do item 14 (self-check) abaixo, por ser
    conceitualmente parecido (sistema avaliando a própria interação antes
    de responder).

    **Fora de escopo desta leva**: reformulação visual mais ampla da
    interface; migrar o terminal pro mesmo funil; SQL genérico; geração de
    Excel/relatório (o "Criar" do funil fica limitado a transcrição por
    enquanto, como já era).

    **`jarvis.py` implementado e testado** (2026-08-20): as 4 funções
    novas do desenho acima (`classificar_consulta_documento`,
    `classificar_consulta_historico`, `extrair_nome_aba`,
    `processar_mensagem_guiada`) foram escritas e testadas contra as 7
    combinações da tabela Categoria+Formato, em 4 rodadas de teste com
    documentos/planilhas reais (`LADDER_MPS_TIA_PORTAL.docx`, `Basic
    Primary_Secondary Modding.docx`, `TECHNICAL_REPORT_CORRECTED.docx`,
    `Soulstone Survivor Megasheet.xlsx`, `TAREFA MATEMATICA.xlsx`), com
    frases reformuladas a cada rodada, não repetidas — achou (e corrigiu)
    3 bugs estruturais novos, nenhum deles existente antes do funil:
    - **Nome de aba/planilha já resolvido vazando pro próximo extrator**:
      "quantas linhas tem a aba Enemy stat da planilha X" — depois de
      `extrair_nome_aba` já ter consumido "Enemy stat" pra escolher a aba,
      a mensagem crua (ainda com "Enemy stat" nela) ia pro
      `extrair_especificacao_consulta`, que reinterpretava esse texto como
      **filtro de dado** (`coluna=="Enemy stat"`), zerando o resultado.
      Mesmo problema em "criar+planilha": o nome da própria planilha foi
      confundido com nome de aba. Corrigido com `remover_referencias_resolvidas()`
      (novo, `consultar_dados.py`) — remove deterministicamente qualquer
      valor já resolvido (nome de aba, nome de planilha) do texto antes de
      mandar pro próximo extrator. Aplicado nos 2 pontos do funil que
      encadeiam extração (`consultar+planilha` e `criar+planilha`) e dentro
      de `consultar_dado_estruturado`/`transcrever_planilha`.
    - **Filtro de texto usando `==` em vez de `contem`, de forma não
      determinística mesmo com `temperature: 0`**: "eu tenho o Python
      instalado?" ora funcionava (2 resultados), ora dava 0 — mesma
      pergunta, resposta diferente dependendo do que rodou antes (efeito
      de lote/GPU do motor de inferência local, não bug de código). A
      regra "texto usa `contem`, nunca `==`" já existia como instrução no
      prompt (ver item 5), mas só como instrução — o modelo nem sempre
      seguia. Corrigido reforçando a regra **em código**: `aplicar_filtros`
      agora corrige `==` pra `contem` sempre que a coluna não for numérica
      nem data, garantido independente do que o modelo decidir.
    - **`responder_pergunta()` ignorava a fonte já resolvida pelo funil**
      (achado mais sério dos três — mina o propósito central do funil):
      dentro de "Consultar+Documento"/"Consultar+Histórico", quando a
      subcategoria era "pergunta", `responder_pergunta()` continuava
      rodando `detectar_fonte()` por conta própria, do zero, reabrindo a
      mesma ambiguidade documento-vs-histórico que o funil deveria ter
      eliminado por completo nesse caminho. Achado com mensagem vaga ("e
      sobre isso?") em Consultar+Documento, que trouxe conteúdo de
      histórico de navegação misturado na resposta. Corrigido com
      parâmetro novo `fonte_forcada` em `responder_pergunta()` e
      `responder_com_detalhamento()` (`perguntar.py`) — quando vem
      preenchido, pula `detectar_fonte()` inteiro. `jarvis.py` passa
      `fonte_forcada="documento"`/`"historico_navegacao"` nos 2 pontos do
      funil correspondentes; `processar_mensagem()` do terminal continua
      chamando sem esse parâmetro (`None`), mantendo auto-detecção.

    **Bug de robustez encontrado testando pergunta de negócio real**
    (usuário apontou que perguntas de teste anteriores eram mecânicas
    demais — "quantas linhas tem" não reflete uso real; pediu perguntas
    tipo "quantos são homem/mulher", "quantos de cada partido", "quantas
    avarias acima de X tempo"): "quantos políticos têm mais de 60 anos?"
    **quebrava com `TypeError` cru** — a coluna "Idade" da planilha real
    tinha tipo misto (`int`/`float`/`str` na mesma coluna, dado sujo real,
    não sintético), e o operador `>` do motor de consulta comparava direto
    sem converter tipo. Corrigido com `comparar_numerico()` (novo,
    `consultar_dados.py`) — coage série e valor pra número antes de
    comparar com operador de ordem (`>`,`<`,`>=`,`<=`); célula que não
    converte vira `NaN` e não bate no filtro, em vez de travar o programa.
    Confirmado sem regressão nos casos numéricos que já funcionavam
    (histórico, programas instalados).

    **Achados adicionais registrados sem corrigir agora** (pequenos
    demais pra virar item de fila, mas reais — ver `Planos/PENDENCIAS.md`):
    mapeamento semântico errado quando a planilha tem coluna codificada
    (M/F) e coluna auxiliar parecida; motor de consulta não sabe "agrupar
    por X e contar cada grupo" (perguntas tipo "quantos de cada partido");
    DOCX sem paginação real fazendo filtro de página falhar em silêncio.

    **`interface.py` reescrito e testado** (2026-08-20): barra lateral
    fica só com Upload (as outras 6 seções antigas foram removidas — ver
    nota de revisão no item 1).

    **⚠ Correção posterior desta decisão (2026-08-20, auditoria)**: remover
    "as outras 6 seções" custou 3 capacidades já validadas e ainda marcadas
    ✅ (itens 4, 5 e 7) — todas restauradas depois, ver as notas de
    regressão em cada item e a lição estrutural registrada em "Decisões
    técnicas importantes". A parte do desenho que continua válida é
    **tirar do caminho principal** as ações que competiam com o funil; o
    erro foi tratar "sai da barra lateral" como sinônimo de "não precisa
    mais existir em lugar nenhum". Duas das três voltaram para a barra
    lateral (upload e pastas catalogadas são configuração, não consulta), e
    a terceira voltou **dentro do funil** (listar programas é uma consulta,
    então pertence à Etapa 3 da combinação correspondente). Área principal implementa o funil com
    `st.session_state.funil_categoria`/`funil_formato`: Etapa 1 (3
    botões), Etapa 2 (botões dependentes da categoria, tabela
    `FORMATOS_POR_CATEGORIA`), Etapa 3 (`st.chat_input`, escopado, chama
    `processar_mensagem_guiada`). Botões "← Trocar categoria" (sempre
    visível a partir da Etapa 2) e "Trocar formato/fonte" (Etapa 3, volta
    só a Etapa 2) resetam a etapa sem apagar `st.session_state.mensagens`
    (transcrição visível) — mas **resetam `st.session_state.historico`**
    (memória de conversa usada na reformulação de pergunta) a cada troca
    de categoria/formato, deliberado: evita a reformulação puxar assunto
    de um contexto diferente do que acabou de ser trocado.

    **Revisto em 2026-08-20 (pedido do usuário, depois de usar de verdade)**:
    agora a troca de categoria/formato limpa **também** a transcrição visível
    (`st.session_state.mensagens`), não só o `historico` — função
    `limpar_conversa()` em `interface.py`, usada pelos dois botões. Motivo: com
    a transcrição antiga na tela e a memória já zerada por baixo, a interface
    dizia uma coisa e o sistema fazia outra — o usuário via uma listagem de
    histórico de navegação logo acima de uma pergunta sobre planilha e supunha
    que aquilo ainda contava como contexto, quando o modelo já não enxergava
    nada daquilo. Limpar de vez deixa a tela honesta com o que o sistema
    realmente está levando em conta.

    **Testado sem navegador** (ambiente sem acesso a browser/screenshot):
    usado `streamlit.testing.v1.AppTest` pra simular clique real de botão
    e envio de chat, não só checar que o script sobe sem exceção. Validado
    de ponta a ponta: Etapa 1 → 2 → 3 → resposta real do modelo (ex:
    "Consultar"→"Documento"→pergunta sobre `LADDER_MPS_TIA_PORTAL.docx`
    devolveu conteúdo correto sobre o PLC Siemens S7-1200); caminho
    100%-sem-LLM também testado ("Procurar"→"Por pasta"→listagem real da
    pasta `Docs`); "Trocar categoria" e "Trocar formato" confirmados
    voltando pra etapa certa sem exceção. **Ressalva explícita**: isso
    confirma que a lógica de estado e a integração com `jarvis.py`
    funcionam de verdade, mas não substitui conferência visual num
    navegador real (aparência, responsividade) — usuário deve abrir
    `http://localhost:8501` e usar a interface antes de considerar
    definitivamente fechado.

    **Episódio importante, registrado por completo pra não se repetir
    (2026-08-20)**: depois do funil "completo" acima, o usuário testou de
    verdade na interface e achou um problema real de UX: quando uma
    planilha tem várias abas, o sistema pede "especifique qual aba" — mas
    se o usuário responde só com o nome da aba (ex: "detalhes1"), isso é
    tratado como pergunta nova do zero (busca uma planilha chamada
    "detalhes1", falha), não como resposta à pergunta anterior.

    Tentativa 1: generalizar `reformular_pergunta()` (`perguntar.py`) pra
    também completar resposta curta de acompanhamento, chamando ela
    incondicionalmente no topo do `processar_mensagem_guiada`. Testado com
    bateria de 5 casos (aba curta, pronome, já completa, resposta longa
    sem pronome, correção sem pronome) — **cada ajuste de prompt
    consertava um caso e quebrava outro que já funcionava** (ex: um
    ajuste resolveu "correção sem pronome" mas passou a misturar histórico
    irrelevante numa pergunta que devia ficar intacta; outro resolveu isso
    mas alucinou um nome de aba específico que não existia em lugar
    nenhum do histórico). Comparado `llama3.1:8b` vs `qwen2.5:14b` na
    mesma bateria — o modelo maior foi qualitativamente melhor em alguns
    casos, mas **nem ele resolveu o bug mais grave** (confusão de coluna
    numa pergunta de negócio real), ficou 2-9x mais lento por chamada
    (pior caso 36.5s numa chamada só), e ocupou 12.4GB de 12.28GB de VRAM
    — inviabilizando os outros 2 modelos do projeto (auxiliar + embedding)
    rodarem junto. Qwen removido do disco depois do teste.

    **Diagnóstico do usuário, correto**: o problema não era o prompt nem o
    modelo — era a abordagem. Fazer a IA "entender" uma escolha a partir
    de texto livre exige uma regra por nuance de linguagem (o que
    aconteceria com o usuário escrevendo em outro idioma, por exemplo?) —
    não escala, não importa quão bom o modelo seja. **Decisão**: revertido
    `reformular_pergunta()` de volta ao escopo original (só substituição
    de pronome, como já era antes desta sessão) e removida a chamada
    incondicional no topo de `processar_mensagem_guiada`. Levou à criação
    do **Princípio central de arquitetura #2** (topo deste documento): a
    IA nunca escolhe entre opções conhecidas, isso é sempre botão/dropdown
    na interface. O redesenho de verdade da Etapa 3 pra aplicar esse
    princípio (escolha de arquivo/aba/pasta por botão, antes do chat) é o
    **item 12 da fila, novo, próximo passo planejado — ver lá o desenho
    completo**.

    **Bug real confirmado e RESOLVIDO em 2026-08-25** (a "nota de
    confiabilidade" acima virou investigação de verdade): retestado limpo
    (sem shell, texto idêntico, 3 rodadas) — o mesmo caso de pronome
    (`"quantos anos ele tem?"` com histórico "quem é o personagem
    principal... → Napoleão, um porco.") falhava 3/3, sempre do mesmo
    jeito: ecoava a resposta antiga do histórico ("Napoleão, um porco.")
    em vez de reescrever a pergunta. Bateria de 12 casos variados (gênero,
    histórico de 2 turnos, "isso"/"aquilo", plural) isolou a causa: o
    modelo (`llama3.1:8b`) **sempre** identificava corretamente quem é
    "ele" — o nome certo aparecia até nas saídas erradas — mas confundia
    "reescreva a pergunta" com "continue respondendo" sempre que o
    histórico tinha a forma "quem é X? → Y." (resposta curta, sem frase
    completa) seguida de pergunta sobre atributo de X. Não é falta de
    entendimento, é um padrão de diálogo (trivia curta) mais arraigado no
    treino do modelo que uma instrução isolada no prompt — nenhuma
    reformulação de prompt resolveria de forma confiável.

    **Correção**: `reformular_pergunta()` trocou o LLM por casamento
    gramatical mecânico (spaCy, a mesma infraestrutura da busca literal por
    dependência) — pronome pessoal (ele/ela/dele/dela) casa por GÊNERO com
    o candidato mais recente do histórico (entidade nomeada preferida,
    percorre turnos de trás pra frente até achar); plural (eles/elas/
    deles/delas) junta todos os candidatos do turno achado; "isso"/"aquilo"
    (sem gênero pra casar) usa `_extrair_topico_da_pergunta()` — acha o
    complemento de conteúdo do verbo raiz da pergunta histórica (não o
    pronome interrogativo "o que"/"quem", que é armação) via árvore de
    dependência. Testado com os 12 casos (10 batem exatamente com a versão
    LLM quando ela acertava, 2 CORRIGEM casos que a versão LLM errava) e
    **ponta a ponta contra `responder_pergunta()` real**: nos 3 casos
    verificáveis contra o conteúdo dos livros (idade de Napoleão,
    nascimento de Euclides da Cunha, data do combate de Uauá — confirmado
    por busca direta no texto que a data genuinamente não existe em lugar
    nenhum do livro), a versão gramatical devolveu recusa honesta e
    correta nos 3, contra a produção anterior que reformulava errado e
    ativava 130 trechos do livro inteiro por engano, caindo em recusa por
    excesso de material — pior resultado que a recusa direta da versão
    nova. Sem fallback pro LLM quando não acha candidato (reintroduziria o
    mesmo problema) — a pergunta sai com o pronome ainda presente nesse
    caso raro, não trava nem inventa.

    **Continuação, 2026-08-26 — varredura geral achou 3 bugs reais em
    cadeia, todos resolvidos:**

    **(a) "Minha" (stopword) excluía a cabeça de entidade nomeada.**
    Achado real: "quanto o Brasil gasta com o Minha Casa Minha Vida?" —
    "Minha Casa Minha Vida" é reconhecida pelo spaCy como UMA entidade
    (`ent_type_="MISC"`), mas a palavra-cabeça "Minha" (pronome possessivo
    comum, está na lista de stopword) era excluída do loop de geração de
    candidatos em `frases_ancora_por_dependencia()` antes mesmo de checar
    se fazia parte de entidade — sem essa cabeça, a frase de 4 palavras
    nunca era montada, só sobravam "Brasil"/"Casa"/"Vida" soltos (202
    chunks, o livro inteiro). Corrigido: token que faz parte de entidade
    nomeada nunca é excluído por stopword — "ser stopword" é sobre a
    palavra isolada, nome próprio anula isso. O filtro de POS
    (NOUN/PROPN) já é suficiente sozinho; a checagem de stopword ali era
    redundante e só atrapalhava. Resultado: "Minha Casa Minha Vida" vira
    o nível de entidade mais específico, acha só 2 chunks (o lugar
    certo), em vez de 202.

    **(b) Contexto mais preciso expôs um bug de fusão de blocos vizinhos.**
    Achado real: com (a) corrigido, a pergunta combinada
    "MCMV + AgroBrasil 2030" passou a responder ERRADO o MCMV (dizia
    "R$1,2-1,5 trilhão" em vez de "R$180 bilhões"). Rastreado a fundo:
    NÃO é regressão da busca — o chunk certo (com "R$180 bilhões") estava
    presente nos dois casos. O problema é que o agrupamento de blocos
    vizinhos (`agrupar_em_blocos_contiguos`) só olha POSIÇÃO no documento,
    nunca CONTEÚDO — com a âncora mais precisa (2 chunks concentrados em
    vez de 202 espalhados), o filtro de isolamento passa mais candidatos
    semânticos próximos, e o agrupamento funde o parágrafo certo do MCMV
    com o capítulo SEGUINTE (Desfavelização, assunto diferente, que por
    coincidência também cita um valor grande em reais). Confirmado com
    teste direto: a MESMA sub-pergunta do MCMV, respondida ISOLADA (sem o
    AgroBrasil junto), acertava — só errava quando as duas eram fundidas
    num prompt só e o modelo lia (e respondia) as duas ao mesmo tempo.
    Isso é limite de leitura do modelo (comprovado: 8B parâmetros troca
    dois números parecidos ao ler contexto maior e responder duas coisas
    de uma vez), não bug de retrieval.

    **Correção**: quando sobra mais de uma sub-pergunta de verdade (não
    fundida pela checagem de convergência), `responder_pergunta()` não
    junta mais os blocos de todas num prompt só — cada sub-pergunta ganha
    seu próprio `reunir_contexto`, sua própria decisão de rota (Camada 2)
    e sua própria chamada ao modelo; a resposta final é a concatenação
    dos textos. Reduz drasticamente o contexto por chamada (o MCMV
    sozinho usa só o que é dele) e elimina a contaminação cruzada.

    **(c) Separar as chamadas quebrou referência cruzada entre
    sub-perguntas.** Achado real, mesmo dia: "quem é o ciclope Polifemo e
    o que acontece com ELE?" — dividida em 2, a segunda metade ("o que
    acontece com ele?") não sabe quem é "ele" sozinha, ativa qualquer
    trecho aleatório do livro com esse pronome, e a resposta saiu
    contaminada com uma cena completamente diferente da Odisseia
    (o retorno de Ulisses a Ítaca, não o episódio do ciclope).

    Duas correções em cadeia, reaproveitando `reformular_pergunta()` (a
    mesma peça gramatical de cima, usada de um jeito novo — cada
    sub-pergunta é reformulada usando a RESPOSTA já gerada da anterior
    como "histórico"):
    1. Na hora de RESPONDER cada sub-pergunta separadamente, ela é
       reformulada contra a resposta da anterior antes de buscar contexto
       — resolve "ele" → "Polifemo" mecanicamente.
    2. **Mais cedo, antes até de medir convergência semântica**: se
       resolver o pronome de uma sub-pergunta exige pegar emprestado o
       sujeito de uma ANTERIOR, isso já prova que não são tópicos
       independentes — funde tudo de volta na pergunta original na hora,
       sem tentar separar. Necessário porque "quem é Polifemo?" e "o que
       acontece com ele?" (mesmo resolvida certo) apontam pra POSIÇÕES
       DIFERENTES do episódio (identidade vs. enredo, medido: 275 chunks
       de distância, muito acima do raio de fusão) — a checagem de
       convergência por posição semântica (item acima) não pega esse
       caso, porque as duas metades genuinamente falam de partes
       diferentes da mesma história, não do mesmo ponto exato como
       Uauá/INHIBIT.

    Testado (5 casos, produção real): MCMV+AgroBrasil correto nos dois
    números; Polifemo volta a dar uma narrativa única e completa (fundido
    de volta, não mais separado); INHIBIT/C/B/A e Uauá continuam fundindo
    certo (nenhuma regressão nas duas checagens de convergência
    existentes); pergunta única simples não afetada.
11. **Leitura de tabela dinâmica (pivot table) em Excel** — planejado
    (decisão tomada com o usuário em 2026-08-20, a ser feito **depois** dos
    bugs pendentes do item 10). Achado real testando `TAREFA
    MATEMATICA.xlsx`: 3 das 6 abas (`Planilha1`, `Planilha2`, `Planilha5`)
    têm dado visível no Excel (confirmado por captura de tela do usuário),
    mas o sistema lia como vazias (0 linhas) — não é bug de leitura de
    célula, é característica real do formato: quando uma aba é só uma
    tabela dinâmica com `refreshOnLoad="1"`, o Excel não grava o resultado
    desenhado como células normais no arquivo salvo, só grava a
    configuração da pivot + uma referência viva pra fonte dos dados. Uma
    ferramenta que só lê célula bruta (nosso `pd.read_excel` de hoje) vê a
    aba genuinamente vazia no arquivo, mesmo ela mostrando dado ao vivo
    dentro do Excel.

    **Investigação confirmou viabilidade, sem precisar de dependência
    nova**: `openpyxl` (já em uso) tem um modelo de objetos completo pra
    pivot table (`openpyxl.pivot.cache`, `openpyxl.pivot.table`) — dá pra
    ler, de forma estruturada (sem regex em XML cru), tanto a fonte da
    pivot (`ws._pivots[0].cache.cacheSource.worksheetSource` — sheet +
    range de origem) quanto o layout (`rowFields`/`colFields`/`dataFields`,
    com a função de agregação em `dataField.subtotal`: `count`, `sum`,
    `average` etc.). Testado com o arquivo real: `Planilha1` resolveu como
    fonte `Página1!B1:F231`, agrupada por "Circulo eleitoral", contando
    "Nome" — reproduz exatamente a tabela dinâmica que o usuário mostrou
    (Açores: 5, Aveiro: 16, ...) usando só `pd.read_excel()` +
    `.groupby().count()`/`pivot_table()` do pandas sobre a fonte já
    resolvida. Decisão de ferramenta explicitamente revisada a pedido do
    usuário ("não tenha medo de pegar os melhores, por que escolheu
    openpyxl?") — resposta: não foi escolhido pensando nisso
    especificamente (é dependência transitiva do pandas pra `.xlsx`), mas
    pra essa tarefa ele já tem tudo que é preciso built-in, sem precisar de
    biblioteca nova nem de automação via Excel/COM (que exigiria Excel
    instalado na máquina, contra o princípio do projeto de não depender de
    nada além de Python + Ollama).

    **Escopo do que falta implementar**: quando uma aba pedida não tiver
    célula própria mas tiver `ws._pivots`, resolver a fonte (sheet+range)
    e o layout (linha/coluna/valor/agregação) via essas classes do
    openpyxl, montar a consulta equivalente com pandas
    (`groupby`/`pivot_table`) sobre a fonte, e usar esse resultado no lugar
    da leitura direta — avisando ao usuário que a aba é uma tabela
    dinâmica e de onde veio o dado, não escondendo a substituição.
12. **Redesenho da Etapa 3 do funil: escolha de arquivo/aba/pasta por
    botão, IA só pra pergunta de conteúdo** — ✅ **implementado e testado em
    2026-08-22** (decisão tomada com o usuário em 2026-08-20, ver Princípio
    central de arquitetura #2 no topo do documento, e o episódio completo
    registrado no item 10 sobre por que a tentativa via
    `reformular_pergunta` foi abandonada).

    **O que foi feito, por arquivo:**
    - `interface.py`: sub-etapa nova entre a Etapa 2 e o chat, com
      `st.selectbox(index=None)` — sem pré-seleção **de propósito**: um
      selectbox comum já viria com o primeiro item marcado, ou seja, a
      interface escolhendo pelo usuário, que é o mesmo vício em outra roupa.
      Estado em `funil_arquivo`/`funil_aba`/`funil_pasta`, zerado por
      `limpar_alvo()` a cada troca de categoria/formato. O chat **não
      aparece** enquanto o alvo não estiver escolhido (`st.stop()`), e o alvo
      atual fica visível com um botão "Trocar" ao lado.
    - `jarvis.py`: `processar_mensagem_guiada()` aceita
      `arquivo_selecionado`/`aba_selecionada`/`pasta_selecionada`; quando vêm
      preenchidos, os extratores de NOME são pulados inteiramente. Duas
      funções novas para o caso "arquivo já conhecido":
      `extrair_termo_contagem()` (só o termo) e `extrair_recorte_transcricao()`
      (só página/termo). As antigas (`extrair_nome_arquivo`,
      `extrair_termo_e_arquivo`, `extrair_parametros_transcricao`,
      `extrair_nome_planilha`, `extrair_nome_aba`, `extrair_nome_pasta`)
      continuam existindo e servindo o terminal.
    - `perguntar.py`: parâmetro `arquivo_forcado` em `responder_pergunta()` e
      `responder_com_detalhamento()` — mesma ideia do `fonte_forcada` já
      existente, um nível abaixo. **Sem isso o item 12 seria inútil na rota de
      pergunta**: o documento escolhido no dropdown seria ignorado e a busca
      continuaria varrendo todos os arquivos.
    - `catalogar_arquivos.py`: `listar_pasta_por_caminho()`, listagem por
      caminho exato (sem busca aproximada, que deixa de fazer sentido quando o
      usuário clicou na pasta).

    **Decisões de UX tomadas na implementação** (o documento deixava em
    aberto): "Procurar + Por pasta" **não tem chat** — escolher a pasta já é o
    pedido completo e a listagem sai na hora; um campo de texto ali ficaria
    inerte. E planilha de **aba única** não pergunta nada: resolve sozinha e
    vai direto pro chat.

    **Resultado medido**: "quantas linhas tem?" na aba `Detalhes1` de
    `TAREFA MATEMATICA.xlsx` responde **242** (o valor certo) — o mesmo caso
    que antes falhava de três formas diferentes: extrator devolvendo o nome da
    aba como se fosse o da planilha (3/3 execuções), nome pedido virando filtro
    de dado, e palavra órfã ("aba") virando filtro. Nenhuma dessas correções
    precisou ser feita: **as três deixaram de ser possíveis nesse caminho**.

    **Como foi verificado** (42 checagens, 2 suítes): além do resultado, os
    testes **espionam os extratores de nome** e confirmam que eles não são mais
    chamados (`[]`) quando o alvo vem selecionado — sem isso, um "funcionou"
    poderia estar passando pelo caminho velho sem ninguém notar.
    Retrocompatibilidade também travada em teste: **sem** seleção, o extrator
    antigo volta a ser usado, então o terminal segue intacto. Testado também
    com planilha de aba única (criada e removida na hora), aba inexistente,
    arquivo inexistente, e o reset do alvo ao trocar de categoria.

    **Desenho combinado com o usuário** — cada combinação que envolve um
    arquivo específico ganha uma sub-etapa mecânica (dropdown/botão,
    lista já conhecida, zero LLM) **antes** do chat livre:

    | Combinação | Escolha mecânica antes do chat | Chat livre só pra |
    |---|---|---|
    | Consultar+Documento | qual documento (dropdown, `listar_arquivos_disponiveis`) | resumo/contagem/pergunta sobre ELE |
    | Consultar+Planilha | qual planilha (dropdown, `listar_planilhas_disponiveis`) + qual aba se houver mais de uma (botão, `listar_abas_planilha`) | a pergunta sobre os dados |
    | Criar+Documento | qual documento (dropdown) | página/termo da transcrição |
    | Criar+Planilha | qual planilha + qual aba | coluna/filtro da transcrição |
    | Procurar+Pasta | qual pasta (dropdown, `listar_pastas_disponiveis`/pastas catalogadas) | nada — talvez nem precise de chat, resposta direta ao escolher |
    | Procurar+Arquivo | — (busca fuzzy por nome impreciso É o propósito da funcionalidade, exceção legítima do princípio) | continua livre |
    | Consultar+Histórico | — (fonte única, sem arquivo pra escolher) | continua livre (`classificar_consulta_historico` decide pergunta/consulta_estruturada) |
    | Consultar+Programas | — (fonte única) | continua livre |

    **Por que isso importa, além do princípio geral**: mata na raiz (não
    corrige, remove a necessidade) vários bugs já encontrados hoje —
    "tarefa de matemática" não batendo com "TAREFA MATEMATICA.xlsx" (não
    precisa mais de casamento fuzzy de nome, o usuário clica no nome
    exato), nome de aba vazando pro filtro de dado
    (`remover_referencias_resolvidas` deixa de ser necessário, a mensagem
    nunca mais vai conter nome de arquivo/aba), aba confundida com nome de
    planilha (mesmo motivo). `extrair_especificacao_consulta` também fica
    mais confiável — só precisa interpretar a pergunta sobre o dado, não
    mais identificar QUAL planilha/aba ao mesmo tempo.

    **O que muda em cada arquivo (planejamento, ainda não escrito)**:
    - `interface.py`: novo(s) `st.session_state` pra guardar arquivo/aba/
      pasta já escolhidos dentro da combinação atual (ex:
      `funil_arquivo`, `funil_aba`). Sub-etapa nova entre Etapa 2 e Etapa 3
      pras combinações da tabela acima, usando as funções de listagem que
      já existem (`listar_arquivos_disponiveis`, `listar_planilhas_disponiveis`,
      `listar_abas_planilha`, `listar_pastas_disponiveis`) — nenhuma delas
      precisa de LLM, já são consulta direta.
    - `jarvis.py`: `processar_mensagem_guiada()` precisa aceitar o
      arquivo/aba/pasta já resolvidos (parâmetro novo, ex:
      `arquivo_selecionado=None, aba_selecionada=None`) e, quando vierem
      preenchidos, **pular** os extratores de nome (`extrair_nome_arquivo`,
      `extrair_nome_planilha`, `extrair_nome_aba`, `extrair_nome_pasta`)
      inteiramente pra essas combinações — a mensagem de texto livre passa
      a conter só o pedido de conteúdo (ex: `extrair_termo_e_arquivo`
      precisaria virar só extração de termo, já que o arquivo já é
      conhecido). `classificar_pedido()`/`processar_mensagem()` do
      terminal continuam sem alteração (fora de escopo, só a interface
      Streamlit muda).
    - Detalhe de UX a decidir com o usuário na próxima sessão: se
      "Procurar+Pasta" deve mesmo pular o chat inteiramente (resposta
      direta ao clicar na pasta) ou se todas as combinações devem manter
      um chat_input por consistência visual, mesmo quando não é
      estritamente necessário.

    **Fora de escopo desta leva (mantido)**: reformulação visual mais
    ampla da interface, terminal, SQL genérico, geração de Excel/relatório.
13. **Memória ensinável (usuário → sistema)**: usuário diz "lembre que X"
    (ex: "lembre que o torque do parafuso Y é Z Nm"), sistema grava
    permanentemente como nova entrada indexada — mesmo padrão de fonte de
    dados já usado para PDF/histórico, só que a "fonte" é uma afirmação
    direta do usuário. Não é fine-tuning/deep learning — é indexação de
    mais um tipo de "documento" no mesmo banco vetorial.
14. **Camada de revisão da própria resposta (self-check)** — invisível numa
    demo rápida, mas o usuário reforçou (2x) que o valor técnico continua
    importante mesmo assim: camadas de auditoria ajudam a reduzir o
    impacto de erros do sistema, mesmo que ele não seja perfeito. Possível
    implementação: segunda chamada de IA (mesmo modelo ou auxiliar)
    verificando se a resposta da primeira chamada faz sentido antes de
    entregá-la — não só confiar cegamente na primeira resposta. Continua
    depois do prazo de demo, mas não deve ser descartado.

    **Ideia relacionada, registrada 2026-08-20, não implementada**:
    detectar quando a própria PERGUNTA (não a resposta) é vaga/genérica
    demais pra ter um alvo identificável — equivalente a perguntar pro
    Google "pra que serve isso" sem dizer o que é "isso". Em vez de tentar
    adivinhar ou cair num fallback aproximado, o sistema devolveria algo
    como "pode ser mais específico?". Motivado por um caso de teste do
    Claude ("quantas vezes cada termo aparece no texto?", ver item 10) que
    o próprio usuário observou não ter certeza se acontece no uso real
    (pessoal ou corporativo). Vale considerar junto do self-check quando
    esse item for implementado, mas não antes — é capacidade nova
    (detector de ambiguidade de entrada), com risco próprio de virar mais
    um classificador que erra, não uma correção de bug existente.
15. **Capacidade de criação de arquivos** (ex: gerar tabela Excel a partir
    de dados indexados). **Ligado a isso (registrado 2026-08-19, durante o
    item 8)**: transcrição grande hoje sempre salva em `.txt`
    (`salvar_transcricao_em_arquivo`, `jarvis.py`) — usuário quer, mais pra
    frente, poder escolher o formato de saída (PDF, Excel, além de TXT).
    Viável sem biblioteca nova pra PDF (o `fitz`/PyMuPDF que já lê PDF
    também sabe criar); Excel faz bastante sentido especialmente pra
    transcrição de planilha (preserva estrutura tabular em vez de achatar
    em texto). Adiado deliberadamente — focar primeiro em deixar
    leitura/consulta/resumo/transcrição funcionando bem pros formatos
    atuais (PDF/TXT/Word/Excel).
16. **Indexação configurável (3 modos)** — comando manual via chat primeiro,
    agendamento depois.

    **Item relacionado, adiado junto (decisão do usuário, 2026-08-27)**:
    `garantir_catalogo()` (`catalogar_arquivos.py`) revarre TODAS as pastas
    catalogadas a cada busca de arquivo/pasta — com Desktop+Docs custa ~1s,
    mas com um disco inteiro catalogado custa **~9s antes de qualquer
    resposta**. Não é bug: decisão deliberada (catálogo nunca desatualizado,
    sem arquivo fantasma). Resolver exigiria revarrer por intervalo ou sob
    comando, em vez de sempre — mesma família de decisão deste item 16, só
    que pro catalogador (zona geral) em vez da indexação (zona controlada).
17. **Camada de auditoria/aprovação formal** — invisível numa demo rápida,
    pode ficar pra depois do prazo de 30.
18. **Limpeza de debug** — comentar prints `[DEBUG]` conforme convenção.
19. **Checklist de erros conhecidos para handoff**.
20. **Documentação final para handoff** (ÚLTIMO passo do projeto).
21. ✅ **Localizar a SEÇÃO de um documento sobre um tema** (item M1) —
    **resolvido em 2026-08-25**, como efeito colateral do rework de Camada
    1-3, não por trabalho dedicado a este item. Reconfirmado contra o caso
    canônico que motivou o item (capítulo de segurança pública no
    `livro-amarelo-resumo-2026.pdf`) — ver "M1" na seção "Achados da auditoria
    de coerência" pro registro completo (caso, experimentos que não
    funcionaram, medição do reteste).

## Teste de estresse planejado (fora da fila numerada)
Perto do dia 30/mês, ou quando o sistema estiver robusto o suficiente
(usuário decide o momento — não é um item sequenciado na fila acima), fazer
um "debug monstro": Claude gera várias perguntas de todo tipo pro Jarvis,
testando o máximo de versatilidade e capacidade do sistema — não perguntas
óbvias que já sabemos que funcionam, e sim nuances, casos de borda e
combinações que ainda não foram tentadas. Objetivo: validar profundidade
real antes da demonstração, não só o caminho feliz.

## Erros comuns já resolvidos (para não repetir debug)
- Arquivo `.py` editado no VS Code mas não salvo → script roda versão antiga.
  Auto Save já está ativado no projeto.
- Terminal aberto fora da pasta do projeto (ex: `C:\Windows\system32`) → usar
  sempre o terminal integrado do VS Code, que abre na pasta certa.
- Funções duplicadas com mesmo nome no mesmo arquivo → a segunda sobrescreve a
  primeira silenciosamente, sem erro. Sempre substituir por completo ao
  aplicar correções, não colar em cima.
- Variáveis de ambiente (como `OLLAMA_MODELS`) só são lidas por processos
  **novos** — é necessário reiniciar o serviço/programa, não só o terminal.
- Ao adicionar campo novo aos metadados de um arquivo já indexado, é preciso
  reindexar do zero uma vez — chunks antigos não têm o campo novo, então a
  comparação sempre falha até essa migração única acontecer.
- Migração de pipeline (troca de biblioteca de extração, por exemplo) **não**
  muda o hash do arquivo (hash é dos bytes do PDF, não do texto extraído) —
  por isso hash sozinho não é suficiente pra decidir se reprocessa. Resolvido
  com o campo `pipeline_versao`.

## Convenção de debug
Prints de debug (`[DEBUG] ...`) são adicionados durante desenvolvimento/correção
de bugs específicos. Perto da finalização do projeto (ou quando um módulo for
considerado "estável"), esses prints devem ser comentados (`# print(...)`), não
apagados — mantê-los comentados no código serve como ferramenta de diagnóstico
pronta pra reativar rapidamente se um erro similar aparecer no futuro, sem
precisar escrever a lógica de debug de novo do zero.
## Buracos identificados para escala corporativa (visão futura, distinta da fila pessoal)

> A fila de prioridades acima é pensada para uso pessoal/protótipo de
> demonstração. Os itens abaixo são lacunas estruturais que separam "sistema
> funcional pra uma pessoa" de "ferramenta pronta pra escritório de
> multinacional" — não fazem parte do prazo de 30/mês, ficam registrados
> como visão de médio/longo prazo.

- **Multiusuário com permissão diferenciada**: hoje o sistema é desenhado
  para um único usuário, com acesso irrestrito ao que ele mesmo configurou
  (`PASTAS_CATALOGADAS`, zona controlada). Escritório real tem dezenas de
  pessoas, cada uma com acesso a coisas diferentes (RH não vê financeiro,
  estagiário não vê contrato jurídico). Precisaria de sistema de contas,
  login, e permissão por usuário/grupo — mudança estrutural grande, afeta
  toda a arquitetura de zonas (geral/controlada) que hoje assume um único
  "dono" do sistema.
- **Log de auditoria de uso geral (quem perguntou o quê, quando)**:
  diferente da "camada de auditoria/aprovação formal" já na fila (que
  registra ações *executadas* e aprovadas), isso seria rastreabilidade de
  *toda* interação com o sistema — relevante para compliance corporativo
  real (ex: LGPD, auditoria interna, saber quem consultou dado sensível e
  quando). Não implementado, nem desenhado ainda.
- **Fontes de dados corporativas típicas**: hoje o sistema só lê PDF,
  histórico de navegador e arquivo local. Empresa real tem conhecimento
  espalhado em e-mail, Teams/Slack, sistemas de chamado (ticket), ERP —
  nenhuma dessas fontes está no escopo hoje. Cada uma exigiria sua própria
  integração (API própria, autenticação, formato de dado diferente),
  seguindo o mesmo padrão de "função de extração dedicada" já usado para
  PDF e histórico do Brave.
- **Backup e recuperação do banco vetorial**: hoje, se `banco_vetorial/`
  corromper ou for perdido, o único plano é reindexar tudo do zero. Isso é
  aceitável para uso pessoal (poucos documentos, reindexação rápida), mas
  inviável para uma empresa com volume grande de dados indexados (poderia
  levar horas/dias para reconstruir). Precisaria de rotina de backup
  regular do banco (ChromaDB + SQLite do catálogo).
- **Escalabilidade de hardware além de um PC local**: a arquitetura atual
  assume uma GPU local rodando tudo. Um departamento pequeno cabe nisso;
  uma multinacional inteira exigiria servidor dedicado mais robusto, e
  possivelmente múltiplas instâncias/balanceamento de carga — fora do
  escopo de "um PC pessoal" que o projeto tem hoje.
- **Classificação de dado sensível por nível de sigilo**: hoje "zona
  controlada" é uma pasta só, com um único nível de acesso. Empresa real
  tem dados com sigilos diferentes (RH, financeiro, jurídico, estratégico)
  que não deveriam ser todos igualmente acessíveis mesmo dentro da mesma
  "zona controlada". Precisaria de um sistema de classificação/etiqueta de
  sigilo por documento ou por pasta, combinado com o item de multiusuário
  acima (sigilo só faz sentido pleno quando existe usuário diferenciado
  para restringir).
## Achados da auditoria de coerência (2026-08-20) — todos resolvidos

> Varredura completa de código × documento feita a pedido do usuário. As 3
> regressões encontradas já foram corrigidas (ver itens 4, 5 e 7 da fila).
> Da lista abaixo, todos os itens foram corrigidos e testados em 2026-08-20,
> exceto o `LIKE` com caminho cru — esse ficou marcado `[ ]` por engano até
> 2026-08-27 (o código já tinha sido corrigido de verdade em 2026-08-25,
> registrado no `PENDENCIAS.md`; só este documento não tinha sido
> atualizado — achado relendo os dois arquivos de ponta a ponta a pedido do
> usuário). Decisão do usuário na época: "primeiro endireitar o que já
> temos, não adianta ligar o carro com as peças estragadas".

- [x] **Duas funções `normalizar()` diferentes, com o mesmo nome e
  comportamento divergente** (`resumir.py` × `catalogar_arquivos.py`). A de
  `catalogar_arquivos` remove underscore; a de `resumir` **não**. Consequência
  medida com arquivos reais já indexados: `'TECHNICAL REPORT CORRECTED'` casa
  com `TECHNICAL_REPORT_CORRECTED.docx` na busca do catálogo (`True`) e
  **falha** em `encontrar_arquivo` (`False`) — mesma frase, resultados opostos
  dependendo da rota. Afeta resumo, contagem e transcrição
  (`encontrar_arquivo`), além de `identificar_planilha` e `resolver_aba`, que
  importam a versão de `resumir.py`. 2 dos 8 documentos indexados hoje têm `_`
  no nome. É a mesma classe do "Bug 3" do item 10, que foi corrigido só no
  extrator (`perguntar.py`), nunca nas funções de casamento de nome.

  **✅ Corrigido (2026-08-20)** com um módulo novo, `texto.py`, e a separação
  das duas responsabilidades que a função antiga misturava — ela canonicalizava
  o texto **e** removia palavra de enfeite, e era aplicada aos DOIS lados da
  comparação, então o nome real de um arquivo também tinha artigo arrancado
  ("A Odisseia.pdf" era comparado como "odisseia.pdf"):
  - `normalizar_nome()` — forma canônica pra comparar (caixa, acento, e os três
    separadores intercambiáveis: espaço, hífen, **underscore**). Vale pros dois
    lados.
  - `limpar_termo_pedido()` — tira artigo/qualificador do início. Vale **só**
    pro que o usuário ou o extrator escreveu, nunca pro nome real.
  - `normalizar_pedido()` — atalho que aplica as duas na ordem certa.

  As 6 comparações do projeto foram migradas (`resumir.py`,
  `consultar_dados.py` ×2, `perguntar.py`, `catalogar_arquivos.py` ×2). O
  `nome_normalizado` gravado no SQLite continua idêntico ao de antes
  (`normalizar_nome` == comportamento antigo do catalogador), então **não
  precisou de migração de banco** — verificado no teste. 28 checagens,
  incluindo os casos que falhavam repetidos iguais, os que já passavam
  reformulados, e limites (termo curto, ambíguo, inexistente, aba com nome
  numérico).
- [x] **`remover_referencias_resolvidas()` remove só o nome resolvido, não o
  que o usuário escreveu** (`jarvis.py` × `consultar_dados.py`).

  **Reproduzido antes de corrigir** (era só suspeita de leitura): "me diga o
  total de linhas da tarefa matematica na aba Detalhes1" gerava o filtro
  `{"coluna": "Unnamed: 0", "operador": "==", "valor": "tarefa matematica"}` —
  o nome que o usuário digitou virando critério de dado, numa aba de 242
  linhas. **✅ Corrigido**: os 4 pontos do `jarvis.py` que resolvem um nome
  agora passam adiante a mensagem **já limpa**, e a limpeza virou
  case-insensitive (`re.sub` com `IGNORECASE` em vez de `str.replace`, que só
  casava texto idêntico — "Tarefa Matematica" digitado vs "tarefa matematica"
  extraído não batia, e o bug voltava em silêncio).

  **Limitação residual conhecida, medida**: remover o nome deixa um buraco na
  frase ("na aba ___ da ___"), e o modelo às vezes preenche o vazio com uma
  palavra órfã da própria frase (reproduzido 3/3: `valor: "aba"`). As travas
  abaixo fazem isso virar aviso visível em vez de resposta errada calada, mas
  **quem elimina a causa é o item 12** — com planilha/aba escolhidas por
  dropdown, a mensagem nunca contém nome nenhum, então não há o que remover
  nem buraco pra preencher.
- [x] **Truncamento silencioso em 20 linhas** — **✅ corrigido**.
  `executar_consulta()` agora devolve `(resultado, avisos)` e informa
  "Mostrando as primeiras 20 de N linhas encontradas". Quando o **usuário**
  pediu o limite explicitamente, não há aviso — o corte foi o que ele pediu,
  não uma surpresa.
- [x] **`indexar.py` ignora `MODELO_EMBEDDING` do `config.py`** — **✅
  corrigido**, passa a usar a constante.
- [x] **Dois endpoints de embedding diferentes** — **✅ padronizado**.
  `perguntar.py` migrou do endpoint legado `/api/embeddings` para `/api/embed`,
  o mesmo da indexação (confirmado no teste: vetor de consulta agora sai com
  norma 1.0, e as buscas continuam trazendo o conteúdo certo). Como medido
  antes, isso **não era bug** — era armadilha esperando uma mudança de métrica
  pra virar um.
- [x] **`LIKE` com caminho de pasta cru — RESOLVIDO em 2026-08-25** (era o
  único item aberto desta lista; documento não tinha sido atualizado até
  agora, 2026-08-27 — achado relendo os dois arquivos de ponta a ponta a
  pedido do usuário). `catalogar_arquivos.py`: `WHERE caminho LIKE
  'C:\...%'` — `_` é curinga de um caractere dentro do `LIKE` no SQLite
  (catalogar `D:\Meus_Documentos` casaria com `D:\MeusXDocumentos`), e
  prefixo de string sem checar limite de pasta casava `...\Desktop` com
  `...\Desktop2`. Confirmado como bug real (não teórico) simulando o
  `LIKE` cru direto no SQLite antes de corrigir. Corrigido com
  `_caminho_esta_sob_pasta()` — comparação de string exata em Python ("é a
  pasta OU começa com a pasta seguida de uma barra real"), sem depender de
  `LIKE` pra essa checagem em `catalogar_pasta()` nem em `listar_pasta()`.
  Ver `PENDENCIAS.md` pro relato completo, incluindo um segundo bug
  descoberto no mesmo código em 2026-08-26 (raiz de disco gerando barra
  dupla, limpeza de fantasma nunca rodando pra nada catalogado sob `D:\`).

### Consulta sem filtro nenhum agora se anuncia (2026-08-20)

Achado pelo usuário usando a interface: "liste meus últimos vídeos assistidos"
devolveu os 4000 registros do histórico, com cara de resposta. Diagnóstico
medido: **não é erro do extrator** — as colunas do histórico são `titulo`,
`url`, `data_visita`, `origem`, e **nenhuma diz o que é um vídeo**. O modelo só
filtra quando a palavra existe no dado; dizendo "no youtube" ele acerta o
filtro na hora.

**Categorizar por domínio foi proposto e recusado pelo usuário**, com o
argumento certo: seria uma lista de casos isolados (`youtube.com/watch`,
`crunchyroll`, `twitch`...), plataforma nova nunca entraria sozinha, e isso é
*catalogar o que já conhecemos* em vez de identificar de verdade — a mesma
armadilha do few-shot, em forma de tabela. Fica como está: o usuário é
específico na pergunta.

**O que foi feito**: quando uma consulta (`listar`/`contar`) roda **sem nenhum
filtro**, a resposta passa a dizer isso — que cobre todos os N registros da
fonte, não um recorte da pergunta — e sugere como pedir o recorte. Não vale
para `somar`/`media` (soma total sem filtro é pedido normal) nem para
transcrição (`avisar_sem_filtro=False`: transcrever é mostrar tudo por
definição, ali "sem filtro" é o certo, não um alerta).

Medição que motivou tudo isso, guardada porque é útil: filtrar por "youtube"
**também** estaria errado — pega 853 linhas, sendo só 415 vídeos de verdade
(`youtube.com/watch`); o resto é home/busca/feed. E deixaria de fora 183
acessos ao Crunchyroll.

### Bugs novos, achados durante a própria correção (todos ✅ corrigidos)

Nenhum destes estava na lista original — apareceram porque testar a correção
com dado real exercitou caminhos que nunca tinham sido percorridos:

- **`contem` interpretava o valor do filtro como EXPRESSÃO REGULAR** (bug
  pré-existente, desde que o filtro `contem` existe). `str.contains()` do pandas
  tem `regex=True` por padrão, e o valor vem de texto livre do usuário:
  um `?` ou `(` derrubava a consulta inteira com `ArrowInvalid` (aconteceu de
  verdade no teste), e um `.` casava errado calado — "Apple Inc." casaria com
  "AppleXInc". Corrigido com `regex=False`: a intenção sempre foi busca literal
  de substring.
- **Filtro com valor vazio ou só pontuação corrompia o resultado em silêncio**:
  combinado com a conversão automática `==` → `contem`, um `valor: ""` virava
  `str.contains("")`, que casa com quase toda linha não-nula — uma aba de 274
  linhas respondeu 67. Corrigido com trava em `aplicar_filtros`: valor `None`,
  vazio, ou sem nenhum caractere alfanumérico é descartado. Regra deliberadamente
  linguagem-agnóstica (`isalnum` cobre qualquer alfabeto Unicode) — remover a
  palavra "aba"/"sheet" do texto teria sido remendo de idioma, que quebra assim
  que alguém escrever em inglês.
- **"0 resultados" deixou de ser resposta muda** (isto também resolve o item 1
  do `PENDENCIAS.md`, o caso M/F): quando um filtro zera uma tabela que não
  estava vazia, a resposta passa a incluir qual filtro não bateu e, se a coluna
  for categórica (≤15 valores distintos), **quais valores existem de verdade**.
  Era exatamente a correção já imaginada no `PENDENCIAS`: o usuário pergunta
  "quantos são homens" numa coluna que guarda "M"/"F", e em vez de "0" recebe
  "os valores que existem nessa coluna são: 'M', 'F'". Coluna de alta
  cardinalidade não despeja a lista, só informa quantos valores distintos há.

## Ciclo de validação: quando o usuário entra para testar (2026-08-21)

Divisão de trabalho combinada com o usuário, para não desperdiçar o teste humano
nem confiar só no teste automatizado:

- **Claude** implementa e valida com os próprios testes (automatizados, stress
  tests, casos de borda) a cada mudança.
- **O usuário** entra com **"perguntas humanas"** — uso real, linguagem livre —
  quando um **bloco de funcionalidades principais** estiver construído, e não a
  cada item da fila. O sinal de que chegou a hora: naquele bloco só faltam
  ajustes estéticos e de QOL.
- A validação humana **não isenta** os testes automatizados (o usuário deixou
  explícito). São camadas somadas, não alternativas.

Motivo: chamar o usuário item a item desperdiça o tipo de achado que só uso real
produz; não chamá-lo nunca deixa passar bugs que só a linguagem natural expõe —
no próprio projeto, perguntas de negócio reais ("quantos são homens", "liste meus
vídeos") acharam bugs que testes mecânicos ("quantas linhas tem") jamais achariam.
Claude deve **avisar proativamente** quando um bloco estiver pronto para essa
rodada.

## Achados da 1ª bateria de testes humanos (2026-08-22)

> Primeira rodada de teste humano depois do item 12. O usuário usou a interface
> de verdade e trouxe anotações misturando bugs, ideias e dúvidas — separadas
> abaixo, porque cada tipo tem tratamento diferente. Registrado **antes** de
> qualquer correção, a pedido do usuário: a sessão já caiu duas vezes neste dia,
> e o que estivesse só na conversa se perderia.

### Bugs encontrados

- [x] **B1 — CORRIGIDO em 2026-08-22. Crash ao trocar de formato com um alvo já escolhido** (`interface.py`).
  `InvalidFileException: openpyxl does not support .docx file format`, em tela
  cheia. Reprodução: Consultar → Documento → escolher um `.docx` → "Trocar
  formato/fonte" → Planilha Excel. Causa: `trocar_formato()` limpa o formato e a
  conversa, mas **não** chama `limpar_alvo()` — o `.docx` sobrevive em
  `funil_arquivo`, a rota de planilha o encontra preenchido, pula o dropdown e
  entrega o arquivo errado ao `openpyxl`. **Introduzido por mim no item 12**:
  pus `limpar_alvo()` no botão de trocar *categoria* e esqueci no de trocar
  *formato* — e o teste cobriu exatamente a transição que eu lembrei, não a
  irmã. Correção: chamar `limpar_alvo()` em `trocar_formato()`, mais defesa em
  profundidade (validar extensão do alvo antes de usá-lo como planilha e tratar
  erro de leitura na interface, para arquivo ilegível não derrubar a página).
- [x] **B2 — CORRIGIDO em 2026-08-22. Loop fechado: o sistema sugere uma ação impossível no caminho
  atual**. O usuário pediu transcrição de um trecho, a trava de cobertura
  recusou e sugeriu *"tente uma pergunta normal (ex: 'o que o livro conta sobre
  segurança pública')"*. Ele digitou exatamente isso e recebeu **a mesma
  recusa** — porque em "Criar + Documento" (`jarvis.py`) **tudo** vai para
  `transcrever_arquivo()`: não existe rota de pergunta ali. A mensagem
  (`resumir.py`) foi escrita quando o terminal decidia a rota sozinho e nunca
  foi revista depois do funil. **Regra adotada: mensagem de erro só pode sugerir
  ação alcançável a partir do caminho em que o usuário está.**
- [x] **B3 — CORRIGIDO em 2026-08-22. Filtro aplicado na coluna errada** (`consultar_dados.py`). "Quais
  foram meus últimos vídeos assistidos?" gerou filtro em `origem` (a coluna que
  guarda de qual PC veio o dado) procurando "youtube"; a coluna certa era `url`.
  O prompt do extrator manda só os **nomes** das colunas, sem dizer o que cada
  uma contém. **O aviso criado em 2026-08-20 funcionou como devia** — mostrou
  "os valores que existem nessa coluna são: 'pc-casa'", tornando o erro visível
  em vez de devolver "0 resultados" com cara de fato. Correção proposta
  (determinística): quando um filtro não bate com nenhuma linha, verificar se o
  valor existe em **outra** coluna; se existir em exatamente uma, refazer ali e
  dizer o que foi feito; se em várias, listar. Não é a IA adivinhando — é código
  conferindo onde o dado está.
- [x] **B4 — CONFERIDO em 2026-08-22. Veredito: os temas existem, mas há
  distorção real por fusão de trechos.** O usuário anotou "não sei se está
  correto" — ele **não** afirmou que houve alucinação, disse que não conhecia o
  conteúdo completo do livro. O livro foi então lido direto (PyMuPDF) e cada
  afirmação foi checada contra o texto.

  - **Todos os 13 temas citados existem no livro** — PEC 188/2019 (pág. 15),
    Consolidação Municipal (14-15), terras raras (31-43), BNDES (39-42), IPHAN e
    tombamentos (28), Lei Rouanet 8.313 (27-28), Kim Kataguiri e PEC de Transição
    (10, 27), regulação da mídia (29), Minha Casa Minha Vida (48-49), crime
    organizado (10-48). **Nada foi inventado do nada.**
  - **"13 propostas" tem respaldo** (páginas 45 e 47), mas o sumário lista
    **14 capítulos** (I a XIV): a resposta misturou níveis — "propostas
    estratégicas" e "capítulos" não são a mesma coisa.
  - **DUAS afirmações estão distorcidas**, e do tipo mais perigoso: pedaços
    verdadeiros de partes diferentes do livro, colados numa frase só que soa
    plausível.

    | | Livro (original) | Resposta do Jarvis |
    |---|---|---|
    | 1 | "...aproximadamente 20 bilhões de reais **ao longo de uma década**" (pág. 40, terras raras) | "...20 bilhões ao longo das décadas **do plano de governo da candidatura Arthur do Val à prefeitura de São Paulo em 2020**" |
    | 2 | "código unificado de imprensa ... eliminar **as lacunas legais que geram insegurança jurídica**" (pág. 29) | "código unificado de imprensa ... eliminar **as distorções anuais, minando a capacidade do Estado de investir em defesa**" |

    "Arthur do Val / prefeitura de São Paulo" existe — na página **28**, sobre
    cultura e IPHAN. "Minando a capacidade do Estado de investir em defesa"
    existe — na página **44**, sobre o custo do crime organizado. Ou seja: o
    modelo **não inventou fatos, recombinou fatos verdadeiros de contextos
    diferentes** — mais difícil de detectar do que invenção pura, porque cada
    metade da frase resiste a uma checagem superficial.

  **Consequência para a fila (decidida com o usuário em 2026-08-22):** o **item
  14 (self-check)** passa a ser **tão urgente quanto o item 21 (localizar
  seção)** era na época. Não é polimento: é o sistema afirmando com confiança
  coisas que o documento não diz. **Item 21 resolvido em 2026-08-25** (ver
  acima); item 14 continua em aberto, sem essa comparação relativa mudar sua
  urgência própria.

  **Nota de método:** o usuário estava certo em recusar o rótulo "alucinação"
  antes de conferir. Fica o precedente: diante de dúvida sobre veracidade, ler a
  fonte e comparar item a item — não discutir se a resposta *parece* plausível.

### Decisões técnicas tomadas nesta rodada

- **M1 — Localizar a SEÇÃO de um documento sobre um tema** (levantado pelo
  usuário). **Investigado a fundo em 2026-08-22, promovido a item próprio da
  fila, e ✅ RESOLVIDO em 2026-08-25** como efeito colateral do rework de
  Camada 1-3 (não foi desenhado especificamente pra isso — ver "Reconfirmado
  em 2026-08-25" no fim deste bloco). Histórico completo mantido abaixo
  porque continua sendo a referência certa se um caso parecido (achar algo
  por significado, sem estrutura de documento pra apoiar) aparecer de novo —
  **não repetir os experimentos já feitos aqui**.

  **O caso que motivou:** o usuário pediu "transcreva a parte sobre segurança
  pública" no `livro-amarelo-resumo-2026.pdf` e o sistema recusou alegando que o
  termo "aparece espalhado por 90% do documento". Mas existe um capítulo
  dedicado — `II PRENDEU, MATOU? SEGURANÇA PÚBLICA`, páginas **11 a 13**
  (confirmado pelo usuário e pelo texto).

  **Fato central descoberto, que invalida a abordagem por palavra:** o termo
  "segurança pública" aparece **7 vezes no livro inteiro** — páginas 2 e 8
  (sumário/divisória), 6, 11 (2×), 39 e 46. **Dentro do capítulo dedicado
  (11-13) ele aparece só na página 11.** As páginas 12 e 13 tratam do assunto
  usando outras palavras: "violência", "narcoestado", "facções", "polícias". O
  título impresso na página 11 é "PRENDEU, MATOU?"; o rótulo "SEGURANÇA PÚBLICA"
  vive no sumário. **Conclusão: nenhuma métrica baseada no termo literal acha
  essa seção** — nem contagem, nem densidade, nem janela de concentração. O que
  liga a pergunta ao capítulo é significado, não vocabulário.

  **Resultado dos experimentos (o que NÃO funciona, com o porquê):**

  | Método | Resultado |
  |---|---|
  | Janela de concentração de ocorrências | ❌ Não separa. Medido: "sr jones" em Revolução dos Bichos deu razão de concentração **8.48** — mais concentrado que "segurança pública" (**2.70**), que é o caso que deveria ser reconhecido como seção. E a janela achada para "segurança pública" foi páginas 2-11, que **é o sumário até o começo do capítulo**, não o capítulo. |
  | Índice embutido do PDF (`fitz.get_toc()`) | ❌ **Nenhum dos 5 PDFs do acervo tem** bookmarks. Verificado um a um. |
  | Estilos de título no DOCX (`Heading`) | ❌ **Nenhum dos 3 DOCX tem**: todos os parágrafos usam o estilo `normal`. Só `Basic Primary_Secondary Modding.docx` tem quebras de página manuais (5); os outros têm zero. |
  | Sumário em texto | ⚠️ Existe neste livro, mas o usuário levantou objeções corretas: depende de o documento ter sumário, do formato e do idioma. Descartado como mecanismo principal. |

  **Método que se mostrou promissor em 2026-08-22 (na época, parcial):** busca
  semântica + contiguidade — perguntar "quais trechos *falam sobre isso*" (RAG
  já existente) e verificar de forma determinística se formam bloco contíguo.
  Medição da época:

  | Consulta | Top-5 (páginas) | Veredito (2026-08-22) |
  |---|---|---|
  | "violência e crime organizado" | **10, 11, 13, 11, 12** | acerta o capítulo em cheio |
  | "segurança pública" | 18, 46, 4, 12, 11 | falha (espalhado) |
  | "os animais da fazenda" (contraste) | 100, 45, 44, 76, 104 | corretamente espalhado |

  Na época, a busca acertava quando a consulta descrevia o **conteúdo** e
  errava quando usava o **rótulo** do capítulo — RAG puro (top-5 fixo, sem o
  resto do pipeline) não bastava sozinho pra fechar o caso do rótulo.

  **Erro de método cometido no caminho (registrado para não repetir):** a
  primeira medição pegou o `top-15` e mediu o espalhamento dos 15 — os últimos
  colocados têm relevância baixa e poluem a conta, escondendo o bloco real. A
  segunda tentativa cortou por similaridade relativa (min/max) e ficou agressiva
  demais, sobrando 1 trecho. **O que finalmente mostrou o quadro foi olhar o
  ranking cru, em ordem de relevância, com as distâncias** — o diagnóstico mais
  simples, que deveria ter vindo primeiro.

  **✅ Reconfirmado em 2026-08-25, resolvido — não é mais busca "parcial".** O
  rework de Camada 1-3 (`reunir_contexto()`: busca ampla, corte relativo,
  busca literal híbrida, filtro de isolamento, vizinhança adaptativa,
  agrupamento contíguo, leitura em passada única) é exatamente o resto do
  pipeline que faltava em volta da busca semântica de 2026-08-22 — não foi
  desenhado pensando neste item, mas resolveu o mesmo problema de raiz.
  Reteste contra o mesmo caso canônico (`livro-amarelo-resumo-2026.pdf`,
  banco de produção, pipeline atual):

  | Consulta | Resultado |
  |---|---|
  | "o que o livro conta sobre segurança pública?" (o **rótulo** que falhava) | ✅ achou e nomeou os capítulos certos ("PRENDEU, MATOU?", "QUEM PAGA A BANDA...") |
  | "o que o livro diz sobre violência e crime organizado?" (conteúdo) | ✅ continua acertando |

  O caso do rótulo, que falhava em 2026-08-22, passou a funcionar sozinho.
  As alternativas cogitadas então (tipografia, segmentação semântica por
  embeddings/TextTiling) ficam **abandonadas, não precisam ser retomadas** —
  o caminho que já existia (busca semântica) só precisava do resto do
  pipeline em volta, que agora existe. A recusa por tema genuinamente diluído
  continua correta e não muda (medido em 2026-08-22: "os animais da fazenda"
  espalha por 66% do livro) — isso nunca foi o problema, o problema era só o
  caso rótulo↔conteúdo.

  **Ressalva honesta:** confirmado com um caso (o canônico, que é também o
  mais difícil já medido). Vale um olho extra durante as baterias de teste já
  planejadas, não porque haja sinal de falha, mas porque uma reconfirmação
  não é a mesma coisa que uma bateria formal.
- **M2 — Recorte em `.docx` deve usar a estrutura que o arquivo realmente tem**
  (levantado pelo usuário: "o doc tem separações visuais, por que não consegue
  distinguir?"). **Correção de um registro anterior deste documento**: dizer que
  "DOCX não tem paginação" era incompleto. O que o formato não guarda é a quebra
  de página **automática** (o Word a calcula ao renderizar, variando com fonte,
  margem e impressora). Mas o arquivo **guarda** quebras de página **manuais**
  (`w:br w:type="page"`), quebras de **seção** (`w:sectPr`) e **estilos de
  título** (`Heading 1/2/3`) — tudo legível pelo `python-docx`, já usado no
  projeto. Ordem de preferência decidida: **(1) títulos** como recorte principal
  ("a seção Configurações Iniciais" é mais útil e mais honesto que "página 3"
  num documento técnico, e casa com M1); **(2) quebras manuais** como
  aproximação de página; **(3) paginação sintética por tamanho** (a ideia do
  usuário de "X palavras = 1 página") apenas como último recurso **e sempre
  declarada como aproximação** — se o sistema disser "página 3" e o usuário
  abrir o Word, a página 3 dele será outra, e essa correspondência falsa é pior
  que admitir que o formato não pagina. Escolha final depende de inspecionar os
  `.docx` reais do usuário. **Resolve de quebra** a pendência do `PENDENCIAS.md`
  sobre filtro de página ignorado em silêncio em DOCX.

### Catálogo: exclusão de lixo técnico (2026-08-22)

Achado por um **teste automatizado**, não por queixa do usuário: `listar_pasta("Docs")` passou a
responder *"Mais de uma pasta corresponde: ['Docs', 'block_docstring']"*. Investigando, o
catálogo estava com **152.012 arquivos** — o usuário havia adicionado o disco `D:\` inteiro pela
interface, e a varredura arrastou junto ~20.000 arquivos de `site-packages`, 8.201 de
`__pycache__` e a lixeira do Windows.

**Corrigido** com `PASTAS_IGNORADAS` + `deve_ignorar_pasta()` em `catalogar_arquivos.py`, podando
a árvore dentro do `os.walk` (altera a lista de subpastas no lugar, então nem desce no ramo).

**Exclusão por NOME de pasta, nunca por caminho — exigência do usuário**: `__pycache__` se chama
assim em qualquer máquina, enquanto uma exceção tipo `D:\jarvis-pessoal\venv` deixaria de valer
no dia em que o projeto mudasse de lugar ou fosse para outro PC. O prefixo `$` cobre as pastas de
sistema do Windows (`$RECYCLE.BIN`, `$WinREAgent`), que mudam de nome mas seguem o padrão.

**Resultado medido — e o que ele NÃO resolveu:**

| | Antes | Depois |
|---|---|---|
| Arquivos no catálogo | 152.012 | 131.455 |
| `site-packages` / `__pycache__` | 19.980 / 8.201 | 0 / 0 |
| Varredura (roda a cada busca) | 9,8s | **8,8s** |

A limpeza resolveu a **poluição das buscas** (o caso "Docs"), mas **não a lentidão**: o ganho foi
de apenas 1 segundo, porque os 131 mil arquivos restantes são arquivos reais do disco do usuário.
A demora vem do volume do disco, não do lixo. **Fica em aberto**: `garantir_catalogo()` revarre
todas as pastas configuradas a cada busca — desenho deliberado (catálogo nunca desatualizado, sem
arquivo fantasma), que custava ~1s com Desktop+Docs e passa a custar ~9s com um disco inteiro.
Para atacar isso seria preciso revarrer por intervalo ou sob comando, mudando aquela decisão.

**Nota de método:** este problema não apareceu no uso real porque, desde o item 12, a interface
escolhe pasta por **dropdown** — a busca por nome digitado só é usada pelo terminal. Ou seja: o
teste automatizado pegou algo que o teste humano não pegaria, o que é exatamente a divisão de
trabalho combinada.

### Ideias do usuário — pauta de discussão (não implementar sem discutir)

Registradas para não se perderem; o usuário pediu explicitamente para debater as
implicações antes de qualquer implementação:

1. **Subcategorizar transcrição em botões** (inteiro / por página / por trecho),
   estendendo o Princípio #2. "Inteiro" e "por página" ficariam 100% sem LLM. O
   mesmo padrão serviria para Consultar+Documento (pergunta/resumo/contagem),
   eliminando mais um classificador. Ponto de atenção: com botão, a limitação de
   paginação do DOCX fica exposta (ou desabilita, ou promete o que não entrega).
2. **Esconder fonte vazia/sem dado no funil** (opção escolhida pelo usuário
   entre as alternativas): não oferecer "Planilha Excel" se não há nenhum
   `.xlsx`. Atenção: botão que simplesmente some confunde — talvez melhor
   desabilitado com o motivo visível.
3. **Ícones de upload / abrir pasta no catálogo de arquivos**. Upload é seguro
   (reaproveita o fluxo existente). **"Abrir a pasta no PC" tem armadilha**: o
   Streamlit abriria a pasta **no servidor**, não no computador de quem acessa.
   Hoje é a mesma máquina e funciona, mas quebra em silêncio se o Jarvis for
   aberto de outro dispositivo — e a interface já é servida na rede local.

### Investigação pedida pelo usuário

- [ ] **O histórico de navegação vale a pena no plano geral?** Dados já medidos:
  4000 entradas indexadas, das quais 415 são vídeo de fato
  (`youtube.com/watch`), 853 batem em "youtube" (incluindo home/busca/feed), 183
  Crunchyroll, 7 Twitch, 2 Netflix. Limitações conhecidas: não há campo que diga
  "isto é um vídeo"; site de página única repete título/URL genéricos; listagem
  cronológica é algo que o próprio navegador já faz melhor. A investigar: quais
  perguntas ele responde bem **e que o navegador não responde** (busca semântica
  por assunto, cruzamento com documentos) versus o custo de manter (reindexação,
  4000 entradas no mesmo banco dos documentos, risco de contaminar busca de
  documento). Entregar recomendação: manter, reduzir escopo, ou tirar do funil.

## Implementar em outro PC

> Revisado em 2026-08-29 contra o estado real do projeto. A versão anterior
> tinha um erro que quebraria a instalação (mandava baixar
> `nomic-embed-text`, substituído por `mxbai-embed-large` em 2026-08-25) e
> não cobria LibreOffice, o travamento do Streamlit no primeiro uso, nem a
> rota via GitHub.

### Antes de tudo: decidir COMO levar

São duas rotas, com propósitos diferentes:

| | Pen drive / HD externo | GitHub |
|---|---|---|
| Leva os documentos e o índice já pronto | Sim | **Não** (e não deve) |
| Precisa reindexar no PC novo | Não | Sim |
| Serve pra mostrar o projeto pra outra pessoa | Sim | Sim |
| Precisa instalar Git | Não | Sim (**não está instalado neste PC**) |
| Tamanho | ~300 MB | ~1 MB (só código) |

**Aviso sério pra rota GitHub**: a pasta do projeto contém dados pessoais que
NÃO podem ser publicados — `catalogo_arquivos.db` (56 MB, listagem de todos
os arquivos do PC, com nome e caminho completo), `historico_temp.db` (11 MB,
histórico de navegação), `Docs/` (77 MB, documentos pessoais) e
`banco_vetorial/` (158 MB, embeddings de onde o conteúdo é recuperável).
Por isso existe o `.gitignore` na raiz — ele exclui exatamente esses.
**Confira com `git status` antes do primeiro commit**: o que aparecer ali é o
que vai pro mundo. (O `.gitignore` foi escrito em 2026-08-29 mas NÃO pôde ser
testado de verdade — não há Git instalado nesta máquina.)

### Pré-requisitos no PC novo
1. **Python 3.14** (versão desta máquina: 3.14.2)
2. **Ollama**: https://ollama.com/download
3. Baixar os **três** modelos (todos obrigatórios — sem o auxiliar o resumo
   não roda; sem o de embedding nada é indexado nem buscado):
   ```powershell
   ollama pull llama3.1:8b
   ollama pull llama3.2:3b
   ollama pull mxbai-embed-large
   ```
   ⚠️ É `mxbai-embed-large`, **não** `nomic-embed-text` (trocado em
   2026-08-25). Misturar os dois não dá erro claro: a dimensão do vetor muda e
   o ChromaDB rejeita a coleção — se o `banco_vetorial/` veio junto, ele foi
   construído com o `mxbai`.
4. **LibreOffice** (`winget install TheDocumentFoundation.LibreOffice`) —
   usado pra converter `.docx` e conseguir página real. Sem ele o sistema não
   quebra, mas todo `.docx` volta a ser "página 1" inteiro.
5. (Opcional) VS Code.

### Levando o projeto

**Rota pen drive** — copie a pasta inteira, **incluindo** `Docs/`,
`banco_vetorial/`, `catalogo_arquivos.db`, `pastas_catalogadas.json`, os
`.py`, `requirements.txt`, `pytest.ini`, `iniciar_jarvis.bat`, `tests/` e
`Planos/` (`ARQUITETURA_V2.MD` + `PENDENCIAS.md`).
**Não copie**: `venv/` (recriar do zero — caminhos absolutos dentro dele
apontam pro PC antigo), `__pycache__/`, `.pytest_cache/`, `transcricoes/`
(saída gerada), os `.log`.

**Rota GitHub** — instale o Git, e então:
```powershell
git init
git add -A
git status          # CONFIRA aqui: nenhum .db, nenhum Docs/, nenhum banco_vetorial/
git commit -m "Jarvis Pessoal"
git branch -M main
git remote add origin <url-do-repo>
git push -u origin main
```
(`git branch -M main` evita a pegadinha do nome do ramo: Git antigo cria
`master`, Git novo cria `main`, e o GitHub espera `main` — renomear antes do
push resolve os dois casos.)
No PC novo, `git clone` traz só o código: `Docs/` chega vazio e
`banco_vetorial/` não existe, então é obrigatório rodar `python indexar.py`
depois de colocar documentos em `Docs/`.

### Recriando o ambiente Python
```powershell
python -m venv venv
.\venv\Scripts\Activate
pip install -r requirements.txt
```
Isso já traz o modelo gramatical do spaCy (`pt_core_news_lg`, declarado por
URL no `requirements.txt`) — não precisa de `spacy download` separado.

### Destravando o Streamlit (obrigatório, senão ele não sobe)
Na primeira execução o Streamlit pede um e-mail no terminal e **fica
esperando input pra sempre** — o servidor nunca sobe, sem mensagem de erro.
Achado em 2026-08-29 testando o `iniciar_jarvis.bat`. Crie o arquivo
`C:\Users\<seu-usuario>\.streamlit\credentials.toml` com:
```toml
[general]
email = ""
```

### Ajustando o `config.py`
- `CAMINHO_HISTORICO_BRAVE` — muda conforme o usuário do Windows no PC novo
- `PASTAS_CATALOGADAS` — ajustar pras pastas relevantes do PC novo.
  **Atenção**: isso é só o padrão da primeira execução. Se
  `pastas_catalogadas.json` veio junto, é **ele** que vale, e estará com os
  caminhos do PC antigo — ou apague o JSON (o config volta a valer), ou ajuste
  as pastas pela própria interface, na barra lateral
- `IDENTIFICADOR_MAQUINA` — trocar pra identificar o PC novo (ex: "pc-viagem").
  Distingue a origem do histórico quando vários PCs indexam no mesmo banco
- `NUM_CTX` / `NUM_CTX_AMPLIADO` — os valores atuais foram medidos numa RTX
  4070 de 12 GB. Placa com menos VRAM precisa baixar (ver as tabelas de medição
  comentadas no próprio `config.py`)

### Testando
```powershell
ollama --version
python indexar.py            # indexa os documentos de Docs/ (incremental)
python indexar_historico.py  # opcional: indexa o histórico do Brave
pytest -m "not slow"         # 25 testes rápidos, ~5s — confere se o básico está de pé
streamlit run interface.py   # uso normal (ou duplo clique em iniciar_jarvis.bat)
python jarvis.py             # alternativa: mesmo sistema pelo terminal
```
O `iniciar_jarvis.bat` é o caminho recomendado pro uso normal: ativa o venv,
sobe a interface e mantém a janela aberta (fechá-la derruba o servidor). Ele
também é o que dispara o batimento que segura os modelos na VRAM
(`manter_modelo_quente.py`) — sem isso, a primeira pergunta depois de 5
minutos parado leva minutos em vez de segundos.