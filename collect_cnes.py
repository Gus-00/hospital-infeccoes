"""Leitos do CNES (arquivo LT) direto do FTP do DATASUS -> data/real/leitos.parquet.
Pega a competência (mês) mais recente publicada para cada UF de config.UF_ALVO.
Uso: python collect_cnes.py
"""
import ftplib
import re
from pathlib import Path

import pandas as pd

from collect_sih import UFS_BR
from config import RAW, REAL, UF_ALVO
from dbc import ler_dbc

HOST = "ftp.datasus.gov.br"
PASTAS = ["/dissemin/publicos/CNES/200508_/Dados/LT"]
COLS = {"CNES", "CODUFMUN", "TP_LEITO", "CODLEITO", "QT_EXIST", "QT_CONTR",
        "QT_SUS", "QT_NSUS", "COMPETEN"}
DESTINO = RAW / "cnes"


def conectar():
    ftp = ftplib.FTP(HOST, timeout=60)
    ftp.login()
    ftp.set_pasv(True)
    for pasta in PASTAS:
        try:
            ftp.cwd(pasta)
            return ftp
        except ftplib.error_perm:
            continue
    try:  # ajuda a diagnosticar se o DATASUS mudou a estrutura de pastas
        ftp.cwd("/dissemin/publicos/CNES/200508_/Dados")
        print("Pasta LT não encontrada. Conteúdo de .../Dados:", ftp.nlst()[:30])
    except ftplib.all_errors as e:
        print("Não consegui listar /dissemin/publicos/CNES:", e)
    raise SystemExit("Estrutura do FTP do CNES diferente do esperado.")


def nome_lt_valido(nome: str, uf: str) -> bool:
    """Aceita só LT{uf}AAMM.DBC (sem diferenciar maiúsculas/minúsculas)."""
    return re.fullmatch(rf"LT{re.escape(uf)}[0-9]{{4}}\.DBC", nome, re.IGNORECASE) is not None


def destino_seguro(nome: str) -> Path:
    """Caminho local do arquivo; recusa nomes que saiam da pasta DESTINO."""
    destino = DESTINO / nome
    if destino.resolve().parent != DESTINO.resolve():
        raise SystemExit(f"Nome de arquivo suspeito do FTP do CNES: {nome!r}")
    return destino


def processar(df: pd.DataFrame, uf: str) -> pd.DataFrame:
    num = lambda c: pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)
    return pd.DataFrame({
        "uf": uf,
        "cnes": df["CNES"],
        "cod_mun": df["CODUFMUN"].astype(str).str[:6],
        "tp_leito": num("TP_LEITO"),
        "codleito": num("CODLEITO"),
        "qt_exist": num("QT_EXIST"),
        "qt_sus": num("QT_SUS"),
        "competencia": df["COMPETEN"] if "COMPETEN" in df else None,
    })


def main():
    ftp = conectar()
    nomes = ftp.nlst()
    partes = []
    for uf in (UF_ALVO or UFS_BR):
        cand = sorted(n for n in nomes if nome_lt_valido(n, uf))
        if not cand:
            print(f"CNES {uf}: nenhum arquivo LT encontrado")
            continue
        nome = cand[-1]  # AAMM mais recente (ordenação lexicográfica = cronológica)
        DESTINO.mkdir(parents=True, exist_ok=True)
        destino = destino_seguro(nome)
        if not destino.exists():
            with open(destino, "wb") as f:
                ftp.retrbinary(f"RETR {nome}", f.write)
        df = processar(ler_dbc(destino, COLS), uf)
        partes.append(df)
        print(f"CNES {uf} ({nome}): {len(df):,} registros de leitos, "
              f"{df['qt_exist'].sum():,} leitos existentes")
    ftp.quit()
    if not partes:
        raise SystemExit("Nada coletado.")
    REAL.mkdir(parents=True, exist_ok=True)
    pd.concat(partes, ignore_index=True).to_parquet(REAL / "leitos.parquet", index=False)
    print("leitos.parquet salvo")


if __name__ == "__main__":
    main()
