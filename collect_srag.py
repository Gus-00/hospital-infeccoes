"""Baixa o SIVEP-Gripe (SRAG) do OpenDataSUS e salva data/real/srag.parquet.

Uso:  python collect_srag.py
"""
import re
import sys
from pathlib import Path

import pandas as pd
import requests

from config import RAW, REAL, SRAG_DATASET_PAGES, SRAG_URLS, UF_ALVO

# Os CSVs públicos de 2023-2026 não trazem o código CNES da unidade (CO_UN_INTE
# foi retirado); só o nome (NM_UN_INTE) e o município de internação (CO_MU_INTE).
COLS = ["NU_NOTIFIC", "DT_NOTIFIC", "SG_UF_NOT", "CO_MUN_NOT", "ID_MUNICIP", "CS_SEXO",
        "NU_IDADE_N", "TP_IDADE", "HOSPITAL", "UTI", "EVOLUCAO",
        "CLASSI_FIN", "NM_UN_INTE", "CO_MU_INTE", "NOSOCOMIAL"]
AGENTE = {1: "Influenza", 2: "Outro vírus respiratório", 3: "Outro agente",
          4: "Não especificado", 5: "COVID-19"}
DIVISOR_IDADE = {1: 365, 2: 12, 3: 1}  # TP_IDADE: 1 = dias, 2 = meses, 3 = anos
IDADE_MAX = 120


def descobrir_urls() -> list[str]:
    urls: list[str] = []
    for page in SRAG_DATASET_PAGES:
        html = requests.get(page, timeout=60).text
        urls += re.findall(
            r"https://s3\.sa-east-1\.amazonaws\.com/ckan\.saude\.gov\.br/SRAG/\d{4}/[^\"'\s<>]+?\.csv",
            html)
    return sorted(set(urls))


def baixar(url: str):
    RAW.mkdir(parents=True, exist_ok=True)
    destino = RAW / url.rsplit("/", 1)[-1]
    if destino.exists():
        return destino
    print(f"baixando {url}")
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(destino, "wb") as f:
            for bloco in r.iter_content(1 << 20):
                f.write(bloco)
    return destino


OBRIGATORIAS = ["DT_NOTIFIC", "SG_UF_NOT", "CO_MUN_NOT", "CLASSI_FIN"]


def col(df: pd.DataFrame, nome: str):
    """Coluna se existir; senão uma série vazia (colunas opcionais variam por ano)."""
    return df[nome] if nome in df.columns else pd.Series(pd.NA, index=df.index)


def parse_data(s: pd.Series) -> pd.Series:
    """Datas do SRAG vêm como '2024-08-29T00:00:00.000Z' (ISO com hora) ou, em
    arquivos antigos, 'DD/MM/AAAA'. ISO primeiro; o que sobrar tenta DD/MM/AAAA.
    Não usar dayfirst=True: ele inverte dia e mês em datas ISO."""
    s = s.astype(str).str.strip()
    d = pd.to_datetime(s, format="ISO8601", errors="coerce", utc=True)
    d = d.dt.tz_localize(None).dt.normalize()
    resto = d.isna()
    if resto.any():
        d[resto] = pd.to_datetime(s[resto], format="%d/%m/%Y", errors="coerce")
    return d


def limpar(df: pd.DataFrame) -> pd.DataFrame:
    faltando = [c for c in OBRIGATORIAS if c not in df.columns]
    if faltando:
        raise KeyError(f"colunas obrigatórias ausentes {faltando}; "
                       f"disponíveis: {list(df.columns)}")
    out = pd.DataFrame()
    out["id_notif"] = col(df, "NU_NOTIFIC")
    out["dt_notific"] = parse_data(df["DT_NOTIFIC"])
    out["uf"] = df["SG_UF_NOT"]
    out["cod_mun"] = df["CO_MUN_NOT"].astype("Int64").astype(str).str[:6]
    out["sexo"] = col(df, "CS_SEXO")
    idade = pd.to_numeric(col(df, "NU_IDADE_N"), errors="coerce")
    tp = pd.to_numeric(col(df, "TP_IDADE"), errors="coerce")
    anos = idade / tp.map(DIVISOR_IDADE)  # TP_IDADE ausente/inválido -> NaN
    invalida = (anos < 0) | (anos > IDADE_MAX)
    out["idade"] = anos.mask(invalida)
    out.attrs["idades_invalidas"] = int(invalida.sum())
    out["internado"] = pd.to_numeric(col(df, "HOSPITAL"), errors="coerce") == 1
    out["uti"] = pd.to_numeric(col(df, "UTI"), errors="coerce") == 1
    evolucao = pd.to_numeric(col(df, "EVOLUCAO"), errors="coerce")
    out["obito"] = evolucao == 2
    # bruta: 1 cura, 2 óbito por SRAG, 3 óbito por outras causas, 9 ignorado, vazio
    out["evolucao"] = evolucao.astype("Int64")
    out["agente"] = (pd.to_numeric(df["CLASSI_FIN"], errors="coerce")
                     .map(AGENTE).fillna("Em investigação"))
    out["nosocomial"] = pd.to_numeric(col(df, "NOSOCOMIAL"), errors="coerce") == 1
    out["un_inte"] = col(df, "NM_UN_INTE")  # nome da unidade de internação
    out["cod_mun_inte"] = col(df, "CO_MU_INTE").astype("string").str[:6]
    return out


def ler_csv(caminho) -> pd.DataFrame:
    cab = pd.read_csv(caminho, sep=";", nrows=0, encoding="latin-1").columns
    print(f"  {Path(caminho).name}: colunas com 'UN_': {[c for c in cab if 'UN_' in c]}")
    ausentes = [c for c in COLS if c not in cab]
    if ausentes:
        print(f"  ! colunas de COLS ausentes neste arquivo: {ausentes}")
    pedacos, vistos, total, apos_uf, amostra = [], {}, 0, 0, None
    for enc in ("utf-8", "latin-1"):
        pedacos, vistos, total, apos_uf, invalidas = [], {}, 0, 0, 0
        try:
            for ch in pd.read_csv(caminho, sep=";", usecols=lambda c: c in COLS,
                                  dtype=str, chunksize=200_000, encoding=enc):
                total += len(ch)
                if amostra is None and "DT_NOTIFIC" in ch:
                    amostra = ch["DT_NOTIFIC"].head(3).tolist()
                if "SG_UF_NOT" in ch:
                    for k, v in ch["SG_UF_NOT"].value_counts().head(5).items():
                        vistos[k] = vistos.get(k, 0) + int(v)
                if UF_ALVO:
                    ch = ch[ch["SG_UF_NOT"].isin(UF_ALVO)]
                apos_uf += len(ch)
                ch = ch.copy()
                for c in ("CO_MUN_NOT", "NU_IDADE_N", "TP_IDADE"):
                    if c in ch.columns:
                        ch[c] = pd.to_numeric(ch[c], errors="coerce")
                parte = limpar(ch)
                invalidas += parte.attrs.get("idades_invalidas", 0)
                pedacos.append(parte)
            break
        except UnicodeDecodeError:
            continue
    df = pd.concat(pedacos, ignore_index=True) if pedacos else pd.DataFrame()
    validas = int(df["dt_notific"].notna().sum()) if not df.empty else 0
    print(f"  {Path(caminho).name}: lidas {total:,} | após filtro UF {apos_uf:,} | "
          f"datas válidas {validas:,} | idades <0 ou >{IDADE_MAX} anos -> NaN: {invalidas:,}")
    if total and apos_uf == 0:
        print(f"  ! nenhuma linha passou no filtro UF_ALVO={UF_ALVO}. "
              f"Valores de SG_UF_NOT mais comuns: {vistos}")
    elif apos_uf and validas == 0:
        print(f"  ! nenhuma data reconhecida. Exemplos de DT_NOTIFIC: {amostra}")
    return df


def main():
    urls = SRAG_URLS  # colar em config.py (ver README); descoberta automática desativada
    if not urls:
        sys.exit("config.SRAG_URLS está vazio. Cole as URLs dos CSVs em config.py "
                 "e SALVE o arquivo.")
    dfs = [ler_csv(baixar(u)) for u in urls]
    df = pd.concat(dfs, ignore_index=True).dropna(subset=["dt_notific"])
    relatorio(df)
    REAL.mkdir(parents=True, exist_ok=True)
    df.to_parquet(REAL / "srag.parquet", index=False)
    print(f"srag.parquet: {len(df):,} linhas")


def relatorio(df: pd.DataFrame):
    """Conferências impressas antes de salvar; não altera o DataFrame."""
    ids = df["id_notif"].dropna()
    dup = ids.duplicated(keep=False)
    print(f"\nid_notif: {df['id_notif'].isna().sum():,} nulos | {dup.sum():,} linhas com "
          f"id repetido ({ids[dup].nunique():,} ids, {ids.duplicated().sum():,} excedentes) "
          f"| nada foi removido")
    ev = df["evolucao"].map({1: "1 cura", 2: "2 óbito SRAG", 3: "3 óbito outras",
                             9: "9 ignorado"}).fillna("vazio")
    print("evolucao (%):", (100 * ev.value_counts(normalize=True)).round(1).to_dict())
    print(f"sem desfecho (vazio ou 9): {100 * ev.isin(['vazio', '9 ignorado']).mean():.1f}%")
    print(f"un_inte preenchido: {100 * df['un_inte'].notna().mean():.1f}% | "
          f"nosocomial = 1: {int(df['nosocomial'].sum()):,} casos")


if __name__ == "__main__":
    main()
