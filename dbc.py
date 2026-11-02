"""Leitor de arquivos .dbc do DATASUS em Python puro (sem extensões compiladas).

.dbc = cabeçalho .dbf + 4 bytes de CRC + dados comprimidos em PKWare DCL
(formato "implode"). A descompressão é um porte do `blast.c` de Mark Adler,
usado também pelo pyreaddbc/PySUS. Depois lemos o .dbf com numpy.
"""
import struct

import numpy as np
import pandas as pd

# Tabelas do blast.c (comprimentos de código compactados em repetições)
_LITLEN = bytes([
    11, 124, 8, 7, 28, 7, 188, 13, 76, 4, 10, 8, 12, 10, 12, 10, 8, 23, 8,
    9, 7, 6, 7, 8, 7, 6, 55, 8, 23, 24, 12, 11, 7, 9, 11, 12, 6, 7, 22, 5,
    7, 24, 6, 11, 9, 6, 7, 22, 7, 11, 38, 7, 9, 8, 25, 11, 8, 11, 9, 12,
    8, 12, 5, 38, 5, 38, 5, 11, 7, 5, 6, 21, 6, 10, 53, 8, 7, 24, 10, 27,
    44, 253, 253, 253, 252, 252, 252, 13, 12, 45, 12, 45, 12, 61, 12, 45,
    44, 173])
_LENLEN = bytes([2, 35, 36, 53, 38, 23])
_DISTLEN = bytes([2, 20, 53, 230, 247, 151, 248])
_BASE = [3, 2, 4, 5, 6, 7, 8, 9, 10, 12, 16, 24, 40, 72, 136, 264]
_EXTRA = [0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8]
_MAXBITS = 13


def _construir(rep: bytes):
    """Tabelas de decodificação: lista (por comprimento) de {código: símbolo}."""
    comprimentos = []
    for b in rep:
        comprimentos += [b & 15] * ((b >> 4) + 1)
    tabelas = [dict() for _ in range(_MAXBITS + 1)]
    primeiro = 0
    for ln in range(1, _MAXBITS + 1):
        simbolos = [s for s, c in enumerate(comprimentos) if c == ln]
        for i, s in enumerate(simbolos):
            tabelas[ln][primeiro + i] = s
        primeiro = (primeiro + len(simbolos)) << 1
    return tabelas


_LIT, _LEN, _DIST = _construir(_LITLEN), _construir(_LENLEN), _construir(_DISTLEN)


def explode(dados: bytes, inicio: int = 0) -> bytes:
    """Descomprime um fluxo PKWare DCL começando em dados[inicio]."""
    n = len(dados)
    pos = inicio
    buf = 0   # buffer de bits (LSB primeiro)
    cnt = 0   # bits disponíveis no buffer
    out = bytearray()

    def bits(k):
        nonlocal pos, buf, cnt
        while cnt < k:
            if pos >= n:
                raise EOFError("fim inesperado do fluxo comprimido")
            buf |= dados[pos] << cnt
            pos += 1
            cnt += 8
        v = buf & ((1 << k) - 1)
        buf >>= k
        cnt -= k
        return v

    def decode(tabelas):
        nonlocal pos, buf, cnt
        codigo = 0
        for ln in range(1, _MAXBITS + 1):
            if cnt < ln:
                if pos >= n:
                    raise EOFError("fim inesperado do fluxo comprimido")
                buf |= dados[pos] << cnt
                pos += 1
                cnt += 8
            codigo = (codigo << 1) | (((buf >> (ln - 1)) & 1) ^ 1)
            s = tabelas[ln].get(codigo)
            if s is not None:
                buf >>= ln
                cnt -= ln
                return s
        raise ValueError("código inválido")

    lit = bits(8)
    if lit > 1:
        raise ValueError("cabeçalho DCL inválido (literais)")
    dic = bits(8)
    if dic < 4 or dic > 6:
        raise ValueError("cabeçalho DCL inválido (dicionário)")

    while True:
        if bits(1):
            sim = decode(_LEN)
            comp = _BASE[sim] + bits(_EXTRA[sim])
            if comp == 519:
                break
            desloc = 2 if comp == 2 else dic
            dist = (decode(_DIST) << desloc) + bits(desloc) + 1
            ini = len(out) - dist
            if ini < 0:
                raise ValueError("distância além do início")
            if dist >= comp:
                out += out[ini:ini + comp]
            else:
                out += (out[ini:] * (comp // dist + 1))[:comp]
        else:
            out.append(decode(_LIT) if lit else bits(8))
    return bytes(out)


def dbc_para_dbf(dbc: bytes) -> bytes:
    """Converte o conteúdo de um .dbc no conteúdo de um .dbf."""
    tam_cab = struct.unpack_from("<H", dbc, 8)[0]
    if tam_cab < 32:
        raise ValueError(f"cabeçalho .dbc implausível ({tam_cab})")
    cab = bytearray(dbc[:tam_cab])
    cab[tam_cab - 1] = 0x0D
    return bytes(cab) + explode(dbc, tam_cab + 4)


def ler_dbf(dbf: bytes, colunas=None, codificacao="latin-1") -> pd.DataFrame:
    """Lê um .dbf (campos de texto) com numpy. `colunas`: nomes a manter."""
    nrec, tam_cab, tam_reg = struct.unpack_from("<IHH", dbf, 4)
    nrec = min(nrec, (len(dbf) - tam_cab) // tam_reg)
    campos, desloc, pos = [], 1, 32  # 1 byte inicial = marca de exclusão
    while pos < tam_cab - 1 and dbf[pos] != 0x0D:
        nome = dbf[pos:pos + 11].split(b"\x00")[0].decode("ascii", "ignore")
        ln = dbf[pos + 16]
        campos.append((nome, desloc, ln))
        desloc += ln
        pos += 32
    mat = np.frombuffer(dbf, dtype=np.uint8, count=nrec * tam_reg,
                        offset=tam_cab).reshape(nrec, tam_reg)
    dados = {}
    for nome, off, ln in campos:
        if colunas is None or nome in colunas:
            col = np.ascontiguousarray(mat[:, off:off + ln]).view(f"S{ln}").ravel()
            dados[nome] = np.char.strip(np.char.decode(col, codificacao))
    return pd.DataFrame(dados)


def ler_dbc(caminho, colunas=None) -> pd.DataFrame:
    with open(caminho, "rb") as f:
        return ler_dbf(dbc_para_dbf(f.read()), colunas)
