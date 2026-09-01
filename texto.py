"""Normalização de texto compartilhada por todo o projeto.

Existe pra resolver um bug estrutural achado na auditoria de 2026-08-20: havia duas
funções chamadas `normalizar()` (uma em `resumir.py`, outra em `catalogar_arquivos.py`)
com comportamento DIFERENTE — a de `catalogar_arquivos` removia underscore, a de
`resumir` não. Resultado: "TECHNICAL REPORT CORRECTED" achava
`TECHNICAL_REPORT_CORRECTED.docx` na busca do catálogo e falhava no resumo/contagem/
transcrição. Mesma frase, resultados opostos dependendo da rota.

A separação abaixo corrige também um erro conceitual da versão antiga: ela juntava
duas tarefas distintas numa função só, e era aplicada aos DOIS lados da comparação —
então o nome REAL de um arquivo também tinha artigo/qualificador arrancado (um arquivo
chamado "A Odisseia.pdf" era comparado como "odisseia.pdf"). São coisas separadas:

- `normalizar_nome()`  → forma canônica pra COMPARAR. Vale para os dois lados.
- `limpar_termo_pedido()` → tira palavra de enfeite. Vale SÓ para o que o usuário
  (ou o extrator de LLM) escreveu — nunca para o nome real do arquivo/aba/pasta.
- `normalizar_pedido()` → atalho que aplica as duas na ordem certa.
"""

import unicodedata

# Marca linhas que são COMENTÁRIO DO SISTEMA sobre a consulta (quantas linhas foram cortadas,
# que nenhum filtro bateu), e não conteúdo da resposta. Existe porque as duas coisas viravam uma
# string só e o modelo que condensa a memória confundia metadado com dado: num teste real ele
# fundiu o aviso "cobre todos os 4000 registros da fonte" com a notícia listada e gravou na
# memória "a Datafolha divulga a pesquisa cobrindo todos os 4000 registros" — uma afirmação que
# não existe em lugar nenhum. Serve também como destaque visual pro usuário.
PREFIXO_AVISO = "⚠ "


def remover_avisos_do_sistema(texto: str) -> str:
    """Tira as linhas de aviso, deixando só o conteúdo da resposta. Usado antes de guardar na
    memória de conversa — o aviso é sobre a consulta que acabou de rodar, não é informação que
    faça sentido carregar pras próximas perguntas."""
    linhas = [l for l in texto.split("\n") if not l.startswith(PREFIXO_AVISO)]
    return "\n".join(linhas).strip()

# Ordem importa: prefixos mais longos primeiro, senão "a " casaria antes de "as ".
ARTIGOS_INICIAIS = ("os ", "as ", "uma ", "um ", "a ", "o ")

# O extrator de LLM costuma devolver a palavra qualificadora junto do nome
# (ex: "planilha teste_vendas.xlsx" em vez de só "teste_vendas.xlsx").
QUALIFICADORES_INICIAIS = ("planilha ", "documento ", "arquivo ", "livro ", "pasta ")


def normalizar_nome(texto) -> str:
    """Forma canônica pra comparar nomes de arquivo/aba/pasta, ignorando diferenças que
    não mudam a identidade do nome: caixa, acento e separadores (espaço, hífen,
    underscore — os três são intercambiáveis em nome de arquivo, e quem digita raramente
    acerta qual foi usado). Aceita não-string (nome de aba de Excel pode vir como número)."""
    texto = str(texto).lower().strip()
    for separador in (" ", "-", "_"):
        texto = texto.replace(separador, "")
    texto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in texto if not unicodedata.combining(c))


def limpar_termo_pedido(texto) -> str:
    """Remove artigo e palavra qualificadora do INÍCIO do termo que o usuário pediu.
    Só um de cada, e só no começo — "livro" no meio do nome é parte do nome de verdade
    (ex: "o livro amarelo" vira "amarelo", mas "meu livro amarelo" fica intacto)."""
    texto = str(texto).lower().strip()
    for grupo in (ARTIGOS_INICIAIS, QUALIFICADORES_INICIAIS):
        for prefixo in grupo:
            if texto.startswith(prefixo):
                texto = texto[len(prefixo):].strip()
                break
    return texto


def normalizar_pedido(texto) -> str:
    """O que aplicar no lado do PEDIDO antes de comparar com `normalizar_nome(real)`."""
    return normalizar_nome(limpar_termo_pedido(texto))


def normalizar_frase(texto) -> str:
    """Normalização de FRASE — minúsculas e sem acento, mas PRESERVA espaço entre palavras.
    Diferente de `normalizar_nome()`: aquela existe pra comparar nome de arquivo/pasta e por
    isso remove separador (espaço/hífen/underscore) de propósito, já que são intercambiáveis num
    nome de arquivo. Numa frase ("capítulo 1", "Pin Configuration") o espaço É a fronteira de
    palavra — removê-lo quebra qualquer lógica que precise separar palavras depois (achado real,
    2026-08-25: `variantes_numerais()` precisa isolar o "1" de "capítulo 1" pra converter em
    romano; com `normalizar_nome()` virava "capitulo1" grudado, um token só, nunca convertia)."""
    texto = str(texto).lower().strip()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join(texto.split())


_VALORES_ROMANOS = [
    (1000, "m"), (900, "cm"), (500, "d"), (400, "cd"),
    (100, "c"), (90, "xc"), (50, "l"), (40, "xl"),
    (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i"),
]


def numero_para_romano(numero: int) -> str:
    """Numeral romano em minúsculas — usado pra casar 'capítulo 1' (como o usuário escreve) com
    'Capítulo I' (como o sumário de um livro costuma numerar capítulo), depois de normalizar
    caixa/acento dos dois lados."""
    resultado = ""
    restante = numero
    for valor, simbolo in _VALORES_ROMANOS:
        while restante >= valor:
            resultado += simbolo
            restante -= valor
    return resultado


def variantes_numerais(termo_normalizado: str) -> set[str]:
    """Gera a variante com número arábico trocado por romano (ex: 'capitulo 1' -> 'capitulo i')
    — só nessa direção (arábico->romano), porque é a direção real observada em sumário de livro
    (usuário pede em arábico, livro numera capítulo em romano). Sempre inclui o termo original."""
    variantes = {termo_normalizado}
    palavras = termo_normalizado.split()
    if any(p.isdigit() for p in palavras):
        convertido = [numero_para_romano(int(p)) if p.isdigit() else p for p in palavras]
        variantes.add(" ".join(convertido))
    return variantes
