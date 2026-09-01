import os

PASTAS_CATALOGADAS = [
    r"C:\Users\Foda\Desktop",
    r"D:\jarvis-pessoal\Docs",
]

# --- Caminhos (únicas coisas que normalmente mudam entre PCs) ---
PASTA_DOCUMENTOS = "Docs"
PASTA_BANCO_VETORIAL = "banco_vetorial"

# Formatos aceitos na zona controlada (Docs/) — centralizado aqui (2026-08-28, achado real: só
# existia dentro de interface.py, e catalogar_arquivos.py também precisa saber quais formatos
# são indexáveis pro link "[indexar]" da listagem de pasta). Formatos modernos apenas — .doc/.xls
# antigos não são lidos, usuário converte pro formato novo no Word/Excel antes de enviar.
EXTENSOES_INDEXAVEIS = (".pdf", ".txt", ".docx")  # viram chunks + embedding, entram no RAG
EXTENSAO_PLANILHA = ".xlsx"  # relida direto, sem indexação (ver consultar_dados.py)
EXTENSOES_PERMITIDAS = EXTENSOES_INDEXAVEIS + (EXTENSAO_PLANILHA,)

# --- Modelos (podem mudar se o PC de destino tiver hardware diferente) ---
MODELO_LLM = "llama3.1:8b"
MODELO_LLM_AUXILIAR = "llama3.2:3b"  # tarefas mecânicas/intermediárias (ex: resumo de bloco) — mais rápido, menor
MODELO_EMBEDDING = "mxbai-embed-large"  # migrado de nomic-embed-text em 2026-08-25 (335M vs
# 137M parâmetros, +400MB VRAM) — decisão por avaliação externa de benchmark, ver ARQUITETURA.md
# ("mxbai-embed-large adotado no lugar de nomic-embed-text"). Exige reindexar tudo (documentos E
# histórico de navegação) do zero — dimensão do vetor muda, ChromaDB não aceita mistura na mesma
# coleção. Não trocar sem também apagar/reconstruir a coleção `documentos_pessoais` inteira.

# --- Parâmetros de processamento ---
TAMANHO_CHUNK = 500
SOBREPOSICAO = 50
TAMANHO_LOTE_EMBEDDING = 50
VERSAO_PIPELINE = "v6-docx-libreoffice"  # achado real 2026-08-25: extrair_texto_docx() sempre
# devolvia página fake ([0], tudo "página 1"); agora .docx é renderizado de verdade via
# LibreOffice headless (converter_docx_para_pdf) e reaproveita extrair_texto_pdf() no resultado
# — página real, e a tabela ganha a mesma detecção/prosa estruturada já validada pro PDF. Bump
# força reindexar TODOS os DOCX já catalogados com a extração nova (v5 era sobre PDF: get_text()
# achatava tabela numa sequência linear de números sem coluna/linha, ver histórico completo em
# PENDENCIAS.md/ARQUITETURA.MD — segue valendo, só a razão do bump mudou).

# --- Comportamento de consulta ---
# Janela de contexto do modelo. Subiu de 8192 para 16384 em 2026-08-22, depois de MEDIR o teto
# real desta máquina (RTX 4070, 12GB):
#   num_ctx  |  tempo  |  VRAM do principal  |  livre
#     8.192  |   9,0s  |       5,53 GB       | 4.178 MB
#    16.384  |  11,2s  |       6,54 GB       | 3.142 MB
#    32.768  |  13,9s  |       8,44 GB       | 1.213 MB
# 32k funciona (coube o steam.pdf inteiro, 37 páginas, com resposta correta), mas com os três
# modelos carregados juntos daria ~11,6 GB de 12,28 GB — a mesma armadilha que fez o Qwen2.5:14b
# ser descartado. 16k deixa ~2,5 GB de folga e custa só ~2s a mais por resposta.
# ATENÇÃO ao aumentar: o custo de VRAM é do MODELO PRINCIPAL, e o auxiliar (llama3.2:3b, 2,89 GB)
# mais o embedding (0,30 GB) podem estar carregados ao mesmo tempo — o resumo usa os dois em
# sequência. Medir com tudo carregado antes de subir.
NUM_CTX = 16384

# O espaço extra do NUM_CTX é para os TRECHOS DO DOCUMENTO, não para memória de conversa:
# TAMANHO_HISTORICO segue em 3 de propósito. Com o funil separando por função, cada conversa é
# curta e escopada (e é zerada ao trocar de categoria/fonte), então mais trocas só encheriam o
# prompt com material que não ajuda a responder. O problema que motivou o aumento foi fusão de
# trechos distantes do documento — falta de contexto do CONTEÚDO, não de histórico.
#
# QUANTIDADE_CHUNKS mudou de sentido no rework da busca (Camada 1, `reunir_contexto()` em
# `perguntar.py` — ver ARQUITETURA.md, "REWORK DA BUSCA E RESPOSTA"): deixou de ser o teto fixo
# de trechos entregues à IA e virou só o tamanho do POOL de candidatos que a busca ampla pede ao
# ChromaDB, antes do corte por relevância decidir quantos realmente entram. Subiu de 15 (5% de
# um livro de 311 trechos — causa raiz da falta de cobertura medida no B4) pra dar espaço a esse
# corte funcionar numa pergunta de cobertura. Ponto de partida, ainda não calibrado com teste
# real — ver "Pontos de calibragem" no plano do rework.
QUANTIDADE_CHUNKS = 60

# Corte por relevância (Camada 1, passo 2): mantém um candidato se a distância dele não passar
# de MELHOR_DISTANCIA * este fator (mais uma margem mínima, pro caso raro de melhor_distancia
# ser ~0). Ponto de partida — a calibrar medindo contra o livro amarelo.
LIMIAR_RELEVANCIA_FATOR = 1.3
LIMIAR_RELEVANCIA_MARGEM_MINIMA = 0.02

# Vizinhança adaptativa (Camada 1, passo 3): quanto MENOS trechos o corte de relevância ativou,
# MAIS vizinhos cada um ganha (falta contexto ao redor — pergunta pontual); quanto MAIS trechos
# já ativaram, MENOS vizinhos (cobertura já existe, expandir só infla o prompt à toa). O valor de
# JANELA_VIZINHANCA_MEDIA vem da tabela já MEDIDA (ARQUITETURA.md, seção "Vizinhança"): "8 × ±2"
# bateu 7 de 8 fatos de gabarito no livro amarelo — não é chute.
#
# JANELA_VIZINHANCA_LARGA subiu de 4 pra 8 (2026-08-24, achado real): com só 1 candidato ativado
# (busca por termo literal, pergunta "quais os cinco pilares do AgroBrasil 2030"), ±4 não foi
# longe o bastante — o bloco cortou NO MEIO DA FRASE do quarto pilar ("O quarto pilar é o salto
# na" — nada mais), porque o ponto de ancoragem (chunk que menciona "AgroBrasil 2030" de
# passagem, na introdução) ficava ANTES de onde os pilares são listados, "gastando" metade da
# janela só pra chegar lá. O modelo completou a frase cortada com um chute e reaproveitou uma
# frase do pilar 1 fingindo ser o pilar 5. Dobrar a janela é seguro aqui porque é justamente o
# caso com MENOS candidatos ativados — sobra orçamento de contexto de sobra (NUM_CTX não chegou
# perto do limite em nenhum teste até agora).
JANELA_VIZINHANCA_LARGA = 8
JANELA_VIZINHANCA_MEDIA = 2
JANELA_VIZINHANCA_ESTREITA = 0

# Limiar que decide a janela (achado real, 2026-08-24, "quantos morreram em Uauá?" no Os
# Sertões): os valores 6 e 12 abaixo foram calibrados como número ABSOLUTO no livro amarelo (311
# chunks) — mas um número absoluto não escala pro tamanho do documento. Em Os Sertões (2.253
# chunks), 19 ativados (0,84% do livro, proporcionalmente escasso) já passava de 12 e caía direto
# em janela estreita (0), o que impediu a vizinhança de alcançar um chunk com o fato certo que
# estava só 6 posições do candidato mais próximo ativado — JANELA_VIZINHANCA_LARGA (8) teria
# alcançado, mas nunca foi escolhida.
# Por isso o limiar agora é o MAIOR entre um piso absoluto (protege documento pequeno — mesmo
# comportamento de antes, calibrado no livro amarelo) e uma fração do total de chunks do arquivo
# (protege documento grande, escala com o tamanho). As frações (2% e 4%) são a proporção que os
# valores antigos (6 e 12) representavam no livro amarelo — não são chute, são o mesmo ponto de
# calibração reexpresso de forma que generalize. Deliberadamente abaixo de 5%: passar disso
# esvaziaria a distinção entre pergunta pontual e de cobertura em documentos muito grandes. Ainda
# não testado contra um documento múltiplas vezes maior que Os Sertões — pendência conhecida.
LIMIAR_ATIVADOS_VIZINHANCA_LARGA_PISO = 6      # documento pequeno: nunca menos que isso
LIMIAR_ATIVADOS_VIZINHANCA_LARGA_FRACAO = 0.02   # documento grande: 2% do total de chunks
# Raio de proximidade entre chunks. Nasceu pra fusão de sub-perguntas (2026-08-25, "quantos
# soldados e quantos jagunços morreram em Uauá?", Os Sertões, 2.253 chunks): piso protege
# documento pequeno, fração escala com o tamanho. **Desde 2026-08-29 a fusão NÃO usa mais isto**
# (passou a medir sobreposição de conjunto, ver LIMIAR_SOBREPOSICAO_SUBPERGUNTAS abaixo) — o uso
# que resta é o refino da busca literal em `buscar_por_termo_literal()` (fica só com os chunks de
# entidade que estão perto de algum chunk de conteúdo). O nome ficou herdado do uso antigo.
RAIO_FUSAO_SUBPERGUNTA_PISO = 16
RAIO_FUSAO_SUBPERGUNTA_FRACAO = 0.02

# Fusão de sub-perguntas (`responder_pergunta()`, perguntar.py): duas sub-perguntas são "a mesma
# coisa" quando o MATERIAL que elas ativam no documento se sobrepõe — não quando os textos delas
# se parecem, nem quando o trecho campeão de cada uma coincide.
#
# Achado real (2026-08-29, "qual a motivação da revolução?" no revolucao-dos-bichos.pdf): a régua
# anterior comparava só o chunk campeão de cada sub-pergunta. Uma ÚNICA palavra move esse
# campeão de ponta a ponta do livro — "quais as causas que levaram à revolução?" bate no chunk
# 409, e "quais FORAM as causas que levaram à revolução?" bate no 21 (mesmo livro, mesma
# pergunta pra um humano). Medida de um ponto só: quando 1º e 2º lugar estão quase empatados,
# qualquer palavrinha vira a disputa e a decisão inteira vira junto. Resultado: a divisão não era
# desfeita e o usuário recebia a mesma resposta escrita duas vezes.
#
# Medido nos dois caminhos antes de escolher (ver também nota do rework da busca):
#   - similaridade de TEXTO entre as sub-perguntas: NÃO separa. Par redundante
#     (motivação × causas) deu 0,79, enquanto um par legítimo ("tema do livro" × "quantas
#     páginas") deu 0,86 — mais alto. Qualquer corte quebraria um dos dois. Descartado.
#   - sobreposição (Jaccard) dos conjuntos ativados: separa com folga —
#     devem fundir: 0,304 / 0,333 / 0,310 | não podem fundir: 0,071 / 0,048 / 0,000.
# 0.15 fica no meio do vão (≈2x o maior "não" e ≈metade do menor "sim"). Custo zero a mais: os
# candidatos já eram buscados, só eram descartados menos o primeiro colocado.
LIMIAR_SOBREPOSICAO_SUBPERGUNTAS = 0.15

# --- Verificação da resposta contra a fonte (verificar_resposta.py) ---
# Verificação por NLI: DESLIGADA por medição (2026-08-29). Custo real ficou em +100 a 250s por
# resposta (decomposição em afirmações atômicas pelo LLM + NLI na CPU sobre trechos grandes), e
# o que ela pega não é o que erra na prática: acertou a contradição escancarada ("Major é um
# cavalo", 0,995) mas passou batido nos DOIS erros reais que apareceram nos testes — atribuir ao
# Major uma fala de Bola de Neve, e inventar a citação "Vamos criar uma sociedade de animais
# livres da fome e do chicote" (o trecho existe, mas é NARRAÇÃO sobre a expectativa da égua
# Quitéria, capítulos depois, e o "Vamos criar" não existe). NLI julga o CONTEÚDO da frase e é
# cego pra autoria e pra literalidade da citação. O código fica, desligado, pra retomar caso
# apareça hardware/modelo que mude a conta.
VERIFICAR_RESPOSTA_ATIVO = False

# Checagens MECÂNICAS da resposta (sempre ligadas — custam milissegundos, sem modelo nenhum).
# Base na literatura: "Deterministic Quoting" (verificar por consulta direta ao texto-fonte se a
# citação é substring literal) é prática estabelecida, e um estudo grande verificou 90,12% das
# linhas com evidência dessa forma. O princípio bate com o do projeto: a máquina confere o que é
# conferível, o humano julga o resto.
VERIFICAR_CITACOES_LITERAIS = True
VERIFICAR_ATRIBUICAO = True

# Uma citação da resposta só é cobrada se tiver pelo menos este tamanho: aspas em torno de uma
# palavra ou duas ("Homem", "a Revolução") são ênfase, não citação de trecho.
MINIMO_CARACTERES_CITACAO = 25

# Ao conferir "Fulano disse que X", procura o nome de Fulano nesta janela de caracteres em volta
# de X dentro do trecho de origem. Fala e nome do falante costumam estar próximos ("'Não', disse
# Bola de Neve firmemente"), mas nem sempre colados.
JANELA_BUSCA_FALANTE = 400

# Modelo de NLI multilíngue, roda em CPU (pequeno, texto curto, e roda DEPOIS da resposta —
# não disputa VRAM com o Ollama). Escolhido por medição em português, 2026-08-29:
# "O Major é um porco" -> entailment 0,996 | "O Major é um cavalo" -> contradiction 0,994 |
# "A fazenda fica na França" -> neutral 0,999. A variante `-mnli-xnli` (sem o 2mil7) errou o
# controle apoiado, dando "neutral" pra afirmação textualmente presente — por isso esta.
MODELO_NLI = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"

# Só CONTRADIÇÃO é marcada, e só acima deste limiar. "neutral" fica de fora de propósito: é
# ambíguo (pode ser invenção, ou só uma afirmação que está em OUTRO trecho), e marcá-lo encheria
# a resposta de alarme falso.
#
# 0.98 calibrado por medição (2026-08-29, ~17 afirmações atômicas contra trechos reais do
# revolucao-dos-bichos.pdf). Nessa amostra: as afirmações FALSAS foram marcadas com 0,993 a
# 0,999 (uma exceção em 0,545), e os falsos positivos ficaram em 0,757 / 0,902 / 0,969. Corte em
# 0.98 => **zero falso positivo, 6 dos 7 acertos**.
#
# Os falsos positivos não são aleatórios: todos vieram do mesmo trecho, de frase CONDICIONAL
# ("Livrem-se apenas do Homem, e os produtos de nosso trabalho seriam nossos"), fraqueza
# conhecida de NLI com hipotético — ele lê o "se" como negação do fato. Por isso o corte
# prioriza PRECISÃO: marcar resposta certa como errada corrói mais confiança do que o erro
# original, então é melhor perder detecção do que gritar à toa.
#
# **Ressalva honesta**: 0.98 foi ajustado contra ~17 medições, não contra um benchmark. É
# calibragem de amostra pequena, e pode não se sustentar em documento de outro tipo (técnico,
# planilha, histórico). Tratar como ponto de partida a revisar com mais casos reais.
LIMIAR_CONTRADICAO = 0.98

# Tetos de custo: a verificação roda em CPU a ~1,4s por par (afirmação × trecho). Sem teto, uma
# resposta longa contra um contexto grande viraria minutos. Conferir as primeiras afirmações
# contra os trechos mais parecidos cobre o caso que importa sem estourar o tempo.
MAXIMO_AFIRMACOES_VERIFICADAS = 8
TRECHOS_CONFERIDOS_POR_AFIRMACAO = 2
LIMIAR_ATIVADOS_VIZINHANCA_MEDIA_PISO = 12
LIMIAR_ATIVADOS_VIZINHANCA_MEDIA_FRACAO = 0.04   # 4% — deliberadamente < 5%, ver nota acima

# Camada 2 — roteamento por volume (`decidir_rota_por_volume()` em perguntar.py): decide entre
# resposta direta e "excede o limite" por MEDIÇÃO de quanto material a Camada 1 ativou
# (caracteres_totais de `reunir_contexto()`), nunca por classificação de LLM (Princípio central
# #2). NUM_CTX (16384 tokens) menos ~1024 de saída e ~1400 de overhead de prompt (instruções
# fixas + histórico) sobra ~14000 tokens pro CONTEXTO; a ~4 caracteres/token dá ~56000 caracteres.
LIMITE_CARACTERES_CONTEXTO_DIRETO = 56000

# Segunda rota direta, com contexto ampliado (achado real, 2026-08-24: substituiu inteiramente a
# Camada 3 original de map-reduce fragmentado — ver ARQUITETURA.md). Testando "quantos morreram
# em Uauá?" no Os Sertões, map-reduce por blocos (fatiar e interpretar cada pedaço separado)
# produzia respostas erradas ou incompletas em qualquer combinação de prompt/modelo/temperature
# testada — porque a tarefa de RETRIEVAL (relatar o que está escrito) não deveria depender de a
# IA interpretar fragmentos isolados. Mandando o MESMO material inteiro, numa passada só, com
# num_ctx=32768, o modelo leu certo e completo, de forma reproduzível. Por isso: sempre que o
# material não couber no teto normal (56000) mas couber neste teto ampliado, lê tudo de uma vez
# em vez de fatiar. 32768 tokens × ~4 caracteres/token, menos a mesma reserva de saída+overhead,
# dá esse teto maior.
# VRAM medida (2026-08-25, RTX 4070 12,28 GB): principal sozinho em 32768 usa 9,1 GB. Junto com
# o embedding (nomic-embed-text, 0,3 GB) — os dois que uma pergunta em rota ampliada realmente
# usa ao mesmo tempo (embedding pra buscar, principal pra responder) — dá 11,0 GB, ~1,0 GB livre:
# cabe, mas é justo. NÃO cabe junto com o auxiliar (llama3.2:3b, 4,1 GB): 9,1+4,1 = 13,2 GB
# estoura os 12,28 GB, e o Ollama descarrega um dos dois pra abrir espaço pro outro. Como o
# auxiliar só é usado por `resumir_arquivo()` (resumo), não pela pergunta, isso só custa uma
# recarga de modelo (mesmo tipo de custo que já existe ao trocar de tarefa) se um resumo e uma
# pergunta de rota ampliada acontecerem em sequência próxima — não é um problema de correção da
# rota ampliada em si.
NUM_CTX_AMPLIADO = 32768
LIMITE_CARACTERES_CONTEXTO_AMPLIADO = 120000

# Quando nem o teto ampliado é suficiente (pergunta ativou material demais pra ler com segurança
# numa passada só), a resposta não tenta cobertura parcial via map-reduce — isso é a alternativa
# que ficou registrada como pendência desde o plano original ("buscar alternativas além de a IA
# dizer que só recuperou parte dos trechos"): em vez de arriscar resposta incompleta/errada
# fatiando o material, avisa e redireciona pra `resumir_arquivo()` (que já faz map-reduce de
# resumo do documento inteiro, tarefa onde perder precisão pontual é aceitável) ou pede pra
# refinar a pergunta.
# Quantas trocas (pergunta+resposta) o sistema lembra. Mantido em 3 deliberadamente (decisão do
# usuário, 2026-08-20): chegou a ser testado em 6, mas como a condensação de resposta longa
# depende do modelo auxiliar — que erra contagem — a escolha foi manter a janela curta e usar a
# condensação só como exceção, em vez de aumentar a memória apoiada numa peça que erra.
# A conversa também é zerada ao trocar de categoria/fonte no funil (assunto novo = memória nova).
TAMANHO_HISTORICO = 3

# Resolução de pronome ENTRE MENSAGENS (`reformular_pergunta()` usando o histórico real de
# conversa, ex: pergunta 1 fala de Leonardo da Vinci, pergunta 3 usa "ele") — desativada em
# 2026-08-27 (decisão do usuário): o uso real do Jarvis hoje é mais consulta independente do que
# chat corrido, e essa resolução foi a origem de todos os bugs de referência cruzada da sessão
# (spaCy classifica "Século XVI" como pessoa, e casos parecidos). Não zera `TAMANHO_HISTORICO`
# de propósito: `historico` continua populado pros outros 2 usos que não mexem com pronome —
# "detalhar mais" (`responder_com_detalhamento`) e contexto passivo no prompt (`montar_prompt`).
# Também não afeta a resolução de pronome DENTRO da mesma pergunta dividida em sub-perguntas
# (ex: "quem é Polifemo e o que acontece com ele?") — essa reaproveita a mesma função gramatical,
# mas com histórico local fabricado na hora a partir da própria mensagem, nunca com o histórico
# real entre mensagens, e continua ativa independente desta flag. `False` = desativado; `True`
# reativa no futuro sem precisar desfazer nada, só virar essa chave.
HISTORICO_PRONOME_ATIVO = False

# --- Fontes de dados (caminhos específicos do sistema operacional) ---
CAMINHO_HISTORICO_BRAVE = os.path.expanduser(
    r"~\AppData\Local\BraveSoftware\Brave-Browser\User Data\Default\History"
)
IDENTIFICADOR_MAQUINA = "pc-casa"  # mude para "pc-viagem", "notebook-trabalho", etc conforme o PC
