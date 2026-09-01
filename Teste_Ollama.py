import requests

def perguntar(prompt: str) -> str:
    try:
        resposta = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "llama3.1:8b",
                "prompt": prompt,
                "stream": False
            },
            timeout=120
        )
        print("Status code:", resposta.status_code)
        dados = resposta.json()
        return dados.get("response", f"[sem campo 'response'] Retorno completo: {dados}")
    except Exception as e:
        return f"[ERRO] {type(e).__name__}: {e}"

if __name__ == "__main__":
    pergunta = "Explique o que é RAG em uma frase curta."
    print("Enviando pergunta...")
    print(perguntar(pergunta))
    print("Fim do script.")