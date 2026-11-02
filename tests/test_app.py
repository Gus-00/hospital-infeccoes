"""Roda o painel inteiro com AppTest (real e demo) e garante que não há exceção."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from config import DEMO, REAL

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def _rodar(fonte: str) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=180)
    at.run()
    if fonte == "demo":
        at.sidebar.radio[0].set_value("demo").run()
    return at


def _mudar_nivel(at: AppTest) -> None:
    at.selectbox(key="mapa_nivel").set_value("Região de saúde").run()
    assert len(at.exception) == 0, [e.message for e in at.exception]


def _confere(at: AppTest) -> None:
    assert len(at.exception) == 0, [e.message for e in at.exception]
    abas = [t.label for t in at.tabs]
    assert abas[-1] == "Métodos"
    assert any("Fontes de dados" in m.value for m in at.markdown)


def test_app_real():
    if not (REAL / "sih.parquet").exists():
        pytest.skip("sem data/real/sih.parquet")
    at = _rodar("real")
    _confere(at)
    _mudar_nivel(at)


def test_app_demo():
    if not (DEMO / "sih.parquet").exists():
        import demo_data
        demo_data.main()
    at = _rodar("demo")
    _confere(at)
    assert any("FICTÍCIOS" in w.value for w in at.warning)
    _mudar_nivel(at)
