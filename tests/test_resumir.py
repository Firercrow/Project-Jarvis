"""Checagem de mitigação de alucinação no resumo de documento (2026-08-27/28) -- LENTO
(~4-5min por rodada, chama o Ollama 25 vezes: 21 blocos + 3 grupos + 1 síntese final).

A bateria completa de 6 rodadas (0/6 reproduziu "Lula Máreo") já foi feita manualmente e está
documentada no PENDENCIAS.md -- aqui roda só 1 rodada, como regressão de "ainda não voltou a
alucinar E ainda não travou", não uma reprova estatística completa."""
import os
import re

import pytest

from config import PASTA_DOCUMENTOS
import resumir

pytestmark = pytest.mark.slow

PADRAO_ALUCINACAO_CONHECIDA = re.compile(r"lula\s*m[aá]reo", re.IGNORECASE)


@pytest.mark.skipif(
    not os.path.exists(os.path.join(PASTA_DOCUMENTOS, "livro-amarelo-resumo-2026.pdf")),
    reason="falta Docs/livro-amarelo-resumo-2026.pdf",
)
def test_resumo_livro_amarelo_nao_reproduz_alucinacao_conhecida(colecao):
    resumo = resumir.resumir_arquivo("livro-amarelo-resumo-2026.pdf", colecao)
    assert not PADRAO_ALUCINACAO_CONHECIDA.search(resumo)
    assert len(resumo) > 500  # não travou/devolveu recusa vazia
