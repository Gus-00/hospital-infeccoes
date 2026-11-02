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
    # população parcial inflaria a taxa: basta um município sem população para a unidade ficar NaN
    soma = (base.groupby([cod, nome], as_index=False)
            .agg(valor=("valor", "sum"),
                 populacao=("populacao", lambda s: s.sum() if s.notna().all() else np.nan))
            .rename(columns={cod: "chave", nome: "nome"}))
    geom = geometrias if geometrias is not None else dissolver(geo, nivel)
    out = geom[["chave", "geometry"]].merge(soma, on="chave", how="left")
    return gpd.GeoDataFrame(out[["chave", "nome", "valor", "populacao", "geometry"]],
                            geometry="geometry", crs=geo.crs)


def fora_do_mapa(contagem: pd.DataFrame, geo: gpd.GeoDataFrame) -> int:
    """Soma de valor cujo cod_mun não está na malha (outras UFs ou códigos inválidos)."""
    return int(contagem.loc[~contagem["cod_mun"].isin(geo["cod_mun"]), "valor"].sum())


def municipios_sem_pop(geo: gpd.GeoDataFrame, pop: pd.DataFrame) -> int:
    """Municípios da malha sem população conhecida (deixam a unidade sem taxa)."""
    com_pop = pop.loc[pop["populacao"].notna(), "cod_mun"]
    return int((~geo["cod_mun"].isin(com_pop)).sum())


def periodo_efetivo(datas: pd.Series, ini, fim):
    """Período realmente coberto pela fonte dentro do filtro: (início, fim, anos-pessoa).
    O dia final conta (inclusivo); sem dados, vale o próprio filtro."""
    inicio, termino = pd.Timestamp(ini).normalize(), pd.Timestamp(fim).normalize()
    if len(datas):
        inicio = max(inicio, pd.Timestamp(datas.min()).normalize())
        termino = min(termino, pd.Timestamp(datas.max()).normalize())
    return inicio, termino, max((termino - inicio).days + 1, 1) / 365.25


def taxa_bruta(casos, pop, anos, base: float = 1e5) -> np.ndarray:
    """Casos por `base` habitantes por ano; NaN onde a população é nula ou ausente."""
    casos = np.asarray(casos, dtype=float)
    pop = np.asarray(pop, dtype=float)
    ok = np.isfinite(pop) & (pop > 0)
    return np.where(ok, casos / np.where(ok, pop, 1) / anos * base, np.nan)


def leitos_por_10mil(leitos, pop) -> np.ndarray:
    return taxa_bruta(leitos, pop, 1, 1e4)


def taxa_so_na_uf(taxa, cod_mun, cods_uf) -> np.ndarray:
    """NaN para municípios fora das UFs selecionadas (residentes de fora internados aqui):
    a população nacional não é denominador comparável para o recorte."""
    return np.where(pd.Series(cod_mun).isin(cods_uf).to_numpy(), np.asarray(taxa, dtype=float), np.nan)


def resumo_gravidade(srag: pd.DataFrame, ordem: list[str]) -> pd.DataFrame:
    """Gravidade por agente, sem arredondar. pct_uti e pct_obito têm como denominador todos
    os casos do agente (UTI ignorado/vazio conta como não; óbito = EVOLUCAO 2). Traz as
    contagens e o n com evolução conhecida (1, 2 ou 3) para quem preferir outro denominador."""
    z = srag.assign(
        conhecida=srag["evolucao"].isin([1, 2, 3]) if "evolucao" in srag else False)
    r = z.groupby("agente").agg(casos=("agente", "size"), n_uti=("uti", "sum"),
                                n_obito=("obito", "sum"), n_evolucao_conhecida=("conhecida", "sum"),
                                idade_mediana=("idade", "median"))
    r["pct_uti"] = 100 * r["n_uti"] / r["casos"]
    r["pct_obito"] = 100 * r["n_obito"] / r["casos"]
    r = r.reindex(ordem).reset_index()
    return r[["agente", "casos", "n_uti", "pct_uti", "n_obito", "pct_obito",
              "n_evolucao_conhecida", "idade_mediana"]]
