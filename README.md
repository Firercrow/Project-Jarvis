# PROJECT Jarvis

Assistente pessoal local: roda em cima dos seus próprios documentos e do seu histórico de
navegação, via um LLM local (Ollama) — nada sai da sua máquina.

## 1. Pré-requisitos (instalar antes do `pip install`)

O `requirements.txt` cobre só as bibliotecas Python. Estas peças ficam de fora porque não são
pacotes pip:

- **Python 3.14** (versão usada no desenvolvimento).
- **[Ollama](https://ollama.com/download)** — o LLM roda local através dele. Depois de instalar,
  baixe os três modelos que o projeto usa:
  ```
  ollama pull llama3.1:8b
  ollama pull llama3.2:3b
  ollama pull mxbai-embed-large
  ```
  Sem isso, nada no Jarvis funciona (toda pergunta/resumo/indexação depende do Ollama rodando em
  `localhost:11434`).
- **[LibreOffice](https://www.libreoffice.org/download/)** — opcional, só necessário pra indexar
  arquivos `.docx`. Sem ele, o resto do app funciona normalmente e só a indexação de `.docx` falha
  com um erro claro (ver `_localizar_soffice()` em `indexar.py`).

## 2. Instalação

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## 3. Rodando

```
streamlit run interface.py
```

Na primeira execução, o Streamlit pode pedir um e-mail no terminal (config dele, não do Jarvis) —
pode apertar Enter em branco pra pular.

## 4. Configurações que mudam de máquina pra máquina

Nada disso trava o app se ficar do jeito que está — mas os valores abaixo são específicos de quem
criou o projeto, então ajuste pra fazer sentido no seu uso:

- **Pastas catalogadas** (`pastas_catalogadas.json`, não vem no repo): é a lista de pastas que o
  Jarvis varre pra localizar arquivos por nome. Enquanto esse arquivo não existir, o app usa como
  valor inicial `PASTAS_CATALOGADAS` em `config.py` — que hoje aponta pra pastas específicas desta
  máquina (`C:\Users\Foda\Desktop`, `D:\jarvis-pessoal\Docs`). Isso não quebra nada (pasta que não
  existe só é ignorada na varredura), mas também não cataloga nada seu até você ajustar. Forma mais
  simples: usar os botões "adicionar/remover pasta" na barra lateral do app — isso já grava o
  `pastas_catalogadas.json` certo pra sua máquina, sem precisar editar `config.py`.

- **Histórico do navegador** (`config.py` → `CAMINHO_HISTORICO_BRAVE`): assume o navegador
  **Brave** instalado no caminho padrão do Windows. Se você usa outro navegador (Chrome, Edge,
  Firefox), esse caminho não existe na sua máquina — troque pelo caminho do arquivo `History` do
  seu navegador (todos os baseados em Chromium usam a mesma estrutura de pasta de perfil, só muda
  o nome do programa no caminho).

- **Identificador da máquina** (`config.py` → `IDENTIFICADOR_MAQUINA`): nome livre gravado junto de
  cada entrada de histórico indexado, só relevante se você usa o Jarvis em mais de um PC e quer
  distinguir a origem depois. Troque pra algo como `"notebook-trabalho"`.

## 5. Coisas que NÃO precisam de nenhuma ação

`Docs/`, `transcricoes/`, `banco_vetorial/`, `catalogo_arquivos.db` e `historico_temp.db` são
criados automaticamente na primeira vez que são necessários — não existem no repo (são dados
pessoais, ficam de fora do git de propósito) e não precisam ser criados à mão.
