import plotly.io as pio

import collect_srag
import estilo
from config import GRUPOS_CID


def test_cores_grupo_cobrem_e_distintas():
    assert set(estilo.CORES_GRUPO) == set(GRUPOS_CID)
    cores = list(estilo.CORES_GRUPO.values())
    assert len(set(cores)) == len(cores)
    assert cores == estilo.CATEGORICA[:len(GRUPOS_CID)]


def test_cores_agente_cobrem_srag():
    esperado = set(collect_srag.AGENTE.values()) | {"Em investigação"}
    assert esperado <= set(estilo.CORES_AGENTE)
    assert estilo.ORDEM_AGENTE[-2:] == ["Não especificado", "Em investigação"]
    assert estilo.CORES_AGENTE["Outro agente"] == estilo.CATEGORICA[6]


def test_template_registrado():
    assert "artigo" in pio.templates
    assert pio.templates.default == "plotly_white+artigo"
    assert pio.templates["artigo"].layout.separators == ",."


def test_legenda_completa():
    assert estilo.legenda("sih_serie", "SIH/SUS", "x") == (
        "**Figura 2.** Internações por semana epidemiológica, por grupo de causa. "
        "Fonte: SIH/SUS. Nota: x.")


def test_legenda_sem_nota_e_sem_ponto_duplo():
    assert estilo.legenda("mapa", "IBGE.") == (
        "**Figura 1.** Distribuição espacial do indicador selecionado. Fonte: IBGE.")
    assert estilo.legenda("mapa", "IBGE", "n.").endswith("Fonte: IBGE. Nota: n.")


def test_figuras_numeracao_fixa():
    assert [n for n, _ in estilo.FIGURAS.values()] == list(range(1, 10))


def test_formatacao_ptbr():
    assert estilo.fmt_int(1234567) == "1.234.567"
    assert estilo.fmt_dec(7.24, 1) == "7,2"
    assert estilo.fmt_dec(1234.5, 1) == "1.234,5"


def test_config_plotly():
    c = estilo.config_plotly("fig")
    assert c["displaylogo"] is False
    assert c["toImageButtonOptions"]["format"] == "svg"
    assert c["toImageButtonOptions"]["filename"] == "fig"


def test_config_plotly_altura_da_figura():
    assert estilo.config_plotly("fig")["toImageButtonOptions"]["height"] == 700
    c = estilo.config_plotly("fig", 312)["toImageButtonOptions"]
    assert (c["width"], c["height"]) == (1200, 312)
