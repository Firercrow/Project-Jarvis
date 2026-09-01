"""Bateria de 4 cenários de busca+resposta ponta a ponta, contra os documentos reais do
projeto (Docs/). Precisa do Ollama rodando e dos documentos já indexados. Cada um leva de
~10s a ~1min.

Falta o cenário do Polifemo (Odisseia) dessa bateria: o PDF fonte (`odisseiap.pdf`) só existe
numa coleção de teste temporária fora do projeto (`banco_teste`, pasta de scratchpad da sessão
que fez a calibração) -- não é um arquivo durável de `Docs/`, não dá pra reproduzir aqui sem
adicionar o livro ao projeto de verdade. Ver ARQUITETURA.MD."""
import os

import pytest

from config import PASTA_DOCUMENTOS
import perguntar as pg

pytestmark = pytest.mark.slow


def _arquivo_existe(nome):
    return os.path.exists(os.path.join(PASTA_DOCUMENTOS, nome))


@pytest.mark.skipif(not _arquivo_existe("livro-amarelo-resumo-2026.pdf"), reason="falta Docs/livro-amarelo-resumo-2026.pdf")
def test_mcmv_e_agrobrasil_combinados_nao_contaminam_um_ao_outro(colecao):
    """Achado real 2026-08-26: com âncora de entidade mais precisa, o agrupamento de blocos
    (posição, não conteúdo) fundia o parágrafo certo do MCMV com um capítulo seguinte que
    por coincidência também cita um valor grande em reais."""
    resposta = pg.responder_pergunta(
        "Quanto o Brasil gasta com o Minha Casa Minha Vida e quais são os cinco pilares do AgroBrasil 2030?",
        [], colecao, arquivo_forcado="livro-amarelo-resumo-2026.pdf",
    )
    assert "180 bilh" in resposta.lower() or "180 bilhões" in resposta
    assert "agrobrasil" in resposta.lower()


@pytest.mark.skipif(not _arquivo_existe("livro-amarelo-resumo-2026.pdf"), reason="falta Docs/livro-amarelo-resumo-2026.pdf")
def test_mcmv_sozinho(colecao):
    resposta = pg.responder_pergunta(
        "quanto o Brasil gasta com o Minha Casa Minha Vida", [], colecao,
        arquivo_forcado="livro-amarelo-resumo-2026.pdf",
    )
    assert "180" in resposta


@pytest.mark.skipif(not _arquivo_existe("datasheet cd405.pdf"), reason="falta Docs/datasheet cd405.pdf")
def test_datasheet_tabela_verdade_canal_5(colecao):
    """Achado real 2026-08-25: extração de PDF achatava a tabela-verdade numa sequência linear
    de números -- corrigido extraindo tabela detectada como prosa "Linha N: campo=valor"."""
    resposta = pg.responder_pergunta(
        "no CD4051B, quais os estados de INHIBIT, C, B e A para ativar o canal 5?",
        [], colecao, arquivo_forcado="datasheet cd405.pdf",
    )
    texto = resposta.replace(" ", "")
    assert "INHIBIT=0" in texto or "INHIBIT0" in texto
    assert "C=1" in texto or "C1" in texto


@pytest.mark.skipif(not _arquivo_existe("os_sertoes.pdf"), reason="falta Docs/os_sertoes.pdf")
def test_uaua_primeiro_combate(colecao):
    """Achado real 2026-08-25: hierarquia entidade-primeiro (Uauá) + conteúdo-como-refino
    (combate) por proximidade -- resultado verificado contra o texto fonte."""
    resposta = pg.responder_pergunta(
        "quantos soldados morreram e quantos jagunços morreram no primeiro combate, em Uauá?",
        [], colecao, arquivo_forcado="os_sertoes.pdf",
    )
    assert "150" in resposta
