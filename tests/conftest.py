import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import chromadb
from config import PASTA_BANCO_VETORIAL


@pytest.fixture(scope="session")
def colecao():
    """Coleção de produção (documentos_pessoais) — só usada pelos testes `slow`
    que precisam de documento real já indexado (Os Sertões, livro amarelo, datasheet)."""
    cliente = chromadb.PersistentClient(path=PASTA_BANCO_VETORIAL)
    return cliente.get_or_create_collection(name="documentos_pessoais")
