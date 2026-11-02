"""Configuração central do projeto. Edite aqui."""
from pathlib import Path

ROOT = Path(__file__).parent
REAL = ROOT / "data" / "real"
DEMO = ROOT / "data" / "demo"
RAW = ROOT / "data" / "raw"

# UFs a coletar. Lista vazia = Brasil inteiro (SIH nacional é MUITO pesado).
UF_ALVO = ["CE"]
ANOS = [2023, 2024, 2025, 2026]

# --- SRAG (SIVEP-Gripe, Dados Abertos do SUS) ---------------------------------
# Os nomes dos arquivos têm data e mudam toda semana. Se uma URL der 404, abra
# https://dadosabertos.saude.gov.br/dataset/srag-2019-a-2026 , entre no ano e
# copie o campo "URL" do recurso.
SRAG_URLS: list[str] = [
    "https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/SRAG/2023/INFLUD23-23-03-2026.csv",
    "https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/SRAG/2024/INFLUD24-23-03-2026.csv",
    "https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/SRAG/2025/INFLUD25-28-09-2026.csv",
    "https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/SRAG/2026/INFLUD26-12-10-2026.csv",
]
SRAG_DATASET_PAGES: list[str] = []  # descoberta automática desativada

# --- Grupos de CID-10 ------------------------------------------------------------
# nome -> lista de intervalos (ini, fim), inclusivos, sem ponto. Cada intervalo
# compara o prefixo do CID com o mesmo tamanho dos limites (3 = categoria,
# 4 = subcategoria); ini e fim de um intervalo devem ter o mesmo tamanho.
# COVID-19: no SIH a internação é registrada em B34.2 (Portaria SAES/MS 245/2020);
# U07 quase não aparece no DIAG_PRINC.
GRUPOS_CID: dict[str, list[tuple[str, str]]] = {
    "Tuberculose (A15-A19)": [("A15", "A19")],
    "Infecções intestinais virais/presumidas (A08-A09)": [("A08", "A09")],
    "Infecções agudas de vias aéreas superiores (J00-J06)": [("J00", "J06")],
    "Influenza e pneumonias (J09-J18)": [("J09", "J18")],
    "Bronquite/bronquiolite aguda (J20-J22)": [("J20", "J22")],
    "COVID-19 (B34.2 e U07)": [("B342", "B342"), ("U07", "U07")],
}

# Grupos que, por padrão, a aba "Demanda de isolamento" considera.
# Você decide quais exigem pressão negativa no seu projeto.
ISOLAMENTO_PADRAO = ["Tuberculose (A15-A19)"]

# --- CNES (leitos) --------------------------------------------------------------
# Códigos CODLEITO que representam leitos de isolamento no CNES. Fica vazio de
# propósito: confira na tabela de leitos do CNES (cnes.datasus.gov.br) e preencha,
# ex.: [3, 12]. Sem isso, a aba de leitos mostra o total por tipo de leito.
LEITOS_ISOLAMENTO_CODLEITO: list[int] = []
