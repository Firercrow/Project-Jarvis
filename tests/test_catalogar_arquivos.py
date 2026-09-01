"""Regressão dos bugs achados em catalogar_arquivos.py — todos rápidos, sem Ollama."""
import os
import sqlite3

import catalogar_arquivos as ca


# --- _caminho_esta_sob_pasta(): teste direto da função, sem tocar disco ---

def test_raiz_de_disco_sem_barra_dupla():
    """Achado real 2026-08-26: pasta+os.sep numa raiz de disco ("D:\\") virava barra
    dupla ("D:\\\\"), que nenhum caminho real tem — limpeza de fantasma nunca rodava
    pra nada catalogado sob a raiz."""
    assert ca._caminho_esta_sob_pasta(r"D:\pasta\arquivo.txt", "D:\\")
    assert ca._caminho_esta_sob_pasta("D:\\", "D:\\")


def test_pasta_normal_com_barra_redundante_no_fim():
    assert ca._caminho_esta_sob_pasta(
        r"C:\Users\Foda\Desktop\arquivo.txt", r"C:\Users\Foda\Desktop\\"
    )


def test_pasta_nao_confunde_irma_que_e_prefixo():
    """"...\\Desktop" não pode casar com "...\\Desktop2" (pasta irmã, não subpasta)."""
    assert not ca._caminho_esta_sob_pasta(r"D:\Desktop2\arquivo.txt", r"D:\Desktop")
    assert ca._caminho_esta_sob_pasta(r"D:\Desktop\arquivo.txt", r"D:\Desktop")


def test_caminho_de_rede_unc():
    assert ca._caminho_esta_sob_pasta(r"\\servidor\pasta\arquivo.txt", r"\\servidor\pasta\\")


# --- catalogar_pasta(): reproduz o bug do LIKE/coringa de ponta a ponta, banco isolado ---

def test_catalogar_pasta_nao_apaga_irma_por_wildcard_ou_prefixo(tmp_path, monkeypatch):
    """Achado real 2026-08-25: "_" é curinga-de-1-caractere dentro de LIKE no SQLite —
    catalogar "Meus_Documentos" casava com "MeusXDocumentos" (pasta diferente); e
    prefixo de string sem checar limite de pasta casava "Desktop" com "Desktop2"."""
    banco_teste = str(tmp_path / "catalogo_teste.db")
    monkeypatch.setattr(ca, "BANCO_CATALOGO", banco_teste)
    ca.criar_banco()

    raiz = tmp_path / "raiz"
    pasta_alvo = raiz / "Meus_Documentos"
    pasta_irma_wildcard = raiz / "MeusXDocumentos"
    pasta_desktop = raiz / "Desktop"
    pasta_desktop2 = raiz / "Desktop2"
    for p in (pasta_alvo, pasta_irma_wildcard, pasta_desktop, pasta_desktop2):
        p.mkdir(parents=True)
        (p / "arquivo.txt").write_text("x")

    for p in (pasta_alvo, pasta_irma_wildcard, pasta_desktop, pasta_desktop2):
        ca.catalogar_pasta(str(p))

    # revarrer só "Meus_Documentos" não pode apagar arquivos das pastas irmãs
    ca.catalogar_pasta(str(pasta_alvo))

    conexao = sqlite3.connect(banco_teste)
    restante = {row[0] for row in conexao.execute("SELECT caminho FROM arquivos")}
    conexao.close()

    esperado = {
        str(pasta_alvo / "arquivo.txt"),
        str(pasta_irma_wildcard / "arquivo.txt"),
        str(pasta_desktop / "arquivo.txt"),
        str(pasta_desktop2 / "arquivo.txt"),
    }
    assert restante == esperado
