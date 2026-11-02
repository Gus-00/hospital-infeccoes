"""Dashboard: infecções (TB, virais, vias aéreas) e demanda de isolamento hospitalar.
Rodar:  streamlit run app.py
"""
import math
import textwrap
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import estilo
import metodos
from config import ANOS, DEMO, GRUPOS_CID, ISOLAMENTO_PADRAO, LEITOS_ISOLAMENTO_CODLEITO, REAL
from mapa import (agregar, dissolver, fora_do_mapa, leitos_por_10mil, municipios_sem_pop,
                  periodo_efetivo, resumo_gravidade, taxa_bruta, taxa_eb, taxa_so_na_uf)

st.set_page_config(page_title="Infecções e demanda de isolamento", layout="wide")
MESES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
TIPOS_LEITO = {1: "Cirúrgico", 2: "Clínico", 3: "Complementar (inclui UTI)",
               4: "Obstétrico", 5: "Pediátrico", 6: "Outras especialidades", 7: "Hospital/Dia"}


@st.cache_data(show_spinner=False)
def carregar(base: str):
    b = Path(base)

    def ler(nome):
        p = b / nome
        return pd.read_parquet(p) if p.exists() else pd.DataFrame()

    sih, srag, mun = ler("sih.parquet"), ler("srag.parquet"), ler("municipios.parquet")
    pop, leitos = ler("populacao.parquet"), ler("leitos.parquet")
    nomes = mun.set_index("cod_mun")["municipio"] if not mun.empty else None
    for df in (sih, srag, leitos):
        if not df.empty:
            df["municipio"] = df["cod_mun"].map(nomes).fillna(df["cod_mun"]) if nomes is not None else df["cod_mun"]
    n_antes = 0
    if not sih.empty:
        if "mun_mov" in sih:  # município do hospital (parquets novos)
            sih["municipio_mov"] = sih["mun_mov"].map(nomes).fillna(sih["mun_mov"]) if nomes is not None else sih["mun_mov"]
        sih["dt_inter"] = pd.to_datetime(sih["dt_inter"])
        n0 = len(sih)
        sih = sih[sih["dt_inter"] >= f"{min(ANOS)}-01-01"]  # corta cauda de anos anteriores
        n_antes = n0 - len(sih)  # contado para a aba Métodos
    if not srag.empty:
        srag["dt_notific"] = pd.to_datetime(srag["dt_notific"])
    return sih, srag, pop, leitos, n_antes, mun


def semana(s: pd.Series) -> pd.Series:
    return s.dt.to_period("W-SAT").dt.start_time


def grade_semanas(ini, fim) -> pd.DatetimeIndex:
    """Todas as semanas epidemiológicas (domingo) entre ini e fim."""
    s = semana(pd.Series([pd.Timestamp(ini), pd.Timestamp(fim)]))
    return pd.date_range(s.iloc[0], s.iloc[1], freq="7D")


def contar_semanas(df, col_data, semanas, col_cat=None) -> pd.DataFrame:
    """Contagem semanal (coluna n) com zero nas semanas sem registro: sem isso a linha
    'pula' a semana vazia e a média/P90 da demanda ficam acima do real."""
    sem = semana(df[col_data])
    if col_cat is None:
        return (sem.value_counts().reindex(semanas, fill_value=0)
                .rename_axis("semana").reset_index(name="n"))
    tab = pd.crosstab(sem, df[col_cat]).reindex(semanas, fill_value=0)
    return tab.rename_axis(index="semana", columns=col_cat).stack().reset_index(name="n")


def faixa_etaria(idade: pd.Series) -> pd.Series:
    return pd.cut(idade, [0, 2, 12, 18, 40, 60, 80, 200], right=False,
                  labels=["0-1", "2-11", "12-17", "18-39", "40-59", "60-79", "80+"])


def csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")


def fmt_periodo(cob) -> str:
    return f"{cob[0]:%d/%m/%Y} a {cob[1]:%d/%m/%Y}"


def dec_ou_nd(x) -> str:
    return "sem dado" if pd.isna(x) else estilo.fmt_dec(x)


def mostrar(alvo, fig, nome: str, id_fig: str, fonte_fig: str, nota: str | None = None) -> None:
    """Figura com a config de exportação e a legenda numerada logo abaixo.
    theme=None: o tema "streamlit" sobrescreveria o template "artigo" no navegador."""
    fig.update_layout(plot_bgcolor=estilo.FUNDO, paper_bgcolor=estilo.FUNDO)
    alvo.plotly_chart(fig, width="stretch", theme=None,
                      config=estilo.config_plotly(nome, fig.layout.height))
    alvo.markdown(estilo.legenda(id_fig, fonte_rotulada(fonte_fig), nota))


ARQ_MALHA = REAL / "geo_municipios.parquet"  # malha vale para real e demo (não é fictícia)
NIVEIS_MAPA = {"Município": "municipio", "Região de saúde": "regiao",
               "Macrorregião de saúde": "macro"}
# indicador -> (tipo, rótulo da contagem, fonte); tipos: contagem, taxa, eb, leitos
IND_PADRAO = "Taxa de internação SIH suavizada (bayesiano empírico)"
INDICADORES = {
    "Internações SIH (residência)": ("contagem", "Internações", "sih"),
    "Taxa de internação SIH por 100 mil hab./ano": ("taxa", "Internações", "sih"),
    "Taxa de internação SIH suavizada (bayesiano empírico)": ("eb", "Internações", "sih"),
    "Casos de SRAG (município de notificação)": ("contagem", "Casos", "srag"),
    "Taxa de SRAG por 100 mil hab./ano (município de notificação)": ("taxa", "Casos", "srag"),
    "Leitos existentes por 10 mil hab. (CNES)": ("leitos", "Leitos", "leitos"),
}


@st.cache_resource(show_spinner=False)
def carregar_malha():
    import geopandas as gpd  # import tardio: só a aba Mapa precisa
    return gpd.read_parquet(ARQ_MALHA)


@st.cache_resource(show_spinner=False)
def malha_nivel(nivel: str):
    """Geometria por nível (regiões e macros são dissolvidas uma vez) e seu geojson."""
    g = dissolver(carregar_malha(), nivel)
    return g, g[["chave", "geometry"]].__geo_interface__


# ---------------------------------------------------------------- sidebar
tem_real = (REAL / "sih.parquet").exists() or (REAL / "srag.parquet").exists()
fonte = st.sidebar.radio("Fonte dos dados", ["real", "demo"], index=0 if tem_real else 1,
                         format_func=lambda x: {"real": "Dados reais (coletados)",
                                                "demo": "DEMO (dados fictícios)"}[x])
sih, srag, pop, leitos, n_antes, municipios_ibge = carregar(str(REAL if fonte == "real" else DEMO))
FONTE_SIH = "SIH/SUS, AIH reduzida (DATASUS)"
FONTE_SRAG = "SIVEP-Gripe, SRAG (OpenDataSUS)"


def fonte_rotulada(txt: str) -> str:
    return "DADOS FICTÍCIOS (modo demo); " + txt if fonte == "demo" else txt


if fonte == "demo":
    st.warning("⚠️ Modo DEMO: os números abaixo são FICTÍCIOS, só para testar o painel. "
               "Rode os `collect_*.py` para usar dados reais.")
if sih.empty and srag.empty:
    st.error("Sem dados. Rode `python atualizar_tudo.py` (ou `python demo_data.py` para testar).")
    st.stop()

# Dados recentes são incompletos (AIH é faturada depois; SRAG é notificada com atraso)
st.sidebar.markdown("**Dados recentes incompletos**")
n_mes = st.sidebar.slider("Ocultar últimos meses do SIH", 0, 3, 1,
                          help="Internações dos últimos meses ainda estão sendo faturadas.")
n_sem = st.sidebar.slider("Ocultar últimas semanas do SRAG", 0, 8, 3,
                          help="Notificações de SRAG chegam com atraso.")
cortes = {"sih_antes": n_antes}  # contagens do que saiu, para notas e aba Métodos
nota_oculto_sih = nota_oculto_srag = ""
if not sih.empty and n_mes:
    corte = sih["dt_inter"].max().to_period("M").start_time - pd.DateOffset(months=n_mes - 1)
    cortes.update(sih_oculto=int((sih["dt_inter"] >= corte).sum()), sih_oculto_desde=corte)
    sih = sih[sih["dt_inter"] < corte]
    nota_oculto_sih = (f"{'Último mês oculto' if n_mes == 1 else f'Últimos {n_mes} meses ocultos'} "
                       f"por faturamento incompleto (internações a partir de {corte:%d/%m/%Y}: "
                       f"{estilo.fmt_int(cortes['sih_oculto'])} na base carregada)")
if not srag.empty and n_sem:
    limite = srag["dt_notific"].max() - pd.to_timedelta(n_sem, unit="W")
    cortes.update(srag_oculto=int((srag["dt_notific"] > limite).sum()), srag_oculto_apos=limite)
    srag = srag[srag["dt_notific"] <= limite]
    nota_oculto_srag = (f"{'Última semana oculta' if n_sem == 1 else f'Últimas {n_sem} semanas ocultas'} "
                        f"por atraso de notificação (notificações depois de {limite:%d/%m/%Y}: "
                        f"{estilo.fmt_int(cortes['srag_oculto'])} na base carregada)")

if sih.empty and srag.empty:  # os cortes acima podem esvaziar as duas bases
    st.error("Sem dados depois de ocultar os meses/semanas recentes. Reduza os cortes na barra lateral.")
    st.stop()

datas = pd.concat([s for s in (sih["dt_inter"] if not sih.empty else None,
                               srag["dt_notific"] if not srag.empty else None) if s is not None])
d0, d1 = datas.min().date(), datas.max().date()
periodo = st.sidebar.date_input("Período", (d0, d1), min_value=d0, max_value=d1)
if len(periodo) != 2:
    st.stop()
ini, fim = pd.Timestamp(periodo[0]), pd.Timestamp(periodo[1])
# Pessoas-ano de cada fonte: só o trecho do período que a fonte realmente cobre
# (SIH e SRAG terminam em datas diferentes depois de ocultar meses/semanas recentes)
vazia = pd.Series(dtype="datetime64[ns]")
cobertura = {"sih": periodo_efetivo(sih["dt_inter"] if not sih.empty else vazia, ini, fim),
             "srag": periodo_efetivo(srag["dt_notific"] if not srag.empty else vazia, ini, fim)}

ufs = sorted(set(sih.get("uf", [])) | set(srag.get("uf", [])))
uf_sel = st.sidebar.multiselect("UF", ufs, default=ufs)
muns = sorted(set(sih.get("municipio", [])) | set(srag.get("municipio", [])))
mun_sel = st.sidebar.multiselect("Municípios (vazio = todos)", muns)
grupos_sel = st.sidebar.multiselect("Grupos de doença (SIH)", list(GRUPOS_CID),
                                    default=list(GRUPOS_CID))


def filtrar(df, col_data, grupo=False, por_mun=True):
    if df.empty:
        return df
    m = df[col_data].between(ini, fim) & df["uf"].isin(uf_sel)
    if mun_sel and por_mun:
        m &= df["municipio"].isin(mun_sel)
    if grupo:
        m &= df["grupo"].isin(grupos_sel)
    return df[m]


sih_f, srag_f = filtrar(sih, "dt_inter", True), filtrar(srag, "dt_notific")
# o mapa mostra a UF inteira: ignora o filtro de municípios da barra lateral
sih_m = filtrar(sih, "dt_inter", True, por_mun=False)
srag_m = filtrar(srag, "dt_notific", por_mun=False)
comp_cnes = (leitos["competencia"].dropna().astype(str).max()
             if "competencia" in leitos and not leitos.empty else None)
ano_pop = int(pop["ano_pop"].max()) if not pop.empty and "ano_pop" in pop else None
if not srag_f.empty:
    cortes.update(srag_sem_idade=int(faixa_etaria(srag_f["idade"]).isna().sum()),
                  srag_pct_nao_esp=100 * (srag_f["agente"] == "Não especificado").mean(),
                  srag_pct_investig=100 * (srag_f["agente"] == "Em investigação").mean())
if ARQ_MALHA.exists():
    cod_malha = carregar_malha()["cod_mun"]
    cortes.update(sih_fora_mapa=int((~sih_m["cod_mun"].isin(cod_malha)).sum()) if not sih_m.empty else 0,
                  srag_fora_mapa=int((~srag_m["cod_mun"].isin(cod_malha)).sum()) if not srag_m.empty else 0)
    if not pop.empty:
        cortes["mun_sem_pop"] = municipios_sem_pop(carregar_malha(), pop)

st.title("Infecções respiratórias, tuberculose e infecções virais "
         f"{metodos.local_ufs(uf_sel)}: internações, vigilância e demanda por isolamento")
escopo = ["Período filtrado: "
          + ", ".join(f"{nome} de {fmt_periodo(cobertura[chave])}"
                      for nome, chave, df in (("SIH", "sih", sih_f), ("SRAG", "srag", srag_f))
                      if not df.empty) + "."
          if not (sih_f.empty and srag_f.empty) else "Sem dados no filtro atual.",
          f"UF: {', '.join(uf_sel) if uf_sel else 'nenhuma'}.",
          f"Municípios: {len(mun_sel)} selecionado(s)." if mun_sel else "",
          f"No filtro: {estilo.fmt_int(len(sih_f))} internações (SIH) e "
          f"{estilo.fmt_int(len(srag_f))} casos de SRAG.",
          f"CNES: competência {metodos.fmt_comp(comp_cnes)}."]
st.caption(" ".join(p for p in escopo if p))
t0, t1, t2, t3, t4, t5 = st.tabs(["Mapa", "Internações (SIH)", "SRAG",
                                  "Demanda de isolamento", "Leitos (CNES)", "Métodos"])

# ------------------------------------------------------------------- aba 0
with t0:
    if not ARQ_MALHA.exists():
        st.info("Malha do mapa não encontrada. Rode `python collect_geo.py`.")
    else:
        geo = carregar_malha()
        lt_m = leitos[leitos["uf"].isin(uf_sel)] if not leitos.empty else leitos
        tem_pop = not pop.empty
        tem_dados = {"Internações": not sih_m.empty, "Casos": not srag_m.empty,
                     "Leitos": not lt_m.empty}
        opcoes = [i for i, (tipo, rot, _) in INDICADORES.items()
                  if tem_dados[rot] and (tem_pop or tipo == "contagem")]
        if not opcoes:
            st.info("Sem dados para os filtros atuais.")
        else:
            c1, c2 = st.columns([3, 2])
            # padrão: taxa suavizada (a contagem absoluta é dominada por Fortaleza)
            padrao = opcoes.index(IND_PADRAO) if IND_PADRAO in opcoes else 0
            ind = c1.selectbox("Indicador", opcoes, index=padrao, key="mapa_indicador")
            nivel_rot = c2.selectbox("Nível", list(NIVEIS_MAPA), key="mapa_nivel")
            nivel = NIVEIS_MAPA[nivel_rot]
            tipo, rot_cont, origem_dados = INDICADORES[ind]

            if origem_dados == "srag":
                base, col_val = srag_m, None
            elif origem_dados == "leitos":
                base, col_val = lt_m, "qt_exist"
            else:
                base, col_val = sih_m, None
            p_ini, p_fim, anos_fonte = cobertura.get(origem_dados, (ini, fim, None))
            if col_val:
                contagem = base.groupby("cod_mun")[col_val].sum().reset_index(name="valor")
            else:
                contagem = base.groupby("cod_mun").size().reset_index(name="valor")

            pop_mapa = pop if tem_pop else pd.DataFrame({"cod_mun": [], "populacao": []})
            gdf = agregar(contagem, geo, pop_mapa, nivel, malha_nivel(nivel)[0])
            if tipo == "contagem":
                gdf["indicador"] = gdf["valor"]
            elif tipo == "taxa":
                gdf["indicador"] = taxa_bruta(gdf["valor"], gdf["populacao"], anos_fonte)
            elif tipo == "eb":
                gdf["indicador"] = taxa_eb(gdf["valor"], gdf["populacao"], anos_fonte)
            else:
                gdf["indicador"] = leitos_por_10mil(gdf["valor"], gdf["populacao"])
            casas = 0 if tipo == "contagem" else 1
            tab = pd.DataFrame({
                "chave": gdf["chave"], "nome": gdf["nome"], "indicador": gdf["indicador"],
                "txt_ind": gdf["indicador"].map(
                    lambda x: "sem dado" if pd.isna(x) else estilo.fmt_dec(x, casas)),
                "txt_val": gdf["valor"].map(estilo.fmt_int),
                "txt_pop": gdf["populacao"].map(
                    lambda x: "ausente" if pd.isna(x) else estilo.fmt_int(x))})

            esq, dir_ = st.columns([5, 3])
            geojson = malha_nivel(nivel)[1]
            fig = go.Figure()
            com, sem = tab[tab["indicador"].notna()], tab[tab["indicador"].isna()]
            hover = ("<b>%{customdata[0]}</b><br>" + ind + ": %{customdata[1]}<br>" + rot_cont
                     + ": %{customdata[2]}<br>População: %{customdata[3]}<extra></extra>")
            cols_hover = ["nome", "txt_ind", "txt_val", "txt_pop"]
            if not com.empty:
                fig.add_trace(go.Choropleth(
                    geojson=geojson, featureidkey="properties.chave", locations=com["chave"],
                    z=com["indicador"], customdata=com[cols_hover].to_numpy(), hovertemplate=hover,
                    colorscale=[[i / (len(estilo.SEQUENCIAL) - 1), c]
                                for i, c in enumerate(estilo.SEQUENCIAL)],
                    marker_line_color="#ffffff", marker_line_width=0.5,
                    colorbar=dict(len=0.85, thickness=14, xpad=4, title=dict(text="<br>".join(textwrap.wrap(ind, 26)), side="right"),
                                  tickformat=",~f")))  # "5.000", não "5k"
            if not sem.empty:  # sem dado fica cinza neutro, nunca invisível
                fig.add_trace(go.Choropleth(
                    geojson=geojson, featureidkey="properties.chave", locations=sem["chave"],
                    z=[0] * len(sem), customdata=sem[cols_hover].to_numpy(), hovertemplate=hover,
                    colorscale=[[0, "#f0efec"], [1, "#f0efec"]], showscale=False,
                    marker_line_color="#ffffff", marker_line_width=0.5))
            # enquadra a malha inteira da UF com margem pequena (fitbounds deixava 2/3 vazio)
            x0, y0, x1, y1 = geo.total_bounds
            mx, my = 0.03 * (x1 - x0), 0.03 * (y1 - y0)
            fig.update_geos(projection_type="mercator", visible=False,
                            lonaxis_range=[x0 - mx, x1 + mx], lataxis_range=[y0 - my, y1 + my])
            fig.update_layout(height=620, margin=dict(l=0, r=0, t=10, b=0))
            esq.plotly_chart(fig, width="stretch", theme=None,
                             config=estilo.config_plotly("figura1_mapa"))

            dir_.markdown(f"**Dez maiores ({nivel_rot.lower()})**")
            top = tab.dropna(subset=["indicador"]).nlargest(10, "indicador")
            dir_.dataframe(top[["nome", "txt_ind", "txt_pop"]].rename(
                columns={"nome": "Unidade", "txt_ind": "Valor", "txt_pop": "Pop."}),
                hide_index=True, width="stretch")
            completo = pd.DataFrame({"chave": gdf["chave"], "nome": gdf["nome"],
                                     "contagem": gdf["valor"], "populacao": gdf["populacao"],
                                     "indicador": gdf["indicador"]})
            dir_.download_button("Baixar todas as unidades (CSV)", csv_bytes(completo),
                                 f"mapa_{nivel}.csv")

            if origem_dados == "srag":
                origem = FONTE_SRAG
            elif origem_dados == "leitos":
                origem = f"CNES, leitos, competência {metodos.fmt_comp(comp_cnes)} (DATASUS)"
            else:
                origem = FONTE_SIH
            if tipo != "contagem":
                origem += f"; IBGE, estimativas populacionais {ano_pop or '?'}"
            origem += "; malha municipal e regiões de saúde 2023 (IPEA/geobr)"
            if fonte == "demo":
                origem = "DADOS FICTÍCIOS (modo demo); " + origem
            periodo_txt = ("sem recorte temporal (competência mais recente)" if tipo == "leitos"
                           else f"período de {p_ini:%d/%m/%Y} a {p_fim:%d/%m/%Y}")
            fora = fora_do_mapa(contagem, geo)
            nota = (f"Unidade de análise: {nivel_rot.lower()}; {periodo_txt}. O mapa mostra a UF inteira "
                    f"e ignora o filtro de municípios. {estilo.fmt_int(fora)} {rot_cont.lower()} "
                    "ficaram fora do mapa (código de município fora da malha: outras UFs ou inválido)")
            if origem_dados == "srag" and tipo == "taxa":
                nota += (". Atenção: notificações divididas pela população residente do município "
                         "notificador; infla polos de referência (ex.: Fortaleza) e desinfla a área "
                         "de abrangência; não é taxa de incidência")
            if tipo == "eb":
                nota += ". Taxa suavizada por estimador bayesiano empírico global (Marshall, 1991)"
            if tipo in ("taxa", "eb"):
                nota += (f"; pessoas-ano sobre o período coberto pela fonte "
                         f"({estilo.fmt_dec(anos_fonte, 2)} anos)")
            if tipo != "contagem":
                n_sem_mun = municipios_sem_pop(geo, pop_mapa)
                n_sem_un = int(gdf["indicador"].isna().sum())
                if n_sem_un:
                    nota += (f". {n_sem_mun} município(s) sem população; {n_sem_un} unidade(s) "
                             "afetada(s) ficam sem taxa (cinza)")
            st.markdown(estilo.legenda("mapa", origem, nota))

# ------------------------------------------------------------------- aba 1
with t1:
    if sih_f.empty:
        st.info("Sem dados do SIH para os filtros atuais.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Internações", estilo.fmt_int(len(sih_f)))
        c2.metric("Óbitos", estilo.fmt_int(sih_f["morte"].sum()))
        c3.metric("Letalidade hospitalar", f"{estilo.fmt_dec(100 * sih_f['morte'].mean())}%")
        c4.metric("Permanência média", f"{estilo.fmt_dec(sih_f['dias_perm'].mean())} dias")

        per_sih = f"Período: {fmt_periodo(cobertura['sih'])}"
        local_sih = ("Município de residência do paciente (o filtro de municípios se aplica à "
                     "residência); UF = local do hospital (arquivo)")
        ordem_g = [g for g in GRUPOS_CID if g in set(sih_f["grupo"])]
        ausentes = [g for g in grupos_sel if g not in ordem_g]  # selecionado, mas sem painel
        sem_registro = f"Sem internações no filtro: {'; '.join(ausentes)}. " if ausentes else ""
        semanas_sih = grade_semanas(*cobertura["sih"][:2])
        ser = (contar_semanas(sih_f, "dt_inter", semanas_sih, "grupo")
               .rename(columns={"n": "internacoes"}))
        linhas_fig = math.ceil(len(ordem_g) / 2)
        altura = 90 + 230 * linhas_fig
        # render_mode="svg": com WebGL a exportação em SVG sai como imagem rasterizada
        fig = px.line(ser, x="semana", y="internacoes", color="grupo", facet_col="grupo",
                      facet_col_wrap=2, render_mode="svg", facet_row_spacing=80 / altura,
                      facet_col_spacing=0.08, height=altura,
                      color_discrete_map=estilo.CORES_GRUPO, category_orders={"grupo": ordem_g},
                      labels={"semana": "Semana epidemiológica", "internacoes": "Internações por semana"})
        fig.update_yaxes(matches=None, showticklabels=True, rangemode="tozero", tickformat=",d")
        fig.update_xaxes(showticklabels=True)
        meia = (fig.layout.xaxis.domain[1] - fig.layout.xaxis.domain[0]) / 2
        # rótulo do painel só com o nome do grupo, alinhado à esquerda do painel
        fig.for_each_annotation(lambda a: a.update(text=a.text.split("=", 1)[-1], x=a.x - meia,
                                                   xanchor="left", font=dict(size=13, color=estilo.TINTA)))
        fig.update_traces(line_width=1.5, hovertemplate="%{x|%d/%m/%Y}: %{y:,.0f}<extra></extra>")
        fig.update_layout(showlegend=False, margin=dict(t=40))
        mostrar(st, fig, "figura2_sih_serie", "sih_serie", FONTE_SIH,
                f"{local_sih}. {per_sih}. Escalas do eixo y independentes entre os painéis; "
                f"semanas sem internação contam como zero. {sem_registro}{nota_oculto_sih}")
        st.download_button("Baixar série semanal (CSV)", csv_bytes(ser), "serie_semanal_sih.csv")

        a, b = st.columns(2)
        g = a.selectbox("Sazonalidade do grupo", ordem_g)
        z = sih_f[sih_f["grupo"] == g]
        p_ini, p_fim = cobertura["sih"][:2]
        anos_sih = range(p_ini.year, p_fim.year + 1)
        pv = (z.assign(ano=z["dt_inter"].dt.year, mes=z["dt_inter"].dt.month)
              .pivot_table(index="ano", columns="mes", values="uf", aggfunc="size", fill_value=0)
              .reindex(index=anos_sih, columns=range(1, 13), fill_value=0).astype(float))
        for ano in anos_sih:  # mês fora do período coberto fica em branco, não zero
            for mes in range(1, 13):
                inicio = pd.Timestamp(ano, mes, 1)
                if inicio > p_fim or inicio + pd.offsets.MonthEnd(0) < p_ini.normalize():
                    pv.loc[ano, mes] = float("nan")
        texto = pv.map(lambda v: "" if pd.isna(v) else estilo.fmt_int(v))
        fig = px.imshow(pv.values, x=MESES, y=[str(i) for i in pv.index], aspect="auto",
                        color_continuous_scale=estilo.SEQUENCIAL,
                        labels=dict(x="Mês", y="Ano", color="Internações"))
        fig.update_traces(text=texto.values, texttemplate="%{text}", textfont_size=11,
                          hovertemplate="%{x}/%{y}: %{text}<extra></extra>", xgap=1, ygap=1)
        fig.update_xaxes(side="bottom", showline=False, ticks="")
        fig.update_yaxes(showgrid=False, showline=False, ticks="")
        fig.update_layout(height=120 + 48 * len(pv), margin=dict(t=20))
        mostrar(a, fig, "figura3_sih_sazonal", "sih_sazonal", FONTE_SIH,
                f"Grupo: {g}. {per_sih}; células em branco = meses fora do período coberto; "
                f"meses nas bordas do período podem estar incompletos. {nota_oculto_sih}")

        base = (b.radio("Município de", ["residência", "hospital"], horizontal=True)
                if "municipio_mov" in sih_f else "residência")
        chave = ["cod_mun", "municipio"] if base == "residência" else ["mun_mov", "municipio_mov"]
        por_mun = (sih_f.groupby(chave).size().reset_index(name="internacoes")
                   .set_axis(["cod_mun", "municipio", "internacoes"], axis=1))
        tem_pop = not pop.empty and base == "residência"  # taxa só faz sentido por residência
        opcoes = ["Internações"] + (["Taxa por 100 mil hab./ano"] if tem_pop else [])
        metrica = b.radio("Ranking de municípios por", opcoes, horizontal=True)
        if tem_pop:
            por_mun = por_mun.merge(pop[["cod_mun", "populacao"]], on="cod_mun", how="left")
            por_mun["taxa"] = taxa_bruta(por_mun["internacoes"], por_mun["populacao"], cobertura["sih"][2])
            # residentes de fora das UFs selecionadas: taxa sem sentido, fica NaN
            cods_uf = (municipios_ibge.loc[municipios_ibge["uf"].isin(uf_sel), "cod_mun"]
                       if not municipios_ibge.empty else por_mun["cod_mun"])
            por_mun["taxa"] = taxa_so_na_uf(por_mun["taxa"], por_mun["cod_mun"], cods_uf)
            n_fora_uf = int((~por_mun["cod_mun"].isin(cods_uf)).sum())
        nota_rank = (("Município de residência do paciente" if base == "residência"
                      else "Município do hospital") + "; "
                     "o filtro de municípios se aplica à residência. " + per_sih)
        if metrica == "Internações":
            top, col, ttl, fmt = por_mun.nlargest(15, "internacoes"), "internacoes", "Internações", ",.0f"
            nota_rank += f". {len(top)} municípios com mais internações"
        else:
            min_pop = b.slider("População mínima do município", 0, 100_000, 20_000, 5_000,
                               help="Taxas de municípios pequenos oscilam muito.")
            dentro = por_mun[por_mun["taxa"].notna() | por_mun["cod_mun"].isin(cods_uf)]
            elegiveis = dentro[dentro["populacao"] >= min_pop]
            top = elegiveis.nlargest(15, "taxa")
            col, ttl, fmt = "taxa", "Taxa por 100 mil hab./ano", ",.1f"
            nota_rank += (f" ({estilo.fmt_dec(cobertura['sih'][2], 2)} anos de observação); "
                          f"população IBGE {ano_pop or '?'}. Só municípios com população a partir de "
                          f"{estilo.fmt_int(min_pop)} habitantes: "
                          f"{estilo.fmt_int(len(dentro) - len(elegiveis))} de "
                          f"{estilo.fmt_int(len(dentro))} municípios das UFs selecionadas ficaram de fora "
                          f"({estilo.fmt_int(dentro['populacao'].isna().sum())} sem população). "
                          f"Outros {estilo.fmt_int(n_fora_uf)} municípios de residência fora das UFs "
                          "selecionadas ficam sem taxa (aparecem no CSV com taxa vazia)")
        fig = px.bar(top, x=col, y="municipio", orientation="h", labels={col: ttl, "municipio": ""})
        fig.update_traces(marker_color=estilo.CATEGORICA[0], texttemplate=f"%{{x:{fmt}}}",
                          textposition="outside", cliponaxis=False,
                          hovertemplate=f"%{{y}}: %{{x:{fmt}}}<extra></extra>")
        fig.update_yaxes(autorange="reversed", showgrid=False, ticks="")
        fig.update_xaxes(showgrid=True, gridcolor=estilo.GRADE,
                         tickformat=",d" if col == "internacoes" else None)
        fig.update_layout(height=120 + 26 * max(len(top), 1), margin=dict(t=20, r=48))
        mostrar(b, fig, "figura4_sih_ranking", "sih_ranking", FONTE_SIH, nota_rank)
        st.download_button("Baixar tabela por município (CSV)", csv_bytes(por_mun), "sih_por_municipio.csv")

# ------------------------------------------------------------------- aba 2
with t2:
    if srag_f.empty:
        st.info("Sem dados de SRAG para os filtros atuais.")
    else:
        per_srag = f"Período: {fmt_periodo(cobertura['srag'])}"
        presentes = set(srag_f["agente"])
        ordem_a = ([a for a in estilo.ORDEM_AGENTE if a in presentes]
                   + sorted(presentes - set(estilo.ORDEM_AGENTE)))
        ser = (contar_semanas(srag_f, "dt_notific", grade_semanas(*cobertura["srag"][:2]), "agente")
               .rename(columns={"n": "casos"}))
        fig = px.area(ser, x="semana", y="casos", color="agente",
                      color_discrete_map=estilo.CORES_AGENTE, category_orders={"agente": ordem_a},
                      labels={"semana": "Semana epidemiológica de notificação",
                              "casos": "Casos por semana", "agente": ""})
        for tr in fig.data:  # áreas opacas: a pilha fica legível sem cores misturadas
            tr.update(fillcolor=tr.line.color, line_width=0.5,
                      hovertemplate=f"{tr.name}<br>%{{x|%d/%m/%Y}}: %{{y:,.0f}}<extra></extra>")
        fig.update_yaxes(tickformat=",d")
        fig.update_xaxes(tickformat="%m/%Y", dtick="M6")  # meses em português
        fig.update_layout(height=420)
        n_nao_esp = int((srag_f["agente"] == "Não especificado").sum())
        n_invest = int((srag_f["agente"] == "Em investigação").sum())
        mostrar(st, fig, "figura5_srag_serie", "srag_serie", FONTE_SRAG,
                f"Município de notificação. {per_srag}. Áreas empilhadas. Sem agente definido, em "
                f"cinza no topo: \"Não especificado\" (classificação final 4), "
                f"{estilo.fmt_int(n_nao_esp)} casos ({estilo.fmt_dec(cortes['srag_pct_nao_esp'])}%), "
                f"e \"Em investigação\" (sem classificação final), {estilo.fmt_int(n_invest)} casos "
                f"({estilo.fmt_dec(cortes['srag_pct_investig'])}%); é uma característica dos dados "
                f"do SIVEP-Gripe. O corte de semanas ocultas é de 7 x N dias corridos a partir da última "
                f"notificação, então a última semana exibida pode ser parcial. {nota_oculto_srag}")
        a, b = st.columns(2)
        resumo = resumo_gravidade(srag_f, ordem_a)
        a.subheader("Gravidade por agente")
        # strings pt-BR só para exibir; o CSV baixado traz os números sem arredondar
        exibe = pd.DataFrame({
            "Agente": resumo["agente"], "Casos": resumo["casos"].map(estilo.fmt_int),
            "UTI (%)": resumo["pct_uti"].map(dec_ou_nd),
            "Óbito (%)": resumo["pct_obito"].map(dec_ou_nd),
            "Idade med.": resumo["idade_mediana"].map(dec_ou_nd)})
        a.dataframe(exibe, hide_index=True, width="stretch")
        a.caption("Idade med. = idade mediana, em anos. UTI (%) = casos com UTI = 1 sobre todos os "
                  "casos (ignorado ou vazio conta como não). Óbito (%) = EVOLUCAO = 2 (óbito por SRAG) "
                  "sobre todos os casos, inclusive sem evolução registrada; óbito por outras causas "
                  "(3) não entra. O CSV traz também n_uti, n_obito e n_evolucao_conhecida (EVOLUCAO 1, 2 ou 3).")
        a.download_button("Baixar resumo (CSV)", csv_bytes(resumo), "srag_resumo.csv")
        faixas = faixa_etaria(srag_f["idade"])
        fx = (srag_f.assign(faixa=faixas).groupby(["faixa", "agente"], observed=True)
              .size().reset_index(name="casos"))
        fig = px.bar(fx, x="faixa", y="casos", color="agente",
                     color_discrete_map=estilo.CORES_AGENTE,
                     category_orders={"agente": ordem_a, "faixa": list(faixas.cat.categories)},
                     labels={"faixa": "Faixa etária (anos)", "casos": "Casos", "agente": ""})
        fig.update_traces(hovertemplate="%{x}: %{y:,.0f}<extra></extra>")
        fig.update_yaxes(tickformat=",d")
        fig.update_layout(height=420, bargap=0.25)
        mostrar(b, fig, "figura6_srag_idade", "srag_idade", FONTE_SRAG,
                f"Município de notificação. {per_srag}. Barras empilhadas por agente. "
                f"{estilo.fmt_int(faixas.isna().sum())} casos sem idade válida não aparecem. "
                f"{nota_oculto_srag}")

# ------------------------------------------------------------------- aba 3
estado_iso = None  # (grupos, participação) para a aba Métodos
with t3:
    st.markdown(
        "Estimativa **grosseira** de pacientes internados ao mesmo tempo (ocupação média = "
        "admissões/dia × permanência média). Os dados são da região inteira; use a participação "
        "para aproximar a demanda de **um** hospital.")
    if sih_f.empty:
        st.info("Sem dados do SIH para os filtros atuais.")
    else:
        ordem_g = [g for g in GRUPOS_CID if g in set(sih_f["grupo"])]
        padrao = [g for g in ISOLAMENTO_PADRAO if g in ordem_g]
        iso = st.multiselect("Grupos que exigem isolamento (você define)", ordem_g, default=padrao)
        share = st.slider("Participação do seu hospital na região (%)", 0.1, 100.0, 5.0, 0.1)
        if iso:
            estado_iso = (iso, share)
            z = sih_f[sih_f["grupo"].isin(iso)]
            adm = (contar_semanas(z, "dt_inter", grade_semanas(*cobertura["sih"][:2]))
                   .set_index("semana")["n"])
            perm = z["dias_perm"].mean()
            censo = (adm * perm / 7) * share / 100
            p90, pico = censo.quantile(0.9), censo.max()
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Permanência média", f"{estilo.fmt_dec(perm)} dias")
            c2.metric("Ocupação média", estilo.fmt_dec(censo.mean(), 2))
            c3.metric("Ocupação P90", estilo.fmt_dec(p90, 2))
            c4.metric("Salas p/ cobrir P90", math.ceil(p90) if p90 > 0 else 0)
            fig = px.line(censo.reset_index(name="pacientes"), x="semana", y="pacientes",
                          labels={"semana": "Semana epidemiológica",
                                  "pacientes": "Pacientes simultâneos estimados"})
            fig.update_traces(line_color=estilo.CATEGORICA[0], line_width=1.5,
                              hovertemplate="%{x|%d/%m/%Y}: %{y:,.2f}<extra></extra>")
            fig.add_hline(y=p90, line_width=1, line_color=estilo.TINTA_SECUNDARIA,
                          annotation_text="P90", annotation_position="top left",
                          annotation_font=dict(size=12, color=estilo.TINTA_SECUNDARIA))
            fig.update_yaxes(rangemode="tozero")
            fig.update_xaxes(tickformat="%m/%Y", dtick="M6")
            fig.update_layout(height=380, margin=dict(t=20))
            censo_df = pd.DataFrame({"semana": censo.index, "admissoes": adm.values,
                                     "pacientes": censo.values})
            mostrar(st, fig, "figura7_iso_censo", "iso_censo", FONTE_SIH,
                    f"Grupos: {'; '.join(iso)}. Participação do hospital: {estilo.fmt_dec(share)}%; "
                    f"permanência média {estilo.fmt_dec(perm)} dias (período inteiro). "
                    f"P90 = {estilo.fmt_dec(p90, 2)}; pico semanal = {estilo.fmt_dec(pico, 2)}. "
                    "Fórmula (Lei de Little) na aba Métodos. Semanas sem admissão contam como zero; "
                    "semanas incompletas nas bordas do período também são divididas por 7, o que "
                    f"baixa um pouco a média e o P90. {local_sih}. {per_sih}. Ponto de partida "
                    "de dimensionamento; não substitui dados do próprio hospital nem a norma "
                    f"aplicável (ex.: RDC 50/ANVISA, ABNT NBR 7256). {nota_oculto_sih}")
            st.download_button("Baixar série semanal do censo (CSV)", csv_bytes(censo_df),
                               "iso_censo_semanal.csv")

# ------------------------------------------------------------------- aba 4
with t4:
    if leitos.empty:
        st.info("Sem dados de leitos. Rode `python collect_cnes.py`.")
    else:
        lt = leitos[leitos["uf"].isin(uf_sel)]
        if mun_sel:
            lt = lt[lt["municipio"].isin(mun_sel)]
        fonte_cnes = f"CNES, leitos, competência {metodos.fmt_comp(comp_cnes)} (DATASUS)"
        filtro_lt = ("Município do estabelecimento; filtros de UF e de municípios aplicados "
                     "(o período não se aplica: é a competência mais recente)")
        c1, c2, c3 = st.columns(3)
        c1.metric("Estabelecimentos com leitos", estilo.fmt_int(lt["cnes"].nunique()))
        c2.metric("Leitos existentes", estilo.fmt_int(lt["qt_exist"].sum()))
        c3.metric("Leitos SUS", estilo.fmt_int(lt["qt_sus"].sum()))
        por_tipo = lt.groupby("tp_leito")[["qt_exist", "qt_sus"]].sum().reset_index()
        por_tipo["tipo"] = por_tipo["tp_leito"].map(TIPOS_LEITO).fillna(por_tipo["tp_leito"].astype(str))
        longo = (por_tipo.melt(id_vars="tipo", value_vars=["qt_exist", "qt_sus"],
                               var_name="serie", value_name="leitos")
                 .replace({"serie": {"qt_exist": "Existentes", "qt_sus": "SUS"}}))
        fig = px.bar(longo, x="tipo", y="leitos", color="serie", barmode="group",
                     color_discrete_map={"Existentes": estilo.CATEGORICA[0], "SUS": estilo.CATEGORICA[1]},
                     category_orders={"tipo": list(por_tipo["tipo"]), "serie": ["Existentes", "SUS"]},
                     labels={"tipo": "Tipo de leito", "leitos": "Leitos", "serie": ""})
        fig.update_traces(hovertemplate="%{x}: %{y:,.0f}<extra></extra>")
        fig.update_yaxes(tickformat=",d")
        fig.update_layout(height=420, bargap=0.3)
        mostrar(st, fig, "figura8_leitos_tipo", "leitos_tipo", fonte_cnes,
                f"{filtro_lt}. Rótulos de tipo de leito (TP_LEITO) ainda não conferidos contra a "
                "tabela oficial do CNES")
        if LEITOS_ISOLAMENTO_CODLEITO:
            iso_l = lt[lt["codleito"].isin(LEITOS_ISOLAMENTO_CODLEITO)]
            st.metric("Leitos de isolamento (códigos configurados)", estilo.fmt_int(iso_l["qt_exist"].sum()))
        else:
            st.info("Para contar leitos de isolamento, preencha `LEITOS_ISOLAMENTO_CODLEITO` em "
                    "`config.py` com os códigos da tabela de leitos do CNES.")
        top = (lt.groupby("municipio")["qt_exist"].sum().nlargest(15).reset_index())
        fig = px.bar(top, x="qt_exist", y="municipio", orientation="h",
                     labels={"qt_exist": "Leitos existentes", "municipio": ""})
        fig.update_traces(marker_color=estilo.CATEGORICA[0], texttemplate="%{x:,.0f}",
                          textposition="outside", cliponaxis=False,
                          hovertemplate="%{y}: %{x:,.0f}<extra></extra>")
        fig.update_yaxes(autorange="reversed", showgrid=False, ticks="")
        fig.update_xaxes(showgrid=True, gridcolor=estilo.GRADE, tickformat=",d")
        fig.update_layout(height=120 + 26 * max(len(top), 1), margin=dict(t=20, r=48))
        mostrar(st, fig, "figura9_leitos_mun", "leitos_mun", fonte_cnes,
                f"{filtro_lt}. {len(top)} municípios com mais leitos existentes")

# ------------------------------------------------------------------- aba 5
with t5:
    texto = metodos.texto_metodos(
        uf_sel, {"sih": None if sih_f.empty else cobertura["sih"],
                 "srag": None if srag_f.empty else cobertura["srag"]},
        comp_cnes=comp_cnes, ano_pop=ano_pop, n_mes=n_mes, n_sem=n_sem, cortes=cortes,
        municipios=mun_sel, grupos=grupos_sel, isolamento=estado_iso, demo=fonte == "demo")
    st.download_button("Baixar métodos (Markdown)", texto.encode("utf-8"), "metodos.md",
                       mime="text/markdown")
    st.markdown(texto)
