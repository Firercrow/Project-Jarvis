from bisect import bisect_left
from itertools import combinations

import requests
import chromadb
import spacy
from spacy.lang.pt.stop_words import STOP_WORDS as PALAVRAS_FUNCIONAIS_PT

# Modelo de análise gramatical (não só stopwords) — achado real, 2026-08-25, "quais são os cinco
# pilares do AgroBrasil 2030?": a busca literal por n-grama (ver buscar_por_termo_literal) achava
# "pilares do" como âncora só porque "pilares" (não-stopword) e "do" (stopword) ficam adjacentes na
# pergunta — mas "pilares do" sozinho não é uma frase de verdade, é um fragmento cortado no meio de
# "pilares do AgroBrasil 2030". "do" está gramaticalmente preso a "AgroBrasil" (marcador de caso),
# nunca solto de "pilares" — a análise de dependência sabe disso, o corte por tamanho de n-grama
# não. Carregado uma vez só (carregar o modelo custa ~1s, não é pra fazer a cada pergunta).
# `lg` (não `sm`): testado contra pergunta mal formada de propósito — `sm` errou 2 de 3 casos
# difíceis, `lg` só 1 (e esse 1 é uma frase genuinamente sem verbo, nenhum modelo resolveria).
_MODELO_GRAMATICAL = spacy.load("pt_core_news_lg")

# Relações de dependência que descrevem O QUE UMA PALAVRA É (modificador de conteúdo) — mantidas
# ao montar a frase-âncora. Deliberadamente EXCLUÍDAS: nsubj/det/cop/mark/punct (armação da
# PERGUNTA — "quais", "são", "?" — não fazem parte do que o texto de origem realmente diz).
_RELACOES_MODIFICADORAS_CONTEUDO = {
    "nmod", "amod", "nummod", "compound", "flat", "flat:name", "appos", "case", "conj", "cc",
}


def _texto_subarvore(token) -> str:
    """Frase de um token + TODOS os descendentes modificadores de conteúdo, recursivo — usada só
    como texto de um filho já ESCOLHIDO em `_variantes_do_token`, não pra montar o candidato
    inteiro (essa função sozinha não varia quais filhos entram, sempre inclui todos)."""
    antes = [
        _texto_subarvore(f) for f in token.children
        if f.i < token.i and f.dep_ in _RELACOES_MODIFICADORAS_CONTEUDO
    ]
    depois = [
        _texto_subarvore(f) for f in token.children
        if f.i > token.i and f.dep_ in _RELACOES_MODIFICADORAS_CONTEUDO
    ]
    return " ".join(antes + [token.text] + depois)


def _variantes_do_token(token) -> list[str]:
    """Gera TODAS as combinações de "token + subconjunto dos filhos-modificadores diretos", da
    mais completa à mais enxuta — achado real, 2026-08-25 ("cinco pilares do AgroBrasil 2030"): o
    livro nunca escreve a frase inteira junta ("o plano AgroBrasil 2030 se sustenta em cinco
    pilares" — sem o "AgroBrasil" do lado de "pilares"), só pedaços dela separados. Uma função que
    só monta a árvore inteira ou nada (`_texto_subarvore` sozinha) nunca acharia "cinco pilares"
    OU "AgroBrasil 2030" isolados. Cada filho, quando escolhido, entra com a PRÓPRIA subárvore
    completa (não varia dentro dele aqui — variação recursiva viria de esse filho também ser
    processado como token raiz próprio no loop de `frases_ancora_por_dependencia`).

    Correção 2026-08-25 (achado real, "quantos morreram dos dois lados no combate DE Uauá?" —
    mesma pergunta do Uauá, só reparafraseada): quando o token é uma ENTIDADE NOMEADA
    (`token.ent_type_`), a preposição que a liga ao resto da frase (relação `case`, ex: "de" em
    "combate de Uauá") é acidente de COMO A PERGUNTA foi escrita, não faz parte do nome da
    entidade — "de Uauá" bateu, por coincidência, num ÚNICO trecho sem relação nenhuma com o
    combate ("...jagunço, que vinha pela estrada de Uauá..."), e por ser "mais específico" que
    "Uauá" sozinho, venceu a busca e parou nela, descartando os 25 trechos reais sobre o lugar.
    Pra substantivo comum, um modificador (adjetivo, numeral) É parte do que restringe o
    significado ("cinco pilares" vs "pilares" quaisquer) — pra nome próprio, a preposição nunca é:
    o nome já é a coisa inteira, não importa como a pergunta o encaixou na frase. Só entidades
    excluem `case` dos filhos considerados; substantivo comum continua igual."""
    filhos = [
        f for f in token.children
        if f.dep_ in _RELACOES_MODIFICADORAS_CONTEUDO
        and not (token.ent_type_ != "" and f.dep_ == "case")
    ]
    variantes = []
    for k in range(len(filhos), -1, -1):
        for escolhidos in combinations(filhos, k):
            escolhidos_set = set(escolhidos)
            antes = [_texto_subarvore(f) for f in filhos if f in escolhidos_set and f.i < token.i]
            depois = [_texto_subarvore(f) for f in filhos if f in escolhidos_set and f.i > token.i]
            variantes.append(" ".join(antes + [token.text] + depois))
    return variantes


def _densidade_conteudo(frase: str) -> float:
    """Fração das palavras de uma frase-âncora que são conteúdo de verdade (não stopword) — usada
    pra desempatar frases do mesmo tamanho (ver `frases_ancora_por_dependencia`). Achado real,
    2026-08-25 ("quantos soldados morreram e quantos jagunços morreram no primeiro combate, em
    Uauá?"): "no combate" (preposição+substantivo) e "primeiro combate" (adjetivo+substantivo) têm
    o mesmo tamanho, mas só o segundo é específico — sem esse desempate, a ordem de geração da
    árvore decide por acaso, e "no combate" bateu em 3 trechos de OUTRAS batalhas do livro."""
    palavras = frase.lower().split()
    if not palavras:
        return 0.0
    uteis = sum(1 for p in palavras if p not in PALAVRAS_FUNCIONAIS_PT)
    return uteis / len(palavras)


def frases_ancora_por_dependencia(pergunta: str) -> list[tuple[bool, list[str]]] | None:
    """Gera candidatos a âncora literal usando a estrutura gramatical da pergunta, em vez de
    fatiar em janelas de N palavras (ver `buscar_por_termo_literal`). Devolve `None` quando a
    análise falha (mais de uma raiz — pergunta mal formada/fragmento sem verbo, ex: "uauá quantos
    jagunços mortos"): nesse caso o chamador deve cair pro método de n-grama antigo, não confiar
    numa árvore gramatical que não fechou.

    Devolve uma LISTA DE NÍVEIS, cada nível como `(eh_entidade, frases)` — não uma lista plana de
    frases. Dentro de um nível, todas as frases têm o mesmo tamanho e densidade de conteúdo, dos
    mais específicos aos menos; `buscar_por_termo_literal` testa TODAS as frases de um nível juntas
    (união dos achados) antes de cair pro próximo nível, nunca escolhendo "uma frase vencedora"
    sozinha quando duas são igualmente válidas (achado real, 2026-08-25: escolher só uma por ordem
    de geração foi o que causou o erro do "no combate" acima — testar o nível inteiro junto deixa
    o próprio texto decidir, sem precisar adivinhar qual das duas frases empatadas é a certa).

    O flag `eh_entidade` (nome próprio reconhecido pelo spaCy, ex: "Uauá"=LOC) marca os níveis que
    `buscar_por_termo_literal` usa como âncora PRIMÁRIA — ver a correção 2026-08-25 lá pra
    entender por que nível de entidade e nível de conteúdo comum são tratados diferente, não só
    ordenados um atrás do outro."""
    doc = _MODELO_GRAMATICAL(pergunta)
    raizes = [tok for tok in doc if tok.dep_ == "ROOT"]
    if len(raizes) != 1:
        return None

    # é_entidade: nome próprio de verdade (spaCy reconhece "Uauá"=LOC, "Polifemo"=PER, etc.) pesa
    # mais que qualquer substantivo comum, não importa o tamanho — achado real, 2026-08-25 (mesma
    # pergunta do Uauá): "primeiro combate" (substantivo comum, aparece em VÁRIAS batalhas do
    # livro) empatou em tamanho/densidade com "em Uauá" (nome de lugar, único no livro) e os dois
    # entraram juntos no mesmo nível, diluindo a resposta com páginas de outras batalhas. Nome
    # próprio reconhecido é sempre mais específico que substantivo comum do mesmo tamanho.
    # Correção 2026-08-26 (achado real, "quanto o Brasil gasta com o Minha Casa Minha Vida"): a
    # cabeça de "Minha Casa Minha Vida" é a palavra "Minha" — mas "minha" (pronome possessivo
    # comum) está na lista de stopword, então o filtro (antes de checar `pos_`+stopword juntos)
    # excluía esse token inteiro, impedindo a frase de 4 palavras de ser gerada (só sobravam
    # "Casa"/"Vida" soltos, sem o "Minha" que os uniria). "Ser stopword" é sobre a palavra
    # ISOLADA — nome próprio reconhecido pelo spaCy (`ent_type_`) anula isso. Removida a checagem
    # de stopword daqui: o filtro de POS (NOUN/PROPN) já é suficiente e mais confiável — uma
    # palavra função de verdade (preposição, artigo, pronome) não sai tageada NOUN/PROPN pelo
    # spaCy pra começar, então a lista de stopword em cima disso só desfazia decisão gramatical
    # correta, nunca acrescentava precisão.
    candidatos = []
    for token in doc:
        if token.pos_ in ("NOUN", "PROPN"):
            e_entidade = token.ent_type_ != ""
            for frase in _variantes_do_token(token):
                if frase and frase not in [c[0] for c in candidatos]:
                    candidatos.append((frase, e_entidade))
    candidatos.sort(key=lambda c: (c[1], len(c[0].split()), _densidade_conteudo(c[0])), reverse=True)

    niveis = []
    for frase, e_entidade in candidatos:
        chave = (e_entidade, len(frase.split()), _densidade_conteudo(frase))
        if niveis and niveis[-1][0] == chave:
            niveis[-1][1].append(frase)
        else:
            niveis.append((chave, [frase]))
    return [(chave[0], frases_do_nivel) for chave, frases_do_nivel in niveis]

from config import (
    PASTA_BANCO_VETORIAL,
    MODELO_LLM,
    MODELO_EMBEDDING,
    QUANTIDADE_CHUNKS,
    TAMANHO_HISTORICO,
    HISTORICO_PRONOME_ATIVO,
    NUM_CTX,
    LIMIAR_RELEVANCIA_FATOR,
    LIMIAR_RELEVANCIA_MARGEM_MINIMA,
    JANELA_VIZINHANCA_LARGA,
    JANELA_VIZINHANCA_MEDIA,
    JANELA_VIZINHANCA_ESTREITA,
    LIMIAR_ATIVADOS_VIZINHANCA_LARGA_PISO,
    LIMIAR_ATIVADOS_VIZINHANCA_LARGA_FRACAO,
    LIMIAR_ATIVADOS_VIZINHANCA_MEDIA_PISO,
    LIMIAR_ATIVADOS_VIZINHANCA_MEDIA_FRACAO,
    LIMITE_CARACTERES_CONTEXTO_DIRETO,
    NUM_CTX_AMPLIADO,
    LIMITE_CARACTERES_CONTEXTO_AMPLIADO,
    RAIO_FUSAO_SUBPERGUNTA_PISO,
    RAIO_FUSAO_SUBPERGUNTA_FRACAO,
    LIMIAR_SOBREPOSICAO_SUBPERGUNTAS,
    VERIFICAR_RESPOSTA_ATIVO,
    VERIFICAR_CITACOES_LITERAIS,
    VERIFICAR_ATRIBUICAO,
)
from resumir import (
    listar_arquivos_disponiveis,
    buscar_pares_chunk_metadata,
    remover_sobreposicao,
    normalizar_busca_conteudo,
)
from texto import normalizar_nome, normalizar_pedido

LIMITE_ITENS_DETALHADOS = 12  # trava de segurança pra não disparar dezenas de buscas RAG numa pergunta só

def gerar_embedding(texto: str) -> list[float]:
    """Usa `/api/embed` — o MESMO endpoint da indexação (`indexar.py`,
    `indexar_historico.py`). Antes usava o endpoint legado `/api/embeddings`, que devolve o
    vetor sem normalizar (norma ~21 em vez de 1.0, mesma direção). Medido em 2026-08-20: o
    ranking não mudava, porque a coleção usa distância L2 e todos os vetores gravados têm norma
    1, o que preserva a ordenação — ou seja, não era bug, era armadilha esperando métrica
    diferente (ex: produto interno) ou um caminho novo de indexação pra virar bug de verdade."""
    resposta = requests.post(
        "http://localhost:11434/api/embed",
        json={"model": MODELO_EMBEDDING, "input": [texto]}
    )
    return resposta.json()["embeddings"][0]

def montar_historico_texto(historico: list[dict]) -> str:
    if not historico:
        return "(nenhuma pergunta anterior)"
    linhas = []
    for troca in historico:
        linhas.append(f"Usuário: {troca['pergunta']}")
        linhas.append(f"Assistente: {troca['resposta']}")
    return "\n".join(linhas)

_PRONOMES_SINGULARES = {"ele": "Masc", "ela": "Fem"}
_PRONOMES_PLURAIS = {"eles": "Masc", "elas": "Fem"}
_CONTRACOES_PRONOME = {"dele": "de", "dela": "de", "deles": "de", "delas": "de"}
_PRONOMES_NEUTROS = {"isso", "aquilo"}


def _texto_com_determinante(entidade) -> str:
    """Puxa o artigo (det) grudado antes de uma entidade nomeada, se houver — spaCy marca só o
    núcleo ("Sertões") como entidade, não o artigo ("Os"); sem isso "Os Sertões" vira "Sertões"."""
    raiz = entidade.root
    det = next((f for f in raiz.children if f.dep_ == "det" and f.i < raiz.i), None)
    return f"{det.text} {entidade.text}" if det else entidade.text


def _candidatos_correferencia(resposta: str) -> list[tuple[str, str | None]]:
    """Candidatos a antecedente de pronome (texto, gênero) numa resposta do histórico — prefere
    entidades nomeadas (`doc.ents`, já com artigo via `_texto_com_determinante`), cai pra
    substantivo comum se a resposta não tiver nenhuma entidade reconhecida."""
    doc = _MODELO_GRAMATICAL(resposta)
    candidatos = []
    for ent in doc.ents:
        genero = ent.root.morph.get("Gender")
        candidatos.append((_texto_com_determinante(ent), genero[0] if genero else None))
    if not candidatos:
        for tok in doc:
            if tok.pos_ in ("PROPN", "NOUN"):
                genero = tok.morph.get("Gender")
                candidatos.append((tok.text, genero[0] if genero else None))
    return candidatos


def _extrair_topico_da_pergunta(pergunta: str) -> str | None:
    """Pra 'isso'/'aquilo' (não apontam pra um substantivo com gênero, apontam pro FATO/EVENTO
    da pergunta anterior inteira): acha o complemento de conteúdo do VERBO raiz — não o pronome
    interrogativo em si ("o que", "quem"), que é armação da pergunta, não conteúdo — e devolve a
    subárvore completa dele (já inclui modificadores como "de Uauá"), sem a preposição EXTERNA
    que ligava esse complemento ao verbo (quem fornece o encaixe agora é a frase nova, não o
    tópico substituído)."""
    doc = _MODELO_GRAMATICAL(pergunta)
    raizes = [t for t in doc if t.dep_ == "ROOT"]
    if len(raizes) != 1:
        return None
    raiz = raizes[0]
    # "o que aconteceu...?" -> spaCy marca "o" como ROOT e "aconteceu" como filho via acl:relcl
    # (oração relativa sem antecedente) -- desce pro verbo de verdade nesse caso.
    filho_verbo = next((f for f in raiz.children if f.dep_ == "acl:relcl" and f.pos_ == "VERB"), None)
    if filho_verbo:
        raiz = filho_verbo
    complementos = [
        f for f in raiz.children
        if f.dep_ in ("obl", "obj", "nsubj") and f.pos_ in ("NOUN", "PROPN")
    ]
    if not complementos:
        return None
    escolhido = complementos[0]
    det = next((f for f in escolhido.children if f.dep_ == "det" and f.i < escolhido.i), None)
    antes = [
        _texto_subarvore(f) for f in escolhido.children
        if f.i < escolhido.i and f.dep_ in _RELACOES_MODIFICADORAS_CONTEUDO and f.dep_ != "case"
    ]
    depois = [
        _texto_subarvore(f) for f in escolhido.children
        if f.i > escolhido.i and f.dep_ in _RELACOES_MODIFICADORAS_CONTEUDO and f.dep_ != "case"
    ]
    prefixo = [det.text] if det else []
    return " ".join(prefixo + antes + [escolhido.text] + depois)


def reformular_pergunta(pergunta: str, historico: list[dict]) -> str:
    """Substitui pronome ambíguo (ele/ela/dele/dela/eles/elas/isso/aquilo) na pergunta atual pelo
    termo concreto que representa, usando o histórico — casamento gramatical mecânico (spaCy),
    não mais LLM.

    Correção 2026-08-25 (achado real, "quem é o personagem principal da revolução dos bichos? →
    Napoleão, um porco." + "quantos anos ele tem?"): a versão original pedia pro LLM (`MODELO_LLM`)
    reescrever a pergunta por instrução ("sua única tarefa é..."). Testado com 12 casos variados:
    sempre que o histórico tem a FORMA "quem é X? → Y." (resposta curta, sem frase completa) e a
    pergunta nova pergunta sobre um atributo de X, o modelo confunde "reescreva" com "continue
    respondendo" e devolve a resposta antiga ("Napoleão, um porco.") em vez da pergunta reescrita
    — mesmo com a instrução explícita "NÃO tente responder, apenas reescreva". Comprovado que o
    modelo SEMPRE identifica corretamente quem é "ele" (o nome certo aparece em toda saída, até as
    erradas) — o problema nunca foi entendimento, foi obediência de formato sob um padrão de
    diálogo (trivia curta) fortemente arraigado no treino do modelo, mais forte que uma instrução
    isolada no prompt. Não é "decisão" (Princípio central #2): é casamento gramatical — pronome
    pessoal (ele/ela/dele/dela) casa por GÊNERO com o candidato mais recente do histórico (entidade
    nomeada preferida, cai pra substantivo comum); pronome plural (eles/elas/deles/delas) junta
    TODOS os candidatos do turno achado, não escolhe um só; pronome neutro (isso/aquilo) não tem
    gênero pra casar — usa `_extrair_topico_da_pergunta()` pra puxar o núcleo de conteúdo da
    pergunta histórica em vez de um substantivo isolado.

    Testado ponta a ponta (não só o texto reescrito — a RESPOSTA final via `responder_pergunta()`,
    contra conteúdo real dos livros): nos 3 casos verificáveis, a versão gramatical devolveu recusa
    honesta e correta quando a informação não existe no material (idade de Napoleão, nascimento de
    Euclides da Cunha, data do combate de Uauá — confirmado por busca direta no texto que a data
    genuinamente não aparece em lugar nenhum do livro). Comparado à produção anterior no mesmo
    caso: o LLM reformulava errado ("Napoleão, um porco."), que virava a pergunta em si e ativava
    130 trechos do livro inteiro, caindo em recusa por excesso de material — pior resultado que a
    recusa direta e correta da versão gramatical.

    Sem substituto quando a árvore não fecha numa raiz só ou não acha candidato — a pergunta sai
    com o pronome ainda presente, não cai pro LLM antigo (reintroduziria o mesmo problema)."""
    if not historico:
        return pergunta

    doc_pergunta = _MODELO_GRAMATICAL(pergunta)
    pergunta_nova = pergunta

    for tok in doc_pergunta:
        palavra = tok.lower_

        if palavra in _PRONOMES_NEUTROS:
            substituto = _extrair_topico_da_pergunta(historico[-1]["pergunta"])
            if substituto:
                pergunta_nova = pergunta_nova.replace(tok.text, substituto, 1)
            continue

        eh_plural = palavra in _PRONOMES_PLURAIS or palavra in ("deles", "delas")
        eh_singular = palavra in _PRONOMES_SINGULARES or palavra in ("dele", "dela")
        if not (eh_plural or eh_singular):
            continue

        genero_pronome = tok.morph.get("Gender")
        genero_pronome = genero_pronome[0] if genero_pronome else None

        candidatos = []
        for troca in reversed(historico):
            candidatos = _candidatos_correferencia(troca["resposta"])
            if candidatos:
                break

        substituto = None
        if eh_plural:
            if candidatos:
                substituto = " e ".join(c[0] for c in candidatos)
        else:
            for texto, genero in reversed(candidatos):
                if genero == genero_pronome:
                    substituto = texto
                    break
            if substituto is None and candidatos:
                substituto = candidatos[-1][0]

        if substituto:
            if palavra in _CONTRACOES_PRONOME:
                substituto = f"{_CONTRACOES_PRONOME[palavra]} {substituto}"
            pergunta_nova = pergunta_nova.replace(tok.text, substituto, 1)

    return pergunta_nova


def dividir_em_subperguntas(pergunta: str) -> list[str]:
    prompt = f"""A pergunta abaixo pode conter um ou mais tópicos distintos de busca.
Se ela pedir informação sobre MAIS DE UM assunto/fonte diferente (ex: "Google E YouTube",
ou "Google, YouTube E Instagram"), divida em perguntas separadas, uma pergunta COMPLETA
por tópico — não escreva fragmentos como "e sobre X?", escreva a pergunta inteira de novo
para cada tópico. Se for um único tópico, devolva só a pergunta original.

Exemplo:
PERGUNTA: o que eu vi no youtube e pesquisei no google?
PERGUNTAS SEPARADAS:
o que eu vi no youtube?
o que eu pesquisei no google?

Responda APENAS com uma pergunta completa por linha, sem numeração, sem explicação.

PERGUNTA: {pergunta}

PERGUNTAS SEPARADAS:"""

    resposta = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": MODELO_LLM,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": 150, "temperature": 0}
        }
    )
    texto = resposta.json()["response"].strip()
    subperguntas = [linha.strip() for linha in texto.split("\n") if linha.strip()]
    return subperguntas if subperguntas else [pergunta]

def detectar_fonte(pergunta: str) -> str | None:
    prompt_classificacao = f"""Classifique a pergunta abaixo em uma categoria:
- "historico" se for sobre sites visitados, vídeos assistidos, pesquisas feitas na internet, ou atividade de navegação do usuário.
- "geral" para qualquer outra coisa (perguntas sobre livros, documentos, ou assuntos gerais).

Responda APENAS com a palavra "historico" ou "geral", nada mais.

PERGUNTA: {pergunta}

CATEGORIA:"""

    resposta = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": MODELO_LLM,
            "prompt": prompt_classificacao,
            "stream": False,
            "options": {"num_predict": 10, "temperature": 0}
        }
    )
    categoria = resposta.json()["response"].strip().lower()
    return "historico_navegacao" if "historico" in categoria else None

def extrair_nome_documento_mencionado(pergunta: str) -> str | None:
    prompt = f"""Extraia APENAS o nome ou palavras-chave do livro/documento mencionado explicitamente
na mensagem abaixo. Se nenhum documento específico for mencionado por nome, responda apenas "NENHUM".

Exemplo 1:
MENSAGEM: quais as propostas do livro amarelo?
DOCUMENTO: livro amarelo

Exemplo 2:
MENSAGEM: o que eu vi no youtube essa semana?
DOCUMENTO: NENHUM

Exemplo 3:
MENSAGEM: quais as coordenadas de latitude e longitude usadas no relatório TECHNICAL_REPORT_CORRECTED.docx?
DOCUMENTO: TECHNICAL_REPORT_CORRECTED.docx

Agora extraia da mensagem real abaixo.

MENSAGEM: {pergunta}

DOCUMENTO:"""

    resposta = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": MODELO_LLM,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": 20, "temperature": 0}
        }
    )
    termo = resposta.json()["response"].strip()
    # o modelo às vezes ecoa o próprio rótulo do prompt ("DOCUMENTO: NENHUM") em vez de responder
    # só o valor — sem isso, o termo ecoado era tratado como se fosse um nome de arquivo real.
    if termo.upper().startswith("DOCUMENTO:"):
        termo = termo.split(":", 1)[1].strip()
    return None if not termo or termo.upper() == "NENHUM" else termo

def identificar_arquivo_na_pergunta(pergunta: str, colecao) -> str | None:
    termo = extrair_nome_documento_mencionado(pergunta)
    if not termo:
        return None

    arquivos_disponiveis = listar_arquivos_disponiveis(colecao)
    pedido = normalizar_pedido(termo)
    correspondencias = [a for a in arquivos_disponiveis if pedido in normalizar_nome(a)]
    return correspondencias[0] if len(correspondencias) == 1 else None

def buscar_candidatos(pergunta: str, colecao, fonte: str | None, arquivo: str | None) -> list[dict]:
    """Camada 1, passo 1 (busca ampla com distâncias — ver ARQUITETURA.md, "REWORK DA BUSCA E
    RESPOSTA"). Pede um POOL de candidatos (QUANTIDADE_CHUNKS, hoje ponto de partida do corte,
    não teto final) e devolve cada um com sua distância — sem cortar ainda. `include=["distances"]`
    é o que muda em relação à busca antiga: sem a distância não dá pra saber QUÃO relevante cada
    candidato é em relação aos outros, só a ordem."""
    embedding_pergunta = gerar_embedding(pergunta)
    parametros = {
        "query_embeddings": [embedding_pergunta],
        "n_results": QUANTIDADE_CHUNKS,
        "include": ["documents", "metadatas", "distances"]
    }
    condicoes = []
    if fonte:
        condicoes.append({"fonte": fonte})
    if arquivo:
        condicoes.append({"arquivo": arquivo})
    if len(condicoes) == 1:
        parametros["where"] = condicoes[0]
    elif len(condicoes) > 1:
        parametros["where"] = {"$and": condicoes}
    resultados = colecao.query(**parametros)

    return [
        {"documento": doc, "metadata": meta, "distancia": dist}
        for doc, meta, dist in zip(
            resultados["documents"][0], resultados["metadatas"][0], resultados["distances"][0]
        )
    ]


def cortar_por_relevancia(candidatos: list[dict]) -> list[dict]:
    """Camada 1, passo 2. Substitui o teto fixo (sempre os mesmos N) por um corte relativo ao
    MELHOR resultado da própria busca: pergunta pontual naturalmente mantém poucos candidatos
    (só o melhor bate perto), pergunta de cobertura mantém muitos (vários ficam próximos do
    melhor) — o mesmo critério resolve os dois casos sem a IA precisar classificar qual é qual
    (Princípio central #2: escolha mecânica é do código)."""
    if not candidatos:
        return []
    melhor_distancia = min(c["distancia"] for c in candidatos)
    limiar = max(
        melhor_distancia * LIMIAR_RELEVANCIA_FATOR,
        melhor_distancia + LIMIAR_RELEVANCIA_MARGEM_MINIMA,
    )
    return [c for c in candidatos if c["distancia"] <= limiar]


def conjunto_ativado_por_subpergunta(pergunta: str, colecao, fonte: str | None, arquivo: str | None) -> set[int] | None:
    """Sonda leve pra `responder_pergunta()` decidir se sub-perguntas geradas por
    `dividir_em_subperguntas()` cobrem o MESMO material do documento ou material diferente de
    verdade — por MEDIÇÃO, nunca por classificação de LLM (Princípio central #2). Devolve o
    CONJUNTO de chunks que a sub-pergunta ativa. Só busca e corta por relevância
    (`buscar_candidatos` + `cortar_por_relevancia`); pula busca literal, vizinhança e agrupamento,
    caros e desnecessários aqui. Sem arquivo conhecido (ex: histórico de navegação, sem noção de
    posição/vizinho), não há o que medir — devolve None.

    Substituiu `melhor_posicao_semantica()` em 2026-08-29, que devolvia só o chunk CAMPEÃO. O
    problema do campeão é ser um ponto só: medido no revolucao-dos-bichos.pdf, "quais as causas
    que levaram à revolução?" campeia no chunk 409 e "quais FORAM as causas..." no 21 — uma
    palavra de diferença, 388 chunks de distância, e a decisão de fundir virava junto. Os mesmos
    dois textos compartilham 30% do conjunto ativado, que é a medida estável. O custo é idêntico:
    os candidatos já eram buscados aqui, só eram descartados menos o primeiro colocado."""
    if not arquivo:
        return None
    candidatos = cortar_por_relevancia(buscar_candidatos(pergunta, colecao, fonte, arquivo))
    if not candidatos:
        return None
    return {c["metadata"]["chunk_num"] for c in candidatos}


def sobreposicao_de_conjuntos(a: set[int], b: set[int]) -> float:
    """Jaccard — fração do material em comum entre dois conjuntos de chunks (0 = nada em comum,
    1 = idênticos). União vazia devolve 0."""
    uniao = a | b
    return len(a & b) / len(uniao) if uniao else 0.0


def buscar_por_termo_literal(pergunta: str, pares: list[tuple[dict, str]]) -> list[dict]:
    """Busca COMPLEMENTAR à semântica (achado real, 2026-08-24): "quanto o Brasil gasta com o
    Minha Casa Minha Vida" não recuperou o chunk certo por nenhum problema de corte de
    relevância — o chunk (pág. 48) fala majoritariamente de OUTRO assunto (fracasso histórico de
    políticas habitacionais) e só cita o programa de passagem, então o embedding do chunk inteiro
    não se destaca entre dezenas de outros trechos do livro com assinatura semântica parecida
    ("crítica a política pública"). O termo em si bate palavra por palavra, só não pesa o
    suficiente no vetor do chunk inteiro pra vencer a competição.

    Acha o chunk que contém um trecho LITERAL da pergunta, começando pelo n-grama mais longo e
    parando no primeiro tamanho que bater — prefere sempre o match mais específico. Busca
    semântica e busca literal erram em casos opostos (uma erra termo exato embutido em contexto
    genérico, a outra erra paráfrase/sinônimo) — juntas cobrem mais que cada uma sozinha. Mesma
    normalização usada pra recorte de transcrição por conteúdo (`normalizar_busca_conteudo`, tira
    pontuação e caixa) — diferente da normalização exata de `contar_termo_no_arquivo`, que é
    proposital sobre isso.

    Correção 2026-08-24 (achado real, "quem é o ciclope Polifemo e o que acontece com ele?"): a
    versão original ia só de 6 até 3 palavras e devolvia assim que achava QUALQUER n-grama que
    batesse, sem checar se ele tinha algum conteúdo. Pra um nome próprio de uma palavra só
    ("Polifemo"), nenhum n-grama de 3+ palavras bate no texto, então o loop caía no primeiro de 3
    palavras que existisse por acaso — "e o que", um conectivo sem relação nenhuma com a
    pergunta — e devolvia 15 chunks errados espalhados pelo livro inteiro, achando que tinha
    achado algo. Agora só considera n-gramas com PELO MENOS UMA palavra fora da lista de
    stopwords do português (`PALAVRAS_FUNCIONAIS_PT`, do spaCy — lista mantida pela comunidade,
    não inventada aqui) e desce até uma palavra só. Cobre tanto frase específica quanto nome
    próprio isolado, sem precisar de lista de nomes conhecidos nem depender de maiúscula. Uma
    lista de stopword é sempre de UM idioma — hoje só português está coberto (spaCy tem listas
    prontas pra outros idiomas, mas o sistema não detecta o idioma da pergunta ainda; ficou
    registrado como pendência futura, não bloqueia esta correção).

    Correção 2026-08-25 (achado real, "quais são os cinco pilares do AgroBrasil 2030?"): n-grama
    por TAMANHO não sabe se o pedaço que bateu é uma frase de verdade ou um fragmento cortado no
    meio — "pilares do" bateu em dois trechos sem nada a ver (usam a mesma construção retórica
    "pilares do X" pra outro assunto), porque "do" fica solto de "AgroBrasil" só por causa do
    corte por tamanho, não porque a gramática manda. Agora tenta primeiro achar a âncora via
    `frases_ancora_por_dependencia()` (análise gramatical de verdade — "do" nunca sai solto de
    "AgroBrasil", a árvore sabe que são uma coisa só). Só cai pro n-grama por tamanho se a
    gramática não achar nada ou a pergunta não fechar numa árvore só (fragmento sem verbo, ver
    docstring de `frases_ancora_por_dependencia`) — nunca perde o método antigo, só usa um melhor
    primeiro.

    Correção 2026-08-25, mesmo dia ("quantos soldados morreram e quantos jagunços morreram no
    primeiro combate, em Uauá?"): testar uma frase gramatical de cada vez e parar na primeira que
    bater tem o mesmo problema do n-grama antigo — "no combate" (preposição+substantivo) empatou em
    tamanho com "primeiro combate" (adjetivo+substantivo), mas venceu por ordem de geração e bateu
    em 3 trechos de OUTRAS batalhas do livro, nenhuma delas Uauá. `frases_ancora_por_dependencia()`
    agora devolve NÍVEIS (grupos de frases igualmente específicas, ver docstring dela) — testa
    TODAS as frases do mesmo nível juntas (união dos achados) antes de cair pro próximo nível, em
    vez de escolher uma só por ordem de geração.

    Correção 2026-08-25, terceira rodada, mesma pergunta: mesmo com o nível certo, "Uauá" (entidade
    nomeada, único no livro) e "primeiro combate" (substantivo comum, se repete em VÁRIAS batalhas)
    empatavam em prioridade e entravam JUNTOS num só nível — a união dos dois inclui os 25 chunks
    que só citam Uauá de passagem em outros contextos, sem falar do combate, estourando o contexto.
    A correção anterior (`e_entidade` como critério de ordenação mais alto) resolveu isso — mas
    ERROU pro lado oposto: como o nível de entidade vence sozinho e a busca para no primeiro nível
    não-vazio, "primeiro combate" nunca chega a ser considerado, e "Uauá" sozinho já basta pra
    parar a busca. Resultado: os 25 chunks espalhados pelo livro entram todos, sem filtro nenhum
    pelo que a pergunta realmente pede (o COMBATE, não qualquer menção ao lugar).

    A hierarquia certa (conferida com o usuário): a entidade (Uauá = ONDE) é a âncora primária —
    ela decide o universo de busca. Mas dentro desse universo, um trecho que também bate no termo
    de conteúdo (combate = O QUE aconteceu) é estritamente melhor que um que só bate na entidade.
    Nunca o contrário: conteúdo sozinho ("combate" sem "Uauá" por perto) nunca vira âncora quando a
    pergunta tem uma entidade — combate acontece em toda batalha do livro, "Uauá" é o que restringe
    pro capítulo certo. Por isso: acha o nível de entidade primeiro; se achar algo, tenta REFINAR
    pelos níveis de conteúdo (fica só com os chunks de entidade que estão perto de algum chunk de
    conteúdo — raio reaproveita `RAIO_FUSAO_SUBPERGUNTA_PISO/FRACAO`, calibrado nesta mesma
    pergunta/livro pra distância de convergência entre sub-perguntas relacionadas); se o refino
    achar algo, é o resultado ideal (Uauá E combate perto um do outro); se não achar nada perto,
    cai pra entidade pura sem refino (aceitável — ver exemplo do usuário: página só com "Uauá" é
    válida, página só com "guerra" não é). Só quando NÃO há nível de entidade nenhum (pergunta sem
    nome próprio) é que os níveis de conteúdo comum voltam a valer como âncora independente,
    exatamente como antes desta correção."""
    niveis_gramaticais = frases_ancora_por_dependencia(pergunta)
    if niveis_gramaticais:
        def _achados_do_nivel(frases: list[str]) -> list[dict]:
            frases_norm = {normalizar_busca_conteudo(f) for f in frases} - {""}
            if not frases_norm:
                return []
            return [
                {"documento": doc, "metadata": meta, "distancia": None}
                for meta, doc in pares
                if any(frase_norm in normalizar_busca_conteudo(doc) for frase_norm in frases_norm)
            ]

        niveis_entidade = [frases for eh_entidade, frases in niveis_gramaticais if eh_entidade]
        niveis_conteudo = [frases for eh_entidade, frases in niveis_gramaticais if not eh_entidade]

        achados_entidade = []
        for nivel in niveis_entidade:
            achados_entidade = _achados_do_nivel(nivel)
            if achados_entidade:
                break

        if achados_entidade:
            achados_conteudo = []
            for nivel in niveis_conteudo:
                achados_conteudo = _achados_do_nivel(nivel)
                if achados_conteudo:
                    break

            if achados_conteudo:
                raio_refino = max(
                    RAIO_FUSAO_SUBPERGUNTA_PISO,
                    RAIO_FUSAO_SUBPERGUNTA_FRACAO * len(pares),
                )
                chunks_conteudo = {a["metadata"]["chunk_num"] for a in achados_conteudo}
                refinados = [
                    a for a in achados_entidade
                    if any(
                        abs(a["metadata"]["chunk_num"] - c) <= raio_refino
                        for c in chunks_conteudo
                    )
                ]
                if refinados:
                    return refinados
            return achados_entidade

        # Só usa conteúdo comum como âncora independente quando a pergunta NÃO tem nenhuma
        # entidade nomeada (niveis_entidade vazio). Se tem entidade mas ela não bateu em nada
        # (achados_entidade vazio, caso raro — variação ortográfica etc.), a regra é clara:
        # conteúdo sozinho nunca vira âncora quando há entidade na pergunta. Cai direto pro
        # n-grama antigo lá embaixo em vez de usar "primeiro combate" sozinho, por exemplo.
        if not niveis_entidade:
            for nivel in niveis_conteudo:
                achados = _achados_do_nivel(nivel)
                if achados:
                    return achados

    palavras = normalizar_busca_conteudo(pergunta).split()
    for tamanho in range(min(6, len(palavras)), 0, -1):
        ngramas = {" ".join(palavras[i:i + tamanho]) for i in range(len(palavras) - tamanho + 1)}
        ngramas_com_conteudo = {
            ngrama for ngrama in ngramas
            if any(p not in PALAVRAS_FUNCIONAIS_PT for p in ngrama.split())
        }
        achados = [
            {"documento": doc, "metadata": meta, "distancia": None}
            for meta, doc in pares
            if any(ngrama in normalizar_busca_conteudo(doc) for ngrama in ngramas_com_conteudo)
        ]
        if achados:
            return achados
    return []


def calcular_janela_vizinhanca(quantidade_ativados: int, quantidade_chunks_no_arquivo: int = 0) -> int:
    """Camada 1, passo 3 (vizinhança adaptativa — ideia do usuário). Poucos trechos ativados =
    falta contexto ao redor de cada um (pode ser a CONTINUAÇÃO de uma proposta, sem repetir a
    palavra buscada) = janela larga. Muitos trechos já ativados = cobertura já existe = janela
    estreita, senão a vizinhança de cada um se soma e o prompt explode à toa.

    Correção 2026-08-24 (achado real, "quantos morreram em Uauá?" no Os Sertões, 2.253 chunks):
    o limiar não pode ser só um número absoluto — 19 ativados são 0,84% de um livro grande
    (proporcionalmente escassos, mereciam janela larga) mas passavam de 12 (limiar antigo) e
    caíam em janela estreita, impedindo alcançar um fato a só 6 posições do candidato mais
    próximo. Agora o limiar é o MAIOR entre um piso absoluto (protege documento pequeno, mesmo
    comportamento de sempre) e uma fração do total de chunks do arquivo (protege documento
    grande, escala com o tamanho) — ver config.py para a derivação das frações."""
    limiar_larga = LIMIAR_ATIVADOS_VIZINHANCA_LARGA_PISO
    limiar_media = LIMIAR_ATIVADOS_VIZINHANCA_MEDIA_PISO
    if quantidade_chunks_no_arquivo:
        limiar_larga = max(limiar_larga, LIMIAR_ATIVADOS_VIZINHANCA_LARGA_FRACAO * quantidade_chunks_no_arquivo)
        limiar_media = max(limiar_media, LIMIAR_ATIVADOS_VIZINHANCA_MEDIA_FRACAO * quantidade_chunks_no_arquivo)

    if quantidade_ativados <= limiar_larga:
        return JANELA_VIZINHANCA_LARGA
    if quantidade_ativados <= limiar_media:
        return JANELA_VIZINHANCA_MEDIA
    return JANELA_VIZINHANCA_ESTREITA


def agrupar_em_blocos_contiguos(candidatos_arquivo: list[dict], pares: list[tuple[dict, str]], janela: int) -> tuple[list[dict], int]:
    """Camada 1, passo 4 — a parte que ataca a fusão de trechos distantes (B4). Expande cada
    candidato ativado em ±janela vizinhos por POSIÇÃO no documento (não por embedding), agrupa
    os índices que se tocam num bloco de texto corrido só, e marca a página de onde o bloco
    começa. O modelo passa a receber blocos na ORDEM DO DOCUMENTO com origem declarada, em vez
    de fragmentos pequenos colados fora de ordem parecendo texto contínuo — que foi como "20
    bilhões ao longo de uma década" (pág. 40) se fundiu com "Arthur do Val" (pág. 28) numa
    resposta só.

    `pares` já vem pronto de `buscar_pares_chunk_metadata()` (resumir.py), ordenado por
    chunk_num — reaproveita a mesma função usada pelo resumo/transcrição, em vez de outra busca
    no ChromaDB por vizinho."""
    indice_por_chunk_num = {meta["chunk_num"]: i for i, (meta, _) in enumerate(pares)}

    indices_ativados = set()
    for candidato in candidatos_arquivo:
        indice = indice_por_chunk_num.get(candidato["metadata"]["chunk_num"])
        if indice is None:
            continue
        inicio = max(0, indice - janela)
        fim = min(len(pares) - 1, indice + janela)
        indices_ativados.update(range(inicio, fim + 1))

    if not indices_ativados:
        return [], 0

    indices_ordenados = sorted(indices_ativados)
    grupos = [[indices_ordenados[0]]]
    for indice in indices_ordenados[1:]:
        if indice == grupos[-1][-1] + 1:
            grupos[-1].append(indice)
        else:
            grupos.append([indice])

    blocos = []
    for grupo in grupos:
        chunks_do_grupo = [pares[i][1] for i in grupo]
        # mesma remoção de sobreposição usada na transcrição (resumir.py): os chunks vizinhos
        # têm sobreposição proposital (config.SOBREPOSICAO) pra não cortar frase no meio, mas
        # concatenar direto duplicaria texto.
        partes = [chunks_do_grupo[0]]
        for chunk in chunks_do_grupo[1:]:
            partes.append(remover_sobreposicao(partes[-1], chunk))
        texto_bloco = "".join(partes)
        pagina = pares[grupo[0]][0].get("pagina", 1)
        texto_com_pagina = f"[trecho da página {pagina}] {texto_bloco}"
        blocos.append({"texto": texto_com_pagina, "caracteres": len(texto_com_pagina)})

    return blocos, len(indices_ativados)


def filtrar_semanticos_isolados(candidatos_arquivo: list[dict], pares: list[tuple[dict, str]]) -> tuple[list[dict], int]:
    """Filtro de concentração (achado real, 2026-08-24, ver ARQUITETURA.md — "quem é Polifemo"):
    `cortar_por_relevancia()` não discrimina em texto narrativo — toda a Odisseia tem dicção
    uniforme, então o pool inteiro de candidatos passou no corte (60 de 60). Sem um segundo
    filtro, um chunk parecido no vetor mas de OUTRO assunto (mesmo estilo épico, tema diferente)
    entra no contexto igual ao trecho genuíno, e a fusão junta os dois numa resposta só.

    Primeira versão testada (concentração ENTRE candidatos semânticos, ideia original do
    usuário): descartada por medição — mesmo no ajuste mais agressivo (raio 8, mínimo 3
    vizinhos), ainda sobrava ~28% de ruído e já tinha perdido 2/3 do material genuíno. Motivo:
    outras cenas do livro (ex.: o concurso do arco) também formam cluster ENTRE SI sem terem
    nada a ver com a pergunta — concentração sozinha não sabe do que o cluster é sobre.

    Versão que funciona, medida: ancorar num chunk achado pela busca LITERAL
    (`buscar_por_termo_literal`, `distancia is None`) — prova direta no texto, não intuição de
    vetor. Um candidato achado só pela semântica só sobrevive se estiver perto de uma âncora
    literal; testado com raio=16: zerou o ruído (0/45 chunks fora do episódio) mantendo quase
    metade do material genuíno (7/15) — bem melhor que a concentração mútua. Uma âncora literal
    NUNCA é descartada aqui, mesmo isolada — é o caso do Minha Casa Minha Vida: achado literal
    isolado, único jeito de recuperar aquele fato, sem vizinho nenhum por perto.

    Quando NÃO existe nenhuma âncora literal (pergunta sem termo específico que bata no texto),
    não há o que ancorar — o filtro não age, mantém o comportamento de sempre (nenhum descarte).
    É um buraco conhecido (pergunta parafraseada, sem termo exato, em documento narrativo denso)
    — mais raro que "nome próprio específico", registrado como pendência, não bloqueia esta
    correção.

    Raio de proximidade reaproveita JANELA_VIZINHANCA_LARGA (a mais generosa já calibrada) em
    vez de um número novo: um candidato só conta como "perto" de uma âncora se ainda pudesse
    acabar no MESMO bloco contíguo em `agrupar_em_blocos_contiguos()` mesmo sob a janela mais
    larga que o sistema usa (dois pontos com janela w se tocam se a distância entre eles for
    <= 2w)."""
    indice_por_chunk_num = {meta["chunk_num"]: i for i, (meta, _) in enumerate(pares)}
    raio = JANELA_VIZINHANCA_LARGA * 2

    indices_ancoras_literais = sorted({
        indice_por_chunk_num[c["metadata"]["chunk_num"]]
        for c in candidatos_arquivo
        if c["distancia"] is None and c["metadata"]["chunk_num"] in indice_por_chunk_num
    })
    if not indices_ancoras_literais:
        return candidatos_arquivo, 0

    def perto_de_ancora(indice: int) -> bool:
        posicao = bisect_left(indices_ancoras_literais, indice)
        candidatas = indices_ancoras_literais[max(0, posicao - 1):posicao + 1]
        return any(abs(ancora - indice) <= raio for ancora in candidatas)

    filtrados = []
    descartados = 0
    for candidato in candidatos_arquivo:
        indice = indice_por_chunk_num.get(candidato["metadata"]["chunk_num"])
        # âncora literal sempre fica; achado só via semântica precisa estar perto de uma âncora
        if candidato["distancia"] is None or indice is None or perto_de_ancora(indice):
            filtrados.append(candidato)
        else:
            descartados += 1
    return filtrados, descartados


def reunir_contexto(pergunta: str, colecao, fonte: str | None = None, arquivo: str | None = None,
                     usar_busca_hibrida: bool = True) -> dict:
    """Camada 1 do rework da busca (ver ARQUITETURA.md, "REWORK DA BUSCA E RESPOSTA"): substitui
    o corte fixo de N chunks por busca ampla + corte por relevância relativa + busca híbrida por
    termo literal + filtro de concentração + vizinhança adaptativa + agrupamento contíguo na
    ordem do documento, com página marcada.

    usar_busca_hibrida: parâmetro de calibração (2026-08-24) — liga/desliga
    `buscar_por_termo_literal()` sem precisar de dois caminhos de código separados, pra comparar
    com/sem durante o teste da Camada 1. Default True; pode virar constante fixa em config.py
    depois que a calibração decidir.

    Devolve um DIAGNÓSTICO, não só os blocos — a Camada 2 (`decidir_rota_por_volume()`, mais
    abaixo) usa `caracteres_totais` pra decidir resposta direta vs cobertura por medição, nunca
    por classificação de LLM."""
    candidatos = buscar_candidatos(pergunta, colecao, fonte, arquivo)
    ativados = cortar_por_relevancia(candidatos)

    # Busca híbrida por termo literal (só quando o arquivo já é conhecido — mesma limitação da
    # vizinhança adaptativa, chunk_num só é comparável dentro do mesmo arquivo). Busca semântica
    # e busca literal erram em casos opostos; some os achados aos já ativados por relevância,
    # sem duplicar.
    pares_arquivo_unico = None
    quantidade_ativados_por_termo = 0
    if usar_busca_hibrida and arquivo:
        pares_arquivo_unico = buscar_pares_chunk_metadata(arquivo, colecao)
        chunk_nums_ja_ativados = {c["metadata"]["chunk_num"] for c in ativados}
        for achado in buscar_por_termo_literal(pergunta, pares_arquivo_unico):
            if achado["metadata"]["chunk_num"] not in chunk_nums_ja_ativados:
                ativados.append(achado)
                chunk_nums_ja_ativados.add(achado["metadata"]["chunk_num"])
                quantidade_ativados_por_termo += 1

    # Vizinhança e ordem de documento só fazem sentido DENTRO do mesmo arquivo — chunk_num não
    # é comparável entre documentos diferentes. Histórico de navegação (sem campo 'arquivo' nos
    # metadados) não tem essa noção de vizinho nem de isolamento: cada entrada continua sendo seu
    # próprio bloco, sem passar pelo filtro de concentração.
    candidatos_por_arquivo: dict[str, list[dict]] = {}
    pares_por_arquivo: dict[str, list[tuple[dict, str]]] = {}
    blocos_sem_arquivo = []
    for candidato in ativados:
        nome_arquivo = candidato["metadata"].get("arquivo")
        if nome_arquivo:
            candidatos_por_arquivo.setdefault(nome_arquivo, []).append(candidato)
        else:
            origem = candidato["metadata"].get("origem")
            texto = f"{candidato['documento']} [origem: {origem}]" if origem else candidato["documento"]
            blocos_sem_arquivo.append({"texto": texto, "caracteres": len(texto)})

    # Filtro de concentração ANTES de calcular a janela: se ele não rodasse aqui, a janela seria
    # calculada com a contagem ainda inflada pelo ruído descartado, ficando estreita demais até
    # pro material que sobreviveu ao filtro (achado real: "Polifemo" ativava 75 candidatos, dos
    # quais a maioria era ruído semântico isolado — sem filtrar antes, o pouco que sobrava de
    # legítimo ainda receberia janela=0 por causa da contagem antiga).
    #
    # Tentativa revertida em 2026-08-25: cheguei a testar pular esse filtro quando o material sem
    # filtrar já coubesse no teto de caracteres (achado que motivou: "os animais da fazenda",
    # Revolução dos Bichos, perdia cobertura legítima espalhada pelo livro). Testado ponta a ponta
    # contra os 4 casos conhecidos e REVERTIDO: o filtro de isolamento não serve só pra caber no
    # teto de caracteres, serve pra evitar contaminação entre episódios PARECIDOS mas diferentes
    # (achado real: sem o filtro, "Polifemo" passou a citar uma "planta que faz dormir" — invenção
    # que não existe no episódio, contaminação vinda de outro trecho da Odisseia com tema
    # parecido — Circe/Lotófagos). Medir só tamanho não capta esse risco de conteúdo. O caso do
    # Bichos continua sem solução — registrado como pendência, não resolvido por aqui.
    quantidade_descartados_por_isolamento = 0
    for nome_arquivo, candidatos_arquivo in candidatos_por_arquivo.items():
        pares = pares_arquivo_unico if nome_arquivo == arquivo and pares_arquivo_unico else buscar_pares_chunk_metadata(nome_arquivo, colecao)
        pares_por_arquivo[nome_arquivo] = pares
        filtrados, descartados = filtrar_semanticos_isolados(candidatos_arquivo, pares)
        candidatos_por_arquivo[nome_arquivo] = filtrados
        quantidade_descartados_por_isolamento += descartados

    quantidade_ativados_filtrada = sum(len(c) for c in candidatos_por_arquivo.values()) + len(blocos_sem_arquivo)
    # Soma o tamanho de todos os arquivos envolvidos (quase sempre um só) — é o que faz o limiar
    # escalar por tamanho de documento em vez de número fixo (ver calcular_janela_vizinhanca).
    quantidade_chunks_total_arquivos = sum(len(p) for p in pares_por_arquivo.values())
    janela = calcular_janela_vizinhanca(quantidade_ativados_filtrada, quantidade_chunks_total_arquivos)

    blocos = []
    quantidade_indices_ativados = 0
    quantidade_chunks_no_arquivo = 0
    for nome_arquivo, candidatos_arquivo in candidatos_por_arquivo.items():
        pares = pares_por_arquivo[nome_arquivo]
        blocos_arquivo, indices_arquivo = agrupar_em_blocos_contiguos(candidatos_arquivo, pares, janela)
        blocos.extend(blocos_arquivo)
        quantidade_indices_ativados += indices_arquivo
        quantidade_chunks_no_arquivo += len(pares)
    blocos.extend(blocos_sem_arquivo)

    # Fração do documento ativada só tem sentido claro quando a busca girou em torno de UM
    # arquivo (caso comum: funil já filtrou, ou identificar_arquivo_na_pergunta achou um só).
    fracao_documento_ativada = None
    if len(candidatos_por_arquivo) == 1 and quantidade_chunks_no_arquivo:
        fracao_documento_ativada = quantidade_indices_ativados / quantidade_chunks_no_arquivo

    return {
        "blocos": [b["texto"] for b in blocos],
        "quantidade_candidatos": len(candidatos),
        "quantidade_ativados": len(ativados),
        "quantidade_ativados_por_termo_literal": quantidade_ativados_por_termo,
        "quantidade_descartados_por_isolamento": quantidade_descartados_por_isolamento,
        "quantidade_blocos": len(blocos),
        "caracteres_totais": sum(b["caracteres"] for b in blocos),
        "janela_vizinhanca": janela,
        "fracao_documento_ativada": fracao_documento_ativada,
    }


def buscar_chunks_relevantes(pergunta: str, colecao, fonte: str | None = None, arquivo: str | None = None) -> list[str]:
    """Mantida para quem só precisa da lista de blocos prontos (hoje: `responder_pergunta()` e
    `responder_com_detalhamento()` — este último ainda não passou pela Camada 2/3 do rework, ver
    ARQUITETURA.md). Por baixo já usa `reunir_contexto()`: mesmo ganho de blocos contínuos com
    página marcada, só sem o diagnóstico que o roteamento por volume vai precisar."""
    return reunir_contexto(pergunta, colecao, fonte, arquivo)["blocos"]


def decidir_rota_por_volume(caracteres_totais: int) -> str:
    """Camada 2 do rework (ver ARQUITETURA.md / plano do rework, "roteamento por volume"):
    decide a rota por MEDIÇÃO de quanto material a Camada 1 ativou — nunca por classificação de
    LLM (Princípio central #2). Três rotas, nunca fatiando o material em pedaços interpretados
    separadamente (achado real, 2026-08-24: substituiu o map-reduce fragmentado original — ver
    nota em config.py sobre LIMITE_CARACTERES_CONTEXTO_AMPLIADO):
    - "direta": cabe no teto normal (NUM_CTX) -> resposta rápida de sempre.
    - "direta_ampliada": não cabe no teto normal mas cabe no teto ampliado (NUM_CTX_AMPLIADO) ->
      mesma resposta direta, só com contexto maior — mais lenta, mas ainda uma leitura ÚNICA e
      completa do material, sem fatiar.
    - "excede_limite": não cabe nem no teto ampliado -> não tenta cobertura parcial arriscando
      erro; avisa e redireciona (`montar_mensagem_limite_excedido()`)."""
    if caracteres_totais <= LIMITE_CARACTERES_CONTEXTO_DIRETO:
        return "direta"
    if caracteres_totais <= LIMITE_CARACTERES_CONTEXTO_AMPLIADO:
        return "direta_ampliada"
    return "excede_limite"


def montar_mensagem_limite_excedido(quantidade_blocos: int, caracteres_totais: int) -> str:
    """Substitui o map-reduce fragmentado (Camada 3 original — ver ARQUITETURA.md, pendência
    registrada em 2026-08-24 pra achar "alternativas além de a IA dizer que só recuperou parte
    dos trechos"). Achado real testando "quantos morreram em Uauá?" no Os Sertões: fatiar o
    material e pedir pra IA interpretar cada pedaço separadamente (e depois juntar) produziu
    respostas erradas ou incompletas em toda combinação de prompt/modelo/temperature testada —
    porque relatar o que está escrito é tarefa de RETRIEVAL, não deveria depender de interpretar
    fragmentos isolados fora de contexto. Quando nem o contexto ampliado basta pra uma leitura
    única seguir, a resposta honesta não é arriscar isso — é apontar o caminho certo: resumo do
    documento inteiro (tarefa onde perder precisão pontual é aceitável, já resolvida por
    `resumir_arquivo()`) ou uma pergunta mais específica, que ative menos material."""
    return (
        f"Essa pergunta ativou material demais pra eu ler com segurança numa resposta só "
        f"({quantidade_blocos} trechos, {caracteres_totais} caracteres). Fatiar isso em pedaços e "
        f"interpretar cada um separadamente arrisca misturar ou perder informação, então prefiro "
        f"não arriscar. Duas saídas:\n\n"
        f"- Se você quer uma visão geral do documento inteiro, peça um **resumo** dele.\n"
        f"- Se você quer uma resposta pontual, tente refinar a pergunta pra um assunto mais "
        f"específico, que ative menos trechos."
    )


# extrair_resposta_do_bloco, consolidar_extracoes, consolidar_grupo_intermediario_cobertura,
# selecionar_blocos_com_teto e responder_por_cobertura (Camada 3 original, map-reduce fragmentado)
# foram removidas em 2026-08-24 — ver decidir_rota_por_volume() e montar_mensagem_limite_excedido()
# acima pro porquê: fatiar o material e interpretar cada pedaço separado se mostrou pouco confiável
# em teste real (Os Sertões), e a rota direta ampliada resolveu o mesmo caso sem fatiar nada.


def montar_prompt(pergunta: str, chunks: list[str], historico: list[dict]) -> str:
    contexto = "\n\n---\n\n".join(chunks)
    historico_texto = montar_historico_texto(historico)
    return f"""Você é um assistente que responde com base em informações reais do usuário.
O CONTEXTO abaixo pode conter trechos de documentos (livros, PDFs) OU registros de
atividade do usuário (páginas visitadas no navegador, com título, link e data).
Alguns registros de navegação têm uma tag [origem: nome-do-pc] indicando de qual
computador aquele dado veio — use essa informação se o usuário perguntar sobre origem,
de qual PC/máquina algo veio, ou pedir para filtrar por dispositivo. Alguns trechos de
documento vêm marcados com "[trecho da página N]", indicando a página de origem daquele
trecho.

CITE A ORIGEM DE CADA AFIRMAÇÃO. Sempre que o trecho que você usou vier marcado com
"[trecho da página N]", termine a frase indicando a página, assim: (página N). Se uma
afirmação sua não puder ser apoiada em nenhum trecho do CONTEXTO, não a escreva — prefira
dizer que aquilo não está no material a afirmar sem origem.

Nunca cite capítulo, seção ou página de uma informação a menos que essa marcação apareça
literalmente no CONTEXTO abaixo, junto ao trecho de onde você tirou a informação. Use SOMENTE
uma marcação "[trecho da página N]" que esteja de fato ali. Não infira, não deduza e não
invente número de capítulo, seção ou página — é preferível não citar a origem do que citar uma
origem errada. Registro de navegação e dado sem marcação de página não recebem citação.

Atribua cada fala a quem realmente a disse no CONTEXTO. Antes de escrever "fulano disse X",
confira no trecho quem é o autor da fala — não presuma que é o personagem principal da sua
resposta.

Use o CONTEXTO para responder a pergunta da forma mais completa possível. Interprete
o pedido com bom senso: por exemplo, se o usuário pergunta o que "pesquisou" ou "viu"
e o contexto mostra páginas "visitadas", isso conta como resposta válida — não exija
correspondência exata de palavras.

Se depois de analisar o contexto com atenção a informação realmente não estiver lá,
diga claramente que não encontrou.

HISTÓRICO DA CONVERSA:
{historico_texto}

CONTEXTO:
{contexto}

PERGUNTA ATUAL: {pergunta}

RESPOSTA:"""

def perguntar_ao_modelo(prompt: str, num_ctx: int = NUM_CTX) -> str:
    # num_ctx exposto como parâmetro pra rota "direta_ampliada" (`responder_pergunta()`) poder
    # pedir NUM_CTX_AMPLIADO só quando o material não coube no teto normal — sem duplicar a
    # chamada HTTP pra isso.
    #
    # temperature=0 (achado real, 2026-08-25): sem isso, a mesma pergunta com o mesmo contexto
    # dava respostas bem diferentes entre uma chamada e outra — testando "quantos morreram em
    # Uauá?" no Os Sertões, uma chamada leu certo (150 sertanejos, dez mortes da expedição,
    # dezesseis feridos) e a chamada seguinte, com o MESMO prompt, perdeu a distinção entre
    # jagunços e soldados e confundiu mortos com feridos. É a tarefa de "bibliotecária" (achar e
    # relatar o que está escrito, ver ARQUITETURA.md) — não deveria variar por amostragem
    # aleatória a cada chamada. temperature=0 não corrige limite de leitura do modelo (isso é
    # limite de capacidade, não de aleatoriedade), mas garante que o mesmo material produza a
    # mesma leitura, em vez de um resultado às vezes bom e às vezes ruim por sorte.
    resposta = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": MODELO_LLM,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": 1024, "num_ctx": num_ctx, "temperature": 0}
        }
    )
    return resposta.json()["response"]

PALAVRAS_SINAL_DETALHAMENTO = ("cada", "todos os", "todas as")

def pede_detalhamento_de_itens(pergunta: str) -> bool:
    # Pré-checagem determinística: só considera candidato a "detalhado" se a pergunta tiver
    # sinal explícito de múltiplos itens. Sem isso, o classificador via LLM já disparou à toa
    # várias vezes em perguntas simples (ex: chegou a inventar um item que não existia nem na
    # pergunta nem no documento) — reduzir a superfície de erro aqui é mais confiável do que
    # empilhar mais exemplo few-shot pro modelo aprender a não errar.
    pergunta_normalizada = pergunta.lower()
    sinais_encontrados = [s for s in PALAVRAS_SINAL_DETALHAMENTO if s in pergunta_normalizada]
    if not sinais_encontrados:
        return False
    # "cada vez que..." é expressão temporal comum ("toda vez que"), não tem relação com
    # detalhar itens — sem essa exclusão, "cada vez que eu abro o arquivo dá erro" disparava
    # o classificador só por conter a palavra "cada" isolada. Só exclui quando "cada" é o
    # ÚNICO sinal encontrado — se a pergunta também tiver "todos os"/"todas as", ainda é válida.
    if sinais_encontrados == ["cada"] and "cada vez" in pergunta_normalizada:
        return False
    # "quantas vezes cada X" / "quantos Y cada Z" é pedido de contagem (frequência), não
    # detalhamento — sem essa exclusão, o modelo confundia contagem por item com explicação
    # aprofundada de item. Padrão determinístico em vez de exemplo few-shot: cobre qualquer
    # variação de frase com verbo de contagem + "cada", não só a frase testada.
    if sinais_encontrados == ["cada"] and any(
        verbo in pergunta_normalizada for verbo in ("quantas vezes", "quantos", "quantas", "conte")
    ):
        return False

    prompt = f"""Classifique o pedido abaixo:
- "detalhado" se o usuário quer uma explicação separada e aprofundada de VÁRIOS itens/tópicos
  distintos de um documento ou assunto (ex: cada proposta, cada personagem, cada motivo listado)
  — seja pedindo isso na própria pergunta ("com detalhes de cada uma", "explique cada item"),
  seja pedindo mais profundidade sobre algo que a conversa já tinha listado antes ("seja mais
  específico em cada um", "aprofunde cada ponto", "detalhe isso melhor").
- "simples" para qualquer outra pergunta pontual, que não pede um detalhamento item por item.

Exemplo 1:
PEDIDO: quais as propostas do livro X, com detalhes de cada uma
CATEGORIA: detalhado

Exemplo 2:
PEDIDO: seja mais específico em cada proposta
CATEGORIA: detalhado

Exemplo 3:
PEDIDO: quem é o personagem principal do livro X
CATEGORIA: simples

Exemplo 4:
PEDIDO: quem treina novos funcionários segundo o manual Y?
CATEGORIA: simples

Responda APENAS com "detalhado" ou "simples".

PEDIDO: {pergunta}

CATEGORIA:"""

    resposta = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": MODELO_LLM,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": 10, "temperature": 0}
        }
    )
    return "detalhado" in resposta.json()["response"].strip().lower()

def extrair_itens_de_texto(texto: str) -> list[str]:
    prompt = f"""Extraia os itens/tópicos distintos mencionados no texto abaixo, um por linha, só
o nome curto de cada item (sem explicação, sem numeração, sem marcador de lista). Se o texto não
enumerar itens distintos claros, responda apenas "NENHUM".

Exemplo:
TEXTO: As propostas incluem: contenção de gastos, reforma trabalhista e redução de supersalários.
ITENS:
contenção de gastos
reforma trabalhista
redução de supersalários

Agora extraia do texto real abaixo.

TEXTO: {texto}

ITENS:"""

    resposta = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": MODELO_LLM,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": 200, "temperature": 0}
        }
    )
    texto_resposta = resposta.json()["response"].strip()
    if texto_resposta.upper() == "NENHUM":
        return []
    return [linha.strip("-• ").strip() for linha in texto_resposta.split("\n") if linha.strip()]

def montar_prompt_item(item: str, chunks: list[str], pergunta_original: str) -> str:
    contexto = "\n\n---\n\n".join(chunks)
    return f"""Você é um assistente que responde com base em informações reais de documentos do usuário.
Explique especificamente o que o CONTEXTO abaixo diz sobre "{item}", no âmbito da pergunta original
do usuário: "{pergunta_original}". Seja objetivo e completo sobre esse item específico. Não repita
informação de outros itens, foque só em "{item}". Se o contexto não tiver informação sobre esse item,
diga isso claramente, não invente.

CONTEXTO:
{contexto}

DETALHES SOBRE "{item}":"""

def responder_com_detalhamento(pergunta: str, historico: list[dict], colecao, fonte_forcada: str | None = None, arquivo_forcado: str | None = None) -> str | None:
    itens = []
    contexto_pergunta = pergunta
    fonte = fonte_forcada

    if historico:
        itens = extrair_itens_de_texto(historico[-1]["resposta"])
        if itens:
            # follow-up vago ("seja mais específico") não tem contexto suficiente sozinho pra
            # detectar a fonte certa — usa a pergunta ORIGINAL que gerou a lista, não o follow-up.
            contexto_pergunta = historico[-1]["pergunta"]
            if fonte_forcada is None:
                fonte = detectar_fonte(contexto_pergunta)

    if not itens:
        pergunta_para_busca = reformular_pergunta(pergunta, historico if HISTORICO_PRONOME_ATIVO else [])
        contexto_pergunta = pergunta_para_busca
        if fonte_forcada is None:
            fonte = detectar_fonte(pergunta_para_busca)
        chunks_iniciais = buscar_chunks_relevantes(pergunta_para_busca, colecao, fonte)
        resposta_inicial = perguntar_ao_modelo(montar_prompt(pergunta, chunks_iniciais, historico))
        itens = extrair_itens_de_texto(resposta_inicial)

    if not itens:
        return None  # não achou itens distintos pra detalhar — deixa o fluxo normal responder

    # se um documento específico foi mencionado (na pergunta original, não no follow-up vago),
    # trava a busca de TODOS os itens nesse arquivo — evita vazar conteúdo de outro documento.
    # Quando o arquivo já veio escolhido por dropdown, não há o que identificar.
    arquivo = arquivo_forcado if arquivo_forcado is not None else identificar_arquivo_na_pergunta(contexto_pergunta, colecao)

    itens_cortados = itens[:LIMITE_ITENS_DETALHADOS]

    blocos = []
    for item in itens_cortados:
        # embute o contexto da pergunta original na busca — o nome do item sozinho ("ajustes
        # fiscais") é ambíguo demais e pode puxar chunks de outro documento por acaso.
        consulta_item = f"{item} — {contexto_pergunta}"
        chunks_item = buscar_chunks_relevantes(consulta_item, colecao, fonte, arquivo)
        resposta_item = perguntar_ao_modelo(montar_prompt_item(item, chunks_item, pergunta))
        blocos.append(f"**{item}**\n{resposta_item.strip()}")

    resposta_final = "\n\n".join(blocos)
    if len(itens) > LIMITE_ITENS_DETALHADOS:
        resposta_final += f"\n\n(mostrando os {LIMITE_ITENS_DETALHADOS} primeiros itens de {len(itens)} encontrados)"
    return resposta_final

def responder_pergunta(pergunta: str, historico: list[dict], colecao, fonte_forcada: str | None = None,
                        arquivo_forcado: str | None = None, progresso_callback=None) -> str:
    """fonte_forcada: quando o chamador já sabe a fonte (ex: funil da interface já resolveu
    "Documento" ou "Histórico" via botão), pula detectar_fonte() inteiro — sem isso, o filtro por
    fonte era decidido de novo aqui dentro mesmo quando essa decisão já tinha sido tomada fora,
    reabrindo exatamente o tipo de ambiguidade que o funil existe pra eliminar (achado testando o
    funil: pergunta vaga em "Consultar+Documento" trouxe conteúdo de histórico de navegação
    misturado). `None` mantém o comportamento de sempre (auto-detecção), usado pelo terminal.

    arquivo_forcado: mesma ideia, um nível abaixo — quando o usuário já escolheu o documento
    num dropdown (item 12 da fila), não há nada a identificar: a busca é travada nesse arquivo e
    `identificar_arquivo_na_pergunta()` (que depende do usuário nomear o arquivo dentro da frase)
    nem é chamada. `None` mantém a detecção automática, usada pelo terminal.

    progresso_callback: não usado nas rotas atuais (nenhuma delas é mais um map-reduce de vários
    passos — ver `decidir_rota_por_volume()`), mantido no parâmetro só pra não quebrar quem já
    chama `responder_pergunta()` passando esse argumento (ex: `jarvis.py`). `None` mantém o
    spinner indeterminado de sempre."""
    if pede_detalhamento_de_itens(pergunta):
        resposta_detalhada = responder_com_detalhamento(pergunta, historico, colecao, fonte_forcada, arquivo_forcado)
        if resposta_detalhada:
            return resposta_detalhada

    pergunta_para_busca = reformular_pergunta(pergunta, historico if HISTORICO_PRONOME_ATIVO else [])
    subperguntas = dividir_em_subperguntas(pergunta_para_busca)
    #print(f"[DEBUG] Subperguntas geradas: {subperguntas}")

    # Correção 2026-08-26 (achado real, "quem é o ciclope Polifemo e o que acontece com ele?"):
    # se resolver o pronome de uma sub-pergunta exige pegar emprestado o sujeito de uma
    # sub-pergunta ANTERIOR, isso já prova que não são tópicos independentes — "ele" só existe
    # por causa da primeira metade, não têm posição semântica própria comparável (testado: "quem
    # é Polifemo?" e "o que acontece com ele?", mesmo resolvida certo pra "Polifemo", caem em
    # posições DIFERENTES do episódio — identidade e enredo não convergem pro mesmo ponto,
    # mesmo sendo sobre o mesmo assunto). Funde tudo de volta na pergunta original ANTES de
    # sequer medir posição semântica — reaproveita `reformular_pergunta()` com o texto CRU da
    # sub-pergunta anterior como pseudo-histórico (não tem resposta de verdade ainda aqui).
    if len(subperguntas) > 1:
        houve_referencia_cruzada = False
        for i in range(1, len(subperguntas)):
            anterior = subperguntas[i - 1]
            resolvida = reformular_pergunta(subperguntas[i], [{"pergunta": anterior, "resposta": anterior}])
            if resolvida != subperguntas[i]:
                houve_referencia_cruzada = True
                break
        if houve_referencia_cruzada:
            subperguntas = [pergunta_para_busca]

    # Correção 2026-08-25 (achado real: datasheet técnico, "quais os estados de INHIBIT, C, B e A
    # para ativar o canal 5?" virou 4 sub-perguntas, uma por sinal, cada uma perdendo o resto do
    # contexto — a soma das 4 buscas separadas estourou o teto de contexto por ativar ruído que a
    # pergunta original, inteira, nunca teria ativado). `dividir_em_subperguntas()` classifica por
    # sintaxe (vírgula/"e" entre nomes) se é "um tópico ou vários" — não tem como saber por
    # sintaxe se uma lista de nomes é uma ENUMERAÇÃO DE PARTES DE UMA MESMA COISA (sinais de uma
    # linha de tabela) ou tópicos de verdade independentes (Google e YouTube). Em vez de ensinar
    # mais casos por exemplo de prompt (mesmo remendo de tentativa-e-erro já evitado na Camada 3),
    # MEDE: se as sub-perguntas "diferentes" ativam o MESMO material do documento (conjuntos de
    # chunks que se sobrepõem), são partes de uma coisa só — descarta a divisão e busca a pergunta
    # inteira, de uma vez. Só se aplica quando todas as sub-perguntas resolvem pro MESMO arquivo —
    # sub-perguntas de arquivos diferentes (ou sem arquivo, ex: histórico de navegação) não têm
    # material comparável, e continuam pelo caminho de sempre.
    #
    # Régua trocada em 2026-08-29 (era: distância entre os chunks CAMPEÕES de cada sub-pergunta).
    # O campeão é um ponto só e vira com qualquer palavra — "quais as causas que levaram à
    # revolução?" campeia no chunk 409 e "quais FORAM as causas..." no 21, mesmo livro, mesma
    # pergunta pra um humano. Resultado: a divisão não era desfeita e o usuário recebia a mesma
    # resposta escrita duas vezes. Ver LIMIAR_SOBREPOSICAO_SUBPERGUNTAS no config.py pros números
    # medidos (incluindo a alternativa por similaridade de TEXTO, que foi testada e reprovada).
    if len(subperguntas) > 1:
        fontes_e_arquivos = [
            (
                fonte_forcada if fonte_forcada is not None else detectar_fonte(sub),
                arquivo_forcado if arquivo_forcado is not None else identificar_arquivo_na_pergunta(sub, colecao),
            )
            for sub in subperguntas
        ]
        arquivos_distintos = {a for _, a in fontes_e_arquivos if a}
        if len(arquivos_distintos) == 1:
            arquivo_comum = next(iter(arquivos_distintos))
            fonte_comum = fontes_e_arquivos[0][0]
            conjuntos = [
                conjunto_ativado_por_subpergunta(sub, colecao, fonte_comum, arquivo_comum)
                for sub in subperguntas
            ]
            # MEDIANA das sobreposições par a par, não a média nem a unanimidade: uma sub-pergunta
            # pode sair malformada (achado real, "quais os estados de INHIBIT, C, B e A" -> a
            # sub-pergunta de INHIBIT sozinha perdeu o qualificador "para ativar o canal 5" que as
            # outras 3 mantiveram, então ativa material diferente mesmo sendo a mesma combinação).
            # A mediana ignora esse par destoante sem precisar detectá-lo; a média seria puxada
            # por ele. Com 2 sub-perguntas (o caso comum, "X e Y") só existe um par, e a mediana
            # degenera pra ele mesmo — correto, não há outlier a tolerar com um ponto só.
            conjuntos_validos = [c for c in conjuntos if c]
            if len(conjuntos_validos) >= 2:
                sobreposicoes = [
                    sobreposicao_de_conjuntos(conjuntos_validos[i], conjuntos_validos[j])
                    for i in range(len(conjuntos_validos))
                    for j in range(i + 1, len(conjuntos_validos))
                ]
                mediana_sobreposicao = sorted(sobreposicoes)[len(sobreposicoes) // 2]
                if mediana_sobreposicao >= LIMIAR_SOBREPOSICAO_SUBPERGUNTAS:
                    subperguntas = [pergunta_para_busca]

    # Correção 2026-08-26 (achado real, "quanto o Brasil gasta com o Minha Casa Minha Vida e
    # quais são os cinco pilares do AgroBrasil 2030?"): quando sobra mais de uma sub-pergunta de
    # VERDADE (assuntos diferentes, não fundidos pela checagem de convergência acima), juntar os
    # blocos de TODAS elas num prompt só e fazer UMA chamada ao modelo pra responder as duas
    # de uma vez arrisca contaminação cruzada — o bloco de uma sub-pergunta pode ter, colado por
    # coincidência de posição no documento, um número parecido de OUTRO assunto (aqui: "R$180
    # bilhões" do MCMV colado com "R$1,2-1,5 trilhão" de um programa de desfavelização diferente,
    # no capítulo seguinte), e o modelo troca qual pertence a qual ao ler as duas perguntas na
    # mesma passada. Testado: a MESMA sub-pergunta do MCMV, respondida ISOLADA (próprio contexto,
    # própria chamada), acerta o número certo — só errava quando fundida com a do AgroBrasil.
    # Por isso, com mais de uma sub-pergunta real, cada uma ganha seu próprio `reunir_contexto`,
    # sua própria decisão de rota e sua própria chamada ao modelo — a resposta final é a
    # concatenação dos textos, não uma leitura conjunta. Com só 1 sub-pergunta (nunca dividiu, ou
    # foi fundida de volta pela checagem de convergência), o caminho continua exatamente como
    # antes: um prompt só, uma chamada só, usando a pergunta ORIGINAL completa.
    if len(subperguntas) > 1:
        # Correção 2026-08-26 (achado real, "quem é o ciclope Polifemo e o que acontece com
        # ele?"): dividir em sub-perguntas ANTES de resolver pronome quebra referência CRUZADA
        # entre elas — "o que acontece com ele?" sozinha não sabe quem é "ele", busca por um
        # pronome solto e ativa qualquer trecho aleatório do livro com "ele". Reaproveita
        # `reformular_pergunta()` (a mesma correção gramatical de hoje) encadeando cada
        # sub-pergunta com a RESPOSTA já gerada da anterior como "histórico" — resolve "ele" ->
        # "Polifemo" com a mesma árvore de dependência, sem heurística nova.
        respostas = []
        historico_encadeado = []
        for sub in subperguntas:
            sub_resolvida = reformular_pergunta(sub, historico_encadeado) if historico_encadeado else sub
            fonte_detectada = fonte_forcada if fonte_forcada is not None else detectar_fonte(sub_resolvida)
            arquivo_detectado = arquivo_forcado if arquivo_forcado is not None else identificar_arquivo_na_pergunta(sub_resolvida, colecao)
            contexto = reunir_contexto(sub_resolvida, colecao, fonte_detectada, arquivo_detectado)
            blocos = list(dict.fromkeys(contexto["blocos"]))
            caracteres = sum(len(b) for b in blocos)
            rota = decidir_rota_por_volume(caracteres)
            prompt = montar_prompt(sub_resolvida, blocos, historico)
            if rota == "direta":
                resposta = perguntar_ao_modelo(prompt)
            elif rota == "direta_ampliada":
                resposta = perguntar_ao_modelo(prompt, num_ctx=NUM_CTX_AMPLIADO)
            else:
                resposta = montar_mensagem_limite_excedido(len(blocos), caracteres)
            respostas.append(resposta)
            historico_encadeado.append({"pergunta": sub, "resposta": resposta})
        return "\n\n".join(respostas)

    todos_blocos = []
    for sub in subperguntas:
        fonte_detectada = fonte_forcada if fonte_forcada is not None else detectar_fonte(sub)
        arquivo_detectado = arquivo_forcado if arquivo_forcado is not None else identificar_arquivo_na_pergunta(sub, colecao)
        #print(f"[DEBUG] Sub: '{sub}' | Fonte: {fonte_detectada or 'todas'} | Arquivo: {arquivo_detectado or 'todos'}")
        contexto = reunir_contexto(sub, colecao, fonte_detectada, arquivo_detectado)
        todos_blocos.extend(contexto["blocos"])

    blocos_unicos = list(dict.fromkeys(todos_blocos))
    #print(f"[DEBUG] Total de blocos únicos após juntar: {len(blocos_unicos)}")
    caracteres_totais = sum(len(b) for b in blocos_unicos)

    # Camada 2 (ver ARQUITETURA.md / plano do rework, "roteamento por volume"): decisão mecânica
    # por medição do material ativado, nunca por classificação de LLM (Princípio central #2).
    # Três rotas (achado real, 2026-08-24: substituiu o map-reduce fragmentado original — ver
    # `decidir_rota_por_volume()` e `montar_mensagem_limite_excedido()` acima pro porquê).
    rota = decidir_rota_por_volume(caracteres_totais)
    prompt = montar_prompt(pergunta, blocos_unicos, historico)

    if rota == "direta":
        return _com_verificacao(perguntar_ao_modelo(prompt), blocos_unicos)
    if rota == "direta_ampliada":
        return _com_verificacao(perguntar_ao_modelo(prompt, num_ctx=NUM_CTX_AMPLIADO), blocos_unicos)
    return montar_mensagem_limite_excedido(len(blocos_unicos), caracteres_totais)


def _com_verificacao(resposta: str, blocos: list[str]) -> str:
    """Confere a resposta contra os trechos que a originaram e ANEXA avisos. Nunca reescreve nem
    apaga a resposta — só sinaliza, deixando a decisão com quem lê (mesmo princípio do aviso de
    colagem em planilha).

    São três conferências independentes, e as duas MECÂNICAS são as que pagam a conta (custam
    milissegundos, sem modelo nenhum):
      - citação literal: o que está entre aspas existe mesmo na fonte?
      - autoria: quem a resposta diz que falou aparece perto da fala na fonte?
      - contradição (NLI): desligada por padrão — ver VERIFICAR_RESPOSTA_ATIVO no config.py.

    Falha silenciosa de propósito: verificação é acessório de confiança, não pode virar ponto
    único de falha. Qualquer erro aqui devolve a resposta como ela saía antes."""
    try:
        from verificar_resposta import (afirmacoes_contraditas, citacoes_nao_encontradas,
                                        atribuicoes_suspeitas, montar_aviso)
        contraditas = afirmacoes_contraditas(resposta, blocos) if VERIFICAR_RESPOSTA_ATIVO else []
        citacoes = citacoes_nao_encontradas(resposta, blocos) if VERIFICAR_CITACOES_LITERAIS else []
        atribuicoes = atribuicoes_suspeitas(resposta, blocos) if VERIFICAR_ATRIBUICAO else []
        return resposta + montar_aviso(contraditas, citacoes, atribuicoes)
    except Exception:
        return resposta


if __name__ == "__main__":
    cliente = chromadb.PersistentClient(path=PASTA_BANCO_VETORIAL)
    colecao = cliente.get_or_create_collection(name="documentos_pessoais")

    historico = []

    print("Assistente pronto. Digite 'sair' pra encerrar.\n")

    while True:
        pergunta = input("Você: ")
        if pergunta.lower() in ("sair", "exit"):
            break

        resposta = responder_pergunta(pergunta, historico, colecao)
        print(f"\nAssistente: {resposta}\n")

        historico.append({"pergunta": pergunta, "resposta": resposta})
        if len(historico) > TAMANHO_HISTORICO:
            historico.pop(0)

