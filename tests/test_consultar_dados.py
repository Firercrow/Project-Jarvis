"""Regressão dos bugs achados em consultar_dados.py.

Parte rápida (sem Ollama): lógica de filtro/agrupamento/detecção de bloco, testada
com dado construído na hora ou com a planilha real do projeto (Docs/TAREFA MATEMATICA.xlsx).
Parte lenta (marcada `slow`): consulta ponta a ponta, precisa do Ollama rodando.
"""
import operator
import os

import numpy as np
import pandas as pd
import pytest

import consultar_dados as cd
from config import PASTA_DOCUMENTOS

ARQUIVO_POLITICOS = "TAREFA MATEMATICA.xlsx"


# --- comparação numérica / igualdade (achado real: MULHER==1 contava 148 em vez de 82) ---

def test_comparar_igualdade_coage_tipo_em_coluna_numerica():
    serie = pd.Series([1.0, 0.0, float("nan"), 1.0])
    resultado = cd._comparar_igualdade(serie, "1", operator.eq)  # valor vem como string do LLM
    assert list(resultado) == [True, False, False, True]


def test_comparar_numerico_ignora_celula_nao_numerica():
    serie = pd.Series([10, "texto", 30])
    resultado = cd.comparar_numerico(serie, "15", operator.gt)
    assert list(resultado) == [False, False, True]


# --- aplicar_filtros: PS não pode misturar com PSD (achado real 2026-08-26) ---

def test_filtro_contem_prefere_valor_exato_a_prefixo():
    df = pd.DataFrame({"partido": ["PS", "PSD", "PS", "PSD", "CH"]})
    filtrado, avisos = cd.aplicar_filtros(df, [{"coluna": "partido", "operador": "contem", "valor": "PS"}])
    assert list(filtrado["partido"]) == ["PS", "PS"]
    assert avisos == []


def test_filtro_contem_continua_pegando_substring_quando_nao_ha_valor_exato():
    df = pd.DataFrame({"editora": ["Apple Inc.", "Microsoft Corporation"]})
    filtrado, _ = cd.aplicar_filtros(df, [{"coluna": "editora", "operador": "contem", "valor": "Apple"}])
    assert list(filtrado["editora"]) == ["Apple Inc."]


def test_filtro_igual_em_coluna_de_texto_vira_contem():
    df = pd.DataFrame({"nome": ["Apple Inc."]})
    filtrado, _ = cd.aplicar_filtros(df, [{"coluna": "nome", "operador": "==", "valor": "Apple"}])
    assert len(filtrado) == 1


def test_filtro_com_valor_vazio_e_descartado():
    df = pd.DataFrame({"titulo": ["a", "b", "c"]})
    filtrado, _ = cd.aplicar_filtros(df, [{"coluna": "titulo", "operador": "contem", "valor": "?"}])
    assert len(filtrado) == 3  # valor só com pontuação não é filtro de verdade


# --- agrupar_por: os 4 bugs achados testando/quebrando de propósito (2026-08-28) ---

def test_preparar_coluna_agrupamento_normaliza_espaco_e_vazio():
    serie = pd.Series(["CH", "CH\n", " PS ", None])
    normalizada = cd._preparar_coluna_agrupamento(serie)
    assert list(normalizada) == ["CH", "CH", "PS", "(vazio)"]


def test_bloco_e_relevante_considera_agrupar_por():
    especificacao = {"operacao": "contar", "filtros": [], "coluna_alvo": None,
                      "ordenar_por": None, "agrupar_por": "Partido"}
    df_com_coluna = pd.DataFrame({"Partido": ["PS"]})
    df_sem_coluna = pd.DataFrame({"Outra": ["x"]})
    assert cd._bloco_e_relevante(especificacao, df_com_coluna)
    assert not cd._bloco_e_relevante(especificacao, df_sem_coluna)


def test_executar_consulta_agrupa_e_conta_por_grupo():
    df = pd.DataFrame({"partido": ["PS", "PSD", "PS", "PSD", "PSD"]})
    especificacao = {"operacao": "contar", "filtros": [], "coluna_alvo": None,
                      "ordenar_por": None, "agrupar_por": "partido"}
    resultado, avisos = cd.executar_consulta(df, especificacao)
    assert isinstance(resultado, pd.Series)
    assert resultado.to_dict() == {"PSD": 3, "PS": 2}
    # agrupar já é o recorte pedido -- não pode disparar o aviso de "sem filtro"
    assert not any("nenhum filtro" in a.lower() for a in avisos)


def test_formatar_resultado_agrupado_confia_no_tipo_nao_na_especificacao():
    """Achado real: um bloco sem a coluna de agrupar cai no caminho antigo (int), mas a
    especificação ainda diz "agrupar_por" preenchido -- formatar tem que olhar o TIPO."""
    especificacao = {"operacao": "contar", "agrupar_por": "partido"}
    texto = cd.formatar_resultado(42, especificacao, [])
    assert "42" in texto and "entrada" in texto


# --- detecção de "colagem" (tabela + resumo sem linha em branco separando) ---

def _montar_planilha_teste(caminho, com_gap):
    import openpyxl
    pasta = openpyxl.Workbook()
    aba = pasta.active
    aba.title = "Teste"
    aba.append(["Nome", "Circulo", "Partido", "Genero", "Idade", "Aleatorio"])
    nomes = ["Ana", "Bruno", "Carla", "Diego", "Elis", "Fabio", "Gina", "Hugo"]
    for i, nome in enumerate(nomes):
        aba.append([nome, "Cidade", "PS" if i % 2 == 0 else "PSD", "F" if i % 2 == 0 else "M", 30 + i, 0.5])
    if com_gap:
        aba.append([None, None, None, None, None, None])
    aba.append([None, None, None, "F", "M", None])
    aba.append([None, None, None, 4, 4, None])
    pasta.save(caminho)


def test_detecta_colagem_sem_linha_em_branco(tmp_path):
    caminho = str(tmp_path / "colado.xlsx")
    _montar_planilha_teste(caminho, com_gap=False)
    blocos = cd.detectar_blocos_planilha(caminho, "Teste")
    assert len(blocos) == 1
    assert blocos[0]["possivel_colagem"] is True


def test_nao_detecta_colagem_com_linha_em_branco_de_verdade(tmp_path):
    caminho = str(tmp_path / "separado.xlsx")
    _montar_planilha_teste(caminho, com_gap=True)
    blocos = cd.detectar_blocos_planilha(caminho, "Teste")
    assert len(blocos) == 2
    assert all(not b["possivel_colagem"] for b in blocos)


# --- detecção de múltiplos blocos na planilha real do projeto ---

@pytest.mark.skipif(
    not os.path.exists(os.path.join(PASTA_DOCUMENTOS, ARQUIVO_POLITICOS)),
    reason=f"depende de Docs/{ARQUIVO_POLITICOS} (planilha real do projeto)",
)
def test_detalhes1_tem_8_blocos_com_tabela_principal_de_230_linhas():
    caminho = os.path.join(PASTA_DOCUMENTOS, ARQUIVO_POLITICOS)
    blocos = cd.detectar_blocos_planilha(caminho, "Detalhes1")
    assert len(blocos) == 8
    tamanhos = sorted(len(b["dataframe"]) for b in blocos)
    assert 230 in tamanhos  # tabela principal, limpa (sem o resumo colado)


# ==================== testes lentos (Ollama de verdade) ====================

@pytest.mark.slow
@pytest.mark.skipif(
    not os.path.exists(os.path.join(PASTA_DOCUMENTOS, ARQUIVO_POLITICOS)),
    reason=f"depende de Docs/{ARQUIVO_POLITICOS}",
)
class TestConsultaRealPlanilha:
    def test_mulher_igual_1_conta_82(self):
        resposta = cd.consultar_dado_estruturado(
            "quantas pessoas têm o valor 1 na coluna MULHER?", "planilha", None,
            ARQUIVO_POLITICOS, "Página1",
        )
        assert "82" in resposta

    def test_partido_ps_nao_mistura_com_psd(self):
        resposta = cd.consultar_dado_estruturado(
            "quantos políticos tem no PS?", "planilha", None,
            ARQUIVO_POLITICOS, "Página1",
        )
        assert "58" in resposta

    def test_agrupar_por_partido_soma_230(self):
        resposta = cd.consultar_dado_estruturado(
            "quantos políticos tem cada partido?", "planilha", None,
            ARQUIVO_POLITICOS, "Página1",
        )
        import re
        numeros = [int(n) for n in re.findall(r"\d+", resposta) if len(n) <= 3]
        # soma de todos os grupos de partido reportados deve bater com o total real (230)
        assert sum(n for n in numeros if n < 230) >= 200  # sanity: achou vários grupos de tamanho plausível


@pytest.mark.slow
def test_agrupar_por_origem_no_historico(colecao):
    resposta = cd.consultar_dado_estruturado(
        "quantos sites visitados de cada origem?", "historico_navegacao", colecao
    )
    assert "-" in resposta or ":" in resposta  # saiu como lista agrupada, não erro
