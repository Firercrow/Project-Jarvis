import os
import re
from datetime import datetime
import requests
import chromadb

from config import PASTA_BANCO_VETORIAL, MODELO_LLM, TAMANHO_HISTORICO
from catalogar_arquivos import (localizar_arquivo, garantir_catalogo, listar_pasta,
                                listar_pasta_por_caminho, carregar_pastas_catalogadas, buscar_arquivo)
from perguntar import responder_pergunta
from resumir import resumir_arquivo, contar_termo_no_arquivo, transcrever_arquivo, condensar_para_historico
from consultar_dados import consultar_dado_estruturado, detectar_fonte_estruturada, identificar_planilha, transcrever_planilha, remover_referencias_resolvidas

COMANDOS_DE_AJUDA = ("/comandos", "/ajuda", "/help")

# Regra adotada em 2026-08-22: mensagem de erro só pode sugerir ação alcançável a partir do
# caminho em que o usuário está. Em "Criar + Documento" o funil só transcreve — mandar "faça uma
# pergunta" sem dizer como sair dali criou um loop: o usuário obedeceu e recebeu a mesma recusa.
SUGESTAO_TROCAR_PARA_CONSULTAR = (
    "Para perguntar sobre o tema em vez de transcrever: use o botão **← Trocar categoria**, "
    "escolha **Consultar → Documento**, selecione o mesmo arquivo e faça a pergunta lá."
)
PASTA_TRANSCRICOES = "transcricoes"
LIMITE_TRANSCRICAO_INLINE = 2000  # acima disso, salva em arquivo em vez de devolver texto cru no chat

def nome_arquivo_seguro(texto: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", texto).strip()[:80] or "documento"

def salvar_transcricao_em_arquivo(nome_pedido: str, texto: str) -> str:
    os.makedirs(PASTA_TRANSCRICOES, exist_ok=True)
    carimbo = datetime.now().strftime("%Y%m%d_%H%M%S")
    nome_saida = f"{nome_arquivo_seguro(nome_pedido)}_transcricao_{carimbo}.txt"
    caminho_saida = os.path.join(PASTA_TRANSCRICOES, nome_saida)
    with open(caminho_saida, "w", encoding="utf-8") as f:
        f.write(texto)
    return caminho_saida

# Lembrete: toda vez que uma categoria nova for adicionada em classificar_pedido()/
# processar_mensagem(), atualizar essa lista também (e o ARQUITETURA.md).
def texto_de_ajuda() -> str:
    return """Comandos disponíveis:

- **Resumir um documento**: "resuma o livro X" / "faça um resumo de X"
- **Contar termo num documento**: 'quantas vezes "lobo" aparece no livro X'
- **Localizar um arquivo no PC**: "onde está o arquivo Y" / "procure o arquivo Y"
- **Listar conteúdo de uma pasta**: "o que tem na pasta Desktop", "liste os arquivos de Docs"
- **Transcrever um documento ou planilha** (conteúdo literal, sem resumir): "transcreva o livro X",
  "transcreva as 10 primeiras páginas de X", "transcreva a parte sobre março em X",
  "transcreva a coluna preço da planilha Y"
- **Consultar histórico de navegação**: "quais os últimos sites que eu visitei",
  "quantos vídeos do youtube eu vi" (contagem, listagem cronológica, filtro)
- **Consultar programas instalados**: "eu tenho o Photoshop instalado?",
  "que versão do Python eu tenho instalado" (contagem, listagem, filtro)
- **Consultar planilha Excel**: "quantas vendas teve em março na planilha X",
  "qual a soma da coluna preço na planilha Y" (contagem, soma, média, filtro, coluna específica)
- **Pergunta livre**: qualquer outra pergunta sobre os documentos indexados
  ou sobre assunto/tema que você pesquisou/visitou (busca semântica)

Formatos aceitos pra upload/leitura: PDF, TXT, Word (.docx) e Excel (.xlsx).
Arquivos antigos (.doc, .xls) não são lidos — abra no Word/Excel e salve
como .docx/.xlsx antes de enviar.

Digite /comandos, /ajuda ou /help a qualquer momento pra ver essa lista de novo."""

def classificar_pedido(mensagem: str) -> str:
    prompt = f"""Classifique o pedido abaixo em uma categoria:
- "resumo" se o usuário está pedindo um resumo do documento/livro/arquivo INTEIRO, de ponta a
  ponta. NÃO use essa categoria se o pedido for sobre uma parte específica, um personagem, um
  tema ou um trecho do documento (ex: "resuma a história de X no livro Y") — isso é "pergunta",
  mesmo usando a palavra "resumir", porque exige buscar e focar num ponto específico, não o
  documento inteiro.

  Exemplo resumo: "resuma o livro Y" (documento inteiro)
  Exemplo pergunta: "resuma a história de Napoleão no livro Y" (um personagem específico, não o livro todo)
- "transcricao" se o usuário quer o TEXTO LITERAL de um documento (ou parte dele), sem resumir e
  sem interpretar — ex: "transcreva o livro X", "me dê o texto completo das 10 primeiras páginas
  de X", "transcreva a parte sobre março no relatório Y". Diferente de "resumo" (que condensa) e
  de "pergunta" (que responde com base no conteúdo, não devolve o texto original completo).
- "contagem" se o usuário está perguntando quantas vezes uma palavra ou termo aparece em um documento.
- "localizar" se o usuário quer saber onde está um arquivo específico pelo NOME dele, ou pedir para
  encontrar/procurar um arquivo no PC.
- "listar_pasta" se o usuário quer saber o que tem DENTRO de uma pasta específica (ex: "o que tem no
  Desktop", "liste os arquivos da pasta Docs") — diferente de "localizar", que busca um arquivo pelo
  nome sem saber a pasta.
- "consulta_estruturada" se o usuário pede uma operação objetiva sobre o histórico de navegação,
  sobre os programas instalados no PC, ou sobre dados de uma planilha Excel: contar quantas
  entradas/linhas existem, listar em ordem, somar/tirar média de uma coluna, ou filtrar por um
  critério exato (site, data, nome de programa, valor de coluna). A pergunta não menciona um
  ASSUNTO/TEMA aberto — pede quantidade, ordem, cálculo ou filtro exato. NÃO use essa categoria se
  a pergunta for sobre o CONTEÚDO/ASSUNTO de algo que o usuário pesquisou, viu ou visitou (isso é
  "pergunta", mesmo se for sobre histórico de navegação).

  Exemplo consulta_estruturada: "quais os últimos 5 sites que eu visitei" (pede ordem cronológica, sem tema)
  Exemplo consulta_estruturada: "quantos vídeos do youtube eu vi" (pede contagem, sem tema)
  Exemplo consulta_estruturada: "eu tenho o Photoshop instalado?" (pede filtro exato sobre programas)
  Exemplo consulta_estruturada: "qual a soma da coluna preço na planilha vendas.xlsx" (cálculo sobre planilha)
  Exemplo pergunta: "o que eu pesquisei sobre inteligência artificial" (pede um ASSUNTO específico)
  Exemplo pergunta: "o que eu vi sobre política no youtube" (pede um ASSUNTO específico)
- "pergunta" para qualquer outro tipo de pergunta ou pedido.

Responda APENAS com uma palavra: "resumo", "transcricao", "contagem", "localizar", "listar_pasta",
"consulta_estruturada" ou "pergunta".

PEDIDO: {mensagem}

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
    if "transcricao" in categoria:
        return "transcricao"
    if "listar_pasta" in categoria:
        return "listar_pasta"
    if "localizar" in categoria:
        return "localizar"
    if "contagem" in categoria:
        return "contagem"
    if "resumo" in categoria:
        return "resumo"
    if "consulta_estruturada" in categoria:
        return "consulta_estruturada"
    return "pergunta"

def extrair_nome_arquivo(mensagem: str) -> str:
    prompt = f"""Extraia APENAS o nome ou palavras-chave do arquivo/livro/documento mencionado na mensagem abaixo, sem mais nada.

MENSAGEM: {mensagem}

PALAVRAS-CHAVE:"""

    resposta = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": MODELO_LLM,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": 20, "temperature": 0}
        }
    )
    return resposta.json()["response"].strip()

def extrair_termo_e_arquivo(mensagem: str) -> tuple[str, str]:
    prompt = f"""Extraia duas informações da mensagem do usuário: o TERMO que ele quer contar (uma palavra ou nome curto) e o ARQUIVO onde ele quer contar (nome de um livro/documento).

Exemplo:
MENSAGEM: quantas vezes "lobo" aparece no livro dos três porquinhos?
TERMO: lobo
ARQUIVO: três porquinhos

Agora extraia da mensagem real abaixo. Responda EXATAMENTE neste formato, sem mais nada:
TERMO: <termo aqui>
ARQUIVO: <nome do arquivo aqui>

MENSAGEM: {mensagem}"""

    resposta = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": MODELO_LLM,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": 60, "temperature": 0}
        }
    )
    texto = resposta.json()["response"].strip()

    termo = ""
    arquivo = ""
    for linha in texto.split("\n"):
        if linha.upper().startswith("TERMO:"):
            termo = linha.split(":", 1)[1].strip()
        elif linha.upper().startswith("ARQUIVO:"):
            arquivo = linha.split(":", 1)[1].strip()

    return termo, arquivo

def extrair_termo_arquivo(mensagem: str) -> str:
    prompt = f"""Extraia APENAS o nome ou palavras-chave do arquivo que o usuário quer localizar,
exatamente como escrito na mensagem, sem traduzir, sem corrigir, sem completar.

Exemplo:
MENSAGEM: onde está o arquivo relatorio final?
TERMO DE BUSCA: relatorio final

Agora extraia da mensagem real abaixo. Responda APENAS com o termo, sem mais nada.

MENSAGEM: {mensagem}

TERMO DE BUSCA:"""

    resposta = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": MODELO_LLM,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": 20, "temperature": 0}
        }
    )
    return resposta.json()["response"].strip()

def localizar_arquivo_estruturado(mensagem: str) -> tuple[str, list[dict]]:
    """Extrai o termo de busca (LLM) e consulta o catálogo. Retorna (termo, resultados) — usado
    pela interface Streamlit pra desenhar os resultados como botão de verdade em vez de link
    (ver interface.py: renderizar_lista_arquivos()). `localizar_arquivo()`
    (catalogar_arquivos.py) continua sendo a versão em texto puro, pro terminal
    (`processar_mensagem()`)."""
    garantir_catalogo(carregar_pastas_catalogadas())
    termo = extrair_termo_arquivo(mensagem)
    return termo, buscar_arquivo(termo)

def extrair_nome_pasta(mensagem: str) -> str:
    prompt = f"""Extraia APENAS o nome da pasta que o usuário quer listar, exatamente como escrito
na mensagem, sem traduzir, sem corrigir, sem completar.

Exemplo:
MENSAGEM: o que tem na pasta Desktop?
NOME DA PASTA: Desktop

Agora extraia da mensagem real abaixo. Responda APENAS com o nome, sem mais nada.

MENSAGEM: {mensagem}

NOME DA PASTA:"""

    resposta = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": MODELO_LLM,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": 20, "temperature": 0}
        }
    )
    return resposta.json()["response"].strip()

def extrair_nome_planilha(mensagem: str) -> str:
    prompt = f"""Extraia APENAS o nome da planilha Excel mencionada na mensagem abaixo, exatamente
como escrito, sem traduzir, sem corrigir, sem completar.

Exemplo:
MENSAGEM: quanto foi a soma da coluna preço na planilha vendas.xlsx?
NOME DA PLANILHA: vendas.xlsx

Agora extraia da mensagem real abaixo. Responda APENAS com o nome, sem mais nada.

MENSAGEM: {mensagem}

NOME DA PLANILHA:"""

    resposta = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": MODELO_LLM,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": 20, "temperature": 0}
        }
    )
    return resposta.json()["response"].strip()

def extrair_parametros_transcricao(mensagem: str) -> dict:
    prompt = f"""Extraia os parâmetros de transcrição pedidos na mensagem abaixo. Responda EXATAMENTE
nesse formato, uma linha por campo, sem mais nada:
ARQUIVO: <nome do documento>
PAGINA_INICIO: <número ou NENHUM>
PAGINA_FIM: <número ou NENHUM>
TERMO: <palavra/trecho que marca a seção desejada, ou NENHUM>

Regras:
- Se o pedido for do documento inteiro, todos os campos de intervalo ficam NENHUM.
- Se pedir "as N primeiras páginas", PAGINA_INICIO=1, PAGINA_FIM=N.
- Se pedir um trecho relacionado a um termo/assunto/data específico (ex: "a parte de março"),
  preencha TERMO com esse termo, deixe PAGINA_INICIO/PAGINA_FIM como NENHUM.

Exemplo 1:
MENSAGEM: transcreva as 10 primeiras páginas do livro X
ARQUIVO: livro X
PAGINA_INICIO: 1
PAGINA_FIM: 10
TERMO: NENHUM

Exemplo 2:
MENSAGEM: transcreva a parte de março do relatório Y
ARQUIVO: relatório Y
PAGINA_INICIO: NENHUM
PAGINA_FIM: NENHUM
TERMO: março

Exemplo 3:
MENSAGEM: transcreva o livro Z
ARQUIVO: livro Z
PAGINA_INICIO: NENHUM
PAGINA_FIM: NENHUM
TERMO: NENHUM

Agora extraia da mensagem real abaixo.

MENSAGEM: {mensagem}"""

    resposta = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": MODELO_LLM,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": 60, "temperature": 0}
        }
    )
    texto = resposta.json()["response"].strip()

    campos = {"ARQUIVO": "", "PAGINA_INICIO": None, "PAGINA_FIM": None, "TERMO": None}
    for linha in texto.split("\n"):
        if ":" not in linha:
            continue
        chave, valor = linha.split(":", 1)
        chave = chave.strip().upper()
        valor = valor.strip()
        if chave not in campos:
            continue
        if chave == "ARQUIVO":
            campos[chave] = valor
        elif chave == "TERMO":
            campos[chave] = None if valor.upper() == "NENHUM" else valor
        else:
            campos[chave] = int(valor) if valor.isdigit() else None

    return campos

def extrair_recorte_transcricao(mensagem: str) -> dict:
    """Extrai só o RECORTE da transcrição (páginas ou termo) — o arquivo já veio escolhido por
    dropdown. Equivalente a `extrair_parametros_transcricao()` sem o campo ARQUIVO."""
    prompt = f"""O documento a transcrever JÁ foi escolhido. Extraia apenas qual PARTE dele o
usuário quer. Responda EXATAMENTE nesse formato, uma linha por campo, sem mais nada:
PAGINA_INICIO: <número ou NENHUM>
PAGINA_FIM: <número ou NENHUM>
TERMO: <palavra/trecho que marca a seção desejada, ou NENHUM>

Regras:
- Se o pedido for do documento inteiro, todos os campos ficam NENHUM.
- Se pedir "as N primeiras páginas", PAGINA_INICIO=1, PAGINA_FIM=N.
- Se pedir um trecho ligado a um termo/assunto/data (ex: "a parte de março"), preencha TERMO e
  deixe as páginas como NENHUM.

Exemplo 1:
MENSAGEM: transcreva as 10 primeiras páginas
PAGINA_INICIO: 1
PAGINA_FIM: 10
TERMO: NENHUM

Exemplo 2:
MENSAGEM: quero a parte que fala de março
PAGINA_INICIO: NENHUM
PAGINA_FIM: NENHUM
TERMO: março

Exemplo 3:
MENSAGEM: transcreva tudo
PAGINA_INICIO: NENHUM
PAGINA_FIM: NENHUM
TERMO: NENHUM

Agora extraia da mensagem real abaixo.

MENSAGEM: {mensagem}"""

    resposta = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": MODELO_LLM,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": 40, "temperature": 0}
        }
    )
    texto = resposta.json()["response"].strip()

    campos = {"PAGINA_INICIO": None, "PAGINA_FIM": None, "TERMO": None}
    for linha in texto.split("\n"):
        if ":" not in linha:
            continue
        chave, valor = linha.split(":", 1)
        chave, valor = chave.strip().upper(), valor.strip()
        if chave not in campos:
            continue
        if chave == "TERMO":
            campos[chave] = None if valor.upper() == "NENHUM" else valor
        else:
            campos[chave] = int(valor) if valor.isdigit() else None
    return campos

def extrair_nome_aba(mensagem: str) -> str | None:
    prompt = f"""Extraia APENAS o nome da aba/planilha interna (sheet) mencionada explicitamente na
mensagem abaixo. Se nenhuma aba for mencionada por nome, responda apenas "NENHUMA".

Exemplo 1:
MENSAGEM: quantas linhas tem a aba Vendas da planilha dados.xlsx?
ABA: Vendas

Exemplo 2:
MENSAGEM: quantas linhas tem a planilha dados.xlsx?
ABA: NENHUMA

Agora extraia da mensagem real abaixo. Responda APENAS com o nome da aba, sem mais nada.

MENSAGEM: {mensagem}

ABA:"""

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
    # mesmo bug já visto em extrair_nome_documento_mencionado (perguntar.py): o modelo às vezes
    # ecoa o próprio rótulo do prompt em vez de responder só o valor.
    if termo.upper().startswith("ABA:"):
        termo = termo.split(":", 1)[1].strip()
    return None if not termo or termo.upper() == "NENHUMA" else termo

def classificar_consulta_historico(mensagem: str) -> str:
    """Classificador estreito (2 vias) usado só dentro do funil, quando a Etapa 2 já escolheu
    'Histórico de navegação' — mesma distinção consulta_estruturada/pergunta de
    classificar_pedido, sem as outras 5 categorias que não se aplicam a esse caminho."""
    prompt = f"""Classifique o pedido abaixo, sobre histórico de navegação, em uma categoria:
- "consulta_estruturada" se pede uma operação objetiva: contar quantas entradas existem, listar em
  ordem cronológica, ou filtrar por um critério exato (site, data). A pergunta não menciona um
  ASSUNTO/TEMA aberto — pede quantidade, ordem ou filtro exato.
- "pergunta" se for sobre o CONTEÚDO/ASSUNTO de algo que o usuário pesquisou, viu ou visitou.

  Exemplo consulta_estruturada: "quais os últimos 5 sites que eu visitei" (ordem cronológica, sem tema)
  Exemplo consulta_estruturada: "quantos vídeos do youtube eu vi" (contagem, sem tema)
  Exemplo pergunta: "o que eu pesquisei sobre inteligência artificial" (ASSUNTO específico)
  Exemplo pergunta: "o que eu vi sobre política no youtube" (ASSUNTO específico)

Responda APENAS com uma palavra: "consulta_estruturada" ou "pergunta".

PEDIDO: {mensagem}

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
    return "consulta_estruturada" if "estruturada" in categoria else "pergunta"

def formatar_saida_transcricao(nome_pedido: str, texto_transcrito: str) -> str:
    """Versão em texto puro (terminal). A interface usa `transcrever_estruturado()`, que devolve
    também o caminho do arquivo salvo — pra oferecer um botão que abre esse arquivo."""
    resposta, _ = transcrever_estruturado_saida(nome_pedido, texto_transcrito)
    return resposta


def transcrever_estruturado_saida(nome_pedido: str, texto_transcrito: str) -> tuple[str, str | None]:
    """Formata a saída da transcrição e devolve `(mensagem, caminho_do_arquivo_ou_None)`.
    Transcrição curta cabe no chat e não gera arquivo (caminho `None`); a longa vira arquivo, e
    aí o caminho serve pro botão de abrir da interface (achado 2026-08-29: o usuário recebia só
    o caminho escrito na mensagem e tinha que ir até a pasta na mão)."""
    if len(texto_transcrito) > LIMITE_TRANSCRICAO_INLINE:
        caminho_saida = salvar_transcricao_em_arquivo(nome_pedido, texto_transcrito)
        mensagem = (
            f"Transcrição salva em '{caminho_saida}' ({len(texto_transcrito)} caracteres) — "
            f"abra o arquivo pra ver o conteúdo completo."
        )
        return mensagem, os.path.abspath(caminho_saida)
    return texto_transcrito, None


def recorte_pede_documento_inteiro(recorte: dict) -> bool:
    """Diz se o recorte extraído NÃO restringe nada — do começo ao fim, sem termo.

    Achado real (2026-08-29, usuário pediu "transcreva o primeiro capitulo" e recebeu o livro
    inteiro, 139.554 caracteres, sem aviso): `extrair_recorte_transcricao()` só entende intervalo
    de página e termo literal. Pedido que não cabe em nenhum dos dois (capítulo, seção, unidade —
    em qualquer idioma) não vira "não entendi", vira campo vazio — e campo vazio significa
    "documento inteiro". Ou seja, o pedido MENOS compreendido virava a MAIOR ação possível, em
    silêncio. Esta função existe pra interface poder confirmar antes, em vez de assumir.

    `PAGINA_INICIO` em 1 conta como "sem restrição" junto com `PAGINA_FIM` vazio, porque é
    exatamente o que "primeiro capítulo" produziu (página 1 até o fim = tudo). Já "a partir da
    página 10" (início 10, fim vazio) é recorte de verdade e não entra aqui."""
    return (
        not recorte.get("TERMO")
        and recorte.get("PAGINA_INICIO") in (None, 1)
        and recorte.get("PAGINA_FIM") is None
    )


def transcrever_documento_estruturado(nome_arquivo: str, recorte: dict, colecao) -> tuple[str, str | None]:
    """Transcreve um documento com o recorte JÁ extraído, devolvendo `(mensagem, caminho|None)`.
    Recebe o recorte pronto (em vez de extrair aqui dentro) porque a interface precisa olhar pra
    ele ANTES — pra confirmar quando o pedido não restringe nada (ver
    `recorte_pede_documento_inteiro()`)."""
    texto_transcrito = transcrever_arquivo(
        nome_arquivo, colecao,
        pagina_inicio=recorte["PAGINA_INICIO"],
        pagina_fim=recorte["PAGINA_FIM"],
        termo_busca=recorte["TERMO"],
        sugestao_alternativa=SUGESTAO_TROCAR_PARA_CONSULTAR,
    )
    return transcrever_estruturado_saida(nome_arquivo, texto_transcrito)

def processar_mensagem_guiada(mensagem: str, categoria: str, formato: str, historico: list[dict], colecao,
                              progresso_callback=None, arquivo_selecionado: str | None = None,
                              aba_selecionada: str | None = None, pasta_selecionada: str | None = None) -> str:
    """Orquestrador do funil de decisão em etapas (Streamlit) — Categoria e Formato já vêm
    decididos por botão na interface (zero LLM), só o texto livre da Etapa 3 passa por
    classificação, e só nas 2 combinações que genuinamente precisam (Consultar+Documento,
    Consultar+Histórico). As outras combinações vão direto pra função certa. Reaproveita todos
    os extratores/funções já usados por processar_mensagem() — nenhum deles muda.

    Princípio de arquitetura (ver ARQUITETURA.md, 2026-08-20): a IA nunca escolhe entre opções
    conhecidas (qual arquivo, qual aba, qual pasta) — isso é responsabilidade da interface
    (botão/dropdown). Por isso esta função NÃO tenta resolver escolha via reformulação de texto
    livre/histórico — quando uma combinação envolve escolher arquivo/aba, isso é feito por botão
    na interface antes da mensagem chegar aqui (ver interface.py).

    progresso_callback: repassado pro resumo (`resumir_arquivo()`, map-reduce bloco a bloco, com
    sinal de progresso granular) e pra pergunta — nesta última não é mais efetivamente usado desde
    que a Camada 3 (map-reduce fragmentado) foi substituída por rotas de leitura única (ver
    `decidir_rota_por_volume()` em perguntar.py); passado só por compatibilidade de assinatura.
    Tanto a rota direta quanto a ampliada seguem com o spinner indeterminado da interface.

    arquivo_selecionado / aba_selecionada / pasta_selecionada (item 12 da fila): vêm preenchidos
    quando a interface já resolveu a escolha por dropdown. Nesse caso os extratores de NOME
    (`extrair_nome_arquivo`, `extrair_nome_planilha`, `extrair_nome_aba`, `extrair_nome_pasta`,
    `extrair_termo_e_arquivo`) são **pulados inteiramente** — a mensagem de texto livre passa a
    conter só o pedido de conteúdo. Isso não "corrige" os bugs de casamento de nome: remove a
    necessidade deles existirem nesse caminho. Quando vêm `None`, o comportamento antigo
    (extrair da frase) é mantido, o que preserva o terminal e os testes anteriores."""
    if mensagem.strip().lower() in COMANDOS_DE_AJUDA:
        return texto_de_ajuda()

    if categoria == "consultar" and formato == "documento":
        # Resumo e contagem saíram daqui — viram botão/caixa mecânicos na interface (ver
        # PENDENCIAS.md, itens 1 e 6), sem LLM decidindo. Achado real, 2026-08-25: o usuário
        # apontou que digitar "resumo" no chat ainda acionava classificar_consulta_documento()
        # mesmo com o botão mecânico já existindo — os dois caminhos coexistiam. Removido o
        # classificador inteiro (não só essa chamada): chat livre em "Consultar+Documento" agora
        # significa só "pergunta", sempre.
        return responder_pergunta(mensagem, historico, colecao, fonte_forcada="documento",
                                  arquivo_forcado=arquivo_selecionado, progresso_callback=progresso_callback)

    if categoria == "consultar" and formato == "planilha":
        if arquivo_selecionado:
            # planilha e aba já resolvidas por dropdown: a mensagem contém só a pergunta sobre
            # os dados, então nada precisa ser removido dela antes do extrator de especificação.
            return consultar_dado_estruturado(mensagem, "planilha", colecao, arquivo_selecionado, aba_selecionada)
        nome_pedido = extrair_nome_planilha(mensagem)
        nome_planilha, erro = identificar_planilha(nome_pedido)
        if erro:
            return erro
        # remove o nome da planilha (já resolvido) antes de perguntar pela aba — sem isso, o
        # próprio nome do arquivo podia ser confundido com nome de aba pelo extrator.
        # A MESMA mensagem limpa segue pra consulta: passar a mensagem crua adiante fazia o
        # extrator de especificação reinterpretar o nome que o usuário digitou como filtro de
        # dado (reproduzido em 2026-08-20: "total de linhas da tarefa matematica na aba X"
        # virava filtro coluna=="tarefa matematica", zerando o resultado numa aba de 242 linhas).
        mensagem_sem_planilha = remover_referencias_resolvidas(mensagem, nome_pedido, nome_planilha)
        nome_aba = extrair_nome_aba(mensagem_sem_planilha)
        return consultar_dado_estruturado(mensagem_sem_planilha, "planilha", colecao, nome_planilha, nome_aba)

    if categoria == "consultar" and formato == "historico":
        subcategoria = classificar_consulta_historico(mensagem)
        if subcategoria == "consulta_estruturada":
            return consultar_dado_estruturado(mensagem, "historico_navegacao", colecao)
        return responder_pergunta(mensagem, historico, colecao, fonte_forcada="historico_navegacao",
                                  progresso_callback=progresso_callback)

    if categoria == "consultar" and formato == "programas":
        return consultar_dado_estruturado(mensagem, "programas_instalados", colecao)

    if categoria == "criar" and formato == "documento":
        if arquivo_selecionado:
            recorte = extrair_recorte_transcricao(mensagem)
            nome_pedido = arquivo_selecionado
        else:
            parametros = extrair_parametros_transcricao(mensagem)
            recorte = parametros
            nome_pedido = parametros["ARQUIVO"]
        texto_transcrito = transcrever_arquivo(
            nome_pedido, colecao,
            pagina_inicio=recorte["PAGINA_INICIO"],
            pagina_fim=recorte["PAGINA_FIM"],
            termo_busca=recorte["TERMO"],
            # Dentro do funil, "faça uma pergunta" NÃO é alcançável aqui: esta combinação
            # (Criar + Documento) só transcreve. A saída precisa dizer como sair daqui.
            sugestao_alternativa=SUGESTAO_TROCAR_PARA_CONSULTAR,
        )
        return formatar_saida_transcricao(nome_pedido, texto_transcrito)

    if categoria == "criar" and formato == "planilha":
        if arquivo_selecionado:
            texto_transcrito = transcrever_planilha(mensagem, arquivo_selecionado, aba_selecionada)
            return formatar_saida_transcricao(arquivo_selecionado, texto_transcrito)
        nome_pedido = extrair_nome_planilha(mensagem)
        nome_planilha, erro = identificar_planilha(nome_pedido)
        if erro:
            return erro
        mensagem_sem_planilha = remover_referencias_resolvidas(mensagem, nome_pedido, nome_planilha)
        nome_aba = extrair_nome_aba(mensagem_sem_planilha)
        texto_transcrito = transcrever_planilha(mensagem_sem_planilha, nome_planilha, nome_aba)
        return formatar_saida_transcricao(nome_planilha, texto_transcrito)

    if categoria == "procurar" and formato == "arquivo":
        garantir_catalogo(carregar_pastas_catalogadas())
        termo = extrair_termo_arquivo(mensagem)
        return localizar_arquivo(termo)

    if categoria == "procurar" and formato == "pasta":
        garantir_catalogo(carregar_pastas_catalogadas())
        if pasta_selecionada:
            # caminho exato escolhido no dropdown — sem busca por nome, sem ambiguidade possível
            return listar_pasta_por_caminho(pasta_selecionada)
        nome_pasta = extrair_nome_pasta(mensagem)
        return listar_pasta(nome_pasta)

    return "Combinação de categoria/formato não reconhecida. Tente reformular."

def processar_mensagem(mensagem: str, historico: list[dict], colecao) -> str:
    if mensagem.strip().lower() in COMANDOS_DE_AJUDA:
        return texto_de_ajuda()

    categoria = classificar_pedido(mensagem)

    if categoria == "resumo":
        nome_arquivo = extrair_nome_arquivo(mensagem)
        resposta = resumir_arquivo(nome_arquivo, colecao)
    elif categoria == "transcricao":
        parametros = extrair_parametros_transcricao(mensagem)
        nome_planilha, _ = identificar_planilha(parametros["ARQUIVO"])
        if nome_planilha:
            texto_transcrito = transcrever_planilha(
                remover_referencias_resolvidas(mensagem, parametros["ARQUIVO"], nome_planilha),
                nome_planilha,
            )
        else:
            texto_transcrito = transcrever_arquivo(
                parametros["ARQUIVO"], colecao,
                pagina_inicio=parametros["PAGINA_INICIO"],
                pagina_fim=parametros["PAGINA_FIM"],
                termo_busca=parametros["TERMO"],
            )
        if len(texto_transcrito) > LIMITE_TRANSCRICAO_INLINE:
            caminho_saida = salvar_transcricao_em_arquivo(parametros["ARQUIVO"], texto_transcrito)
            resposta = (
                f"Transcrição salva em '{caminho_saida}' ({len(texto_transcrito)} caracteres) — "
                f"abra o arquivo pra ver o conteúdo completo."
            )
        else:
            resposta = texto_transcrito
    elif categoria == "contagem":
        termo, nome_arquivo = extrair_termo_e_arquivo(mensagem)
        resposta = contar_termo_no_arquivo(nome_arquivo, termo, colecao)
    elif categoria == "localizar":
        garantir_catalogo(carregar_pastas_catalogadas())
        termo = extrair_termo_arquivo(mensagem)
        #print(f"[DEBUG] Termo extraído para busca: '{termo}'")
        resposta = localizar_arquivo(termo)
    elif categoria == "listar_pasta":
        garantir_catalogo(carregar_pastas_catalogadas())
        nome_pasta = extrair_nome_pasta(mensagem)
        resposta = listar_pasta(nome_pasta)
    elif categoria == "consulta_estruturada":
        fonte = detectar_fonte_estruturada(mensagem)
        if fonte == "planilha":
            nome_pedido = extrair_nome_planilha(mensagem)
            nome_planilha, erro = identificar_planilha(nome_pedido)
            resposta = erro if erro else consultar_dado_estruturado(
                remover_referencias_resolvidas(mensagem, nome_pedido, nome_planilha),
                fonte, colecao, nome_planilha,
            )
        else:
            resposta = consultar_dado_estruturado(mensagem, fonte, colecao)
    else:
        resposta = responder_pergunta(mensagem, historico, colecao)

    return resposta

def obter_colecao():
    cliente = chromadb.PersistentClient(path=PASTA_BANCO_VETORIAL)
    return cliente.get_or_create_collection(name="documentos_pessoais")

if __name__ == "__main__":
    colecao = obter_colecao()

    historico = []

    print("Jarvis pronto. Digite 'sair' pra encerrar.\n")

    while True:
        mensagem = input("Você: ")
        if mensagem.lower() in ("sair", "exit"):
            break

        resposta = processar_mensagem(mensagem, historico, colecao)

        print(f"\nJarvis: {resposta}\n")

        historico.append({"pergunta": mensagem, "resposta": condensar_para_historico(resposta)})
        if len(historico) > TAMANHO_HISTORICO:
            historico.pop(0)

