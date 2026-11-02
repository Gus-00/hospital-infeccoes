"""Gera dados FICTÍCIOS (sazonalidade plausível, números inventados) só para
testar o dashboard sem baixar nada. Escreve em data/demo/.
Uso: python demo_data.py
"""
import numpy as np
import pandas as pd

from config import DEMO

rng = np.random.default_rng(42)
MUNS = {"230440": ("Fortaleza", 0.40), "230370": ("Caucaia", 0.08),
        "230765": ("Maracanaú", 0.08), "231290": ("Sobral", 0.08),
        "230730": ("Juazeiro do Norte", 0.08), "230410": ("Crato", 0.05),
        "230690": ("Itapipoca", 0.05), "230770": ("Maranguape", 0.05),
        "230640": ("Iguatu", 0.05), "231130": ("Quixadá", 0.08)}
DIAS = pd.date_range("2023-01-01", "2026-09-30")
mes = DIAS.month.values


def sazonal(pico, largura=2.2):
    d = np.minimum(abs(mes - pico), 12 - abs(mes - pico))
    return 0.5 + 1.5 * np.exp(-(d ** 2) / (2 * largura ** 2))


def gerar_sih():
    cfg = {  # grupo: (CID de exemplo, casos/dia, sazonalidade, perm. média, letalidade)
        "Tuberculose (A15-A19)": ("A150", 2.0, np.ones(len(DIAS)), 14, 0.07),
        "Infecções intestinais virais/presumidas (A08-A09)": ("A09", 3.0, sazonal(2), 3, 0.005),
        "Infecções agudas de vias aéreas superiores (J00-J06)": ("J069", 1.2, sazonal(5), 2, 0.001),
        "Influenza e pneumonias (J09-J18)": ("J189", 9.0, sazonal(5), 6, 0.09),
        "Bronquite/bronquiolite aguda (J20-J22)": ("J219", 3.0, sazonal(5), 4, 0.01),
        "COVID-19 (B34.2 e U07)": ("B342", 0.8, sazonal(4), 8, 0.12),
    }
    linhas = []
    cods, pesos = list(MUNS), np.array([v[1] for v in MUNS.values()])
    for grupo, (cid, lam, saz, perm, let) in cfg.items():
        n = rng.poisson(lam * saz)
        datas = np.repeat(DIAS.values, n)
        k = len(datas)
        linhas.append(pd.DataFrame({
            "dt_inter": datas, "uf": "CE",
            "cod_mun": rng.choice(cods, k, p=pesos / pesos.sum()),
            "cid3": cid[:3], "cid4": cid, "grupo": grupo,
            "dias_perm": rng.gamma(2.0, perm / 2.0, k).round().clip(1),
            "morte": rng.random(k) < let,
            "uti_dias": 0.0, "cnes": "0000000", "valor": 0.0,
            "mun_mov": "230440", "ident": "1",
            "competencia": pd.DatetimeIndex(datas).strftime("%Y%m")}))
    df = pd.concat(linhas, ignore_index=True)
    df["n_aih"] = [f"DEMO{i:09d}" for i in range(len(df))]
    return df


def gerar_srag():
    base = rng.poisson(14 * sazonal(5))
    datas = np.repeat(DIAS.values, base)
    k = len(datas)
    agente = rng.choice(
        ["Influenza", "COVID-19", "Outro vírus respiratório", "Outro agente",
         "Não especificado"], k, p=[0.25, 0.2, 0.2, 0.15, 0.2])
    cods, pesos = list(MUNS), np.array([v[1] for v in MUNS.values()])
    idade = np.where(rng.random(k) < 0.3, rng.gamma(2, 1.2, k),
                     rng.gamma(6, 9, k)).clip(0, 100)
    evolucao = rng.choice([1, 2, 3, 9], k, p=[0.78, 0.12, 0.03, 0.07])
    return pd.DataFrame({
        "id_notif": [f"DEMO{i:09d}" for i in range(k)],
        "dt_notific": datas, "uf": "CE",
        "cod_mun": rng.choice(cods, k, p=pesos / pesos.sum()),
        "sexo": rng.choice(["M", "F"], k), "idade": idade,
        "internado": True, "uti": rng.random(k) < 0.28,
        "obito": evolucao == 2, "evolucao": pd.array(evolucao, dtype="Int64"),
        "agente": agente, "nosocomial": rng.random(k) < 0.02,
        "un_inte": "HOSPITAL DEMO", "cod_mun_inte": "230440"})


def main():
    DEMO.mkdir(parents=True, exist_ok=True)
    gerar_sih().to_parquet(DEMO / "sih.parquet", index=False)
    gerar_srag().to_parquet(DEMO / "srag.parquet", index=False)
    pd.DataFrame([{"cod_mun": c, "municipio": n, "uf": "CE"}
                  for c, (n, _) in MUNS.items()]).to_parquet(
        DEMO / "municipios.parquet", index=False)
    pop = {"230440": 2_500_000, "230370": 370_000, "230765": 230_000, "231290": 210_000,
           "230730": 280_000, "230410": 135_000, "230690": 140_000, "230770": 120_000,
           "230640": 105_000, "231130": 90_000}
    pd.DataFrame([{"cod_mun": c, "populacao": p, "ano_pop": 2025}
                  for c, p in pop.items()]).to_parquet(DEMO / "populacao.parquet", index=False)
    linhas = []
    for c, (n, w) in MUNS.items():
        for h in range(max(1, int(w * 12))):
            for tp, cod, q in [(2, 33, 40), (3, 75, 10), (3, 3, 4), (5, 45, 12)]:
                linhas.append({"uf": "CE", "cnes": f"{c}{h:02d}", "cod_mun": c, "tp_leito": tp,
                               "codleito": cod, "qt_exist": int(rng.integers(1, q + 1) * w * 5 + 1),
                               "qt_sus": int(rng.integers(1, q + 1) * w * 4 + 1),
                               "competencia": "202608"})
    pd.DataFrame(linhas).to_parquet(DEMO / "leitos.parquet", index=False)
    print("dados demo gerados em", DEMO)


if __name__ == "__main__":
    main()
