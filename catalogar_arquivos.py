import os
import json
import sqlite3
from datetime import datetime

from config import PASTAS_CATALOGADAS
from texto import normalizar_nome, normalizar_pedido

BANCO_CATALOGO = "catalogo_arquivos.db"
ARQUIVO_PASTAS_CATALOGADAS = "pastas_catalogadas.json"

# Pastas que a varredura nunca entra. São nomes UNIVERSAIS de propósito (decisão do usuário,
# 2026-08-22): "__pycache__" se chama assim em qualquer PC, enquanto uma exceção por caminho
# absoluto (D:\jarvis-pessoal\venv) deixaria de valer no dia em que o projeto mudar de lugar ou
# for para outra máquina.
#
# Motivo: ao catalogar um disco inteiro, o catálogo foi para 152.012 arquivos, sendo ~20.000 de
# bibliotecas Python (site-packages) e 8.201 de __pycache__ — arquivos que ninguém procura, mas
# que competiam nas buscas por nome e faziam a revarredura (que roda a cada busca) levar 9,8s.
PASTAS_IGNORADAS = {
    "__pycache__", "node_modules", ".git", ".svn", ".hg",
    "venv", ".venv", "env", ".env", "site-packages", "dist-info",
    ".cache", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox",
    "system volume information", ".idea", ".vs", ".vscode",
    # Achado real, 2026-08-26: buscar "xlsx"/"docx" trazia de volta os .txt salvos aqui (nome do
    # arquivo original + "_transcricao_data" no nome, então contém a extensão como substring),
    # misturado com os arquivos de verdade — arquivo gerado/derivado não é o que o usuário
    # procura quando busca pelo nome de um documento. Mesmo padrão dos outros: nome universal do
    # projeto (`jarvis.py: PASTA_TRANSCRICOES`), nunca caminho absoluto.
    "transcricoes",
}

def deve_ignorar_pasta(nome: str) -> bool:
    """Nomes de pasta que não entram no catálogo. O prefixo '$' cobre as pastas de sistema do
    Windows ($RECYCLE.BIN, $WinREAgent, $SysReset), que variam de nome mas seguem esse padrão."""
    return nome.startswith("$") or nome.lower() in PASTAS_IGNORADAS

def carregar_pastas_catalogadas() -> list[str]:
    if os.path.exists(ARQUIVO_PASTAS_CATALOGADAS):
        with open(ARQUIVO_PASTAS_CATALOGADAS, "r", encoding="utf-8") as f:
            return json.load(f)
    return PASTAS_CATALOGADAS

def salvar_pastas_catalogadas(pastas: list[str]):
    with open(ARQUIVO_PASTAS_CATALOGADAS, "w", encoding="utf-8") as f:
        json.dump(pastas, f, ensure_ascii=False, indent=2)

def garantir_catalogo(pastas: list[str]):
    if not os.path.exists(BANCO_CATALOGO):
        criar_banco()

    for pasta in pastas:
        catalogar_pasta(pasta)

def localizar_arquivo(termo: str) -> str:
    """Versão em texto puro (terminal, `processar_mensagem()`). A interface Streamlit usa
    `buscar_arquivo()` direto (ver `jarvis.py: localizar_arquivo_estruturado()`) pra desenhar os
    resultados como botão de verdade em vez de link — link markdown/HTML sempre abre em aba nova
    no Streamlit (achado 2026-08-29, sem jeito de desligar), e forçar a mesma aba reseta a sessão
    inteira (recarga completa da página). Botão de verdade não tem esse problema."""
    resultados = buscar_arquivo(termo)
    if not resultados:
        return f"Nenhum arquivo encontrado com '{termo}' no nome."

    linhas = [f"Encontrei {len(resultados)} arquivo(s) com '{termo}' no nome:"]
    for r in resultados:
        linhas.append(f"  - {r['nome']} → {r['caminho']}")
    return "\n".join(linhas)

def criar_banco():
    conexao = sqlite3.connect(BANCO_CATALOGO)
    cursor = conexao.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS arquivos (
            caminho TEXT PRIMARY KEY,
            nome TEXT,
            nome_normalizado TEXT,
            extensao TEXT,
            tamanho_bytes INTEGER,
            modificado_em TEXT
        )
    """)
    conexao.commit()
    conexao.close()

def _caminho_esta_sob_pasta(caminho: str, pasta: str) -> bool:
    """Testa se `caminho` é a própria `pasta` ou está dentro dela (subpasta a qualquer
    profundidade) — comparação de string EXATA, nunca `LIKE` com o caminho cru como prefixo.

    Correção 2026-08-25 (achado registrado em `PENDENCIAS.md` desde 2026-08-20): usar
    `caminho LIKE ?` com `f"{pasta}%"` tem dois problemas ao mesmo tempo. Primeiro, `_` é
    curinga-de-1-caractere dentro de `LIKE` no SQLite — catalogar `D:\\Meus_Documentos` casaria
    também com `D:\\MeusXDocumentos`, uma pasta completamente diferente. Segundo, prefixo de
    string sem checar limite de pasta casa `D:\\Desktop` com `D:\\Desktop2` (mesma letra inicial,
    pasta irmã, não subpasta). Isso importa de verdade em `catalogar_pasta()`: o resultado dessa
    comparação decide quais registros são "fantasma" (arquivo sumiu, apagar do catálogo) — um
    falso positivo aqui APAGA do catálogo arquivos de uma pasta que nem foi revarrida.

    Correção 2026-08-26 (achado real: arquivo apagado de verdade do disco dentro da raiz "D:\\"
    continuava aparecendo na busca, a limpeza de fantasma nunca rodava pra nada dentro dessa
    pasta): raiz de disco ("D:\\") já termina com barra — colar `+ os.sep` em cima virava barra
    DUPLA ("D:\\\\"), que nenhum caminho real tem, então a comparação nunca batia pra nada dentro
    da raiz de disco. Tira a barra do fim da pasta ANTES de colar de novo — testado contra raiz de disco,
    pasta normal, barra redundante (uma ou duas) e caminho de rede (UNC): nenhum desses casos tem
    problema, porque barra no FIM de um caminho é sempre redundante (nunca muda qual pasta é)."""
    pasta_normalizada = pasta.rstrip(os.sep)
    return caminho == pasta or caminho.startswith(pasta_normalizada + os.sep)


def catalogar_pasta(caminho_pasta: str) -> int:
    conexao = sqlite3.connect(BANCO_CATALOGO)
    cursor = conexao.cursor()

    caminhos_encontrados = set()
    total = 0
    for raiz, pastas, arquivos in os.walk(caminho_pasta):
        # Poda a árvore ANTES de descer: alterar `pastas` no lugar faz o os.walk pular esses
        # ramos inteiros, em vez de percorrê-los e descartar arquivo por arquivo depois.
        pastas[:] = [p for p in pastas if not deve_ignorar_pasta(p)]
        for nome_arquivo in arquivos:
            caminho_completo = os.path.join(raiz, nome_arquivo)
            try:
                stats = os.stat(caminho_completo)
                cursor.execute("""
                    INSERT OR REPLACE INTO arquivos
                    (caminho, nome, nome_normalizado, extensao, tamanho_bytes, modificado_em)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    caminho_completo,
                    nome_arquivo,
                    normalizar_nome(nome_arquivo),  # nome REAL: só canonicaliza, não tira enfeite
                    os.path.splitext(nome_arquivo)[1].lower(),
                    stats.st_size,
                    datetime.fromtimestamp(stats.st_mtime).strftime("%d/%m/%Y %H:%M:%S")
                ))
                caminhos_encontrados.add(caminho_completo)
                total += 1
            except (PermissionError, FileNotFoundError):
                continue

    # Remove registros dessa pasta que não foram reconfirmados nessa varredura. Filtro em
    # Python (`_caminho_esta_sob_pasta`), não `LIKE` — ver docstring da função pro motivo.
    cursor.execute("SELECT caminho FROM arquivos")
    caminhos_no_banco = {
        row[0] for row in cursor.fetchall() if _caminho_esta_sob_pasta(row[0], caminho_pasta)
    }
    caminhos_fantasmas = caminhos_no_banco - caminhos_encontrados

    for caminho_fantasma in caminhos_fantasmas:
        cursor.execute("DELETE FROM arquivos WHERE caminho = ?", (caminho_fantasma,))

    conexao.commit()
    conexao.close()

    if caminhos_fantasmas:
        print(f"  {len(caminhos_fantasmas)} registro(s) removido(s) (arquivo(s) não encontrado(s) mais).")

    return total

def buscar_arquivo(termo: str) -> list[dict]:
    termo_normalizado = normalizar_pedido(termo)
    conexao = sqlite3.connect(BANCO_CATALOGO)
    conexao.row_factory = sqlite3.Row
    cursor = conexao.cursor()
    cursor.execute("SELECT * FROM arquivos WHERE nome_normalizado LIKE ?", (f"%{termo_normalizado}%",))
    resultados = [dict(row) for row in cursor.fetchall()]
    conexao.close()
    return resultados

def listar_pastas_disponiveis() -> list[str]:
    conexao = sqlite3.connect(BANCO_CATALOGO)
    cursor = conexao.cursor()
    cursor.execute("SELECT DISTINCT caminho FROM arquivos")
    caminhos = [row[0] for row in cursor.fetchall()]
    conexao.close()
    return sorted(set(os.path.dirname(c) for c in caminhos))

def arquivos_diretos_de(pasta_real: str) -> list[dict]:
    """Arquivos diretos (não-recursivo) de uma pasta cujo caminho EXATO já é conhecido — usada
    quando o usuário escolheu a pasta num dropdown (item 12), então não há nome a adivinhar nem
    ambiguidade a resolver. Base de `listar_pasta_por_caminho()` (texto) e da listagem com botão
    de verdade na interface Streamlit (`interface.py: renderizar_lista_arquivos()`)."""
    conexao = sqlite3.connect(BANCO_CATALOGO)
    conexao.row_factory = sqlite3.Row
    cursor = conexao.cursor()
    cursor.execute("SELECT nome, caminho, tamanho_bytes FROM arquivos")
    todos = cursor.fetchall()
    conexao.close()
    return [dict(r) for r in todos if os.path.dirname(r["caminho"]) == pasta_real]

def listar_pasta_por_caminho(pasta_real: str) -> str:
    """Versão em texto puro. A interface Streamlit usa `arquivos_diretos_de()` direto pra
    desenhar botão de verdade em vez de link — ver `localizar_arquivo()` pro motivo."""
    diretos = arquivos_diretos_de(pasta_real)
    if not diretos:
        return f"Nenhum arquivo encontrado diretamente em '{pasta_real}' (o catalogador não lista subpastas separadamente, só os arquivos)."

    linhas = [f"  - {r['nome']} ({r['tamanho_bytes']} bytes)" for r in diretos]
    return f"{len(diretos)} arquivo(s) em '{pasta_real}':\n" + "\n".join(linhas)


def listar_pasta(termo: str) -> str:
    pedido = normalizar_pedido(termo)
    if len(pedido) < 3:
        return f"'{termo}' é um termo de busca curto demais pra identificar a pasta com segurança. Seja mais específico."

    pastas_disponiveis = listar_pastas_disponiveis()
    # Casa só por nome-base: o usuário parte de uma ideia do NOME do arquivo/pasta, não do
    # caminho (se já soubesse o caminho, não precisaria perguntar) — bater em qualquer parte do
    # caminho completo foi tentado e revertido, trazia subpasta como falso positivo (ex:
    # "...\Desktop\Jogos e Games" só por morar dentro de uma pasta chamada Desktop) sem resolver
    # nada de real, porque o cenário que motivava (reperguntar citando um pedaço do caminho) não
    # é como a ferramenta é usada de verdade.
    correspondencias = [
        p for p in pastas_disponiveis
        if pedido in normalizar_nome(os.path.basename(p))
    ]

    if not correspondencias:
        return f"Nenhuma pasta encontrada parecida com '{termo}'. Verifique o nome."
    if len(correspondencias) > 1:
        # Correção 2026-08-26 (achado real): mostrar só o nome-base ("Desktop", "Desktop",
        # "Desktop") não ajuda o usuário a reconhecer visualmente qual pasta é qual quando várias
        # pastas reais têm o MESMO nome (ex: Desktop normal + Desktop de outro programa/pasta) —
        # mostra o caminho completo de cada uma, que é a informação que de fato distingue.
        linhas = "\n".join(f"  - {p}" for p in correspondencias)
        return f"Mais de uma pasta corresponde a '{termo}':\n{linhas}\nVeja qual é a pasta certa pelo caminho acima."

    pasta_real = correspondencias[0]
    conexao = sqlite3.connect(BANCO_CATALOGO)
    conexao.row_factory = sqlite3.Row
    cursor = conexao.cursor()
    # Sem LIKE com caminho cru como prefixo (mesmo motivo de `_caminho_esta_sob_pasta`) — o
    # filtro exato de `os.path.dirname` logo abaixo já era a garantia de verdade; aqui só se
    # deixa de correr o risco de um pré-filtro impreciso, mesmo que hoje ele fosse inofensivo.
    cursor.execute("SELECT nome, caminho, tamanho_bytes FROM arquivos")
    todos = cursor.fetchall()
    conexao.close()

    diretos = [r for r in todos if os.path.dirname(r["caminho"]) == pasta_real]
    if not diretos:
        return f"Nenhum arquivo encontrado diretamente em '{pasta_real}' (o catalogador não lista subpastas separadamente, só os arquivos)."

    linhas = [f"  - {r['nome']} ({r['tamanho_bytes']} bytes)" for r in diretos]
    return f"{len(diretos)} arquivo(s) em '{pasta_real}':\n" + "\n".join(linhas)

if __name__ == "__main__":
    criar_banco()
    pasta = input("Digite o caminho da pasta para catalogar: ")
    total = catalogar_pasta(pasta)
    print(f"\n{total} arquivos catalogados.\n")

    while True:
        termo = input("Buscar arquivo (ou 'sair'): ")
        if termo.lower() == "sair":
            break
        resultados = buscar_arquivo(termo)
        if not resultados:
            print("Nenhum arquivo encontrado.\n")
            continue
        print(f"\n{len(resultados)} resultado(s):")
        for r in resultados:
            print(f"  {r['nome']} — {r['caminho']}")
        print()