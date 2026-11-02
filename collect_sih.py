"""Baixa internações do SIH/SUS (AIH reduzida, grupo RD) direto do FTP do DATASUS
e salva data/real/sih.parquet, filtrado para os grupos de CID de config.GRUPOS_CID.

Não usa PySUS nem extensões compiladas: baixa os .dbc por ftplib e lê com dbc.py.
Os .dbc ficam em data/raw/sih/ (apague a pasta para forçar novo download).

Uso:  python collect_sih.py
"""
import ftplib
import time

import pandas as pd

from config import ANOS, GRUPOS_CID, RAW, REAL, UF_ALVO
from dbc import ler_dbc

HOST = "ftp.datasus.gov.br"
PASTA = "/dissemin/publicos/SIHSUS/200801_/Dados"
UFS_BR = ["AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT",
          "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO",
          "RR", "SC", "SP", "SE", "TO"]
COLS = {"MUNIC_RES", "DIAG_PRINC", "DT_INTER", "DT_SAIDA", "DIAS_PERM", "MORTE",
        "UTI_MES_TO", "CNES", "VAL_TOT", "N_AIH", "MUNIC_MOV", "IDENT"}
OBRIGATORIAS = ["DIAG_PRINC", "DT_INTER", "MUNIC_RES"]
DESTINO = RAW / "sih"


def grupo_do_cid(cid: str):
    """Grupo de config.GRUPOS_CID do CID (sem ponto). Cada intervalo compara o
    prefixo do CID com o tamanho dos seus limites (3 ou 4 caracteres)."""
    for nome, intervalos in GRUPOS_CID.items():
        for ini, fim in intervalos:
            prefixo = cid[:len(ini)]
            if len(prefixo) == len(ini) and ini <= prefixo <= fim:
                return nome
    return None


def para_data(s: pd.Series) -> pd.Series:
    d = pd.to_datetime(s, format="%Y%m%d", errors="coerce")
    if d.isna().all():
        d = pd.to_datetime(s, errors="coerce")
    return d


def limpar(df: pd.DataFrame, uf: str, competencia: str | None = None) -> pd.DataFrame:
    faltando = [c for c in OBRIGATORIAS if c not in df.columns]
    if faltando:
        raise KeyError(f"colunas ausentes {faltando}; disponíveis: {list(df.columns)[:40]}")
    df = df.copy()
    df["cid4"] = df["DIAG_PRINC"].astype(str).str.strip().str.upper().str[:4]
    df["cid3"] = df["cid4"].str[:3]
    mapa = {c: grupo_do_cid(c) for c in df["cid4"].unique()}
    df["grupo"] = df["cid4"].map(mapa)
    df = df.dropna(subset=["grupo"])
    num = lambda c: pd.to_numeric(df[c], errors="coerce") if c in df else pd.NA
    txt = lambda c, n=None: (df[c].astype(str).str[:n] if c in df else None)
    out = pd.DataFrame({
        "dt_inter": para_data(df["DT_INTER"]),
        "uf": uf,
        "cod_mun": df["MUNIC_RES"].astype(str).str[:6],
        "cid3": df["cid3"],
        "cid4": df["cid4"],
        "grupo": df["grupo"],
        "dias_perm": num("DIAS_PERM"),
        "morte": num("MORTE") == 1,
        "uti_dias": num("UTI_MES_TO"),
        "cnes": df["CNES"] if "CNES" in df else None,
        "valor": num("VAL_TOT"),
        "n_aih": txt("N_AIH"),
        "mun_mov": txt("MUNIC_MOV", 6),  # município do hospital
        "ident": txt("IDENT"),           # 1 = AIH normal, 5 = longa permanência
        "competencia": competencia,      # AAAAMM do arquivo (mês de processamento)
    })
    return out.dropna(subset=["dt_inter"])


def relatorio(df: pd.DataFrame):
    """Conferências impressas ao final; não altera o DataFrame."""
    print("\nCOVID-19 por cid4 (B342 e U07*):")
    covid = df[df["cid4"].str.startswith(("B342", "U07"))]
    cont = covid["cid4"].value_counts().sort_index()
    for cid, n in cont.items():
        print(f"  {cid}: {n:,}")
    if cont.empty:
        print("  nenhuma! confira GRUPOS_CID em config.py")

    print("\nN_AIH repetidos (nada foi removido):")
    rep = df[df["n_aih"].duplicated(keep=False)]
    if rep.empty:
        print("  nenhum n_aih repetido")
        return
    por_aih = rep.groupby("n_aih").agg(linhas=("n_aih", "size"),
                                       meses=("competencia", "nunique"))
    print(f"  {len(por_aih):,} n_aih aparecem mais de uma vez ({len(rep):,} linhas, "
          f"{len(rep) - len(por_aih):,} excedentes)")
    for meses, n in por_aih["meses"].value_counts().sort_index().items():
        print(f"  em {meses} mês(es) diferente(s): {n:,} n_aih")
    print(f"  linhas repetidas por IDENT (5 = longa permanência): "
          f"{rep['ident'].value_counts().to_dict()}")


def conectar() -> ftplib.FTP:
    ftp = ftplib.FTP(HOST, timeout=60)
    ftp.login()
    ftp.set_pasv(True)
    ftp.cwd(PASTA)
    return ftp


def baixar(ftp, nome: str):
    destino = DESTINO / nome
    if destino.exists() and destino.stat().st_size > 0:
        return destino
    DESTINO.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(".part")
    with open(tmp, "wb") as f:
        ftp.retrbinary(f"RETR {nome}", f.write)
    tmp.replace(destino)
    return destino


def main():
    try:
        ftp = conectar()
        remotos = {n.upper(): n for n in ftp.nlst()}
        print(f"FTP ok: {len(remotos):,} arquivos na pasta do SIH")
    except ftplib.all_errors as e:
        # sem FTP: processa só os .dbc já baixados
        ftp = None
        remotos = {p.name.upper(): p.name for p in DESTINO.glob("*.dbc")}
        print(f"AVISO: FTP indisponível ({type(e).__name__}: {e}); "
              f"usando {len(remotos)} .dbc locais em {DESTINO}")
    partes, ausentes, erros = [], 0, 0
    for uf in (UF_ALVO or UFS_BR):
        for ano in ANOS:
            for mes in range(1, 13):
                nome = f"RD{uf}{ano % 100:02d}{mes:02d}.dbc"
                if nome.upper() not in remotos:
                    ausentes += 1  # mês ainda não publicado
                    continue
                try:
                    for tentativa in range(3):
                        try:
                            caminho = baixar(ftp, remotos[nome.upper()])
                            break
                        except (ftplib.all_errors, OSError):
                            time.sleep(3)
                            ftp = conectar()
                    else:
                        raise ConnectionError("falhou 3 vezes")
                    bruto = ler_dbc(caminho, COLS)
                    parte = limpar(bruto, uf, f"{ano}{mes:02d}")
                    partes.append(parte)
                    print(f"SIH {uf} {ano}-{mes:02d}: {len(bruto):,} AIH, {len(parte):,} no escopo")
                except Exception as e:
                    erros += 1
                    print(f"SIH {uf} {ano}-{mes:02d}: ERRO ({type(e).__name__}: {str(e)[:100]})")
    try:
        if ftp is not None:
            ftp.quit()
    except Exception:
        pass
    if not partes:
        raise SystemExit("Nada processado. Veja as mensagens acima.")
    df = pd.concat(partes, ignore_index=True)
    # AIHs processadas em 2023-01 incluem internações de meses anteriores: recorta
    inicio = pd.Timestamp(f"{min(ANOS)}-01-01")
    antes = len(df)
    df = df[df["dt_inter"] >= inicio]
    print(f"\ncorte dt_inter >= {inicio.date()}: {antes - len(df):,} linhas removidas")
    relatorio(df)
    REAL.mkdir(parents=True, exist_ok=True)
    df.to_parquet(REAL / "sih.parquet", index=False)
    print(f"\nsih.parquet: {len(df):,} linhas | meses não publicados: {ausentes} | erros: {erros}")
    print(f"  dt_inter de {df['dt_inter'].min().date()} a {df['dt_inter'].max().date()}")


if __name__ == "__main__":
    main()
