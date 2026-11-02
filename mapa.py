"""Funções puras do mapa: suavização bayesiana empírica e agregação por nível."""
import geopandas as gpd
import numpy as np
import pandas as pd

# nível -> (coluna do código, coluna do nome) em geo_municipios
NIVEIS = {"municipio": ("cod_mun", "municipio"),
          "regiao": ("cod_regiao", "regiao"),
          "macro": ("cod_macro", "macro")}


def taxa_eb(casos, pop, anos) -> np.ndarray:
    """Bayesiano empírico global (Marshall, 1991): taxa por 100 mil hab./ano.
    Unidades com população nula ou ausente ficam NaN e não entram nas estatísticas."""
    casos = np.asarray(casos, dtype=float)
    pop = np.asarray(pop, dtype=float)
    ok = np.isfinite(pop) & (pop > 0) & np.isfinite(casos)
    eb = np.full(casos.shape, np.nan)
    if not ok.any():
        return eb
    n = pop[ok] * anos
    r = casos[ok] / n
    m = casos[ok].sum() / n.sum()
    s2 = (n * (r - m) ** 2).sum() / n.sum()
    a = max(s2 - m / n.mean(), 0.0)
    ruido = m / n
    # com m = 0 (sem casos) não há o que suavizar: peso 0 e resultado 0
    w = np.divide(a, a + ruido, out=np.zeros_like(n), where=(a + ruido) > 0)
    eb[ok] = (w * r + (1 - w) * m) * 1e5
    return eb


def dissolver(geo: gpd.GeoDataFrame, nivel: str) -> gpd.GeoDataFrame:
    """Geometria por unidade (chave, nome, geometry); caro para regiões e macros."""
    cod, nome = NIVEIS[nivel]
    if nivel == "municipio":
        return geo[[cod, nome, "geometry"]].set_axis(["chave", "nome", "geometry"], axis=1)
    d = geo.dissolve(by=[cod, nome]).reset_index()
    return d[[cod, nome, "geometry"]].set_axis(["chave", "nome", "geometry"], axis=1)


def agregar(contagem: pd.DataFrame, geo: gpd.GeoDataFrame, pop: pd.DataFrame, nivel: str,
            geometrias: gpd.GeoDataFrame | None = None) -> gpd.GeoDataFrame:
    """Soma valor e população por unidade. Parte de `geo`, então só unidades mapeadas
    aparecem e município sem casos fica com 0. `geometrias` evita redissolver (cache)."""
    cod, nome = NIVEIS[nivel]
    val = contagem.groupby("cod_mun", as_index=False)["valor"].sum()
    base = (geo.drop(columns="geometry")
            .merge(val, on="cod_mun", how="left")
            .merge(pop[["cod_mun", "populacao"]], on="cod_mun", how="left"))
    base["valor"] = base["valor"].fillna(0)
    # min_count=1: unidade sem nenhuma população conhecida fica NaN, não 0
    soma = (base.groupby([cod, nome], as_index=False)
            .agg(valor=("valor", "sum"), populacao=("populacao", lambda s: s.sum(min_count=1)))
            .rename(columns={cod: "chave", nome: "nome"}))
    geom = geometrias if geometrias is not None else dissolver(geo, nivel)
    out = geom[["chave", "geometry"]].merge(soma, on="chave", how="left")
    return gpd.GeoDataFrame(out[["chave", "nome", "valor", "populacao", "geometry"]],
                            geometry="geometry", crs=geo.crs)


def fora_do_mapa(contagem: pd.DataFrame, geo: gpd.GeoDataFrame) -> int:
    """Soma de valor cujo cod_mun não está na malha (outras UFs ou códigos inválidos)."""
    return int(contagem.loc[~contagem["cod_mun"].isin(geo["cod_mun"]), "valor"].sum())
