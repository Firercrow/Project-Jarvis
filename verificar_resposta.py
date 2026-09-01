"""Confere se a resposta gerada é sustentada pelos trechos que a originaram.

Problema real (2026-08-29, usuário perguntou "qual a motivação da revolução?" no
revolucao-dos-bichos.pdf): o modelo afirmou que "o Major era um velho cavalo" quando o
documento diz "um porco da raça middle white". O trecho que identificava o Major não tinha sido
recuperado, e o modelo preencheu o vazio com narrativa plausível em vez de dizer que não sabia.
Ou seja: nada no sistema conferia a resposta contra a fonte depois de pronta.

Método: NLI (inferência de linguagem natural) — para cada afirmação da resposta, o modelo
classifica se o trecho a APOIA (entailment), a CONTRADIZ (contradiction) ou é indiferente
(neutral). É o método que a literatura aponta como o mais prático pra RAG, justamente por ter
uma fonte clara pra comparar (ver ARQUITETURA_V2.MD, seção de pesquisa).

**Escopo deliberado: só marcamos CONTRADIÇÃO.** Medido antes de escolher (mDeBERTa-v3-base-xnli,
multilíngue, em português):
  - "O Major é um porco"  -> entailment   0,996  (controle: apoiado)
  - "O Major é um cavalo" -> contradiction 0,994  (pega a alucinação real que motivou isto)
  - "A fazenda fica na França" -> neutral 0,999  (controle: assunto alheio)
"neutral" NÃO é marcado de propósito: é ambíguo — pode ser invenção, ou pode ser só uma
afirmação que está em outro trecho que não este. Marcar neutro encheria a resposta de alarme
falso; marcar contradição é alta precisão.

**Limitação conhecida e medida: NÃO pega troca de autor.** "O Major disse que não temos meios de
fazer açúcar" (quem disse foi Bola de Neve) passou como entailment 0,915, quase igual à versão
correta (0,998). É limitação conhecida de NLI: o modelo julga o CONTEÚDO da frase e ignora o
invólucro "fulano disse que". Fica registrado como buraco em aberto — não presumir que este
módulo cobre atribuição.

O modelo roda em CPU de propósito: é pequeno, o texto é curto, e roda DEPOIS da resposta pronta
— não disputa VRAM com o Ollama.
"""

import re

import requests

from config import (MODELO_NLI, MODELO_LLM, LIMIAR_CONTRADICAO,
                    MAXIMO_AFIRMACOES_VERIFICADAS, TRECHOS_CONFERIDOS_POR_AFIRMACAO,
                    MINIMO_CARACTERES_CITACAO, JANELA_BUSCA_FALANTE)

_verificador = None


def _obter_verificador():
    """Carrega o modelo uma vez só (leva ~14s na primeira chamada). Import de `transformers`
    fica aqui dentro, não no topo: assim quem importa este módulo sem usar a verificação (ex:
    testes rápidos) não paga o custo de carregar a biblioteca."""
    global _verificador
    if _verificador is None:
        from transformers import pipeline
        _verificador = pipeline("text-classification", model=MODELO_NLI, device=-1)
    return _verificador


def separar_afirmacoes(resposta: str) -> list[str]:
    """Quebra a resposta em afirmações ATÔMICAS — uma ideia por frase.

    Atômica, e não "uma frase da resposta": achado real (2026-08-29, medido). A mesma alucinação,
    contra o MESMO trecho que a desmente:
      - frase da resposta ("A Revolução começa com a inspiração do Major, um velho cavalo que
        incita os outros animais...")  -> neutral 0,580, passa batido
      - versão atômica ("O Major é um velho cavalo.")                  -> contradiction 0,995
    Numa frase composta, as partes verdadeiras diluem a falsa e o veredito vira morno. Por isso a
    decomposição é obrigatória, não enfeite — é também o que a literatura de verificação de
    fatos descreve ("the answer gets broken into individual claims").

    Usa o LLM que já está carregado. Risco baixo por construção: se ele inventar uma afirmação
    que não estava na resposta, o pior caso é o NLI conferir algo irrelevante — o erro vira uma
    detecção perdida, nunca um alarme falso sobre a resposta real."""
    if not resposta.strip():
        return []

    prompt = f"""Quebre o TEXTO abaixo em afirmações atômicas: uma ideia simples por linha.

Regras:
- Cada linha deve ser uma frase completa, curta, que se sustente sozinha.
- Troque pronomes pelo nome a que se referem ("ele" -> "o Major").
- Não acrescente nada que não esteja no texto. Não interprete, não conclua.
- Ignore frases sem conteúdo factual ("em resumo", "espero ter ajudado").

TEXTO:
{resposta}

AFIRMAÇÕES (uma por linha, sem numeração):"""

    try:
        resposta_http = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": MODELO_LLM,
                "prompt": prompt,
                "stream": False,
                "options": {"num_predict": 400, "temperature": 0},
            },
            timeout=120,
        )
        linhas = resposta_http.json()["response"].strip().split("\n")
    except (requests.RequestException, KeyError):
        # Ollama fora do ar: cai pro corte por frase. Pior detecção, mas a verificação não
        # derruba a resposta — ela é acessório, não pode virar ponto único de falha.
        linhas = re.split(r"(?<=[.!?])\s+", resposta.replace("\n", " "))

    limpas = [re.sub(r"^[\s\-\*\d\.\)]+", "", linha).strip() for linha in linhas]
    return [linha for linha in limpas if len(linha) > 15]


def afirmacoes_contraditas(resposta: str, trechos: list[str]) -> list[dict]:
    """Devolve as afirmações da resposta que algum trecho CONTRADIZ.

    Cada afirmação é conferida contra os `TRECHOS_CONFERIDOS_POR_AFIRMACAO` trechos mais
    parecidos com ela — não contra todos: o modelo tem teto de 512 tokens (o contexto inteiro
    não caberia) e conferir tudo contra tudo custaria tempo demais. A escolha de quais trechos
    é MECÂNICA (sobreposição de palavras), sem LLM decidindo.

    Uma afirmação apoiada por qualquer trecho não é marcada, mesmo que outro a contradiga —
    contradição aparente entre trechos é assunto do documento, não erro da resposta."""
    if not resposta.strip() or not trechos:
        return []

    afirmacoes = separar_afirmacoes(resposta)[:MAXIMO_AFIRMACOES_VERIFICADAS]
    if not afirmacoes:
        return []

    # Monta TODOS os pares de uma vez e manda num lote só: o modelo roda em CPU, e chamada a
    # chamada o custo é dominado por overhead por chamada, não pelo texto (medido: verificação
    # sequencial triplicava o tempo total da resposta).
    pares, indices = [], []
    for indice, afirmacao in enumerate(afirmacoes):
        for trecho in _trechos_mais_parecidos(afirmacao, trechos):
            pares.append({"text": trecho, "text_pair": afirmacao})
            indices.append(indice)

    verificador = _obter_verificador()
    # `truncation` é obrigatório: o modelo tem teto de 512 TOKENS, e cortar por caractere não
    # garante isso (achado real — um trecho de 2000 caracteres deu 598 tokens e o transformers
    # avisou que ia gerar erro de indexação).
    vereditos = verificador(pares, truncation=True, max_length=512, batch_size=8)

    por_afirmacao: dict[int, list[dict]] = {}
    for indice, veredito in zip(indices, vereditos):
        por_afirmacao.setdefault(indice, []).append(veredito)

    marcadas = []
    for indice, resultados in por_afirmacao.items():
        if any(v["label"] == "entailment" for v in resultados):
            continue
        contradicoes = [
            v for v in resultados
            if v["label"] == "contradiction" and v["score"] >= LIMIAR_CONTRADICAO
        ]
        if contradicoes:
            marcadas.append({
                "afirmacao": afirmacoes[indice],
                "confianca": max(v["score"] for v in contradicoes),
            })
    return marcadas


def _trechos_mais_parecidos(afirmacao: str, trechos: list[str]) -> list[str]:
    """Ordena os trechos por quantas palavras eles têm em comum com a afirmação. Mecânico de
    propósito (Princípio #2): escolher qual trecho conferir não é tarefa de interpretação."""
    palavras_afirmacao = set(re.findall(r"\w{4,}", afirmacao.lower()))
    def pontuacao(trecho: str) -> int:
        return len(palavras_afirmacao & set(re.findall(r"\w{4,}", trecho.lower())))
    return sorted(trechos, key=pontuacao, reverse=True)[:TRECHOS_CONFERIDOS_POR_AFIRMACAO]


def normalizar_para_comparar(texto: str) -> str:
    """Deixa o texto comparável com o que veio do PDF. Duas armadilhas reais, as duas medidas:
    o PDF quebra palavras com hífen no fim da linha ("te- mos"), e reparte espaços/quebras de
    forma imprevisível. Sem desfazer isso, a busca literal dá falso "não encontrei" — aconteceu
    comigo em 3 de 6 citações reais durante a conferência de 2026-08-29."""
    texto = re.sub(r"(\w)-\s+(\w)", r"\1\2", texto)
    return re.sub(r"\s+", " ", texto).strip().lower()


def citacoes_nao_encontradas(resposta: str, trechos: list[str]) -> list[str]:
    """Devolve o que a resposta pôs entre aspas mas NÃO existe literalmente nos trechos.

    Isto é o "Deterministic Quoting" da literatura: conferir por comparação direta com o
    texto-fonte, sem modelo nenhum. Pega o erro que o NLI não pegava — inventar uma citação cujo
    CONTEÚDO é plausível (achado real: "Vamos criar uma sociedade de animais livres da fome e do
    chicote" — a segunda metade existe, mas é narração sobre a égua Quitéria, e o "Vamos criar"
    é invenção; o NLI aprovou porque a ideia bate com o livro)."""
    fonte = normalizar_para_comparar(" ".join(trechos))
    suspeitas = []
    for citacao in re.findall(r'["“]([^"“”]{%d,})["”]' % MINIMO_CARACTERES_CITACAO, resposta):
        if normalizar_para_comparar(citacao) not in fonte:
            suspeitas.append(citacao.strip())
    return suspeitas


def atribuicoes_suspeitas(resposta: str, trechos: list[str]) -> list[dict]:
    """Devolve as falas que a resposta atribui a alguém que NÃO aparece perto delas na fonte.

    Achado real (2026-08-29): "O Major afirma que 'não temos os meios necessários para fazer
    açúcar nesta fazenda'" — a frase existe, mas quem a diz é Bola de Neve. O conteúdo está
    certo, o dono está errado, e nenhuma verificação de conteúdo pega isso (NLI deu entailment
    0,915, quase igual à versão correta).

    Mecânica: acha o padrão "<Nome> <verbo de dizer> ... <citação>", localiza a citação na fonte
    e procura na vizinhança dela uma marcação de fala EXPLÍCITA ("disse Fulano"). Só acusa
    quando encontra OUTRO falante — nunca pela simples ausência do nome esperado.

    Essa distinção veio de um falso positivo real (2026-08-29): a citação "O Homem é o único e
    verdadeiro inimigo que temos" é mesmo do Major, mas naquele ponto o texto está no meio do
    discurso dele e o nome não se repete — num discurso longo o falante é nomeado uma vez, no
    começo. Ausência do nome é evidência fraca; presença de outro falante é evidência forte.

    Só cobra quando a citação EXISTE na fonte — se não existe, o problema já é outro
    (`citacoes_nao_encontradas`) e cobrar duas vezes seria ruído."""
    fonte = normalizar_para_comparar(" ".join(trechos))
    suspeitas = []
    padrao = r'([A-ZÁÉÍÓÚÂÊÔÃÕÇ][\wÀ-ÿ]*(?:\s+de\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ][\wÀ-ÿ]*)*)\s+(?:disse|afirma|afirmou|declara|declarou|diz)\b[^"“]{0,80}["“]([^"“”]{%d,})["”]' % MINIMO_CARACTERES_CITACAO
    for nome, citacao in re.findall(padrao, resposta):
        citacao_normalizada = normalizar_para_comparar(citacao)
        posicao = fonte.find(citacao_normalizada)
        if posicao < 0:
            continue  # citação inexistente: já cobrada pela conferência literal
        inicio = max(0, posicao - JANELA_BUSCA_FALANTE)
        vizinhanca = fonte[inicio:posicao + len(citacao_normalizada) + JANELA_BUSCA_FALANTE]
        nome_normalizado = normalizar_para_comparar(nome)
        if nome_normalizado in vizinhanca:
            continue  # o nome que a resposta citou está ali mesmo: nada a apontar
        falantes = _falantes_marcados(vizinhanca)
        if falantes and all(nome_normalizado not in f and f not in nome_normalizado for f in falantes):
            suspeitas.append({
                "nome": nome,
                "citacao": citacao.strip(),
                "falante_no_texto": sorted(falantes)[0],
            })
    return suspeitas


def _falantes_marcados(texto: str) -> set[str]:
    """Nomes que o texto marca EXPLICITAMENTE como quem falou ("disse Bola de Neve"). O texto
    chega normalizado (minúsculo), então o nome não pode ser achado por maiúscula — é a marcação
    de fala que o identifica. Cobre nome composto ("bola de neve")."""
    padrao = r'(?:disse|afirmou|declarou|respondeu|perguntou|gritou|explicou)\s+((?:o\s+|a\s+)?[\wÀ-ÿ]+(?:\s+de\s+[\wÀ-ÿ]+)*)'
    achados = set()
    for bruto in re.findall(padrao, texto):
        nome = re.sub(r'^(o|a)\s+', '', bruto).strip()
        if len(nome) > 2:
            achados.add(nome)
    return achados


def montar_aviso(contraditas: list[dict] = (), citacoes: list[str] = (),
                 atribuicoes: list[dict] = ()) -> str:
    """Texto do aviso anexado à resposta. Nunca APAGA nem reescreve o que o modelo respondeu —
    só sinaliza, deixando a decisão com quem lê (mesmo princípio do aviso de colagem em
    planilha: avisar, nunca alterar o resultado silenciosamente)."""
    partes = []
    if contraditas:
        linhas = "\n".join(f'- "{c["afirmacao"]}"' for c in contraditas)
        partes.append(f"⚠️ **Confira estas afirmações** — o documento parece dizer o contrário:\n{linhas}")
    if citacoes:
        linhas = "\n".join(f'- "{c}"' for c in citacoes)
        partes.append(f"⚠️ **Citação não encontrada no documento** — confira antes de usar:\n{linhas}")
    if atribuicoes:
        linhas = "\n".join(
            f'- "{a["citacao"]}" — atribuída a **{a["nome"]}**, mas no documento quem fala ali '
            f'é **{a["falante_no_texto"]}**'
            for a in atribuicoes
        )
        partes.append(f"⚠️ **Autoria trocada** — confira quem disse:\n{linhas}")
    return "\n\n---\n" + "\n\n".join(partes) if partes else ""
