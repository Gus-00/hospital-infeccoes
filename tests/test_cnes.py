import pytest

import collect_cnes
from collect_cnes import destino_seguro, nome_lt_valido


@pytest.mark.parametrize("nome", ["LTCE2609.dbc", "LTCE2609.DBC", "ltce2609.DBC"])
def test_nome_lt_valido_aceita(nome):
    assert nome_lt_valido(nome, "CE") is True


@pytest.mark.parametrize("nome", [
    "LTCE/../x.DBC",
    "LTCE2609.dbc.exe",
    "LTPE2609.dbc",
    "LTCE26.dbc",
])
def test_nome_lt_valido_rejeita(nome):
    assert nome_lt_valido(nome, "CE") is False


def test_destino_seguro_aceita_nome_valido(tmp_path, monkeypatch):
    monkeypatch.setattr(collect_cnes, "DESTINO", tmp_path)
    assert destino_seguro("LTCE2609.DBC") == tmp_path / "LTCE2609.DBC"


def test_destino_seguro_rejeita_saida_da_pasta(tmp_path, monkeypatch):
    monkeypatch.setattr(collect_cnes, "DESTINO", tmp_path / "cnes")
    with pytest.raises(SystemExit):
        destino_seguro("../x.DBC")
