# Infecções hospitalares e demanda de isolamento (dados públicos do Brasil)

Coleta dados públicos de tuberculose, infecções virais e de vias aéreas e mostra tudo
em um painel Streamlit, com uma estimativa de demanda por salas de isolamento.

## Fontes e scripts
| Script | Fonte | Saída (`data/real/`) |
|---|---|---|
| `collect_ibge.py` | API de localidades e SIDRA (IBGE): municípios e população estimada | `municipios.parquet`, `populacao.parquet` |
| `collect_srag.py` | SIVEP-Gripe (SRAG), Dados Abertos do SUS (CSV) | `srag.parquet` |
| `collect_sih.py` | SIH/SUS (AIH reduzida) via FTP do DATASUS, filtrado por CID-10 | `sih.parquet` |
| `collect_cnes.py` | CNES, leitos (LT), competência mais recente | `leitos.parquet` |
| `dbc.py` | Leitor de `.dbc` em Python puro (sem extensões compiladas) | — |

## Como rodar
```powershell
pip install -r requirements.txt
python atualizar_tudo.py        # roda os 4 coletores (ou um a um)
streamlit run app.py
```
`python demo_data.py` gera dados FICTÍCIOS para testar o painel (fonte "DEMO").

## Configuração (`config.py`)
- `UF_ALVO`, `ANOS`: escopo da coleta (`UF_ALVO = []` = Brasil inteiro, pesado no SIH).
- `SRAG_URLS`: URLs dos CSVs (mudam toda semana; copie de
  dadosabertos.saude.gov.br/dataset/srag-2019-a-2026 se der 404).
- `GRUPOS_CID`, `ISOLAMENTO_PADRAO`: doenças analisadas e as que contam como isolamento.
- `LEITOS_ISOLAMENTO_CODLEITO`: códigos de leito de isolamento do CNES (preencher).

## Painel
1. **Internações (SIH):** série semanal, sazonalidade, ranking de municípios (absoluto ou por 100 mil hab.), mapa.
2. **SRAG:** casos por agente, gravidade, faixa etária.
3. **Demanda de isolamento:** pacientes simultâneos estimados = admissões × permanência; salas para cobrir o P90.
4. **Leitos (CNES):** leitos existentes e SUS por tipo e município.

## Limitações conhecidas
- Dados recentes são incompletos (AIH é faturada depois; SRAG é notificada com atraso): o painel oculta os últimos meses/semanas por padrão (barra lateral).
- SIH conta internações pelo município de residência; UF = local do hospital.
- SRAG: grande parte dos casos fica como "Não especificado".
- SRAG: os CSVs públicos (2023-2026) não trazem o código CNES da unidade; o parquet guarda o nome (`un_inte`) e o município de internação (`cod_mun_inte`).
- SIH: COVID-19 é registrada em B34.2 (Portaria SAES/MS 245/2020), não só em U07. `N_AIH` pode repetir entre meses (AIH de longa permanência, `ident = 5`).
- Não há dado público de IRAS (infecção adquirida no hospital) em microdados.
- A estimativa de demanda é um ponto de partida de dimensionamento, não substitui dados do hospital nem a norma (RDC 50/ANVISA, ABNT NBR 7256).
- Testado com dados sintéticos; coletores de população (SIDRA) e leitos (CNES) ainda não testados contra os servidores reais.
