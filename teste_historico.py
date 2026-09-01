import sqlite3
import shutil
from config import CAMINHO_HISTORICO_BRAVE
from datetime import datetime, timedelta

CAMINHO_HISTORICO_COPIA = "historico_temp.db"
def converter_timestamp_chrome(timestamp_chrome: int) -> str:
    if timestamp_chrome == 0:
        return "Data desconhecida"
    data = datetime(1601, 1, 1) + timedelta(microseconds=timestamp_chrome)
    return data.strftime("%d/%m/%Y %H:%M:%S")

def copiar_historico():
    shutil.copy2(CAMINHO_HISTORICO_BRAVE, CAMINHO_HISTORICO_COPIA)

def ler_historico(limite: int = 10):
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

if __name__ == "__main__":
    print(f"Copiando de: {CAMINHO_HISTORICO_BRAVE}")
    copiar_historico()
    print("Cópia feita. Lendo histórico...\n")

    entradas = ler_historico(limite=10)
    for titulo, url, timestamp in entradas:
        print(f"Título: {titulo}")
        print(f"URL: {url}")
        print(f"Data da visita: {converter_timestamp_chrome(timestamp)}")
        print("---")