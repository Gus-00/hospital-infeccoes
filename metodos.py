"""Texto da aba Métodos (markdown), gerado de config e do estado atual dos dados e filtros."""
from pathlib import PurePosixPath
from urllib.parse import urlparse

from config import ANOS, GRUPOS_CID, LEITOS_ISOLAMENTO_CODLEITO, SRAG_URLS, UF_ALVO
from estilo import fmt_dec, fmt_int

# Sigla -> nome com a preposição contraída de uso corrente ("no Ceará", "na Bahia")
LOCAL_UF = {
    "AC": "no Acre", "AL": "em Alagoas", "AP": "no Amapá", "AM": "no Amazonas",
    "BA": "na Bahia", "CE": "no Ceará", "DF": "no Distrito Federal",
    "ES": "no Espírito Santo", "GO": "em Goiás", "MA": "no Maranhão",
    "MT": "em Mato Grosso", "MS": "em Mato Grosso do Sul", "MG": "em Minas Gerais",
    "PA": "no Pará", "PB": "na Paraíba", "PR": "no Paraná", "PE": "em Pernambuco",
    "PI": "no Piauí", "RJ": "no Rio de Janeiro", "RN": "no Rio Grande do Norte",
    "RS": "no Rio Grande do Sul", "RO": "em Rondônia", "RR": "em Roraima",
    "SC": "em Santa Catarina", "SP": "em São Paulo", "SE": "em Sergipe",
    "TO": "no Tocantins",
}
MALHA = "Malha municipal com regiões e macrorregiões de saúde, 2023 (IPEA, pacote geobr)"


def _juntar(itens: list[str]) -> str:
    return itens[0] if len(itens) == 1 else ", ".join(itens[:-1]) + " e " + itens[-1]


def local_ufs(ufs) -> str:
    if not ufs:
        return "(nenhuma UF selecionada)"
    return _juntar([LOCAL_UF.get(u, f"em {u}") for u in ufs])


def fmt_comp(comp) -> str:
    """Competência AAAAMM -> MM/AAAA."""
    comp = "" if comp is None else str(comp)
    return f"{comp[4:6]}/{comp[:4]}" if len(comp) == 6 and comp.isdigit() else (comp or "não disponível")


def _cid(cod: str) -> str:
    return f"{cod[:3]}.{cod[3:]}" if len(cod) > 3 else cod


def codigos_cid(intervalos) -> str:
    return "; ".join(_cid(a) if a == b else f"{_cid(a)}-{_cid(b)}" for a, b in intervalos)


def arquivos_srag() -> list[str]:
    return [PurePosixPath(urlparse(u).path).name for u in SRAG_URLS]


def _periodo(cob) -> str:
    if cob is None:
        return "sem dados no filtro"
    ini, fim, anos = cob
    return f"{ini:%d/%m/%Y} a {fim:%d/%m/%Y} ({fmt_dec(anos, 2)} anos de observação)"


def _n(cortes: dict, chave: str) -> str:
    v = cortes.get(chave)
    return "não calculado" if v is None else fmt_int(v)


def texto_metodos(ufs, cobertura, comp_cnes=None, ano_pop=None, n_mes=0, n_sem=0,
                  cortes=None, municipios=None, grupos=None, isolamento=None,
                  demo=False) -> str:
    """cobertura: {"sih"|"srag": (inicio, fim, anos) ou None}; cortes: contagens do que saiu.
    isolamento: (grupos, participação %) da aba de demanda, se calculada."""
    c = cortes or {}
    cob_sih, cob_srag = cobertura.get("sih"), cobertura.get("srag")
    linhas = []
    if demo:
        linhas += ["> **Atenção: dados FICTÍCIOS (modo demo).** Os números abaixo não são reais.", ""]

    # ------------------------------------------------------------ fontes
    linhas += [
        "## Fontes de dados", "",
        f"- **SIH/SUS, AIH reduzida (DATASUS).** Arquivos `RD{{UF}}{{AA}}{{MM}}.dbc` (grupo RD) "
        "baixados do FTP do DATASUS (`ftp.datasus.gov.br/dissemin/publicos/SIHSUS/200801_/Dados`) "
        f"para {', '.join(UF_ALVO) or 'todas as UFs'} e os anos {min(ANOS)} a {max(ANOS)}; "
        "seleção pelo diagnóstico principal (`DIAG_PRINC`) nos grupos de CID-10 da tabela abaixo.",
        "- **SIVEP-Gripe, SRAG (OpenDataSUS).** Conjunto \"srag-2019-a-2026\" do portal "
        "dadosabertos.saude.gov.br. Arquivos usados: "
        + "; ".join(f"`{a}`" for a in arquivos_srag()) + ".",
        f"- **CNES, leitos (DATASUS).** Arquivo LT, competência {fmt_comp(comp_cnes)}.",
        "- **IBGE.** Municípios (API de localidades) e população residente estimada (SIDRA, "
        f"tabela 6579), ano {ano_pop if ano_pop is not None else 'não disponível'}.",
        f"- **Malha.** {MALHA}.",
        "",
    ]

    # ------------------------------------------------------------ definições
    linhas += ["## Definições", "", "| Grupo de causa | Códigos CID-10 (diagnóstico principal) |",
               "|---|---|"]
    linhas += [f"| {g} | {codigos_cid(iv)} |" for g, iv in GRUPOS_CID.items()]
    linhas += [
        "",
        "- Semana epidemiológica: domingo a sábado, identificada pela data do domingo inicial.",
        "- Data de referência: SIH = data de internação (`dt_inter`); SRAG = data de "
        "notificação (`dt_notific`).",
        "- Local: SIH conta a internação pelo município de **residência** (`MUNIC_RES`); a UF é "
        "a do arquivo, isto é, a do hospital. SRAG conta o caso pelo município de "
        "**notificação** (`CO_MUN_NOT`).",
        "- Agente da SRAG pela classificação final (`CLASSI_FIN`): 1 = Influenza, 2 = Outro "
        "vírus respiratório, 3 = Outro agente, 4 = Não especificado, 5 = COVID-19; "
        "campo vazio ou fora de 1 a 5 = Em investigação.",
        "- Gravidade da SRAG: UTI (%) = casos com `UTI` = 1 sobre todos os casos (ignorado ou "
        "vazio conta como não); Óbito (%) = `EVOLUCAO` = 2 (óbito por SRAG) sobre todos os casos, "
        "inclusive sem evolução registrada; óbito por outras causas (3) não entra. O CSV do "
        "resumo traz as contagens e o n com evolução conhecida (1, 2 ou 3).",
        f"- Período efetivo de cada fonte dentro do filtro: SIH {_periodo(cob_sih)}; "
        f"SRAG {_periodo(cob_srag)}. Cada taxa usa o período da própria fonte.",
        "",
    ]

    # ------------------------------------------------------------ exclusões
    if n_mes:
        desde = c.get("sih_oculto_desde")
        oculto_sih = ("último mês oculto" if n_mes == 1 else f"últimos {n_mes} meses ocultos")
        oculto_sih += (" por faturamento incompleto da AIH"
                       + (f" (internações a partir de {desde:%d/%m/%Y})" if desde is not None else "")
                       + f"; internações ocultas (na base carregada, antes dos filtros): "
                         f"{_n(c, 'sih_oculto')}")
    else:
        oculto_sih = "nenhum mês oculto"
    if n_sem:
        apos = c.get("srag_oculto_apos")
        oculto_srag = ("última semana oculta" if n_sem == 1 else f"últimas {n_sem} semanas ocultas")
        oculto_srag += (" por atraso de notificação"
                        + (f" (notificações depois de {apos:%d/%m/%Y})" if apos is not None else "")
                        + f"; casos ocultos (na base carregada, antes dos filtros): "
                          f"{_n(c, 'srag_oculto')}")
    else:
        oculto_srag = "nenhuma semana oculta"
    linhas += [
        "## Exclusões e cortes aplicados", "",
        f"- SIH, internações anteriores a 01/01/{min(ANOS)} (o arquivo de janeiro de "
        f"{min(ANOS)} traz internações do ano anterior), removidas na carga: {_n(c, 'sih_antes')}.",
        f"- SIH, {oculto_sih}.",
        f"- SRAG, {oculto_srag}.",
        "- Mapa, registros com município fora da malha (outras UFs ou código inválido): "
        f"internações do SIH, {_n(c, 'sih_fora_mapa')}; casos de SRAG, {_n(c, 'srag_fora_mapa')}.",
        f"- Mapa, municípios da malha sem população: {_n(c, 'mun_sem_pop')}; a unidade que "
        "contém algum deles fica sem taxa (cinza).",
        f"- SRAG, casos sem idade válida (ausente ou fora de 0 a 120 anos): "
        f"{_n(c, 'srag_sem_idade')}; não entram na Figura 6.",
        f"- Filtros atuais: UF(s) {', '.join(ufs) if ufs else 'nenhuma'}; municípios "
        + (", ".join(municipios) if municipios else "todos")
        + "; grupos de causa do SIH "
        + ("todos" if grupos is None or set(grupos) == set(GRUPOS_CID) else
           (", ".join(grupos) if grupos else "nenhum")) + ".",
        "",
    ]

    # ------------------------------------------------------------ fórmulas
    linhas += [
        "## Fórmulas", "",
        "Anos de observação $a$ = (dias do período efetivo da fonte, contando o último) / 365,25.",
        "",
        "Taxa bruta por 100 mil habitantes por ano, com $c_i$ eventos e população $P_i$:",
        "",
        r"$$T_i = \frac{c_i}{P_i \, a} \times 100.000$$",
        "",
        "Taxa suavizada por bayesiano empírico global (Marshall, 1991), com $n_i = P_i a$:",
        "",
        r"$$r_i = \frac{c_i}{n_i}, \quad m = \frac{\sum c_i}{\sum n_i}, \quad "
        r"s^2 = \frac{\sum n_i (r_i - m)^2}{\sum n_i}$$",
        "",
        r"$$A = \max\left(s^2 - \frac{m}{\bar{n}},\ 0\right), \quad "
        r"w_i = \frac{A}{A + m / n_i}, \quad \hat{\theta}_i = \left[w_i r_i + (1 - w_i)\, m\right] \times 100.000$$",
        "",
        r"Leitos por 10 mil habitantes = leitos existentes / $P_i$ $\times$ 10.000.",
        "",
        "Ocupação média (Lei de Little): pacientes simultâneos = admissões por dia × "
        "permanência média, vezes a participação do hospital na região:",
        "",
        r"$$L_s = \frac{\text{admissões na semana } s}{7} \times \bar{W} \times p$$",
        "",
        "P90: percentil 90 da série semanal de $L_s$ (interpolação linear); salas para "
        r"cobrir o P90 = $\lceil P_{90} \rceil$. Semanas sem admissões entram com zero. As "
        "semanas incompletas nas bordas do período (por exemplo, a cobertura do SIH termina "
        "no meio da semana) também são divididas por 7, o que baixa um pouco a média e o P90.",
    ]
    if isolamento:
        g_iso, share = isolamento
        linhas += ["", f"Configuração atual: grupos {', '.join(g_iso) or 'nenhum'}; "
                        f"participação $p$ = {fmt_dec(share, 1)}%."]
    linhas.append("")

    # ------------------------------------------------------------ limitações
    pct = ""
    if c.get("srag_pct_nao_esp") is not None:
        pct = (f" No filtro atual, {fmt_dec(c['srag_pct_nao_esp'], 1)}% dos casos estão como "
               f"\"Não especificado\" e {fmt_dec(c.get('srag_pct_investig', 0), 1)}% como "
               "\"Em investigação\".")
    linhas += [
        "## Limitações", "",
        "- Dados recentes são incompletos (a AIH é faturada depois; a SRAG é notificada com "
        "atraso). O painel oculta os últimos meses/semanas (contagens acima); não há "
        "correção por nowcasting.",
        "- SIH e SRAG usam locais diferentes (residência x notificação) e períodos efetivos "
        "diferentes; as taxas das duas fontes não são diretamente comparáveis.",
        "- SIH: a unidade é a AIH, não o paciente. `N_AIH` pode repetir entre meses (AIH de "
        "longa permanência, `IDENT` = 5) e reinternações contam mais de uma vez.",
        "- SIH: COVID-19 é registrada em B34.2 (Portaria SAES/MS 245/2020); U07 quase não "
        "aparece no diagnóstico principal.",
        "- SRAG: grande parte dos casos fica sem agente definido." + pct,
        "- SRAG: os CSVs públicos de 2023 a 2026 não trazem o código CNES da unidade.",
        f"- A população de um único ano ({ano_pop if ano_pop is not None else '?'}) é o "
        "denominador de todo o período.",
        "- Taxas de municípios pequenos oscilam muito; a suavização bayesiana empírica é "
        "global (não espacial) e só atenua esse efeito.",
        f"- SIH: o numerador é incompleto, pois só são lidos arquivos de hospitais de {', '.join(UF_ALVO)}; "
        "residentes dessas UFs internados em outras UFs não entram, e as taxas por residência ficam "
        "subestimadas, sobretudo em municípios de divisa.",
        "- Taxa de SRAG por município de notificação divide as notificações pela população "
        "residente do município notificador: infla polos de referência (ex.: Fortaleza) e "
        "desinfla a área de abrangência; não é taxa de incidência.",
        "- A primeira e a última semana do período podem estar incompletas.",
        "- Não há dado público de IRAS (infecção adquirida no hospital) em microdados.",
        "- A demanda de isolamento supõe regime estacionário, usa a permanência média do "
        "período inteiro e a participação informada pelo usuário. É ponto de partida de "
        "dimensionamento e não substitui dados do hospital nem a norma (RDC 50/ANVISA, "
        "ABNT NBR 7256).",
    ]
    if not LEITOS_ISOLAMENTO_CODLEITO:
        linhas.append("- CNES: os códigos de leito de isolamento ainda não foram confirmados "
                      "na tabela oficial (`LEITOS_ISOLAMENTO_CODLEITO` vazio); os rótulos de "
                      "tipo de leito (`TP_LEITO`) também não foram conferidos.")
    return "\n".join(linhas) + "\n"
