"""reformular_pergunta() é casamento gramatical (spaCy), sem LLM -- rápido e determinístico.
Carrega o modelo pt_core_news_lg uma vez por sessão de teste (~7s no primeiro teste)."""
import config
import perguntar as pg


def test_pronome_masculino_casa_com_entidade_mais_recente():
    historico = [{"pergunta": "quem é o personagem principal?", "resposta": "Napoleão, um porco."}]
    resultado = pg.reformular_pergunta("quantos anos ele tem?", historico)
    assert "Napoleão" in resultado
    assert "ele" not in resultado.lower().split()


def test_pronome_feminino_casa_por_genero():
    historico = [{"pergunta": "qual a maior cidade do Brasil?", "resposta": "São Paulo."}]
    resultado = pg.reformular_pergunta("quantos habitantes ela tem?", historico)
    assert "São Paulo" in resultado


def test_pronome_plural_junta_todos_os_candidatos():
    historico = [{"pergunta": "quais planetas são gigantes gasosos?", "resposta": "Júpiter e Saturno."}]
    resultado = pg.reformular_pergunta("quais deles têm anéis visíveis?", historico)
    assert "Júpiter" in resultado and "Saturno" in resultado


def test_pronome_neutro_usa_topico_da_pergunta_anterior():
    historico = [{"pergunta": "o que causou a queda do Império Romano?",
                  "resposta": "Diversos fatores, incluindo invasões bárbaras."}]
    resultado = pg.reformular_pergunta("quando isso aconteceu?", historico)
    assert "isso" not in resultado.lower().split()


def test_sem_historico_devolve_pergunta_inalterada():
    assert pg.reformular_pergunta("quantos anos ele tem?", []) == "quantos anos ele tem?"


def test_sem_pronome_devolve_pergunta_inalterada():
    historico = [{"pergunta": "quem é X?", "resposta": "Y."}]
    pergunta = "qual a capital da França?"
    assert pg.reformular_pergunta(pergunta, historico) == pergunta


def test_historico_pronome_desativado_nao_deve_ser_usado_entre_mensagens():
    """Documenta a decisão de 2026-08-27 (HISTORICO_PRONOME_ATIVO=False): quando o chamador
    passa [] no lugar do histórico real (é isso que responder_pergunta()/
    responder_com_detalhamento() fazem hoje com a flag desligada), o pronome fica sem resolver
    -- comportamento seguro (recusa honesta), não resposta errada."""
    assert config.HISTORICO_PRONOME_ATIVO is False
    historico_real = [
        {"pergunta": "quem pintou a Mona Lisa?", "resposta": "Leonardo da Vinci."},
        {"pergunta": "em que século?", "resposta": "Século XVI."},
    ]
    resultado = pg.reformular_pergunta("onde ele nasceu?", historico_real if config.HISTORICO_PRONOME_ATIVO else [])
    assert resultado == "onde ele nasceu?"
