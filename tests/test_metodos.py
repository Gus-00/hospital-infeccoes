from pathlib import PurePosixPath
from urllib.parse import urlparse

import pandas as pd

import metodos
from config import GRUPOS_CID, SRAG_URLS

COBERTURA = {"sih": (pd.Timestamp("2023-01-01"), pd.Timestamp("2026-07-31"), 3.58),
             "srag": (pd.Timestamp("2023-01-01"), pd.Timestamp("2026-09-20"), 3.72)}


def _texto(**kw):
    base = dict(ufs=["CE"], cobertura=COBERTURA, comp_cnes="202609", ano_pop=2025,
                n_mes=1, n_sem=3, cortes={"sih_antes": 1234, "sih_oculto": 5678})
    base.update(kw)
    return metodos.texto_metodos(**base)


def test_texto_tem_todos_os_grupos_de_cid():
    texto = _texto()
    for grupo in GRUPOS_CID:
        assert grupo in texto


def test_texto_tem_todos_os_arquivos_srag():
    texto = _texto()
    for url in SRAG_URLS:
        assert PurePosixPath(urlparse(url).path).name in texto


def test_texto_tem_secoes_e_periodos_por_fonte():
    texto = _texto()
    for secao in ("Fontes de dados", "Definições", "Exclusões e cortes aplicados",
                  "Fórmulas", "Limitações"):
        assert f"## {secao}" in texto
    assert "01/01/2023 a 31/07/2026" in texto  # SIH
    assert "01/01/2023 a 20/09/2026" in texto  # SRAG
    assert "09/2026" in texto and "2025" in texto
    assert "1.234" in texto and "5.678" in texto  # contagens em pt-BR


def test_codigos_cid_formatados():
    assert metodos.codigos_cid([("B342", "B342"), ("U07", "U07")]) == "B34.2; U07"
    assert metodos.codigos_cid([("A15", "A19")]) == "A15-A19"


def test_demo_rotulado_ficticio():
    assert "FICTÍCIOS" in _texto(demo=True)
    assert "FICTÍCIOS" not in _texto()


def test_local_ufs():
    assert metodos.local_ufs(["CE"]) == "no Ceará"
    assert metodos.local_ufs(["CE", "BA"]) == "no Ceará e na Bahia"
    assert metodos.local_ufs(["CE", "PE", "PI"]) == "no Ceará, em Pernambuco e no Piauí"


def test_fmt_competencia():
    assert metodos.fmt_comp("202609") == "09/2026"
    assert metodos.fmt_comp(None) == "não disponível"


def test_cortes_e_formulas_sem_ambiguidade():
    texto = _texto()
    assert "internações ocultas (na base carregada, antes dos filtros): 5.678" in texto
    assert r"\right] \times 100.000$$" in texto  # EB na mesma base da taxa bruta
    assert "divididas por 7" in texto
