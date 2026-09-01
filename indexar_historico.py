import sqlite3
import shutil
import hashlib
from datetime import datetime, timedelta
import chromadb
from config import CAMINHO_HISTORICO_BRAVE, PASTA_BANCO_VETORIAL, MODELO_EMBEDDING, TAMANHO_LOTE_EMBEDDING, IDENTIFICADOR_MAQUINA
import requests

CAMINHO_HISTORICO_COPIA = "historico_temp.db"
LIMITE_ENTRADAS = 4000

def copiar_historico():
    shutil.copy2(CAMINHO_HISTORICO_BRAVE, CAMINHO_HISTORICO_COPIA)

def converter_timestamp_chrome(timestamp_chrome: int) -> str:
    if timestamp_chrome == 0:
        return "Data desconhecida"
    data = datetime(1601, 1, 1) + timedelta(microseconds=timestamp_chrome)
    return data.strftime("%d/%m/%Y %H:%M:%S")

def ler_historico(limite: int):
    conexao = sqlite3.connect(CAMINHO_HISTORICO_COPIA)
    cursor = conexao.cursor()
    cursor.execute("""
        SELECT title, url, last_visit_time
        FROM urls
        ORDER BY last_visit_time DESC
        LIMIT ?
    """, (limite,))
    resultados = cursor.fetchall()
    conexao.close()
    return resultados

def montar_texto_entrada(titulo: str, url: str, data_visita: str) -> str:
    titulo = titulo or "(sem título)"
    return f"Visitou '{titulo}' ({url}) em {data_visita}"

def gerar_embeddings_em_lote(textos: list[str]) -> list[list[float]]:
    resposta = requests.post(
        "http://localhost:11434/api/embed",
        json={"model": MODELO_EMBEDDING, "input": textos}
    )
    resposta.raise_for_status()
    return resposta.json()["embeddings"]

def filtrar_entradas_novas(ids: list[str], colecao) -> set[str]:
    existentes = colecao.get(ids=ids, include=[])
    return set(existentes["ids"])

def indexar_historico() -> str:
    """Copia o histórico do Brave e indexa as entradas novas no ChromaDB — mesma lógica do
    script standalone, exposta como função pra a interface (botão) também poder chamar, não só
    o `python indexar_historico.py` direto. Retorna uma mensagem de status (nunca lança exceção
    pros dois jeitos de falhar que dependem de algo fora do controle do código: navegador não
    encontrado e Ollama fora do ar)."""
    try:
        copiar_historico()
    except OSError as erro:
        return (f"Não consegui ler o histórico do navegador em '{CAMINHO_HISTORICO_BRAVE}': {erro}. "
                f"Confira se o caminho em config.py (CAMINHO_HISTORICO_BRAVE) aponta pro navegador "
                f"certo — testado com o Brave aberto, não precisa fechar ele antes.")

    cliente = chromadb.PersistentClient(path=PASTA_BANCO_VETORIAL)
    colecao = cliente.get_or_create_collection(name="documentos_pessoais")

    entradas = ler_historico(LIMITE_ENTRADAS)

    textos, ids, metadatas = [], [], []
    for titulo, url, timestamp in entradas:
        data_visita = converter_timestamp_chrome(timestamp)
        textos.append(montar_texto_entrada(titulo, url, data_visita))
        ids.append(hashlib.md5(f"{url}_{timestamp}".encode()).hexdigest())
        metadatas.append({
            "fonte": "historico_navegacao",
            "titulo": titulo or "(sem título)",
            "url": url,
            "data_visita": data_visita,
            "timestamp_chrome": timestamp,
            "origem": IDENTIFICADOR_MAQUINA
        })

    ids_existentes = filtrar_entradas_novas(ids, colecao)
    textos_novos, ids_novos, metadatas_novas = [], [], []
    for texto, id_unico, metadata in zip(textos, ids, metadatas):
        if id_unico not in ids_existentes:
            textos_novos.append(texto)
            ids_novos.append(id_unico)
            metadatas_novas.append(metadata)

    if not ids_novos:
        return f"Histórico já estava em dia — nenhuma entrada nova (total no banco: {colecao.count()})."

    try:
        for inicio in range(0, len(textos_novos), TAMANHO_LOTE_EMBEDDING):
            lote_textos = textos_novos[inicio:inicio + TAMANHO_LOTE_EMBEDDING]
            lote_ids = ids_novos[inicio:inicio + TAMANHO_LOTE_EMBEDDING]
            lote_metadatas = metadatas_novas[inicio:inicio + TAMANHO_LOTE_EMBEDDING]
            embeddings = gerar_embeddings_em_lote(lote_textos)
            colecao.add(ids=lote_ids, embeddings=embeddings, documents=lote_textos, metadatas=lote_metadatas)
    except requests.exceptions.RequestException as erro:
        return (f"Parei no meio da indexação — não consegui falar com o Ollama ({erro}). "
                f"Confira se ele está rodando. O que já foi processado ficou salvo.")

    return (f"Histórico indexado: {len(ids_novos)} entrada(s) nova(s) "
            f"({len(ids) - len(ids_novos)} já estavam indexadas). Total no banco: {colecao.count()}.")

if __name__ == "__main__":
    print(indexar_historico())
