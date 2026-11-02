import geopandas as gpd
import pytest
from shapely.geometry import box

from collect_geo import preparar

COLUNAS = ["cod_mun", "municipio", "uf", "cod_regiao", "regiao", "cod_macro", "macro",
           "geometry"]


def sintetico():
    return gpd.GeoDataFrame({
        "code_muni": [2300101.0, 2304400.0, 2304400.0],
        "name_muni": ["Abaiara", "Fortaleza", "Outro"],
        "abbrev_state": ["CE", "CE", "CE"],
        "code_health_region": [23019.0, 23001.0, 23001.0],
        "name_health_region": [" Brejo Santo ", "Fortaleza", "Fortaleza"],
        "code_health_macroregion": [2302.0, 2301.0, 2301.0],
        "name_health_macroregion": ["Cariri ", "Fortaleza", "Fortaleza"],
        "geometry": [box(0, 0, 1, 1), box(1, 0, 2, 1), box(2, 0, 3, 1)],
    }, crs="EPSG:4674")


def test_colunas_e_codigos():
    out = preparar(sintetico())
    assert list(out.columns) == COLUNAS
    assert out["cod_mun"].tolist() == ["230010", "230440", "230440"]
    assert out["cod_regiao"].tolist() == ["23019", "23001", "23001"]
    assert out["cod_macro"].tolist() == ["2302", "2301", "2301"]
    assert not out["cod_regiao"].str.contains(r"\.").any()


def test_strip_e_nomes_preservados():
    out = preparar(sintetico())
    assert out["regiao"].tolist()[0] == "Brejo Santo"
    assert out["macro"].tolist()[0] == "Cariri"
    assert out["municipio"].tolist() == ["Abaiara", "Fortaleza", "Outro"]


def test_crs_e_geometria_preservados():
    gdf = sintetico()
    out = preparar(gdf)
    assert out.crs == gdf.crs
    assert out.geometry.iloc[1].equals(gdf.geometry.iloc[1])


def test_coluna_ausente_levanta_keyerror():
    gdf = sintetico().drop(columns=["name_health_macroregion"])
    with pytest.raises(KeyError, match="name_health_macroregion"):
        preparar(gdf)
