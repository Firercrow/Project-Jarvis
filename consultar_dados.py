import os
import re
import json
import operator
import requests
import openpyxl
import numpy as np
import pandas as pd
from scipy import ndimage
from datetime import datetime, timedelta

from config import MODELO_LLM, PASTA_DOCUMENTOS
from programas_instalados import listar_programas_instalados
from texto import normalizar_nome, normalizar_pedido, PREFIXO_AVISO


def comparar_numerico(serie: pd.Series, valor, operador_func):
    """Coage série e valor pra número antes de comparar com operador de ordem (>, <, >=, <=).
    Sem isso, uma coluna com tipo misto (ex: "Idade" com a maioria int mas alguma célula com
    texto — dado real sujo de planilha) quebra com TypeError puro ao comparar int com str, e o
    valor do filtro também pode chegar como string ("60") vindo do JSON do LLM. Célula que não
    converte pra número vira NaN e naturalmente não bate no filtro, em vez de travar."""
    serie_numerica = pd.to_numeric(serie, errors="coerce")
    valor_numerico = pd.to_numeric(valor, errors="coerce")
    if pd.isna(valor_numerico):
        return pd.Series(False, index=serie.index)
    return operador_func(serie_numerica, valor_numerico)


def _comparar_igualdade(serie: pd.Series, valor, operador_func):
    """`==`/`!=` numa coluna NUMÉRICA precisam da mesma coerção de tipo de `comparar_numerico()`
    — achado real, 2026-08-26 ("quantas pessoas têm valor 1 na coluna MULHER?"): o valor extraído
    do LLM chega como string `"1"`; a coluna é `float64` (`1.0`/`nan`); `"1" == 1.0` nunca bate em
    pandas (compara tipo, não só valor), então o filtro achava "não existe" e trocava pra outra
    coluna errada por engano. Só se aplica a coluna NUMÉRICA — texto/data continuam com a
    comparação direta de sempre (`aplicar_filtros()` já garante que `==` numa coluna de texto vira
    `"contem"` antes de chegar aqui, então nunca sobra texto pra esse caminho)."""
    if pd.api.types.is_numeric_dtype(serie):
        return comparar_numerico(serie, valor, operador_func)
    return operador_func(serie, valor)


OPERADORES_FILTRO = {
    "==": lambda serie, valor: _comparar_igualdade(serie, valor, operator.eq),
    "!=": lambda serie, valor: _comparar_igualdade(serie, valor, operator.ne),
    ">": lambda serie, valor: comparar_numerico(serie, valor, operator.gt),
    "<": lambda serie, valor: comparar_numerico(serie, valor, operator.lt),
    ">=": lambda serie, valor: comparar_numerico(serie, valor, operator.ge),
    "<=": lambda serie, valor: comparar_numerico(serie, valor, operator.le),
    # regex=False é essencial: o pandas trata o padrão como EXPRESSÃO REGULAR por padrão, e o
    # valor aqui vem de texto livre do usuário. Um "?" ou "(" derrubava a consulta com
    # ArrowInvalid (achado 2026-08-20), e um "." casava errado em silêncio — "Apple Inc." casaria
    # com "AppleXInc". Aqui a intenção é sempre busca literal de substring.
    "contem": lambda serie, valor: serie.astype(str).str.contains(str(valor), case=False, na=False, regex=False),
}


def timestamp_chrome_para_datetime(timestamp_chrome):
    if not timestamp_chrome:
        return pd.NaT
    return datetime(1601, 1, 1) + timedelta(microseconds=timestamp_chrome)


def carregar_historico_dataframe(colecao) -> pd.DataFrame:
    dados = colecao.get(where={"fonte": "historico_navegacao"})
    linhas = []
    for meta in dados["metadatas"]:
        linhas.append({
            "titulo": meta.get("titulo", "(sem título)"),
            "url": meta.get("url", ""),
            "data_visita": timestamp_chrome_para_datetime(meta.get("timestamp_chrome", 0)),
            "origem": meta.get("origem", "desconhecida"),
        })
    return pd.DataFrame(linhas)


def carregar_programas_dataframe() -> pd.DataFrame:
    df = pd.DataFrame(listar_programas_instalados())
    if df.empty:
        return df
    df["data_instalacao"] = pd.to_datetime(df["data_instalacao_bruta"], format="%Y%m%d", errors="coerce")
    return df.drop(columns=["data_instalacao_bruta"])


def listar_planilhas_disponiveis() -> list[str]:
    if not os.path.isdir(PASTA_DOCUMENTOS):
        return []
    return sorted(f for f in os.listdir(PASTA_DOCUMENTOS) if f.lower().endswith(".xlsx"))


def identificar_planilha(nome_pedido: str) -> tuple[str | None, str | None]:
    """Casa o nome pedido com uma planilha .xlsx real. Retorna (nome_real, None) em caso de
    sucesso, ou (None, mensagem_de_erro) se não achar exatamente uma."""
    pedido = normalizar_pedido(nome_pedido)
    if len(pedido) < 3:
        return None, f"'{nome_pedido}' é um termo curto demais pra identificar a planilha com segurança. Seja mais específico."

    planilhas_disponiveis = listar_planilhas_disponiveis()
    correspondencias = [p for p in planilhas_disponiveis if pedido in normalizar_nome(p)]

    if not correspondencias:
        return None, f"Nenhuma planilha encontrada parecida com '{nome_pedido}'. Verifique o nome."
    if len(correspondencias) > 1:
        return None, f"Mais de uma planilha corresponde: {correspondencias}. Seja mais específico."
    return correspondencias[0], None


def listar_abas_planilha(nome_arquivo: str) -> list[str]:
    caminho = os.path.join(PASTA_DOCUMENTOS, nome_arquivo)
    pasta_trabalho = openpyxl.load_workbook(caminho, read_only=True)
    try:
        return pasta_trabalho.sheetnames
    finally:
        pasta_trabalho.close()


def resolver_aba(nome_aba: str, abas_disponiveis: list[str]) -> str | None:
    """Casa o nome de aba pedido com uma aba real. Match exato (ignorando caixa) tem
    prioridade sobre match parcial — sem isso, "enemy stat" ficaria ambíguo entre "Enemy stat"
    e "Enemy stat (9g3)" (planilhas reais podem ter abas com nomes parecidos de propósito)."""
    if nome_aba in abas_disponiveis:
        return nome_aba
    alvo = normalizar_pedido(nome_aba)
    exatas = [a for a in abas_disponiveis if normalizar_nome(a) == alvo]
    if len(exatas) == 1:
        return exatas[0]
    correspondencias = [a for a in abas_disponiveis if alvo in normalizar_nome(a)]
    return correspondencias[0] if len(correspondencias) == 1 else None


def _resolver_caminho_e_aba(nome_arquivo: str, nome_aba: str | None) -> tuple[str | None, str | None, str | None]:
    """Retorna (caminho, aba_resolvida, None) em caso de sucesso, ou (None, None, mensagem_de_erro)
    se a planilha tiver várias abas sem uma especificada, a aba pedida não existir, ou o arquivo
    estiver corrompido/não for um .xlsx válido. Nunca adivinha qual aba usar quando há mais de uma."""
    caminho = os.path.join(PASTA_DOCUMENTOS, nome_arquivo)
    try:
        abas = listar_abas_planilha(nome_arquivo)
    except Exception:
        return None, None, f"Não consegui abrir '{nome_arquivo}' — o arquivo pode estar corrompido ou não é um .xlsx válido."

    if nome_aba is None:
        if len(abas) > 1:
            lista = ", ".join(abas)
            return None, None, f"'{nome_arquivo}' tem várias abas ({lista}). Especifique qual aba você quer consultar."
        nome_aba = abas[0]
    else:
        aba_resolvida = resolver_aba(nome_aba, abas)
        if aba_resolvida is None:
            lista = ", ".join(abas)
            return None, None, f"Não encontrei a aba '{nome_aba}' em '{nome_arquivo}'. Abas disponíveis: {lista}."
        nome_aba = aba_resolvida

    return caminho, nome_aba, None


def _densidade_linha(linha: pd.Series) -> float:
    return 0.0 if len(linha) == 0 else linha.notna().sum() / len(linha)


def _detectar_cabecalho_em_bloco(bloco_bruto: pd.DataFrame) -> int:
    """Acha a linha do cabeçalho DENTRO de um bloco (índice relativo ao bloco, não à planilha
    inteira): a primeira linha com pelo menos metade das células preenchidas. Linhas esparsas
    antes dela (ex.: um rótulo solto tipo "Amostra" escrito sozinho numa célula) nunca viram
    cabeçalho nem dado — servem só de rótulo do bloco (ver `detectar_blocos_planilha`)."""
    densidades = [_densidade_linha(bloco_bruto.iloc[i]) for i in range(len(bloco_bruto))]
    for indice, densidade in enumerate(densidades):
        if densidade >= 0.5:
            return indice
    return int(np.argmax(densidades)) if densidades else 0


LIMIAR_QUEDA_DENSIDADE_BORDA = 0.5  # linha de borda com densidade abaixo da metade do típico = suspeita
MINIMO_LINHAS_PARA_CHECAR_COLAGEM = 5  # poucas linhas de dado não dão uma mediana confiável


def _detectar_possivel_colagem(bloco_bruto: pd.DataFrame, linha_cabecalho_relativa: int) -> bool:
    """Sinal mecânico de que outra tabela ficou colada no fim do bloco sem linha em branco
    separando de verdade (achado real, 2026-08-28, "TAREFA MATEMATICA.xlsx"): um resumo manual
    (rótulo "F"/"M" + contagem) ficou grudado direto depois da última linha de dado real —
    Gênero/Idade continuavam preenchidos na transição, então o corte por linha-totalmente-vazia
    nunca disparou (só corta quando a linha INTEIRA fica vazia). Não julga conteúdo — só compara
    a densidade (fração de células preenchidas) das últimas linhas do bloco contra a densidade
    típica das linhas de dado do meio: uma queda grande (mas não pra zero, que já teria cortado o
    bloco) é a assinatura dessa colagem parcial."""
    linhas_dado = bloco_bruto.iloc[linha_cabecalho_relativa + 1:]
    if len(linhas_dado) < MINIMO_LINHAS_PARA_CHECAR_COLAGEM:
        return False
    densidades = [_densidade_linha(linhas_dado.iloc[i]) for i in range(len(linhas_dado))]
    densidades_borda, densidades_tipicas = densidades[-3:], densidades[:-3]
    if not densidades_tipicas:
        return False
    tipica = float(np.median(densidades_tipicas))
    if tipica == 0:
        return False
    return any(0 < d < tipica * LIMIAR_QUEDA_DENSIDADE_BORDA for d in densidades_borda)


def detectar_blocos_planilha(caminho: str, nome_aba: str) -> list[dict]:
    """Uma aba pode ter mais de uma tabela lado a lado ou empilhada — comum em planilha feita à
    mão só pra cálculo rápido, sem preocupação com formatação (achado real 2026-08-26,
    `TAREFA MATEMATICA.xlsx`, aba "Detalhes1": duas tabelas idênticas de colunas lado a lado, a
    segunda com um rótulo solto "Amostra" escrito em cima). `pd.read_excel()` sozinho assume UMA
    tabela retangular começando na linha 0 — aqui não é o caso.

    Detecta os blocos por COMPONENTES CONECTADOS (`scipy.ndimage.label`) na grade de células
    preenchidas: linha ou coluna totalmente vazia separa blocos; célula preenchida vizinha
    (cima/baixo/esquerda/direita, não diagonal) pertence ao mesmo bloco. Mecânico e não depende
    de idioma nem do conteúdo — funciona pela posição dos vazios, não pelas palavras.

    Cada bloco tem seu próprio cabeçalho (achado por densidade, não assumido como linha 0) e um
    "rótulo" opcional (texto solto ACIMA do cabeçalho, dentro do próprio bloco). O rótulo é só
    devolvido pra quem chamar EXIBIR — decidir o que ele SIGNIFICA (e se dois blocos devem ser
    somados, ignorados, etc.) exigiria entender o texto, não é decisão mecânica, então fica de
    fora daqui (ver PENDENCIAS.md, "planilha Detalhes1", 2026-08-26)."""
    bruto = pd.read_excel(caminho, sheet_name=nome_aba, header=None)
    mascara = bruto.notna().to_numpy()
    if not mascara.any():
        return []

    rotulos_componentes, total = ndimage.label(mascara)
    blocos = []
    for indice in range(1, total + 1):
        linhas, colunas = np.where(rotulos_componentes == indice)
        linha_min, linha_max = int(linhas.min()), int(linhas.max())
        coluna_min, coluna_max = int(colunas.min()), int(colunas.max())
        bloco_bruto = bruto.iloc[linha_min:linha_max + 1, coluna_min:coluna_max + 1]

        linha_cabecalho_relativa = _detectar_cabecalho_em_bloco(bloco_bruto)
        linha_cabecalho_absoluta = linha_min + linha_cabecalho_relativa

        rotulo = None
        if linha_cabecalho_relativa > 0:
            texto_acima = bloco_bruto.iloc[:linha_cabecalho_relativa].to_numpy().ravel()
            valores = [str(v) for v in texto_acima if pd.notna(v)]
            rotulo = " ".join(valores) if valores else None

        linhas_de_dados = linha_max - linha_cabecalho_absoluta
        if linhas_de_dados <= 0:
            continue  # bloco só tem cabeçalho (ou rótulo), nenhuma linha de dado — não é tabela

        # Nomes de coluna vêm do texto CRU já lido (`bloco_bruto`), passados via `names=`, em vez
        # de deixar o pandas inferir/desambiguar sozinho com `header=0`: o pandas desambigua nomes
        # repetidos olhando a LINHA INTEIRA da planilha antes de qualquer `usecols` recortar —
        # achado real (2026-08-26, "Detalhes1"): "Grupo parlamentar/Partido" aparece 2x na mesma
        # linha (tabela principal + "Amostra"), então o pandas grudava ".1" na segunda ocorrência
        # mesmo já sabendo (via `usecols`) que só um bloco seria lido. Isso fazia um bloco
        # genuinamente relevante (a segunda tabela) nunca bater por nome com a coluna pedida.
        linha_nomes = bloco_bruto.iloc[linha_cabecalho_relativa]
        nomes_colunas = [str(v) if pd.notna(v) else f"Unnamed_{i + 1}" for i, v in enumerate(linha_nomes)]

        df_bloco = pd.read_excel(
            caminho, sheet_name=nome_aba,
            skiprows=linha_cabecalho_absoluta + 1,
            header=None,
            names=nomes_colunas,
            usecols=list(range(coluna_min, coluna_max + 1)),
            nrows=linhas_de_dados,
        )
        possivel_colagem = _detectar_possivel_colagem(bloco_bruto, linha_cabecalho_relativa)
        blocos.append({"rotulo": rotulo, "dataframe": df_bloco, "possivel_colagem": possivel_colagem})

    return blocos


def carregar_blocos_planilha(nome_arquivo: str, nome_aba: str | None = None) -> tuple[list[dict] | None, str | None]:
    """Retorna (lista_de_blocos, None) em caso de sucesso, ou (None, mensagem_de_erro). Cada
    bloco é {"rotulo": str|None, "dataframe": pd.DataFrame, "possivel_colagem": bool} — ver
    `detectar_blocos_planilha()`."""
    caminho, nome_aba, erro = _resolver_caminho_e_aba(nome_arquivo, nome_aba)
    if erro:
        return None, erro
    try:
        return detectar_blocos_planilha(caminho, nome_aba), None
    except Exception:
        return None, f"Não consegui ler a aba '{nome_aba}' de '{nome_arquivo}' — o arquivo pode estar corrompido."



def carregar_dataframe_por_fonte(fonte: str, colecao, nome_planilha: str | None = None, nome_aba: str | None = None) -> tuple[pd.DataFrame | None, str | None]:
    """Fonte "planilha" não passa por aqui — `consultar_dado_estruturado()` trata esse caso antes
    de chegar nessa função, via `carregar_blocos_planilha()` (uma aba pode ter mais de uma
    tabela; essa função só serve fontes de tabela única)."""
    if fonte == "historico_navegacao":
        return carregar_historico_dataframe(colecao), None
    if fonte == "programas_instalados":
        return carregar_programas_dataframe(), None
    return None, None


def detectar_fonte_estruturada(pergunta: str) -> str:
    prompt = f"""Classifique a pergunta abaixo em uma categoria:
- "planilha" se for sobre dados de uma planilha Excel (linhas, colunas, valores de uma tabela
  que o usuário carregou — ex: vendas, gastos, faturamento, qualquer dado tabular de arquivo .xlsx).
- "programas_instalados" se for sobre programas/softwares/aplicativos instalados no computador
  (nome, versão, editora, data de instalação).
- "historico_navegacao" para qualquer outra coisa (sites visitados, vídeos assistidos, atividade
  de navegação do usuário).

Responda APENAS com a palavra "planilha", "programas_instalados" ou "historico_navegacao", nada mais.

PERGUNTA: {pergunta}

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
    categoria = resposta.json()["response"].strip().lower()
    if "planilha" in categoria:
        return "planilha"
    return "programas_instalados" if "programa" in categoria else "historico_navegacao"


def extrair_especificacao_consulta(pergunta: str, colunas: list[str]) -> dict | None:
    colunas_texto = ", ".join(str(c) for c in colunas)
    prompt = f"""Traduza o pedido do usuário abaixo numa consulta estruturada sobre uma tabela de dados.

COLUNAS DISPONÍVEIS: {colunas_texto}

Responda APENAS com um JSON válido, no formato abaixo, sem nenhum texto antes ou depois:
{{
  "operacao": "contar" ou "listar" ou "somar" ou "media",
  "coluna_alvo": nome da coluna, ou null. Obrigatório em "somar"/"media" (qual coluna
  somar/tirar média). Opcional em "listar" — preencha só se o usuário pedir explicitamente
  pra ver UMA coluna específica (ex: "mostre só a coluna preço"), senão deixe null (mostra
  todas as colunas).
  "filtros": lista de objetos {{"coluna": ..., "operador": "=="/"!="/">"/"<"/">="/"<="/"contem", "valor": ...}}, ou lista vazia,
  "agrupar_por": nome da coluna, ou null. Preencha quando o pedido for "quantos/quanto de
  CADA X" (uma resposta por valor distinto de X), não um total só. Nesse caso "coluna_alvo"
  continua vazio em "contar" (não precisa de coluna extra pra contar linhas), mas é
  OBRIGATÓRIO em "somar"/"media" (qual coluna somar/tirar média DENTRO de cada grupo).
  "ordenar_por": nome da coluna, ou null,
  "ordem": "asc" ou "desc", ou null,
  "limite": número inteiro, ou null
}}

IMPORTANTE: para filtros de texto (nome, editora, título, url), use SEMPRE o operador
"contem", nunca "==" — o valor exato no dado costuma ter mais texto do que o termo que o
usuário disse (ex: usuário diz "Apple", o dado real é "Apple Inc."; "==" não bate, "contem" bate).
Reserve "==", "!=", ">", "<", ">=", "<=" para números e datas.

Exemplo 1:
PEDIDO: quais os últimos 5 sites que eu visitei
JSON: {{"operacao": "listar", "coluna_alvo": null, "filtros": [], "agrupar_por": null, "ordenar_por": "data_visita", "ordem": "desc", "limite": 5}}

Exemplo 2:
PEDIDO: quantos vídeos do youtube eu vi
JSON: {{"operacao": "contar", "coluna_alvo": null, "filtros": [{{"coluna": "url", "operador": "contem", "valor": "youtube"}}], "agrupar_por": null, "ordenar_por": null, "ordem": null, "limite": null}}

Exemplo 3:
PEDIDO: quantos programas da Apple eu tenho instalados
JSON: {{"operacao": "contar", "coluna_alvo": null, "filtros": [{{"coluna": "editora", "operador": "contem", "valor": "Apple"}}], "agrupar_por": null, "ordenar_por": null, "ordem": null, "limite": null}}

Exemplo 4:
PEDIDO: mostre só a coluna preço dos produtos de março
JSON: {{"operacao": "listar", "coluna_alvo": "preço", "filtros": [{{"coluna": "mês", "operador": "contem", "valor": "março"}}], "agrupar_por": null, "ordenar_por": null, "ordem": null, "limite": null}}

Exemplo 5:
PEDIDO: quantos políticos tem cada partido
JSON: {{"operacao": "contar", "coluna_alvo": null, "filtros": [], "agrupar_por": "partido", "ordenar_por": null, "ordem": null, "limite": null}}

Exemplo 6:
PEDIDO: some o valor gasto por categoria
JSON: {{"operacao": "somar", "coluna_alvo": "valor gasto", "filtros": [], "agrupar_por": "categoria", "ordenar_por": null, "ordem": null, "limite": null}}

Agora responda para o pedido real abaixo.

PEDIDO: {pergunta}

JSON:"""

    resposta = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": MODELO_LLM,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": 200, "temperature": 0}
        }
    )
    texto = resposta.json()["response"].strip()

    inicio = texto.find("{")
    fim = texto.rfind("}")
    if inicio == -1 or fim == -1:
        return None

    try:
        return json.loads(texto[inicio:fim + 1])
    except json.JSONDecodeError:
        return None


def resolver_coluna(nome_coluna, colunas_disponiveis) -> str | None:
    """Resolve o nome de uma coluna ignorando maiúsculas/minúsculas — o LLM às vezes muda a
    caixa da coluna (ex: "produto" em vez de "Produto") mesmo recebendo a lista exata de
    colunas disponíveis no prompt, e uma comparação sensível a caixa perderia o filtro
    silenciosamente."""
    if nome_coluna in colunas_disponiveis:
        return nome_coluna
    mapa = {str(c).lower(): c for c in colunas_disponiveis}
    return mapa.get(str(nome_coluna).lower())


LIMITE_VALORES_NO_AVISO = 15  # acima disso a coluna não é categórica, listar os valores viraria ruído
LIMITE_LINHAS_LISTAGEM = 20   # teto padrão de linhas mostradas numa listagem


def descrever_valores_existentes(serie: pd.Series) -> str:
    """Texto de ajuda pra quando um filtro não bate com nada: se a coluna for categórica
    (poucos valores distintos), dizer quais valores existem de verdade é o que resolve o
    problema do usuário — ele quase sempre usou uma palavra que não é a do dado (perguntou
    "homens" numa coluna que guarda "M"/"F")."""
    valores = pd.Series(serie.dropna().astype(str).unique())
    if valores.empty:
        return "essa coluna está vazia."
    if len(valores) <= LIMITE_VALORES_NO_AVISO:
        return "os valores que existem nessa coluna são: " + ", ".join(f"'{v}'" for v in valores)
    return f"essa coluna tem {len(valores)} valores distintos — verifique se o termo usado aparece nela."


# Quando o mesmo valor aparece em mais de uma coluna, qual delas manda. Ordem do MAIS confiável
# para o menos. Não é preferência estética: a `url` é a fonte de verdade sobre qual site é
# (um vídeo chamado "reagindo ao YouTube" cairia num filtro por título sem ser do YouTube, mas a
# URL não mente); `titulo` é texto livre; `origem` é o PC de onde veio o dado, quase nunca é o
# que alguém quer filtrar. Fontes cujas colunas o projeto conhece têm ordem declarada; para
# planilha arbitrária não há como declarar, e o desempate cai na regra genérica abaixo.
PRIORIDADE_COLUNAS_POR_FONTE = {
    "historico_navegacao": ["url", "titulo", "origem"],
    "programas_instalados": ["nome", "editora", "caminho_instalacao", "versao"],
}


def escolher_coluna_prioritaria(candidatas: list, df: pd.DataFrame, valor, prioridade: list | None) -> object:
    """Entre as colunas onde o valor existe, decide qual usar.

    1) Se a fonte tem ordem declarada, respeita a ordem.
    2) Senão (planilha arbitrária), usa a coluna com MAIS linhas batendo — é a mais provável de
       ser onde o dado realmente mora, e não a que menciona o termo de passagem."""
    if prioridade:
        for coluna in prioridade:
            if coluna in candidatas:
                return coluna
    return max(candidatas,
               key=lambda c: OPERADORES_FILTRO["contem"](df[c], valor).sum())


def procurar_valor_em_outras_colunas(df: pd.DataFrame, valor, coluna_usada) -> list:
    """Devolve as colunas (fora a que foi usada) onde o valor procurado realmente aparece.

    Existe porque o extrator escolhe a coluna a partir dos NOMES delas, sem saber o que cada uma
    contém — e erra. Caso real (2026-08-22): "quais meus últimos vídeos assistidos?" virou filtro
    em `origem` (a coluna que guarda de qual PC veio o dado) procurando "youtube"; a coluna certa
    era `url`. Isto não é a IA adivinhando de novo: é código conferindo onde o dado está."""
    if not isinstance(valor, str) or not valor.strip():
        return []
    achadas = []
    for coluna in df.columns:
        if coluna is coluna_usada or coluna == coluna_usada:
            continue
        try:
            if df[coluna].astype(str).str.contains(valor, case=False, na=False, regex=False).any():
                achadas.append(coluna)
        except Exception:
            continue
    return achadas


def aplicar_filtros(df: pd.DataFrame, filtros: list[dict], prioridade_colunas: list | None = None) -> tuple[pd.DataFrame, list[str]]:
    """Retorna (dataframe_filtrado, avisos). Os avisos existem porque "0 resultados" é uma
    resposta ambígua: pode significar "de fato não há nada" ou "o filtro foi construído errado".
    Entregar 0 sem avisar é falha silenciosa — o usuário lê como fato."""
    avisos = []
    resultado = df
    for filtro in filtros:
        coluna = resolver_coluna(filtro.get("coluna"), resultado.columns)
        operador = filtro.get("operador")
        valor = filtro.get("valor")
        if coluna is None or operador not in OPERADORES_FILTRO:
            continue
        # Filtro sem valor não é filtro — é ruído, e ruído que corrompe em SILÊNCIO: com
        # operador "contem", `str.contains("")` casa com quase toda linha não-nula, então o
        # resultado parece plausível e está errado (achado 2026-08-20: uma aba de 274 linhas
        # virou 67). Acontece quando a mensagem chega ao extrator com um buraco onde havia um
        # nome já resolvido ("na aba ___ da ___") e o modelo tenta preencher o vazio. Trava em
        # código, não instrução no prompt: independe do idioma e do que o modelo decidir.
        # Vale também pra valor que só tem pontuação ("?", "-", "..."): é resto de frase, não
        # critério. `isalnum` cobre qualquer alfabeto Unicode, então a regra não é específica
        # de português nem de inglês.
        if valor is None or (isinstance(valor, str) and not any(c.isalnum() for c in valor)):
            continue
        # Regra do projeto: filtro de texto usa sempre "contem", nunca "==" (o dado real costuma
        # ter mais texto que o termo que o usuário disse). Já era instrução no prompt do extrator,
        # mas o modelo nem sempre segue de forma consistente (mesmo com temperature=0, resposta
        # pra mensagem idêntica variou dependendo do que rodou antes — não-determinismo do motor
        # de inferência, não bug de código). Reforçado aqui: se "==" cair numa coluna de texto,
        # vira "contem" sempre, garantido em código em vez de só esperado do modelo.
        eh_coluna_de_texto = not pd.api.types.is_numeric_dtype(resultado[coluna]) and not pd.api.types.is_datetime64_any_dtype(resultado[coluna])
        if operador == "==" and eh_coluna_de_texto:
            operador = "contem"

        # Correção 2026-08-26 (achado real, "partido PS"): "contem" sem noção nenhuma de valor
        # exato mistura "PS" com "PSD" (PS é prefixo literal de PSD) — 147 de 233 linhas batendo
        # num filtro que devia ser bem mais estreito. Quando o valor pedido bate EXATO (sem
        # diferenciar maiúscula) com um dos valores REAIS da coluna, prefere esse valor exato em
        # vez de aceitar qualquer coisa que contenha o texto como substring — "PS" existe de
        # verdade como valor da coluna, não precisa de correspondência frouxa. Não muda o caso
        # "Apple" -> "Apple Inc." (que já funcionava): "Apple" sozinho não é nenhum valor real da
        # coluna ali, então nenhum valor exato é achado e o "contem" de sempre continua valendo.
        if operador == "contem":
            valor_normalizado = str(valor).strip().lower()
            for valor_real in resultado[coluna].dropna().unique():
                if str(valor_real).strip().lower() == valor_normalizado:
                    operador = "=="
                    valor = valor_real
                    break

        antes = resultado
        resultado = resultado[OPERADORES_FILTRO[operador](resultado[coluna], valor)]

        # Filtro que zera tudo é o sintoma clássico de critério mal construído (o modelo pegou
        # uma palavra solta da pergunta e usou como valor, ou usou a palavra do usuário em vez
        # do código que está no dado). Avisar em vez de devolver 0 calado.
        if resultado.empty and not antes.empty:
            # Antes de dar o filtro como perdido, conferir se o valor existe em OUTRA coluna —
            # o erro mais comum aqui é o extrator ter escolhido a coluna errada, não o valor
            # não existir no dado.
            outras = procurar_valor_em_outras_colunas(antes, valor, coluna)

            if outras:
                coluna_certa = escolher_coluna_prioritaria(outras, antes, valor, prioridade_colunas)
                resultado = antes[OPERADORES_FILTRO["contem"](antes[coluna_certa], valor)]
                aviso = (f"Ajuste automático: '{valor}' não aparece na coluna {coluna}, "
                         f"então filtrei por {coluna_certa}, onde o valor existe de fato.")
                if len(outras) > 1:
                    demais = [str(c) for c in outras if c != coluna_certa]
                    aviso += f" (também aparece em: {', '.join(demais)})"
                avisos.append(aviso)
            else:
                avisos.append(
                    f"Atenção: nenhum resultado bate com o filtro {coluna} {operador} '{valor}' — "
                    + descrever_valores_existentes(antes[coluna])
                )
    return resultado, avisos


def _preparar_coluna_agrupamento(serie: pd.Series) -> pd.Series:
    """Normaliza a coluna antes do `groupby()`. Dois achados reais (2026-08-28, "quantos
    políticos tem cada partido"): (1) célula com espaço/quebra de linha grudada na ponta
    ("CH\\n") virava grupo separado do valor limpo ("CH") — texto tem as pontas cortadas antes
    de agrupar; (2) linha sem valor (NaN) some em silêncio (comportamento padrão do `groupby`
    do pandas, que descarta NaN) — vira grupo próprio "(vazio)" em vez de desaparecer sem
    aviso."""
    if not pd.api.types.is_numeric_dtype(serie):
        serie = serie.where(serie.isna(), serie.astype(str).str.strip())
    return serie.fillna("(vazio)")


def executar_consulta(df: pd.DataFrame, especificacao: dict, avisar_sem_filtro: bool = True,
                      prioridade_colunas: list | None = None) -> tuple[object, list[str]]:
    """Retorna (resultado, avisos) — ver aplicar_filtros() sobre por que os avisos existem.

    avisar_sem_filtro=False para transcrição, onde "sem filtro" é o comportamento correto por
    definição (transcrever é mostrar tudo) e o aviso seria ruído."""
    filtros = especificacao.get("filtros") or []
    filtrado, avisos = aplicar_filtros(df, filtros, prioridade_colunas)
    operacao = especificacao.get("operacao", "listar")

    # Sem nenhum filtro, a resposta é sobre a fonte INTEIRA — não é um recorte da pergunta.
    # Isso engana quando o usuário pediu um recorte usando uma palavra que não existe nos dados
    # (ex: "meus vídeos assistidos": não há coluna que diga o que é vídeo, então nada é filtrado
    # e voltam os 4000 registros com cara de resposta). O sistema não tenta adivinhar o que a
    # palavra significa — deliberado: mapear "vídeo" para uma lista de domínios conhecidos seria
    # catalogar o que já conhecemos, e plataforma nova nunca entraria (decisão do usuário,
    # 2026-08-20). Em vez disso, deixa explícito o que foi feito e como pedir o recorte.
    agrupar_por = resolver_coluna(especificacao.get("agrupar_por"), filtrado.columns) if especificacao.get("agrupar_por") else None

    # "Sem filtro" não vale quando há agrupamento: agrupar por coluna JÁ é o recorte que o
    # usuário pediu ("quantos de CADA partido" tem uma resposta por partido, não é "cobre tudo
    # sem distinção" — o aviso genérico ficaria enganoso, sugerindo que nada foi filtrado quando
    # o resultado está, sim, organizado exatamente como pedido).
    if avisar_sem_filtro and not filtros and not agrupar_por and operacao in ("listar", "contar"):
        # Exemplo propositalmente genérico: este mesmo aviso sai em histórico, programas e
        # planilha — citar "vídeo"/"site" fixo ficaria sem sentido numa tabela de valores.
        avisos.append(
            f"Atenção: nenhum filtro foi aplicado — o resultado cobre todos os {len(df)} registros "
            f"da fonte, não um recorte da sua pergunta. Se quis algo específico, use um termo que "
            f"apareça nos próprios dados, ou peça a busca pela palavra literal (ex: \"que contenham "
            f"a palavra X\")."
        )

    if agrupar_por:
        coluna_grupo = _preparar_coluna_agrupamento(filtrado[agrupar_por])
        if operacao in ("somar", "media"):
            coluna = resolver_coluna(especificacao.get("coluna_alvo"), filtrado.columns)
            if coluna is None:
                return None, avisos
            agregado = filtrado.groupby(coluna_grupo)[coluna]
            resultado = (agregado.sum() if operacao == "somar" else agregado.mean()).sort_values(ascending=False)
        else:
            resultado = filtrado.groupby(coluna_grupo).size().sort_values(ascending=False)
        return resultado, avisos

    if operacao == "contar":
        return len(filtrado), avisos

    if operacao in ("somar", "media"):
        coluna = resolver_coluna(especificacao.get("coluna_alvo"), filtrado.columns)
        if coluna is None:
            return None, avisos
        return (filtrado[coluna].sum() if operacao == "somar" else filtrado[coluna].mean()), avisos

    ordenar_por = resolver_coluna(especificacao.get("ordenar_por"), filtrado.columns)
    if ordenar_por:
        ascendente = especificacao.get("ordem") != "desc"
        filtrado = filtrado.sort_values(by=ordenar_por, ascending=ascendente)

    coluna = resolver_coluna(especificacao.get("coluna_alvo"), filtrado.columns)
    if coluna:
        filtrado = filtrado[[coluna]]

    # O teto de linhas existe pra listagem não virar um paredão de texto, mas cortar sem dizer
    # nada faz o usuário ler 20 linhas como se fossem TODAS (falha silenciosa — ele não tem como
    # perceber que faltou coisa). Se o usuário pediu um limite explícito, o corte é o que ele
    # pediu e não precisa de aviso.
    limite_pedido = especificacao.get("limite")
    limite = limite_pedido or LIMITE_LINHAS_LISTAGEM
    total = len(filtrado)
    if not limite_pedido and total > limite:
        avisos.append(
            f"Mostrando as primeiras {limite} de {total} linhas encontradas — "
            f"peça um limite maior (ex: \"as 100 primeiras\") se quiser ver mais."
        )
    return filtrado.head(limite), avisos


def formatar_linha(linha: pd.Series) -> str:
    partes = []
    for coluna, valor in linha.items():
        if pd.isna(valor) or valor == "":
            continue
        if isinstance(valor, pd.Timestamp):
            tem_hora = valor.hour or valor.minute or valor.second
            valor = valor.strftime("%d/%m/%Y %H:%M:%S" if tem_hora else "%d/%m/%Y")
        partes.append(f"{coluna}: {valor}")
    return "- " + " | ".join(partes)


def formatar_resultado(resultado, especificacao: dict, avisos: list[str] | None = None) -> str:
    operacao = especificacao.get("operacao", "listar")

    # Checa o TIPO de verdade do que voltou (Series só existe no caminho de agrupamento,
    # ver executar_consulta), não o que a especificação pediu — um bloco onde a coluna de
    # agrupar_por não existe cai pro caminho normal (int/float/DataFrame) mesmo com
    # "agrupar_por" preenchido na especificação original, e formatar teria que bater com o
    # que existe de fato, não com a intenção.
    if isinstance(resultado, pd.Series):
        if resultado.empty:
            texto = "Nenhum resultado encontrado para essa consulta."
        else:
            texto = "\n".join(f"- {grupo}: {valor}" for grupo, valor in resultado.items())
    elif operacao == "contar":
        texto = f"Encontrei {resultado} entrada(s)."
    elif operacao in ("somar", "media"):
        if resultado is None:
            texto = "Não encontrei essa coluna nos dados disponíveis."
        else:
            texto = f"Resultado ({operacao}): {resultado}"
    elif resultado.empty:
        texto = "Nenhum resultado encontrado para essa consulta."
    else:
        texto = "\n".join(formatar_linha(linha) for _, linha in resultado.iterrows())

    if avisos:
        # PREFIXO_AVISO marca estas linhas como comentário do sistema, pra que possam ser
        # separadas do conteúdo depois (ver remover_avisos_do_sistema, usado antes de guardar
        # a resposta na memória de conversa).
        texto += "\n\n" + "\n".join(PREFIXO_AVISO + aviso for aviso in avisos)
    return texto


def listar_todos_programas() -> str:
    """Listagem completa, sem LLM nenhum — a lista de programas é pequena (~76 neste PC), então
    cabe inteira sem virar ruído, diferente do catálogo de arquivos do disco. Existe pra que a
    interface tenha um caminho mecânico ("me mostre tudo") em vez de obrigar o usuário a
    formular uma pergunta que passaria por extrair_especificacao_consulta à toa."""
    df = carregar_programas_dataframe()
    if df.empty:
        return "Não encontrei programas instalados no registro do Windows."
    linhas = [formatar_linha(linha) for _, linha in df.iterrows()]
    return f"{len(df)} programa(s) instalado(s):\n" + "\n".join(linhas)


def remover_referencias_resolvidas(pergunta: str, *valores_resolvidos: str | None) -> str:
    """Remove do texto valores que já foram extraídos e resolvidos separadamente antes (nome de
    aba, nome de planilha) antes de mandar pro extrator de especificação de consulta. Sem isso, o
    próprio nome da aba/planilha pode ser reinterpretado como se fosse um valor de filtro — achado
    real testando o funil: "quantas linhas tem a aba Enemy stat da planilha X" virava filtro
    coluna=="Enemy stat" (o LLM tentava achar uso pra cada palavra da mensagem, mesmo pra
    informação que já tinha sido consumida).

    Comparação é case-insensitive (2026-08-20): antes usava `str.replace`, que só casa texto
    idêntico — se o usuário escrevia "Tarefa Matematica" e o extrator devolvia "tarefa matematica",
    a remoção não acontecia e o bug voltava, em silêncio. O chamador deve passar TANTO o nome real
    resolvido QUANTO o termo que o usuário/LLM escreveu (eles quase nunca são iguais: "tarefa
    matematica" vs "TAREFA MATEMATICA.xlsx")."""
    resultado = pergunta
    for valor in valores_resolvidos:
        if valor and str(valor).strip():
            resultado = re.sub(re.escape(str(valor)), " ", resultado, flags=re.IGNORECASE)
    # colapsa o espaçamento que sobra dos trechos removidos — não resolve o buraco semântico
    # ("na aba ___"), que é tratado pela trava de filtro-sem-valor em aplicar_filtros(), mas
    # evita mandar pro modelo um texto visivelmente esburacado.
    return re.sub(r"\s{2,}", " ", resultado).strip()


AVISO_POSSIVEL_COLAGEM = (
    "esta tabela parece ter outra coisa colada no fim, sem linha em branco separando de "
    "verdade — os números podem incluir dado que não é da tabela principal. Vale checar o final "
    "dela no arquivo original e separar com uma linha em branco se for o caso."
)


def _transcrever_bloco(pergunta_limpa: str, df: pd.DataFrame, possivel_colagem: bool = False) -> str:
    if df.empty:
        return "(tabela vazia)"
    especificacao = extrair_especificacao_consulta(pergunta_limpa, list(df.columns)) or {}
    especificacao["operacao"] = "listar"
    if not especificacao.get("limite"):
        especificacao["limite"] = len(df)
    # transcrição é completa por definição: "nenhum filtro" aqui é o comportamento correto,
    # não algo a alertar — o aviso só faz sentido em consulta, onde sugere um recorte que falhou.
    resultado, avisos = executar_consulta(df, especificacao, avisar_sem_filtro=False)
    if possivel_colagem:
        avisos = [*avisos, AVISO_POSSIVEL_COLAGEM]
    return formatar_resultado(resultado, especificacao, avisos)


def transcrever_planilha(pergunta: str, nome_planilha: str, nome_aba: str | None = None) -> str:
    """Transcrição de planilha reaproveita o mesmo extrator de consulta (reconhece coluna/termo
    mencionados), mas força "listar" (transcrever é sempre mostrar, nunca contar/somar) e remove
    o teto padrão de 20 linhas — transcrição é completa por definição.

    Quando a aba tem mais de um bloco de tabela (`detectar_blocos_planilha`), transcreve cada
    bloco separado e rotulado, em vez de juntar tudo numa lista só — ver `_consultar_blocos_planilha`
    pro mesmo raciocínio aplicado à consulta estruturada."""
    blocos, erro = carregar_blocos_planilha(nome_planilha, nome_aba)
    if erro:
        return erro
    if not blocos:
        return f"'{nome_planilha}' está vazia."

    pergunta_limpa = remover_referencias_resolvidas(pergunta, nome_aba, nome_planilha)

    if len(blocos) == 1:
        return _transcrever_bloco(pergunta_limpa, blocos[0]["dataframe"], blocos[0]["possivel_colagem"])

    partes = [
        f"{PREFIXO_AVISO}esta aba tem {len(blocos)} tabelas separadas (estrutura irregular), "
        f"transcritas uma de cada vez abaixo."
    ]
    for indice, bloco in enumerate(blocos, start=1):
        rotulo = f" (rotulada \"{bloco['rotulo']}\")" if bloco["rotulo"] else ""
        texto_bloco = _transcrever_bloco(pergunta_limpa, bloco["dataframe"], bloco["possivel_colagem"])
        partes.append(f"Tabela {indice}{rotulo}:\n{texto_bloco}")
    return "\n\n".join(partes)


def _colunas_referenciadas(especificacao: dict) -> list:
    nomes = [filtro.get("coluna") for filtro in (especificacao.get("filtros") or [])]
    nomes.append(especificacao.get("coluna_alvo"))
    nomes.append(especificacao.get("ordenar_por"))
    nomes.append(especificacao.get("agrupar_por"))
    return [n for n in nomes if n]


def _bloco_e_relevante(especificacao: dict, df: pd.DataFrame) -> bool:
    """Um bloco só é relevante pra essa pergunta se alguma coluna que ela menciona existe DE
    VERDADE nele (match por nome via `resolver_coluna` — não o fallback aproximado de
    `aplicar_filtros`, que existe pra outro problema: coluna errada dentro de uma tabela
    relevante, não tabela errada). Pergunta sem nenhuma coluna mencionada não dá pra filtrar
    mecanicamente — todo bloco vale."""
    colunas_pedidas = _colunas_referenciadas(especificacao)
    if not colunas_pedidas:
        return True
    return any(resolver_coluna(c, df.columns) is not None for c in colunas_pedidas)


def _consultar_blocos_planilha(pergunta_limpa: str, blocos: list[dict]) -> str:
    """Consulta estruturada quando a aba tem mais de um bloco de tabela: nunca junta os blocos
    sozinho (juntar errado pode contar a mesma coisa duas vezes, ex.: uma tabela de "amostra"
    que é subconjunto da tabela principal) — roda a mesma consulta em CADA bloco separado e
    mostra os resultados lado a lado com aviso, deixando a interpretação pra quem lê.

    Um bloco só entra na resposta se a pergunta menciona alguma coluna que existe DE VERDADE
    nele (por nome). Sem isso, um filtro tipo "partido PS" acerta por acaso numa tabela de
    resumo estatístico ou até num bloco de texto solto que não tem nada a ver com o assunto,
    só porque calhou de estar na mesma aba (achado real, "Detalhes1": pedir "PS" batia sozinho
    numa tabela de contagem sem relação alguma). Se a pergunta não menciona nenhuma coluna, não
    há como distinguir mecanicamente — todos os blocos continuam valendo.

    A especificação é extraída UMA VEZ SÓ, mostrando ao LLM a união dos nomes de coluna de
    TODOS os blocos (não os dados — só os nomes) — não uma vez por bloco isolado. Achado real
    (2026-08-26, "Detalhes1"): perguntando bloco a bloco, um bloco com só 2-3 colunas de número
    cru (tabelinha de contagem feita à mão) não tinha como responder "nenhuma dessas colunas
    serve" — era obrigado a inventar um filtro com o que tinha disponível. Com a lista inteira à
    vista, "Grupo parlamentar/Partido" aparece do lado de "4/15"/"PSD" e o LLM escolhe a coluna
    de verdade; o código então decide sozinho (via `_bloco_e_relevante`) quais blocos têm essa
    coluna."""
    if len(blocos) == 1:
        df = blocos[0]["dataframe"]
        especificacao = extrair_especificacao_consulta(pergunta_limpa, list(df.columns))
        if especificacao is None:
            return "Não consegui entender essa pergunta como uma consulta de dados. Tente reformular."
        resultado, avisos = executar_consulta(df, especificacao)
        if blocos[0]["possivel_colagem"]:
            avisos = [*avisos, AVISO_POSSIVEL_COLAGEM]
        return formatar_resultado(resultado, especificacao, avisos)

    colunas_uniao = list(dict.fromkeys(
        coluna for bloco in blocos for coluna in bloco["dataframe"].columns
    ))
    especificacao = extrair_especificacao_consulta(pergunta_limpa, colunas_uniao)
    if especificacao is None:
        return "Não consegui entender essa pergunta como uma consulta de dados. Tente reformular."

    respostas = []
    for indice, bloco in enumerate(blocos, start=1):
        df = bloco["dataframe"]
        rotulo = f" (rotulada \"{bloco['rotulo']}\")" if bloco["rotulo"] else ""
        if not _bloco_e_relevante(especificacao, df):
            continue
        resultado, avisos = executar_consulta(df, especificacao)
        if bloco["possivel_colagem"]:
            avisos = [*avisos, AVISO_POSSIVEL_COLAGEM]
        respostas.append(f"Tabela {indice}{rotulo}:\n{formatar_resultado(resultado, especificacao, avisos)}")

    if not respostas:
        return (
            f"{PREFIXO_AVISO}esta aba tem {len(blocos)} tabelas separadas (estrutura irregular) e "
            f"nenhuma delas parece ter a coluna perguntada — peça a transcrição completa da aba pra "
            f"ver o layout exato."
        )
    aviso_estrutura = (
        f"{PREFIXO_AVISO}esta aba tem {len(blocos)} tabelas separadas (estrutura irregular); "
        f"mostrando só as {len(respostas)} que têm a coluna perguntada — se não for o que você "
        f"espera, peça a transcrição completa da aba pra ver o layout exato."
    )
    return aviso_estrutura + "\n\n" + "\n\n".join(respostas)


def consultar_dado_estruturado(pergunta: str, fonte: str, colecao, nome_planilha: str | None = None, nome_aba: str | None = None) -> str:
    if fonte == "planilha" and nome_planilha:
        blocos, erro = carregar_blocos_planilha(nome_planilha, nome_aba)
        if erro:
            return erro
        if not blocos:
            return "Não há dados disponíveis para essa fonte ainda."
        pergunta_limpa = remover_referencias_resolvidas(pergunta, nome_aba, nome_planilha)
        return _consultar_blocos_planilha(pergunta_limpa, blocos)

    df, erro = carregar_dataframe_por_fonte(fonte, colecao, nome_planilha, nome_aba)
    if erro:
        return erro
    if df is None:
        return f"Fonte '{fonte}' ainda não é suportada por consulta estruturada."
    if df.empty:
        return "Não há dados disponíveis para essa fonte ainda."

    pergunta_limpa = remover_referencias_resolvidas(pergunta, nome_aba, nome_planilha)
    especificacao = extrair_especificacao_consulta(pergunta_limpa, list(df.columns))
    if especificacao is None:
        return "Não consegui entender essa pergunta como uma consulta de dados. Tente reformular."

    resultado, avisos = executar_consulta(
        df, especificacao, prioridade_colunas=PRIORIDADE_COLUNAS_POR_FONTE.get(fonte)
    )
    return formatar_resultado(resultado, especificacao, avisos)
