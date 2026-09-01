import os
import re
import requests
import chromadb

from config import (
    PASTA_BANCO_VETORIAL,
    PASTA_DOCUMENTOS,
    MODELO_LLM,
    MODELO_LLM_AUXILIAR,
    SOBREPOSICAO,
    NUM_CTX,
)
from indexar import (
    EXTENSOES_SEM_PAGINACAO_REAL,
    possui_estrutura_de_secoes,
    extrair_secoes_pdf,
    localizar_titulos_docx,
)
from texto import normalizar_nome, normalizar_pedido, normalizar_frase, remover_avisos_do_sistema, variantes_numerais

CHUNKS_POR_BLOCO = 15
LIMITE_RESUMOS_POR_SINTESE = 10  # acima disso, sintetiza em duas camadas pra não estourar o contexto do modelo

def listar_arquivos_disponiveis(colecao) -> list[str]:
    todos = colecao.get(where={"fonte": "documento"})
    return sorted(set(m["arquivo"] for m in todos["metadatas"]))

def encontrar_arquivo(nome_arquivo: str, colecao) -> tuple[str | None, str | None]:
    """Casa o nome digitado com um arquivo real indexado. Retorna (nome_real, None) em caso de
    sucesso, ou (None, mensagem_de_erro) se não achar exatamente um."""
    pedido = normalizar_pedido(nome_arquivo)
    if len(pedido) < 3:
        return None, f"'{nome_arquivo}' é um termo curto demais pra identificar o arquivo com segurança. Seja mais específico."

    arquivos_disponiveis = listar_arquivos_disponiveis(colecao)
    correspondencias = [
        a for a in arquivos_disponiveis
        if pedido in normalizar_nome(a)
    ]

    if not correspondencias:
        return None, f"Nenhum arquivo encontrado parecido com '{nome_arquivo}'. Verifique o nome."
    if len(correspondencias) > 1:
        return None, f"Mais de um arquivo corresponde: {correspondencias}. Seja mais específico."
    return correspondencias[0], None

def buscar_pares_chunk_metadata(nome_arquivo: str, colecao) -> list[tuple[dict, str]]:
    resultado = colecao.get(where={"arquivo": nome_arquivo})
    pares = list(zip(resultado["metadatas"], resultado["documents"]))
    pares.sort(key=lambda p: p[0]["chunk_num"])
    return pares

def buscar_todos_chunks_do_arquivo(nome_arquivo: str, colecao) -> list[str]:
    return [documento for _, documento in buscar_pares_chunk_metadata(nome_arquivo, colecao)]

def contar_ocorrencias(nome_arquivo: str, termo: str, colecao) -> int:
    chunks = buscar_todos_chunks_do_arquivo(nome_arquivo, colecao)
    texto_completo = " ".join(chunks)
    return texto_completo.lower().count(termo.lower())

def contar_termo_no_arquivo(nome_arquivo: str, termo: str, colecao) -> str:
    nome_real, erro = encontrar_arquivo(nome_arquivo, colecao)
    if erro:
        return erro

    total = contar_ocorrencias(nome_real, termo, colecao)
    return f"O termo '{termo}' aparece aproximadamente {total} vezes em '{nome_real}'."

LIMITE_PAGINAS_LISTADAS = 20  # acima disso, só a quantidade -- listar viraria ruído pra termo comum


def tamanho_aproximado_documento(nome_arquivo: str, colecao) -> int | None:
    """Tamanho APROXIMADO do documento indexado, em caracteres. Usado só pra avisar o usuário do
    volume antes de transcrever tudo (ver interface.py, confirmação de transcrição inteira) —
    nunca pra decidir rota nem cortar conteúdo.

    Aproximado de propósito: os chunks se sobrepõem (`SOBREPOSICAO` no config.py), então somar o
    tamanho de todos conta o texto da emenda duas vezes. Serve pra dar ordem de grandeza ("é um
    arquivo enorme ou pequeno?"), que é o que a confirmação precisa. `None` quando o arquivo não
    tem conteúdo indexado."""
    pares = buscar_pares_chunk_metadata(nome_arquivo, colecao)
    if not pares:
        return None
    return sum(len(texto) for _, texto in pares)


def contar_termo_por_pagina(nome_arquivo: str, termo: str, colecao) -> str:
    """Diferente de `contar_termo_no_arquivo()` (só o total, sem localização): usa o metadado
    `pagina` que cada chunk já carrega (`indexar.py: pagina_do_offset()`, 1-indexado) pra dizer
    ONDE o termo aparece, não só quantas vezes. Formato de saída decidido pelo usuário: termo em
    mais de `LIMITE_PAGINAS_LISTADAS` páginas diferentes → só a quantidade; senão → lista as
    páginas. Em `.txt` (sem paginação real, `EXTENSOES_SEM_PAGINACAO_REAL`), toda ocorrência cai
    em "página 1" — resultado ainda correto, só menos útil, mesma limitação já documentada."""
    nome_real, erro = encontrar_arquivo(nome_arquivo, colecao)
    if erro:
        return erro

    pares = buscar_pares_chunk_metadata(nome_real, colecao)
    if not pares:
        return f"'{nome_real}' não tem conteúdo indexado."

    termo_normalizado = termo.lower()
    paginas_com_termo = set()
    total_ocorrencias = 0
    for metadado, texto in pares:
        ocorrencias = texto.lower().count(termo_normalizado)
        if ocorrencias:
            total_ocorrencias += ocorrencias
            paginas_com_termo.add(metadado["pagina"])

    if not paginas_com_termo:
        return f"O termo '{termo}' não aparece em '{nome_real}'."

    paginas_ordenadas = sorted(paginas_com_termo)
    resultado = f"O termo '{termo}' aparece aproximadamente {total_ocorrencias} vez(es) em '{nome_real}'"
    if len(paginas_ordenadas) > LIMITE_PAGINAS_LISTADAS:
        return f"{resultado}, espalhado por {len(paginas_ordenadas)} páginas diferentes."
    lista_paginas = ", ".join(str(p) for p in paginas_ordenadas)
    return f"{resultado}, nas páginas: {lista_paginas}."

def normalizar_busca_conteudo(texto: str) -> str:
    """Normalização leve pra localizar um termo dentro do conteúdo (não pra contagem exata —
    ver contar_termo_no_arquivo, que é proposital sobre isso). Remove pontuação e caixa, pra
    "Sr. Jones" bater com "sr jones" sem depender de pontuação exata do texto extraído do PDF."""
    return re.sub(r'[.,;:!?"\']', '', texto.lower())

def remover_sobreposicao(anterior: str, atual: str, margem: int = 20) -> str:
    """Remove do início de 'atual' o trecho que já apareceu no fim de 'anterior' — os chunks
    indexados têm sobreposição proposital (config.SOBREPOSICAO) pra não cortar frase no meio,
    mas isso duplicaria texto se os chunks fossem só concatenados direto."""
    limite = min(SOBREPOSICAO + margem, len(anterior), len(atual))
    for tamanho in range(limite, 0, -1):
        if anterior[-tamanho:] == atual[:tamanho]:
            return atual[tamanho:]
    return atual

# Saída oferecida quando a transcrição por trecho não é a ferramenta certa. É o chamador que
# informa o caminho, porque o caminho depende de ONDE o usuário está: no funil da interface ele
# precisa trocar de categoria; no terminal, basta perguntar. Sem isso a mensagem sugeria uma ação
# inexistente no contexto atual — o usuário seguiu a sugestão ao pé da letra e recebeu a MESMA
# recusa, num loop fechado (achado no teste humano de 2026-08-22).
SUGESTAO_PERGUNTA_PADRAO = ("Para saber o que o documento diz sobre isso, faça uma pergunta "
                            "sobre o tema em vez de pedir a transcrição.")


def _secoes_disponiveis(caminho_real: str, extensao: str, pares: list[tuple[dict, str]]) -> list[dict]:
    """Seções detectáveis do documento, com posição — `[{"titulo", "nivel", "posicao"}, ...]`.
    `posicao` é PÁGINA pro PDF (direto do sumário) ou ÍNDICE DE CHUNK pro DOCX (localizado
    buscando o texto do título nos chunks já indexados — mesma técnica de `termo_busca`, porque
    DOCX não tem página real pra usar como posição). Lista vazia se o documento não tiver nenhuma
    seção detectável, ou se o formato não for PDF/DOCX."""
    if extensao == ".pdf":
        return [
            {"titulo": s["titulo"], "nivel": s["nivel"], "posicao": s["pagina"]}
            for s in extrair_secoes_pdf(caminho_real)
        ]
    if extensao == ".docx":
        secoes = []
        for nivel, titulo in localizar_titulos_docx(caminho_real):
            titulo_normalizado = normalizar_busca_conteudo(titulo)
            indice = next(
                (i for i, (_, doc) in enumerate(pares) if titulo_normalizado in normalizar_busca_conteudo(doc)),
                None,
            )
            if indice is not None:
                secoes.append({"titulo": titulo, "nivel": nivel, "posicao": indice})
        return secoes
    return []


def _casar_secao(secoes: list[dict], termo_busca: str) -> dict | None:
    """Acha a seção cujo título casa com o termo pedido — normaliza os dois lados e tenta também
    a variante com número trocado (arábico<->romano, ver `variantes_numerais`), pra 'capítulo 1'
    casar com 'Capítulo I' no sumário."""
    termo_normalizado = normalizar_frase(termo_busca)
    variantes = variantes_numerais(termo_normalizado)
    for secao in secoes:
        titulo_normalizado = normalizar_frase(secao["titulo"])
        if any(variante in titulo_normalizado for variante in variantes):
            return secao
    return None


def _limite_da_secao(secoes: list[dict], secao_casada: dict) -> int | None:
    """Posição onde a seção seguinte de mesmo nível ou mais rasa começa — essa é a fronteira
    certa (uma SUBseção dentro do capítulo não deve cortar o capítulo no meio). `None` quando é a
    última seção nesse nível, ou seja, vai até o fim do documento."""
    candidatos = [
        s["posicao"] for s in secoes
        if s["posicao"] > secao_casada["posicao"] and s["nivel"] <= secao_casada["nivel"]
    ]
    return min(candidatos) if candidatos else None

def transcrever_arquivo(
    nome_arquivo: str, colecao,
    pagina_inicio: int | None = None, pagina_fim: int | None = None,
    termo_busca: str | None = None, sugestao_alternativa: str | None = None,
) -> str:
    nome_real, erro = encontrar_arquivo(nome_arquivo, colecao)
    if erro:
        return erro

    pares = buscar_pares_chunk_metadata(nome_real, colecao)
    if not pares:
        return f"'{nome_real}' não tem conteúdo indexado."

    if termo_busca:
        extensao = os.path.splitext(nome_real)[1].lower()
        caminho_real = os.path.join(PASTA_DOCUMENTOS, nome_real)
        secoes = _secoes_disponiveis(caminho_real, extensao, pares) if extensao in (".pdf", ".docx") else []
        secao_casada = _casar_secao(secoes, termo_busca) if secoes else None

        # Correção 2026-08-25 (achado real: "transcreva o capítulo 1" caía na busca de termo
        # comum abaixo — primeiro-ao-último trecho onde "capítulo 1" aparece literalmente, quase
        # sempre só o próprio título, nunca "até o capítulo acabar". Quando o termo casa com uma
        # seção de verdade do sumário/título do documento, usa a fronteira real da seção (início
        # dela até o início da PRÓXIMA seção de mesmo nível ou mais rasa) em vez da lógica de
        # termo solto — ver `_casar_secao`/`_limite_da_secao`.
        if secao_casada:
            fim = _limite_da_secao(secoes, secao_casada)
            if extensao == ".pdf":
                pares = [
                    (meta, doc) for meta, doc in pares
                    if meta.get("pagina", 0) >= secao_casada["posicao"]
                    and (fim is None or meta.get("pagina", 0) < fim)
                ]
            else:  # .docx — posicao/fim são índice de chunk, não página
                pares = pares[secao_casada["posicao"]:fim]
                # Achado real, 2026-08-25 (testado com DOCX sintético): o chunk que contém o
                # título também pode ter sobra do FIM da seção anterior colada, por causa da
                # sobreposição de chunk (ver `SOBREPOSICAO` em `config.py`) — não muda a
                # sobreposição em si (isso é global, usado em toda a indexação), só corta uma
                # CÓPIA local do texto desse primeiro chunk, só nesta função, pra começar
                # exatamente no título em vez de incluir a sobra que vazou da seção anterior.
                if pares:
                    meta_primeiro, doc_primeiro = pares[0]
                    indice_titulo = normalizar_busca_conteudo(doc_primeiro).find(
                        normalizar_busca_conteudo(secao_casada["titulo"])
                    )
                    if indice_titulo > 0:
                        pares[0] = (meta_primeiro, doc_primeiro[indice_titulo:])
            if not pares:
                return (
                    f"Seção '{secao_casada['titulo']}' identificada em '{nome_real}', mas sem "
                    f"conteúdo indexado nela — pode indicar reindexação pendente."
                )
        else:
            termo_normalizado = normalizar_busca_conteudo(termo_busca)
            indices_com_termo = [
                i for i, (_, doc) in enumerate(pares)
                if termo_normalizado in normalizar_busca_conteudo(doc)
            ]
            if not indices_com_termo:
                if secoes:
                    nomes = ", ".join(f'"{s["titulo"]}"' for s in secoes[:15])
                    a_mais = f" (+{len(secoes) - 15} outras)" if len(secoes) > 15 else ""
                    return (
                        f"'{termo_busca}' não bateu com nenhuma seção nem trecho literal de "
                        f"'{nome_real}'. Seções identificadas no documento: {nomes}{a_mais}."
                    )
                return f"O termo '{termo_busca}' não foi encontrado em '{nome_real}'."

            intervalo = max(indices_com_termo) - min(indices_com_termo) + 1
            cobertura = intervalo / len(pares)
            if cobertura > 0.5:
                return (
                    f"'{termo_busca}' aparece espalhado por {cobertura:.0%} do documento '{nome_real}' "
                    f"— não parece uma seção localizada, e sim um tema recorrente pelo documento "
                    f"inteiro. Transcrever do primeiro ao último trecho devolveria quase o documento "
                    f"todo, fingindo ser um recorte.\n\n{sugestao_alternativa or SUGESTAO_PERGUNTA_PADRAO}"
                )
            pares = pares[min(indices_com_termo):max(indices_com_termo) + 1]
    elif pagina_inicio is not None or pagina_fim is not None:
        extensao = os.path.splitext(nome_real)[1].lower()

        # Correção 2026-08-25 (achado real, 2026-08-20 — "transcreva as 3 primeiras páginas" de
        # um .docx devolvia o documento inteiro, sem avisar): TXT e DOCX sempre têm
        # offsets_paginas=[0] (todo chunk cai em "página 1", ver `indexar.py`), então o filtro
        # abaixo não filtrava NADA nesses formatos — falha silenciosa, a mais perigosa (parece
        # ter funcionado). Recusa honesta em vez disso, e sempre informa se o documento tem ou
        # não estrutura de seção detectável (sumário/título) — mesmo sem ainda saber recortar por
        # ela, é informação útil pro usuário decidir o próximo pedido.
        if extensao in EXTENSOES_SEM_PAGINACAO_REAL:
            if extensao == ".txt":
                nota_estrutura = "TXT é texto corrido — não tem conceito de página nem de seção."
            else:
                caminho_real = os.path.join(PASTA_DOCUMENTOS, nome_real)
                if possui_estrutura_de_secoes(caminho_real, extensao):
                    nota_estrutura = (
                        f"'{nome_real}' tem título/seção identificável — peça pelo nome do "
                        f"capítulo/seção (via termo) em vez de número de página, que esse "
                        f"formato não tem."
                    )
                else:
                    nota_estrutura = f"'{nome_real}' não tem nenhum título/seção identificável."
            return (
                f"{'TXT' if extensao == '.txt' else 'Word (.docx)'} não guarda número de página "
                f"real sem renderizar (diferente de PDF), então não dá pra filtrar por página com "
                f"segurança nesse formato. {nota_estrutura}\n\n"
                f"Alternativas: peça a transcrição do documento inteiro, ou use um termo/trecho "
                f"específico (inclusive um marcador literal escrito no próprio texto, tipo "
                f"\"página 1\", se existir)."
            )

        pares = [
            (meta, doc) for meta, doc in pares
            if (pagina_inicio is None or meta.get("pagina", 0) >= pagina_inicio)
            and (pagina_fim is None or meta.get("pagina", 0) <= pagina_fim)
        ]
        if not pares:
            return f"Nenhum conteúdo encontrado nesse intervalo de páginas em '{nome_real}'. (obs: reindexação recente pode ser necessária pra esse arquivo ter páginas rastreadas)"

    chunks = [doc for _, doc in pares]
    partes = [chunks[0]]
    for chunk in chunks[1:]:
        partes.append(remover_sobreposicao(partes[-1], chunk))
    return "".join(partes)

# Formato fixo da memória de resposta longa (decisão do usuário, 2026-08-20):
# até 1000 caracteres a resposta é guardada inteira; acima disso vira
# 500 caracteres literais do início + até 500 de resumo da conclusão.
LIMITE_RESPOSTA_NO_HISTORICO = 1000
TAMANHO_CABECA_LITERAL = 500   # começo preservado palavra por palavra, sem passar pelo modelo
TAMANHO_RESUMO_CONCLUSAO = 500  # teto do trecho gerado, cortado em código e não só pedido no prompt

def separar_cabeca_literal(texto: str) -> tuple[str, str]:
    """Separa o começo da resposta (preservado literalmente) do resto (que será resumido),
    cortando sempre numa fronteira natural e nunca passando de TAMANHO_CABECA_LITERAL.

    Ordem de preferência do corte: quebra de linha > fim de frase > espaço entre palavras.
    Os três níveis existem porque as respostas do sistema têm formatos bem diferentes: listagem
    de planilha/navegação é feita de muitas linhas curtas, mas resumo de documento e resposta de
    pergunta são texto corrido, que pode não ter nenhuma quebra de linha por milhares de
    caracteres.

    A primeira versão cortava só em quebra de linha e falhava justamente no texto corrido: num
    parágrafo único de 3.000 caracteres ela devolvia o parágrafo inteiro como "cabeça", o corpo
    saía vazio e a resposta NÃO era condensada — sem erro nenhum, o contexto continuava
    estourando (achado 2026-08-20, testando com resumo de livro em vez de listagem)."""
    if len(texto) <= TAMANHO_CABECA_LITERAL:
        return texto, ""

    corte = texto.rfind("\n", 0, TAMANHO_CABECA_LITERAL)
    if corte <= 0:
        corte = max(texto.rfind(fim, 0, TAMANHO_CABECA_LITERAL) for fim in (". ", "! ", "? "))
        corte = corte + 1 if corte > 0 else texto.rfind(" ", 0, TAMANHO_CABECA_LITERAL)
    if corte <= 0:
        corte = TAMANHO_CABECA_LITERAL  # texto sem espaço nenhum: corta no limite mesmo

    return texto[:corte].strip(), texto[corte:].strip()

def condensar_para_historico(texto: str) -> str:
    """Condensa uma resposta longa ANTES de ela entrar na memória de conversa.

    Vale para QUALQUER resposta do chat que passe do limite — resumo de documento, resposta de
    pergunta (RAG), listagem de planilha ou de histórico. Não é uma solução para um formato
    específico: o formato "início literal + conclusão resumida" foi escolhido porque serve aos
    dois extremos — num texto corrido (resumo de livro) o que importa é como começa e como
    termina; numa listagem, o cabeçalho e o fecho.

    Motivo: o histórico inteiro vai dentro do prompt a cada nova pergunta, e uma listagem de
    planilha/navegação passa fácil de 3.000 caracteres — com poucas trocas dessas o `num_ctx`
    (8192) estoura, e estouro aqui não dá erro: o modelo simplesmente ignora parte do material
    (foi o que quebrou a síntese final de livro grande, ver item 10 da fila).

    Por que resumir em vez de cortar nos primeiros N caracteres (decisão do usuário,
    2026-08-20): o corte cego decapita justamente a parte que costuma importar (o fim de uma
    listagem, a conclusão de uma resposta). Um resumo curto preserva do que se tratava. Usa o
    MODELO_LLM_AUXILIAR — é tarefa mecânica e intermediária, o usuário nunca lê este texto
    diretamente; ele existe só pra o modelo saber do que a conversa vinha falando.

    O que o usuário VÊ na tela nunca é afetado — só o que vai pro prompt."""
    # Avisos do sistema ("nenhum filtro foi aplicado", "mostrando as primeiras 20 de 4000") são
    # comentário sobre a consulta que acabou de rodar — não são conteúdo, e não fazem sentido
    # como memória pras próximas perguntas. Saem antes de qualquer coisa: nem entram na cabeça
    # literal, nem chegam ao modelo que resume.
    texto = remover_avisos_do_sistema(texto)

    if len(texto) <= LIMITE_RESPOSTA_NO_HISTORICO:
        return texto

    # A cabeça sai literal, sem passar pelo modelo: é onde mora a contagem ("Encontrei 853
    # entrada(s)") e a frase de abertura da resposta. Testado em 2026-08-20: pedindo pro modelo
    # "preservar o número exato", ele mesmo assim perdeu o 853 e INVENTOU "39 itens" (contou as
    # linhas visíveis). Como o histórico alimenta a resposta seguinte, esse número falso seria
    # repetido como fato. Instrução de prompt não resolve isso — tirar o número do alcance do
    # modelo, sim.
    cabeca, corpo = separar_cabeca_literal(texto)
    if not corpo.strip():
        return texto

    # ATENÇÃO: o teto de 500 caracteres abaixo vale SÓ para esta memória interna de conversa,
    # que o usuário nunca lê. O resumo que o usuário PEDE de um documento é outro caminho
    # (resumir_arquivo -> resumir_bloco -> sintetizar_grupo_intermediario ->
    # sintetizar_resumo_final), roda no modelo principal e não tem limite de caracteres —
    # nunca aplicar este teto lá.
    prompt = f"""Resuma o texto abaixo em no máximo 2 frases curtas, para servir de memória de uma
conversa. O começo já foi guardado à parte — aqui interessa para onde o texto foi e COMO ELE
TERMINA: a conclusão, o desfecho, o resultado a que chegou.

REGRAS:
- Seja breve: no máximo 500 caracteres.
- Não acrescente nada que não esteja no texto.
- Não conte itens nem calcule totais; use só números que apareçam escritos no texto, copiados
  exatamente como estão.

TEXTO:
{corpo}

RESUMO DA CONCLUSÃO:"""

    try:
        resposta = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": MODELO_LLM_AUXILIAR,
                "prompt": prompt,
                "stream": False,
                "options": {"num_predict": 160, "num_ctx": NUM_CTX, "temperature": 0}
            },
            timeout=60,
        )
        resumo = resposta.json()["response"].strip()
        # o teto de tamanho é garantido em código, não só pedido no prompt — o modelo ignora
        # instrução de tamanho com frequência, e aqui o objetivo é justamente não crescer.
        if len(resumo) > TAMANHO_RESUMO_CONCLUSAO:
            resumo = resumo[:TAMANHO_RESUMO_CONCLUSAO].rsplit(" ", 1)[0] + "..."
    except Exception:
        resumo = ""

    # Se a condensação falhar (Ollama fora do ar, timeout), fica só a cabeça literal + aviso:
    # perde-se o detalhe do corpo, mas nada é inventado e o contexto não estoura.
    if not resumo:
        return f"{cabeca}\n[resposta longa, resumo indisponível]"
    return f"{cabeca}\n[resumo da conclusão] {resumo}"

def agrupar_em_blocos(chunks: list[str], tamanho_bloco: int) -> list[str]:
    blocos = []
    for i in range(0, len(chunks), tamanho_bloco):
        grupo = chunks[i:i + tamanho_bloco]
        blocos.append("\n\n".join(grupo))
    return blocos

def dividir_em_grupos(itens: list[str], tamanho: int) -> list[list[str]]:
    return [itens[i:i + tamanho] for i in range(0, len(itens), tamanho)]

def resumir_bloco(texto_bloco: str, indice: int, total: int) -> str:
    """Correção 2026-08-27 (achado real: resumo do livro amarelo inventou "Lula Máreo", nome que
    não existe em nenhum dos 311 chunks indexados): as 3 etapas do resumo (`resumir_bloco`,
    `sintetizar_grupo_intermediario`, `sintetizar_resumo_final`) passaram do modelo AUXILIAR
    (llama3.2:3b) pro PRINCIPAL (llama3.1:8b) nas duas primeiras — modelo menor tende a alucinar
    mais, mesmo lendo texto real (não é só "resumo de resumo" que perde grounding). Custo medido:
    ~1,54x mais lento por bloco (7,0s → 10,7s), ~1,3 min a mais no livro inteiro — parcialmente
    compensado por eliminar a troca de modelo na VRAM que existia entre a etapa 2 (antes auxiliar)
    e a 3 (sempre principal). `temperature=0` também adicionado nas 3 chamadas — sem isso, o
    resumo variava entre execuções idênticas (mesmo padrão já corrigido em `perguntar_ao_modelo()`
    pra busca), o que tornava a alucinação impossível de reproduzir/investigar de propósito."""
    prompt = f"""Resuma o texto abaixo de forma objetiva, preservando os fatos,
nomes e eventos principais. Não invente informação que não esteja no texto.

TEXTO:
{texto_bloco}

RESUMO:"""

    resposta = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": MODELO_LLM,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": 600, "num_ctx": NUM_CTX, "temperature": 0}
        }
    )
    print(f"  Bloco {indice}/{total} resumido.")
    return resposta.json()["response"]

def sintetizar_grupo_intermediario(mini_resumos_grupo: list[str], nome_arquivo: str, indice: int, total: int) -> str:
    todos_resumos = "\n\n---\n\n".join(mini_resumos_grupo)
    prompt = f"""Abaixo estão resumos parciais de uma seção do documento "{nome_arquivo}",
na ordem em que aparecem no texto original. Junte-os em um resumo intermediário
coerente dessa seção, preservando todos os fatos, nomes e eventos importantes —
esse resumo intermediário ainda será combinado com resumos de outras seções
depois, então não corte informação relevante.

RESUMOS PARCIAIS DA SEÇÃO:
{todos_resumos}

RESUMO DA SEÇÃO:"""

    resposta = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": MODELO_LLM,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": 700, "num_ctx": NUM_CTX, "temperature": 0}
        }
    )
    print(f"  Grupo intermediário {indice}/{total} sintetizado.")
    return resposta.json()["response"]

def sintetizar_resumo_final(mini_resumos: list[str], nome_arquivo: str) -> str:
    todos_resumos = "\n\n---\n\n".join(mini_resumos)
    prompt = f"""Abaixo estão resumos parciais de diferentes partes do documento
"{nome_arquivo}", na ordem em que aparecem no texto original. Junte-os em um
resumo único, coerente e bem estruturado do documento inteiro. Não repita
informação desnecessariamente, mantenha a ordem lógica dos eventos/temas.

RESUMOS PARCIAIS:
{todos_resumos}

RESUMO FINAL:"""

    resposta = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": MODELO_LLM,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": 1500, "num_ctx": NUM_CTX, "temperature": 0}
        }
    )
    return resposta.json()["response"]

def resumir_arquivo(nome_arquivo: str, colecao, progresso_callback=None) -> str:
    nome_real, erro = encontrar_arquivo(nome_arquivo, colecao)
    if erro:
        return erro

    chunks = buscar_todos_chunks_do_arquivo(nome_real, colecao)

    blocos = agrupar_em_blocos(chunks, CHUNKS_POR_BLOCO)
    print(f"'{nome_real}': {len(chunks)} chunks agrupados em {len(blocos)} blocos.")

    mini_resumos = []
    for i, bloco in enumerate(blocos, start=1):
        mini_resumos.append(resumir_bloco(bloco, i, len(blocos)))
        if progresso_callback:
            progresso_callback(f"Resumindo blocos... ({i}/{len(blocos)})", i / len(blocos))

    if len(mini_resumos) > LIMITE_RESUMOS_POR_SINTESE:
        grupos = dividir_em_grupos(mini_resumos, LIMITE_RESUMOS_POR_SINTESE)
        print(f"{len(mini_resumos)} mini-resumos — sintetizando em {len(grupos)} grupos intermediários antes da síntese final.")
        mini_resumos = []
        for i, grupo in enumerate(grupos, start=1):
            mini_resumos.append(sintetizar_grupo_intermediario(grupo, nome_real, i, len(grupos)))
            if progresso_callback:
                progresso_callback(f"Sintetizando seção {i}/{len(grupos)}...", 1.0)

    print("Sintetizando resumo final...")
    if progresso_callback:
        progresso_callback("Sintetizando resumo final...", 1.0)
    return sintetizar_resumo_final(mini_resumos, nome_real)

if __name__ == "__main__":
    cliente = chromadb.PersistentClient(path=PASTA_BANCO_VETORIAL)
    colecao = cliente.get_or_create_collection(name="documentos_pessoais")

    arquivos_disponiveis = listar_arquivos_disponiveis(colecao)
    print("Arquivos disponíveis:")
    for nome in arquivos_disponiveis:
        print(f"  - {nome}")

    nome_arquivo = input("\nDigite o nome exato do arquivo para resumir: ")
    resumo = resumir_arquivo(nome_arquivo, colecao)

    print("\n=== RESUMO FINAL ===\n")
    print(resumo)

