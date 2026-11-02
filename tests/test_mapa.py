import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box

from mapa import agregar, fora_do_mapa, taxa_eb


def test_eb_taxas_iguais_devolve_taxa_comum():
    pop = np.array([1000, 5000, 20000])
    casos = pop * 0.002  # taxa comum de 200 por 100 mil por ano
    eb = taxa_eb(casos, pop, anos=1)
    assert np.allclose(eb, 200.0)


def test_eb_variancia_menor_que_esperada_devolve_media_global():
    # taxas quase iguais: A <= 0, todas encolhem para a média global
    pop = np.array([100.0, 100.0, 100.0, 100.0])
    casos = np.array([9.0, 10.0, 10.0, 11.0])
    eb = taxa_eb(casos, pop, anos=2)
    media = casos.sum() / (pop.sum() * 2) * 1e5
    assert np.allclose(eb, media)


def test_eb_unidade_pequena_e_puxada_mais_para_a_media():
    # mesma taxa bruta (acima da média) em unidade pequena e grande
    pop = np.array([200.0, 200_000.0, 100_000.0, 100_000.0, 100_000.0])
    casos = np.array([4.0, 4000.0, 100.0, 100.0, 100.0])
    eb = taxa_eb(casos, pop, anos=1)
    media = casos.sum() / pop.sum() * 1e5
    bruta = casos / pop * 1e5
    assert bruta[0] == bruta[1]
    assert abs(eb[0] - media) < abs(eb[1] - media)
    assert eb[0] < bruta[0]


def test_eb_pop_nula_ou_ausente_vira_nan_e_nao_entra_na_media():
    pop = np.array([1000.0, 0.0, np.nan, 1000.0])
    casos = np.array([2.0, 5.0, 3.0, 2.0])
    eb = taxa_eb(casos, pop, anos=1)
    assert np.isnan(eb[1]) and np.isnan(eb[2])
    assert np.allclose(eb[[0, 3]], 200.0)


def test_eb_sem_casos_devolve_zero():
    eb = taxa_eb(np.zeros(3), np.array([10.0, 20.0, 30.0]), anos=1)
    assert np.allclose(eb, 0.0)


def geo_sintetico():
    return gpd.GeoDataFrame({
        "cod_mun": ["230001", "230002", "230003"],
        "municipio": ["Alfa", "Beta", "Gama"],
        "uf": ["CE"] * 3,
        "cod_regiao": ["23001", "23001", "23002"],
        "regiao": ["Reg A", "Reg A", "Reg B"],
        "cod_macro": ["2301", "2301", "2301"],
        "macro": ["Macro 1"] * 3,
        "geometry": [box(0, 0, 1, 1), box(1, 0, 2, 1), box(5, 0, 6, 1)],
    }, crs="EPSG:4674")


POP = pd.DataFrame({"cod_mun": ["230001", "230002", "230003", "350001"],
                    "populacao": [100, 200, 400, 9999]})


def test_agregar_regiao_soma_e_mantem_municipio_sem_casos_com_zero():
    contagem = pd.DataFrame({"cod_mun": ["230001", "230002"], "valor": [3, 4]})
    out = agregar(contagem, geo_sintetico(), POP, "regiao")
    assert list(out.columns) == ["chave", "nome", "valor", "populacao", "geometry"]
    assert len(out) == 2
    a = out[out["chave"] == "23001"].iloc[0]
    assert a["nome"] == "Reg A" and a["valor"] == 7 and a["populacao"] == 300
    assert a["geometry"].area == 2.0  # dissolvida
    b = out[out["chave"] == "23002"].iloc[0]
    assert b["valor"] == 0 and b["populacao"] == 400


def test_agregar_municipio_ignora_codigos_fora_da_malha():
    contagem = pd.DataFrame({"cod_mun": ["230001", "350001"], "valor": [3, 50]})
    out = agregar(contagem, geo_sintetico(), POP, "municipio")
    assert len(out) == 3
    assert out["valor"].sum() == 3
    assert out.loc[out["chave"] == "230003", "valor"].iloc[0] == 0


def test_agregar_macro_junta_tudo():
    contagem = pd.DataFrame({"cod_mun": ["230001", "230003"], "valor": [1, 2]})
    out = agregar(contagem, geo_sintetico(), POP, "macro")
    assert len(out) == 1
    assert out.iloc[0]["valor"] == 3 and out.iloc[0]["populacao"] == 700


def test_agregar_soma_linhas_repetidas_do_mesmo_municipio():
    contagem = pd.DataFrame({"cod_mun": ["230001", "230001"], "valor": [1, 2]})
    out = agregar(contagem, geo_sintetico(), POP, "municipio")
    assert out.loc[out["chave"] == "230001", "valor"].iloc[0] == 3


def test_fora_do_mapa_conta_codigos_de_outra_uf():
    contagem = pd.DataFrame({"cod_mun": ["230001", "350001", "999999"],
                             "valor": [3, 50, 7]})
    assert fora_do_mapa(contagem, geo_sintetico()) == 57
