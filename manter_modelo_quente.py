"""Mantém o modelo carregado na VRAM enquanto o Jarvis estiver rodando.

Problema real (achado em 2026-08-29, testando pra demo): o Ollama descarrega um modelo da
VRAM após 5 minutos sem uso (`keep_alive` padrão). Numa apresentação isso é fatal — entre uma
pergunta e outra o apresentador fala vários minutos, e a pergunta seguinte paga o
recarregamento inteiro. Medido: a MESMA pergunta ("poderia me falar sobre bomba atômica?" no
livro amarelo) levou 260s com o modelo frio e 14,5s com ele quente — 18x mais lenta, sem
nenhuma diferença de código ou de pergunta. Nunca apareceu nos testes porque teste roda em
sequência, sem pausa; só o padrão de uso REAL (pausas de conversa) expõe isso.

Por que um batimento periódico, e não `OLLAMA_KEEP_ALIVE=-1` no sistema: a variável de ambiente
é global e permanente — prenderia ~7,6 GB de VRAM o tempo todo, atrapalhando qualquer outro uso
da GPU (jogo, por exemplo). Decisão do usuário (2026-08-29): quer o modelo quente só enquanto
usa o Jarvis. Como o batimento vive dentro do processo do Streamlit, fechar o Jarvis mata o
batimento junto, e o modelo se descarrega sozinho no prazo padrão — sem precisar lembrar de
desativar nada.

Por que isso basta sem mexer nas ~48 chamadas do projeto: `keep_alive` é definido por
requisição, e a ÚLTIMA chamada é que vale — ou seja, ajustar só parte das chamadas não
resolveria (qualquer chamada normal reporia os 5 minutos padrão). O batimento contorna isso por
outro caminho: como ele bate a cada 4 minutos, sempre chega ANTES do prazo de 5 expirar, não
importa o que as outras chamadas tenham pedido.

A requisição de batimento manda `prompt` vazio: nesse formato o Ollama só carrega/segura o
modelo e responde na hora, sem gerar texto nenhum — custo desprezível.

Cada tipo de modelo precisa do SEU endpoint (achado testando, 2026-08-29): modelo de embedding
recusa `/api/generate` com erro 400 ("mxbai-embed-large does not support generate") e só carrega
por `/api/embeddings`. Sem isso o aquecimento parecia funcionar (o principal subia) mas o de
embedding ficava de fora em silêncio — e ele também custa recarregamento na hora da busca.
"""

import threading
import time

import requests

from config import MODELO_LLM, MODELO_EMBEDDING, NUM_CTX

# 4 minutos: precisa ser MENOR que os 5 minutos do padrão do Ollama, com folga pra uma batida
# atrasada (ex: máquina ocupada) não deixar o modelo expirar.
INTERVALO_BATIMENTO_SEGUNDOS = 240

# Modelos que a interface realmente usa numa pergunta, cada um com o endpoint que o carrega:
# o principal responde (`/api/generate`), o de embedding faz a busca (`/api/embeddings`). O
# auxiliar (llama3.2:3b) fica de fora de propósito — só o resumo usa, e mantê-lo carregado junto
# com o principal disputa VRAM sem necessidade (ver nota de VRAM no config.py).
MODELOS_PARA_MANTER = (
    (MODELO_LLM, "generate"),
    (MODELO_EMBEDDING, "embeddings"),
)

TEMPO_LIMITE_REQUISICAO = 300  # o primeiro carregamento pode levar minutos (medido: ~260s)


def aquecer_modelo(nome_modelo: str, tipo: str) -> bool:
    """Carrega/segura um modelo na VRAM. Devolve True se o Ollama respondeu OK.

    Nunca levanta exceção: se o Ollama estiver fora do ar, o Jarvis deve continuar de pé e
    falhar só na hora da pergunta de verdade (com a mensagem de erro que já existe), não quebrar
    a interface inteira por causa do aquecimento."""
    corpo = {"model": nome_modelo, "keep_alive": "10m"}
    if tipo == "generate":
        corpo["options"] = {"num_ctx": NUM_CTX}
    else:
        corpo["prompt"] = ""  # `/api/embeddings` exige o campo, mesmo vazio
    try:
        resposta = requests.post(
            f"http://localhost:11434/api/{tipo}",
            json=corpo,
            timeout=TEMPO_LIMITE_REQUISICAO,
        )
        return resposta.status_code == 200
    except requests.RequestException:
        return False


def _laco_batimento():
    while True:
        for nome_modelo, tipo in MODELOS_PARA_MANTER:
            aquecer_modelo(nome_modelo, tipo)
        time.sleep(INTERVALO_BATIMENTO_SEGUNDOS)


def iniciar_batimento():
    """Sobe a thread de batimento. `daemon=True` faz ela morrer junto com o processo do
    Streamlit — é justamente isso que faz "fechar o Jarvis" liberar a GPU sozinho."""
    thread = threading.Thread(target=_laco_batimento, daemon=True, name="manter-modelo-quente")
    thread.start()
    return thread
