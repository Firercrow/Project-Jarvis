import os
import shutil
import subprocess
import streamlit as st

from jarvis import (processar_mensagem_guiada, obter_colecao, localizar_arquivo_estruturado,
                    extrair_recorte_transcricao, recorte_pede_documento_inteiro,
                    transcrever_documento_estruturado)
from config import (TAMANHO_HISTORICO, PASTA_DOCUMENTOS,
                    EXTENSOES_INDEXAVEIS, EXTENSAO_PLANILHA, EXTENSOES_PERMITIDAS)
from indexar import indexar_arquivo
from resumir import condensar_para_historico, contar_termo_por_pagina, tamanho_aproximado_documento
from catalogar_arquivos import (carregar_pastas_catalogadas, salvar_pastas_catalogadas,
                                garantir_catalogo, listar_pastas_disponiveis, arquivos_diretos_de)
from consultar_dados import listar_todos_programas, listar_planilhas_disponiveis, listar_abas_planilha
from resumir import listar_arquivos_disponiveis, resumir_arquivo
from manter_modelo_quente import iniciar_batimento
from indexar_historico import indexar_historico

# Formato/fonte disponível em cada categoria da Etapa 1 — (rótulo do botão, valor interno)
FORMATOS_POR_CATEGORIA = {
    "consultar": [
        ("Documento (PDF/TXT/Word)", "documento"),
        ("Planilha Excel", "planilha"),
        ("Histórico de navegação", "historico"),
        ("Programas instalados", "programas"),
    ],
    "criar": [
        ("Documento (PDF/TXT/Word)", "documento"),
        ("Planilha Excel", "planilha"),
    ],
    "procurar": [
        ("Por nome de arquivo", "arquivo"),
        ("Por pasta", "pasta"),
    ],
}

ROTULO_CATEGORIA = {"consultar": "Consultar", "criar": "Criar", "procurar": "Procurar"}
ROTULO_FORMATO = {
    "documento": "Documento", "planilha": "Planilha Excel",
    "historico": "Histórico de navegação", "programas": "Programas instalados",
    "arquivo": "Por nome de arquivo", "pasta": "Por pasta",
}

# Textos da Etapa 3. Escritos partindo do princípio de que o arquivo/aba JÁ foi escolhido na
# sub-etapa (item 12) — por isso nenhum deles pede pro usuário dizer o nome do arquivo.
AJUDA_ETAPA3 = {
    ("consultar", "documento"): "Pergunte sobre o conteúdo deste documento. Pra resumo "
        "completo ou contagem de termo, use os botões acima.",
    ("consultar", "planilha"): "Pergunte sobre os dados desta aba: contagem, soma, média, "
        "filtro por coluna (ex: \"quantas linhas têm valor acima de 100\").",
    ("consultar", "historico"): "Pergunte sobre sites visitados, vídeos assistidos, ou peça uma "
        "lista/contagem do seu histórico de navegação.",
    ("consultar", "programas"): "Pergunte sobre programas instalados no seu PC (ex: \"eu tenho "
        "o Photoshop instalado?\").",
    ("criar", "documento"): "Peça a transcrição literal deste documento — inteiro (\"transcreva "
        "tudo\"), por página (\"as 10 primeiras páginas\") ou por trecho (\"a parte sobre março\").",
    ("criar", "planilha"): "Peça a transcrição desta aba — inteira, ou de uma coluna específica "
        "(ex: \"só a coluna preço\").",
    ("procurar", "arquivo"): "Diga o nome (ou parte do nome) do arquivo que você quer localizar.",
}

# Combinações em que a escolha do alvo é MECÂNICA (lista conhecida e finita) e portanto pertence
# à interface, nunca à IA — ver Princípio central de arquitetura #2 no ARQUITETURA.md.
# As que ficam de fora são deliberadas: histórico e programas são fonte única (não há o que
# escolher), e "procurar por nome de arquivo" tem a busca aproximada como PROPÓSITO da
# funcionalidade — é a exceção legítima do princípio.
COMBINACOES_COM_DOCUMENTO = {("consultar", "documento"), ("criar", "documento")}
COMBINACOES_COM_PLANILHA = {("consultar", "planilha"), ("criar", "planilha")}
COMBINACAO_COM_PASTA = ("procurar", "pasta")

st.set_page_config(page_title="PROJECT Jarvis", page_icon="🤖")


def executar_acao_abrir(caminho_arquivo: str) -> str:
    """Abre o Explorer com o arquivo já selecionado. Não lança o app associado ao formato
    (`os.startfile`) — achado 2026-08-29 (usuário testou): pra um arquivo `.url` (atalho de
    internet), `os.startfile` abre o NAVEGADOR (comportamento correto do Windows pra esse tipo
    de arquivo, mas não o que se quer aqui). "explorer /select," sempre abre a pasta local,
    previsível pra qualquer formato. Só funciona no PC de quem clicou (Streamlit local) —
    ressalva já assumida pelo usuário (PENDENCIAS.md, item 4).

    Bug real (2026-08-29, usuário testou com "Alan Wake" — caminho com espaço): passar
    `["explorer", f"/select,{caminho}"]` como LISTA faz o `subprocess`/Windows envolver o
    argumento INTEIRO (`/select,` + caminho) entre aspas quando o caminho tem espaço — o
    Explorer não reconhece `/select,` colado dentro de uma aspa só e cai no fallback dele
    (abre "Documentos", não a pasta certa). Confirmado com automação COM (`Shell.Application`,
    lendo `LocationURL` da janela que abriu) — bug reproduzido (abriu Documentos) e corrigido
    (abriu a pasta certa). Corrigido montando a linha de comando como STRING (`subprocess.run`
    sem lista, `shell=False` — no Windows uma string vira a linha de comando literal, sem
    reformatação automática), com aspas só ao redor do CAMINHO, do jeito que o Explorer espera.
    Seguro contra injeção mesmo montando a string na mão: `caminho_arquivo` vem sempre do
    catálogo (path real do disco, nunca texto digitado), e aspas duplas são caractere ilegal em
    nome de arquivo do Windows — não tem como escapar da aspa que envolve o caminho."""
    if not os.path.isfile(caminho_arquivo):
        return f"Arquivo não encontrado: '{caminho_arquivo}'."
    try:
        subprocess.run(f'explorer /select,"{caminho_arquivo}"')
        return f"Abrindo pasta de '{os.path.basename(caminho_arquivo)}'..."
    except OSError as erro:
        return f"Não consegui abrir '{caminho_arquivo}': {erro}"


def garantir_pasta_documentos():
    os.makedirs(PASTA_DOCUMENTOS, exist_ok=True)


def executar_acao_indexar(caminho_arquivo: str, colecao) -> str:
    """Copia o arquivo catalogado pra `Docs/` (só se ainda não estiver lá) e indexa — decisão do
    usuário (2026-08-25): reaproveita o pipeline de upload existente, mantém `Docs/` como única
    zona indexável. Recusa em vez de sobrescrever quando já existe um arquivo DIFERENTE com o
    mesmo nome em `Docs/` — apagar/substituir algo já indexado sem confirmação explícita é o
    tipo de ação irreversível que o projeto evita."""
    if not os.path.isfile(caminho_arquivo):
        return f"Arquivo não encontrado: '{caminho_arquivo}'."
    nome_arquivo = os.path.basename(caminho_arquivo)
    destino = os.path.join(PASTA_DOCUMENTOS, nome_arquivo)
    ja_esta_em_docs = os.path.abspath(destino) == os.path.abspath(caminho_arquivo)
    if not ja_esta_em_docs and os.path.exists(destino):
        return (f"Já existe um arquivo chamado '{nome_arquivo}' em Docs/ — renomeie um dos dois "
                f"antes de indexar, pra não arriscar sobrescrever o que já está lá.")
    if not ja_esta_em_docs:
        garantir_pasta_documentos()
        shutil.copy2(caminho_arquivo, destino)
    return indexar_arquivo(nome_arquivo, colecao)


def renderizar_lista_arquivos(chave_mensagem, arquivos: list[dict]):
    """Desenha cada arquivo como botão de verdade do Streamlit (abrir/indexar) — não link.

    Achado 2026-08-29 (testado com clique de verdade, não só leitura de código): link
    markdown/HTML pra ação sobre arquivo sempre abre em ABA NOVA no Streamlit (`target="_blank"`
    automático, sem parâmetro pra desligar); forçar a mesma aba (`target="_self"`) resolve a aba
    extra mas causa recarga completa da página, que RESETA toda a sessão (funil, busca em
    andamento) — pior que o problema original. Botão de verdade não usa URL nenhuma: roda
    Python direto no servidor, sem navegação, sem aba, sem perder estado. `chave_mensagem`
    garante key única de widget entre mensagens diferentes (ex: duas buscas seguidas com
    arquivos em comum)."""
    for indice, arquivo in enumerate(arquivos):
        coluna_legenda, coluna_abrir, coluna_indexar = st.columns([8, 1, 1])
        coluna_legenda.caption(arquivo["legenda"])
        if coluna_abrir.button("↗", key=f"abrir_{chave_mensagem}_{indice}", help="Abrir a pasta no Explorer"):
            st.toast(executar_acao_abrir(arquivo["caminho"]))
        indexavel = os.path.splitext(arquivo["nome"])[1].lower() in EXTENSOES_INDEXAVEIS
        if indexavel:
            if coluna_indexar.button("⬆", key=f"indexar_{chave_mensagem}_{indice}",
                                      help="Indexar (adicionar aos documentos consultáveis)"):
                st.toast(executar_acao_indexar(arquivo["caminho"], colecao))


def renderizar_arquivo_gerado(chave_mensagem, caminho_arquivo: str):
    """Botão que abre o arquivo que o Jarvis acabou de gerar (hoje: transcrição salva em
    `transcricoes/`). Pedido do usuário em 2026-08-29: antes a mensagem só ESCREVIA o caminho e
    ele tinha que ir até a pasta na mão. Aponta pro arquivo específico, não só pra pasta — a
    pasta acumula transcrições antigas e não diz qual é a nova."""
    coluna_legenda, coluna_abrir = st.columns([9, 1])
    coluna_legenda.caption(os.path.basename(caminho_arquivo))
    if coluna_abrir.button("↗", key=f"abrir_gerado_{chave_mensagem}", help="Abrir a pasta no Explorer"):
        st.toast(executar_acao_abrir(caminho_arquivo))


@st.cache_resource
def carregar_colecao():
    return obter_colecao()


@st.cache_resource
def manter_modelo_quente():
    """Sobe o batimento que impede o Ollama de descarregar o modelo da VRAM (ver
    manter_modelo_quente.py pro problema medido: 260s vs 14,5s na MESMA pergunta). O
    `st.cache_resource` é o que garante UMA thread por processo do servidor — sem ele, cada
    rerun da tela (que é o funcionamento normal do Streamlit) subiria uma thread nova."""
    return iniciar_batimento()


colecao = carregar_colecao()
manter_modelo_quente()

if "mensagens" not in st.session_state:
    st.session_state.mensagens = []
if "historico" not in st.session_state:
    st.session_state.historico = []
if "upload_versao_campo" not in st.session_state:
    st.session_state.upload_versao_campo = 0
if "mensagem_upload" not in st.session_state:
    st.session_state.mensagem_upload = None
if "funil_categoria" not in st.session_state:
    st.session_state.funil_categoria = None
if "funil_formato" not in st.session_state:
    st.session_state.funil_formato = None
if "pasta_versao_campo" not in st.session_state:
    st.session_state.pasta_versao_campo = 0
if "mensagem_pasta" not in st.session_state:
    st.session_state.mensagem_pasta = None
# Arquivo aguardando confirmação de "transcrever inteiro" (None = nada pendente).
if "transcricao_a_confirmar" not in st.session_state:
    st.session_state.transcricao_a_confirmar = None
# Alvo já escolhido dentro da combinação atual (item 12): documento/planilha, aba e pasta.
for chave in ("funil_arquivo", "funil_aba", "funil_pasta"):
    if chave not in st.session_state:
        st.session_state[chave] = None


def limpar_alvo():
    """Zera o alvo escolhido (documento/planilha/aba/pasta). Chamado sempre que a combinação
    muda — um arquivo escolhido em 'Consultar+Documento' não faz sentido em outra combinação."""
    st.session_state.funil_arquivo = None
    st.session_state.funil_aba = None
    st.session_state.funil_pasta = None


def limpar_conversa():
    """Troca de categoria/formato = assunto novo. Limpa TANTO a memória usada pela reformulação
    de pergunta (`historico`) QUANTO a transcrição visível (`mensagens`).

    Antes só o `historico` era limpo, e a transcrição continuava na tela: além de misturar
    visualmente respostas de contextos diferentes (uma listagem de histórico de navegação logo
    acima de uma pergunta sobre planilha), dava a impressão de que aquilo tudo ainda fazia parte
    do contexto da conversa — quando o modelo já não enxergava nada daquilo. Limpar de vez é
    mais honesto com o que o sistema realmente está levando em conta (pedido do usuário,
    2026-08-20)."""
    st.session_state.historico = []
    st.session_state.mensagens = []


def resetar_funil():
    st.session_state.funil_categoria = None
    st.session_state.funil_formato = None
    limpar_alvo()
    limpar_conversa()


with st.sidebar:
    st.header("Adicionar documento")
    st.caption("Formatos aceitos: PDF, TXT, Word (.docx), Excel (.xlsx). Arquivos antigos "
               "(.doc, .xls) não são lidos — salve como .docx/.xlsx antes de enviar.")
    arquivo_upload = st.file_uploader(
        "Enviar arquivo", type=["pdf", "txt", "docx", "xlsx"],
        key=f"input_upload_{st.session_state.upload_versao_campo}"
    )
    if arquivo_upload is not None:
        extensao = os.path.splitext(arquivo_upload.name)[1].lower()
        if extensao not in EXTENSOES_PERMITIDAS:
            st.error(f"Formato '{extensao}' não é suportado. Use PDF, TXT, DOCX ou XLSX.")
        else:
            garantir_pasta_documentos()
            caminho_destino = os.path.join(PASTA_DOCUMENTOS, arquivo_upload.name)
            with open(caminho_destino, "wb") as f:
                f.write(arquivo_upload.getbuffer())
            if extensao == EXTENSAO_PLANILHA:
                # Planilha não é indexada (chunk/embedding) — é relida direto do arquivo
                # a cada consulta (ver consultar_dados.py), então só precisa ser salva.
                st.session_state.mensagem_upload = f"'{arquivo_upload.name}' salva. Pronta pra consulta."
            else:
                with st.spinner("Indexando documento novo..."):
                    st.session_state.mensagem_upload = indexar_arquivo(arquivo_upload.name, colecao)
            st.session_state.upload_versao_campo += 1
            st.rerun()
    if st.session_state.mensagem_upload:
        st.success(st.session_state.mensagem_upload)
        st.session_state.mensagem_upload = None

    # Configuração das pastas da zona geral. Vive aqui (e não no config.py) porque um programa
    # reescrevendo um .py é risco de corromper o arquivo — a interface grava um JSON
    # (pastas_catalogadas.json) e o config.py fica só como valor padrão da 1ª execução.
    # Escolha 100% mecânica, sem LLM (Princípio #2 do ARQUITETURA.md).
    st.divider()
    st.header("Pastas catalogadas")
    st.caption("Pastas que o Jarvis pode varrer pra localizar arquivos e listar conteúdo. "
               "Ele nunca lê o conteúdo desses arquivos — só nome, tamanho e data.")

    pastas = carregar_pastas_catalogadas()
    for indice, pasta in enumerate(pastas):
        coluna_nome, coluna_botao = st.columns([5, 1])
        coluna_nome.caption(pasta)
        if coluna_botao.button("✕", key=f"botao_remover_pasta_{indice}", help="Remover esta pasta"):
            salvar_pastas_catalogadas([p for p in pastas if p != pasta])
            st.session_state.mensagem_pasta = f"'{pasta}' removida da lista."
            st.rerun()

    if not pastas:
        st.warning("Nenhuma pasta catalogada — 'Procurar' não vai encontrar nada até você adicionar uma.")

    nova_pasta = st.text_input(
        "Adicionar pasta (caminho completo)", placeholder=r"D:\Trabalho",
        key=f"input_nova_pasta_{st.session_state.pasta_versao_campo}"
    )
    if nova_pasta:
        caminho = nova_pasta.strip().strip('"')
        if not os.path.isdir(caminho):
            st.error(f"'{caminho}' não é uma pasta existente neste PC. Verifique o caminho.")
        elif caminho in pastas:
            st.warning(f"'{caminho}' já está na lista.")
        else:
            salvar_pastas_catalogadas(pastas + [caminho])
            st.session_state.mensagem_pasta = f"'{caminho}' adicionada. Será varrida na próxima busca."
            st.session_state.pasta_versao_campo += 1
            st.rerun()

    if st.session_state.mensagem_pasta:
        st.success(st.session_state.mensagem_pasta)
        st.session_state.mensagem_pasta = None

st.title("PROJECT Jarvis")

# --- Etapa 1: Categoria ---
if st.session_state.funil_categoria is None:
    st.subheader("O que você quer fazer?")
    col1, col2, col3 = st.columns(3)
    for coluna, categoria in zip((col1, col2, col3), ("consultar", "criar", "procurar")):
        if coluna.button(ROTULO_CATEGORIA[categoria], key=f"botao_categoria_{categoria}", use_container_width=True):
            st.session_state.funil_categoria = categoria
            st.rerun()

else:
    categoria = st.session_state.funil_categoria
    st.button("← Trocar categoria", key="botao_trocar_categoria", on_click=resetar_funil)

    # --- Etapa 2: Formato/Fonte ---
    if st.session_state.funil_formato is None:
        st.subheader(f"{ROTULO_CATEGORIA[categoria]} — qual formato/fonte?")
        opcoes = FORMATOS_POR_CATEGORIA[categoria]
        colunas = st.columns(len(opcoes))
        for coluna, (rotulo, valor) in zip(colunas, opcoes):
            if coluna.button(rotulo, key=f"botao_formato_{valor}", use_container_width=True):
                st.session_state.funil_formato = valor
                st.rerun()

    # --- Etapa 3: texto livre, já escopado ---
    else:
        formato = st.session_state.funil_formato
        st.caption(f"{ROTULO_CATEGORIA[categoria]} → {ROTULO_FORMATO[formato]}")
        def trocar_formato():
            st.session_state.funil_formato = None
            # limpar_alvo() é obrigatório aqui, não só ao trocar de categoria: sem isso o
            # arquivo escolhido na combinação anterior sobrevive e a combinação nova o encontra
            # já preenchido, pulando o próprio dropdown. Foi assim que um .docx escolhido em
            # "Consultar+Documento" chegou ao openpyxl na rota de planilha e derrubou a página
            # inteira (achado no teste humano de 2026-08-22).
            limpar_alvo()
            limpar_conversa()

        st.button("Trocar formato/fonte", key="botao_trocar_formato", on_click=trocar_formato)

        # --- Sub-etapa: qual arquivo/aba/pasta (item 12) ---
        # Escolha entre um conjunto conhecido e finito é da INTERFACE, nunca da IA. Tudo aqui é
        # consulta direta (ChromaDB, disco, SQLite) — zero chamada de modelo. `index=None` é
        # proposital: sem ele o selectbox já viria com o primeiro item marcado, ou seja, a
        # interface escolhendo pelo usuário, que é o mesmo vício em outra roupa.
        combinacao = (categoria, formato)
        alvo_pendente = False

        if combinacao in COMBINACOES_COM_DOCUMENTO and st.session_state.funil_arquivo is None:
            alvo_pendente = True
            documentos = listar_arquivos_disponiveis(colecao)
            if not documentos:
                st.warning("Nenhum documento indexado ainda. Envie um arquivo pela barra lateral.")
            else:
                escolhido = st.selectbox("Qual documento?", documentos, index=None,
                                         placeholder="Escolha um documento...", key="escolha_documento")
                if escolhido:
                    st.session_state.funil_arquivo = escolhido
                    st.rerun()

        elif combinacao in COMBINACOES_COM_PLANILHA and st.session_state.funil_arquivo is None:
            alvo_pendente = True
            planilhas = listar_planilhas_disponiveis()
            if not planilhas:
                st.warning("Nenhuma planilha (.xlsx) disponível. Envie uma pela barra lateral.")
            else:
                escolhida = st.selectbox("Qual planilha?", planilhas, index=None,
                                         placeholder="Escolha uma planilha...", key="escolha_planilha")
                if escolhida:
                    st.session_state.funil_arquivo = escolhida
                    # Planilha de aba única não gera pergunta: resolve sozinha e segue direto.
                    abas = listar_abas_planilha(escolhida)
                    if len(abas) == 1:
                        st.session_state.funil_aba = abas[0]
                    st.rerun()

        elif combinacao in COMBINACOES_COM_PLANILHA and st.session_state.funil_aba is None:
            alvo_pendente = True
            # Defesa em profundidade: mesmo com limpar_alvo() nos dois botões de troca, um alvo
            # incompatível chegando aqui não pode derrubar a página. Antes, qualquer arquivo
            # ilegível estourava a exceção do openpyxl na tela cheia, com traceback.
            arquivo_alvo = st.session_state.funil_arquivo
            if not arquivo_alvo.lower().endswith(EXTENSAO_PLANILHA):
                st.warning(f"'{arquivo_alvo}' não é uma planilha Excel. Escolha uma planilha.")
                limpar_alvo()
                st.stop()
            try:
                abas = listar_abas_planilha(arquivo_alvo)
            except Exception:
                st.error(f"Não consegui abrir '{arquivo_alvo}' — o arquivo pode estar corrompido "
                         f"ou não ser um .xlsx válido. Escolha outra planilha.")
                limpar_alvo()
                st.stop()
            st.caption(f"Planilha: **{st.session_state.funil_arquivo}** ({len(abas)} abas)")
            aba = st.selectbox("Qual aba?", abas, index=None,
                               placeholder="Escolha uma aba...", key="escolha_aba")
            if aba:
                st.session_state.funil_aba = aba
                st.rerun()

        elif combinacao == COMBINACAO_COM_PASTA and st.session_state.funil_pasta is None:
            alvo_pendente = True
            with st.spinner("Varrendo as pastas catalogadas..."):
                garantir_catalogo(carregar_pastas_catalogadas())
                pastas_disponiveis = listar_pastas_disponiveis()
            if not pastas_disponiveis:
                st.warning("Nenhuma pasta catalogada. Adicione uma na barra lateral.")
            else:
                pasta = st.selectbox("Qual pasta?", pastas_disponiveis, index=None,
                                     placeholder="Escolha uma pasta...", key="escolha_pasta")
                if pasta:
                    # Escolher a pasta JÁ é o pedido inteiro — não há nada a perguntar depois,
                    # então a resposta sai na hora e esta combinação não tem chat (decisão de UX
                    # que o item 12 deixou em aberto). Chama a função direto, sem passar pelo
                    # roteador: o catálogo acabou de ser varrido acima, e o roteador varreria de
                    # novo a cada rerun do Streamlit.
                    st.session_state.funil_pasta = pasta
                    st.session_state.mensagens.append(
                        {"papel": "user", "texto": f"Listar o conteúdo de {pasta}"}
                    )
                    diretos = arquivos_diretos_de(pasta)
                    if not diretos:
                        texto_resultado = (
                            f"Nenhum arquivo encontrado diretamente em '{pasta}' (o catalogador "
                            f"não lista subpastas separadamente, só os arquivos)."
                        )
                        st.session_state.mensagens.append({"papel": "assistant", "texto": texto_resultado})
                    else:
                        arquivos_formatados = [
                            {"nome": r["nome"], "caminho": r["caminho"],
                             "legenda": f"{r['nome']} ({r['tamanho_bytes']} bytes)"}
                            for r in diretos
                        ]
                        st.session_state.mensagens.append({
                            "papel": "assistant", "texto": f"{len(diretos)} arquivo(s) em '{pasta}':",
                            "arquivos": arquivos_formatados,
                        })
                    st.rerun()

        if alvo_pendente:
            st.stop()  # não mostra o chat enquanto o alvo não estiver escolhido

        # Alvo escolhido: mostra qual é, e deixa trocar sem perder a combinação
        alvo_atual = st.session_state.funil_arquivo or st.session_state.funil_pasta
        if alvo_atual:
            rotulo_alvo = alvo_atual
            if st.session_state.funil_aba:
                rotulo_alvo += f" — aba \"{st.session_state.funil_aba}\""
            # Resumo (item 1 da UI de Consultar+Documento, PENDENCIAS.md) mora na mesma linha do
            # card/Trocar, não como botão grande abaixo — deixa espaço pra caixa de termo (item 6,
            # ainda não feita) sem empilhar botão sobre botão e poluir o topo do chat.
            mostrar_botao_resumo = (categoria, formato) == ("consultar", "documento")
            if mostrar_botao_resumo:
                coluna_alvo, coluna_resumo, coluna_troca = st.columns([4, 1, 1])
            else:
                coluna_alvo, coluna_troca = st.columns([4, 1])
            coluna_alvo.info(f"📄 {rotulo_alvo}")

            def trocar_alvo():
                limpar_alvo()
                limpar_conversa()

            coluna_troca.button("Trocar", key="botao_trocar_alvo", on_click=trocar_alvo)

            # Botão "Resumo": chama resumir_arquivo() direto, sem LLM decidindo se é isso que o
            # usuário quer — mesmo princípio do atalho de "programas" abaixo (zero interpretação
            # pra ação mecânica). st.rerun() no fim, SEM renderizar a mensagem manualmente aqui:
            # achado real (2026-08-25, teste do usuário) — renderizar na hora E deixar o loop de
            # baixo desenhar de novo a partir de st.session_state.mensagens duplicava a resposta
            # inteira na tela. A barra de progresso ainda aparece ao vivo (roda antes do rerun,
            # dentro do bloco síncrono), só a mensagem final não é escrita duas vezes.
            if mostrar_botao_resumo and coluna_resumo.button("Resumo", key="botao_resumo_documento"):
                pedido_resumo = f"Resumo de {st.session_state.funil_arquivo}"
                st.session_state.mensagens.append({"papel": "user", "texto": pedido_resumo})
                with st.chat_message("assistant"):
                    caixa_progresso = st.empty()

                    def atualizar_progresso_resumo(texto: str, fracao: float):
                        caixa_progresso.progress(min(max(fracao, 0.0), 1.0), text=texto)

                    with st.spinner("Resumindo..."):
                        resposta_resumo = resumir_arquivo(
                            st.session_state.funil_arquivo, colecao, atualizar_progresso_resumo
                        )
                st.session_state.mensagens.append({"papel": "assistant", "texto": resposta_resumo})
                st.rerun()

            # Caixa de termo + botão "Procurar" (item 6, PENDENCIAS.md 2026-08-25): mecânico,
            # sem LLM decidindo se é isso que o usuário quer — chama contar_termo_por_pagina()
            # direto, mesmo princípio do botão Resumo acima.
            if mostrar_botao_resumo:
                coluna_termo, coluna_procurar = st.columns([4, 1])
                termo_busca = coluna_termo.text_input(
                    "Buscar termo/frase no documento", key="input_termo_busca",
                    placeholder="Buscar termo/frase no documento (ex: Uauá)",
                    label_visibility="collapsed",
                )
                if coluna_procurar.button("Procurar", key="botao_procurar_termo") and termo_busca.strip():
                    pedido_busca = f"Quantas vezes \"{termo_busca}\" aparece, e em quais páginas?"
                    st.session_state.mensagens.append({"papel": "user", "texto": pedido_busca})
                    with st.spinner("Procurando..."):
                        resposta_busca = contar_termo_por_pagina(
                            st.session_state.funil_arquivo, termo_busca, colecao
                        )
                    st.session_state.mensagens.append({"papel": "assistant", "texto": resposta_busca})
                    st.rerun()

        st.caption(AJUDA_ETAPA3.get((categoria, formato), ""))

        # Atalho mecânico (zero LLM) pra fonte pequena e fechada: "me mostre tudo" não é uma
        # pergunta que precise ser interpretada. Sem isso, listar os programas passava por
        # extrair_especificacao_consulta sem necessidade — mais lento e com chance de erro.
        if (categoria, formato) == ("consultar", "programas"):
            if st.button("Listar todos os programas instalados", key="botao_listar_programas"):
                st.session_state.mensagens.append(
                    {"papel": "user", "texto": "Listar todos os programas instalados"}
                )
                st.session_state.mensagens.append(
                    {"papel": "assistant", "texto": listar_todos_programas()}
                )
                # De propósito NÃO entra em st.session_state.historico: é uma listagem longa e
                # mecânica, que só inflaria o contexto da reformulação de pergunta seguinte.
                st.rerun()

        # Mesmo princípio do atalho de "programas" acima: indexar não é uma pergunta, é ação
        # mecânica. Sem este botão não havia NENHUM jeito de indexar histórico pela interface —
        # só rodando `python indexar_historico.py` direto no terminal.
        if (categoria, formato) == ("consultar", "historico"):
            if st.button("🔄 Indexar histórico agora", key="botao_indexar_historico"):
                with st.spinner("Copiando e indexando histórico do navegador..."):
                    resultado_indexacao = indexar_historico()
                st.success(resultado_indexacao)

        for indice, mensagem in enumerate(st.session_state.mensagens):
            with st.chat_message(mensagem["papel"]):
                st.write(mensagem["texto"])
                if mensagem.get("arquivos"):
                    renderizar_lista_arquivos(indice, mensagem["arquivos"])
                if mensagem.get("arquivo_gerado"):
                    renderizar_arquivo_gerado(indice, mensagem["arquivo_gerado"])
                # Confirmação de transcrição inteira: botão em vez de a IA assumir sozinha
                # (Princípio #2 — escolha entre opções conhecidas é da interface). Só o último
                # pedido pendente mostra o botão; confirmações antigas viram histórico morto.
                if mensagem.get("confirmar_transcricao") and st.session_state.transcricao_a_confirmar:
                    if st.button("Transcrever documento inteiro", key=f"confirmar_transcricao_{indice}"):
                        arquivo_confirmado = st.session_state.transcricao_a_confirmar
                        st.session_state.transcricao_a_confirmar = None
                        recorte_vazio = {"PAGINA_INICIO": None, "PAGINA_FIM": None, "TERMO": None}
                        with st.spinner("Transcrevendo..."):
                            texto_resposta, caminho_gerado = transcrever_documento_estruturado(
                                arquivo_confirmado, recorte_vazio, colecao
                            )
                        st.session_state.mensagens.append({
                            "papel": "assistant", "texto": texto_resposta,
                            "arquivo_gerado": caminho_gerado,
                        })
                        st.rerun()

        # "Procurar + Por pasta" não tem chat: escolher a pasta no dropdown já é o pedido
        # completo, e a resposta apareceu acima. Um campo de texto aqui ficaria inerte.
        if combinacao == COMBINACAO_COM_PASTA:
            st.stop()

        pergunta = st.chat_input("Digite sua pergunta...")

        if pergunta:
            st.session_state.mensagens.append({"papel": "user", "texto": pergunta})

            # "Procurar + Por nome de arquivo" tem tratamento à parte (não passa por
            # processar_mensagem_guiada): resultado vira lista de botão de verdade (abrir/
            # indexar), não texto — precisa do índice da mensagem pra montar a chave dos
            # widgets, então guarda estruturado e deixa o loop de cima (redesenhado após o
            # rerun) desenhar, em vez de desenhar manualmente aqui também.
            if (categoria, formato) == ("procurar", "arquivo"):
                with st.spinner("Procurando..."):
                    termo, resultados = localizar_arquivo_estruturado(pergunta)
                if not resultados:
                    st.session_state.mensagens.append(
                        {"papel": "assistant", "texto": f"Nenhum arquivo encontrado com '{termo}' no nome."}
                    )
                else:
                    arquivos_formatados = [
                        {"nome": r["nome"], "caminho": r["caminho"], "legenda": f"{r['nome']} → {r['caminho']}"}
                        for r in resultados
                    ]
                    st.session_state.mensagens.append({
                        "papel": "assistant", "texto": f"Encontrei {len(resultados)} arquivo(s) com '{termo}' no nome:",
                        "arquivos": arquivos_formatados,
                    })
                # De propósito NÃO entra em st.session_state.historico: mesmo motivo do atalho
                # de "programas" acima — listagem mecânica, não precisa alimentar o contexto da
                # reformulação de pergunta seguinte.
                st.rerun()

            # "Criar + Documento" (transcrição) também sai do fluxo genérico: precisa olhar o
            # RECORTE pedido antes de transcrever. Achado real (2026-08-29): pedido que o
            # extrator não entende (ex: "o primeiro capítulo") vira recorte vazio, e recorte
            # vazio significa "documento inteiro" — o pedido menos compreendido virava a maior
            # ação possível, calado (139.554 caracteres, sem aviso). Agora confirma antes.
            if (categoria, formato) == ("criar", "documento") and st.session_state.funil_arquivo:
                with st.spinner("Entendendo o pedido..."):
                    recorte = extrair_recorte_transcricao(pergunta)
                if recorte_pede_documento_inteiro(recorte):
                    st.session_state.transcricao_a_confirmar = st.session_state.funil_arquivo
                    tamanho = tamanho_aproximado_documento(st.session_state.funil_arquivo, colecao)
                    medida = f" (~{tamanho:,} caracteres)".replace(",", ".") if tamanho else ""
                    st.session_state.mensagens.append({
                        "papel": "assistant",
                        "texto": (
                            f"Não identifiquei no seu pedido um intervalo de páginas nem um "
                            f"trecho específico — só sei recortar por página (ex: \"as 10 "
                            f"primeiras páginas\") ou por um termo que apareça no texto (ex: "
                            f"\"a parte sobre saúde\"). Posso transcrever o documento "
                            f"inteiro{medida}?"
                        ),
                        "confirmar_transcricao": True,
                    })
                else:
                    with st.spinner("Transcrevendo..."):
                        texto_resposta, caminho_gerado = transcrever_documento_estruturado(
                            st.session_state.funil_arquivo, recorte, colecao
                        )
                    st.session_state.mensagens.append({
                        "papel": "assistant", "texto": texto_resposta,
                        "arquivo_gerado": caminho_gerado,
                    })
                st.rerun()

            with st.chat_message("user"):
                st.write(pergunta)

            with st.chat_message("assistant"):
                # A barra só aparece se o callback for chamado de fato (hoje, só no resumo —
                # única operação com progresso incremental real, bloco a bloco do map-reduce).
                # Nas outras rotas o espaço fica vazio e vale o spinner indeterminado.
                caixa_progresso = st.empty()

                def atualizar_progresso(texto: str, fracao: float):
                    caixa_progresso.progress(min(max(fracao, 0.0), 1.0), text=texto)

                with st.spinner("Pensando..."):
                    # O alvo já resolvido vai junto: com ele preenchido, o roteador pula os
                    # extratores de nome inteiramente (item 12) — a mensagem só precisa conter
                    # o pedido de conteúdo.
                    resposta = processar_mensagem_guiada(
                        pergunta, categoria, formato, st.session_state.historico, colecao,
                        atualizar_progresso,
                        arquivo_selecionado=st.session_state.funil_arquivo,
                        aba_selecionada=st.session_state.funil_aba,
                        pasta_selecionada=st.session_state.funil_pasta,
                    )
                caixa_progresso.empty()
                st.write(resposta)

            st.session_state.mensagens.append({"papel": "assistant", "texto": resposta})
            # A transcrição visível (acima) guarda a resposta inteira; a memória de conversa
            # guarda uma versão condensada quando a resposta é longa — senão poucas listagens
            # já estouram o contexto do modelo (ver condensar_para_historico).
            st.session_state.historico.append(
                {"pergunta": pergunta, "resposta": condensar_para_historico(resposta)}
            )
            if len(st.session_state.historico) > TAMANHO_HISTORICO:
                st.session_state.historico.pop(0)
