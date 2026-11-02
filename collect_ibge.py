"""Municípios (código 6 dígitos, nome, UF) e população estimada, via APIs do IBGE.
Uso: python collect_ibge.py
"""
import time

import pandas as pd
import requests

from config import REAL

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; hospital-infeccoes/1.0)",
           "Accept": "application/json"}


def get_json(url: str, tentativas: int = 5, timeout: int = 120):
    """GET com tentativas e espera crescente: as APIs do IBGE às vezes derrubam
    a conexão (ConnectionResetError) de forma intermitente."""
    ultimo = None
    for i in range(tentativas):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            ultimo = e
            espera = 2 ** (i + 1)
            print(f"  tentativa {i + 1}/{tentativas} falhou ({type(e).__name__}); "
                  f"aguardando {espera}s")
            time.sleep(espera)
    raise ConnectionError(f"{url}: {ultimo}")

URL_MUN = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"
# SIDRA tabela 6579 (população residente estimada), variável 9324, último ano
URL_POP = "https://apisidra.ibge.gov.br/values/t/6579/n6/all/v/9324/p/last%201"


def municipios():
    dados = get_json(URL_MUN)
    linhas = []
    for m in dados:
        micro = m.get("microrregiao") or {}
        uf = ((micro.get("mesorregiao") or {}).get("UF") or {}).get("sigla")
        if uf is None:
            imed = m.get("regiao-imediata") or {}
            uf = ((imed.get("regiao-intermediaria") or {}).get("UF") or {}).get("sigla")
        linhas.append({"cod_mun": str(m["id"])[:6], "municipio": m["nome"], "uf": uf})
    pd.DataFrame(linhas).to_parquet(REAL / "municipios.parquet", index=False)
    print(f"municipios.parquet: {len(linhas)} municípios")


def parse_populacao(dados: list) -> pd.DataFrame:
    cab = dados[0]  # primeira linha traz os rótulos das colunas
    k_mun = next(k for k, v in cab.items() if v.startswith("Município") and "Código" in v)
    k_ano = next(k for k, v in cab.items() if v.startswith("Ano") and "Código" in v)
    linhas = []
    for r in dados[1:]:
        try:
            pop = int(r["V"])
        except (ValueError, KeyError):
            continue
        linhas.append({"cod_mun": str(r[k_mun])[:6], "populacao": pop,
                       "ano_pop": int(r[k_ano])})
    return pd.DataFrame(linhas)


def populacao():
    df = parse_populacao(get_json(URL_POP))
    if df.empty:
        raise ValueError("SIDRA retornou sem valores numéricos")
    df.to_parquet(REAL / "populacao.parquet", index=False)
    print(f"populacao.parquet: {len(df)} municípios (ano {df['ano_pop'].iloc[0]})")


def main():
    REAL.mkdir(parents=True, exist_ok=True)
    try:
        municipios()
    except Exception as e:
        if (REAL / "municipios.parquet").exists():  # já coletado antes: segue com ele
            print(f"AVISO: municípios não atualizados ({e}); usando o arquivo existente.")
        else:
            raise SystemExit(f"Não consegui baixar a lista de municípios: {e}")
    try:
        populacao()
    except Exception as e:  # opcional: o painel funciona sem taxas por habitante
        print(f"AVISO: população não coletada ({type(e).__name__}: {e}). "
              "O painel fica sem taxas por 100 mil hab.")


if __name__ == "__main__":
    main()
