"""Malha municipal com região e macrorregião de saúde (geobr) -> data/real/geo_municipios.parquet.
Uso: python collect_geo.py
Baixa uma vez; o painel lê o parquet local em vez de chamar o geobr a cada uso."""
import geopandas as gpd
import pandas as pd

from collect_sih import UFS_BR
from config import REAL, UF_ALVO

ANO_MALHA = 2023  # o painel cita este ano na legenda do mapa

COLUNAS_ORIGEM = ["code_muni", "name_muni", "abbrev_state", "code_health_region",
                  "name_health_region", "code_health_macroregion",
                  "name_health_macroregion", "geometry"]


def preparar(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Renomeia e tipa as colunas do geobr. Os nomes ficam como vieram (só strip)."""
    faltam = [c for c in COLUNAS_ORIGEM if c not in gdf.columns]
    if faltam:
        raise KeyError(f"colunas ausentes no geobr: {faltam}; "
                       f"disponíveis: {list(gdf.columns)}")
    # code_muni vem como float de 7 dígitos; int() evita fatiar a string "2300101.0"
    out = pd.DataFrame({
        "cod_mun": gdf["code_muni"].map(lambda c: str(int(c) // 10)),
        "municipio": gdf["name_muni"],
        "uf": gdf["abbrev_state"],
        "cod_regiao": gdf["code_health_region"].map(lambda c: str(int(c))),
        "regiao": gdf["name_health_region"].str.strip(),
        "cod_macro": gdf["code_health_macroregion"].map(lambda c: str(int(c))),
        "macro": gdf["name_health_macroregion"].str.strip(),
    })
    return gpd.GeoDataFrame(out, geometry=gdf.geometry.values, crs=gdf.crs)


def main():
    import geobr  # import tardio: só o coletor precisa dele
    partes = [geobr.read_health_region(year=ANO_MALHA, code_state=uf,
                                       geometry_level="municipality", show_progress=False)
              for uf in (UF_ALVO or UFS_BR)]
    geo = preparar(gpd.GeoDataFrame(pd.concat(partes, ignore_index=True), crs=partes[0].crs))
    REAL.mkdir(parents=True, exist_ok=True)
    geo.to_parquet(REAL / "geo_municipios.parquet", index=False)
    print(f"geo_municipios.parquet: {len(geo)} municípios, "
          f"{geo['cod_regiao'].nunique()} regiões de saúde, "
          f"{geo['cod_macro'].nunique()} macrorregiões (malha {ANO_MALHA})")


if __name__ == "__main__":
    main()
