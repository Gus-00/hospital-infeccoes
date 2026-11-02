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
from config import ANOS, DEMO, GRUPOS_CID, ISOLAMENTO_PADRAO, LEITOS_ISOLAMENTO_CODLEITO, REAL
from mapa import (agregar, dissolver, fora_do_mapa, leitos_por_10mil, municipios_sem_pop,
                  periodo_efetivo, taxa_bruta, taxa_eb)

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
    if not sih.empty:
        if "mun_mov" in sih:  # município do hospital (parquets novos)
            sih["municipio_mov"] = sih["mun_mov"].map(nomes).fillna(sih["mun_mov"]) if nomes is not None else sih["mun_mov"]
        sih["dt_inter"] = pd.to_datetime(sih["dt_inter"])
        sih = sih[sih["dt_inter"] >= f"{min(ANOS)}-01-01"]  # corta cauda de anos anteriores
    if not srag.empty:
        srag["dt_notific"] = pd.to_datetime(srag["dt_notific"])
    return sih, srag, pop, leitos


def semana(s: pd.Series) -> pd.Series:
    return s.dt.to_period("W-SAT").dt.start_time


def csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")


ARQ_MALHA = REAL / "geo_municipios.parquet"  # malha vale para real e demo (não é fictícia)
NIVEIS_MAPA = {"Município": "municipio", "Região de saúde": "regiao",
               "Macrorregião de saúde": "macro"}
# indicador -> (tipo, rótulo da contagem, fonte); tipos: contagem, taxa, eb, leitos
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
sih, srag, pop, leitos = carregar(str(REAL if fonte == "real" else DEMO))

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
if not sih.empty and n_mes:
    corte = sih["dt_inter"].max().to_period("M").start_time - pd.DateOffset(months=n_mes - 1)
    sih = sih[sih["dt_inter"] < corte]
if not srag.empty and n_sem:
    srag = srag[srag["dt_notific"] <= srag["dt_notific"].max() - pd.to_timedelta(n_sem, unit="W")]

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
st.title("Infecções respiratórias, TB e virais — demanda hospitalar")
t0, t1, t2, t3, t4 = st.tabs(["Mapa", "Internações (SIH)", "SRAG",
                              "Demanda de isolamento", "Leitos (CNES)"])

# ------------------------------------------------------------------- aba 0
with t0:
    if not ARQ_MALHA.exists():
        st.info("Malha do mapa não encontrada. Rode `python collect_geo.py`.")
    else:
        geo = carregar_malha()
        # o mapa mostra a UF inteira: ignora o filtro de municípios da barra lateral
        sih_m = filtrar(sih, "dt_inter", True, por_mun=False)
        srag_m = filtrar(srag, "dt_notific", por_mun=False)
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
            ind = c1.selectbox("Indicador", opcoes, key="mapa_indicador")
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

            esq, dir_ = st.columns([3, 1])
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
                    colorbar=dict(title=dict(text="<br>".join(textwrap.wrap(ind, 26)), side="right"))))
            if not sem.empty:  # sem dado fica cinza neutro, nunca invisível
                fig.add_trace(go.Choropleth(
                    geojson=geojson, featureidkey="properties.chave", locations=sem["chave"],
                    z=[0] * len(sem), customdata=sem[cols_hover].to_numpy(), hovertemplate=hover,
                    colorscale=[[0, "#f0efec"], [1, "#f0efec"]], showscale=False,
                    marker_line_color="#ffffff", marker_line_width=0.5))
            fig.update_geos(fitbounds="locations", visible=False)
            fig.update_layout(height=620, margin=dict(l=0, r=0, t=10, b=0))
            esq.plotly_chart(fig, width="stretch", config=estilo.config_plotly("figura1_mapa"))

            dir_.markdown(f"**Dez maiores ({nivel_rot.lower()})**")
            top = tab.dropna(subset=["indicador"]).nlargest(10, "indicador")
            dir_.dataframe(top[["nome", "txt_ind", "txt_pop"]].rename(
                columns={"nome": "Unidade", "txt_ind": "Valor", "txt_pop": "População"}),
                hide_index=True, width="stretch")
            completo = pd.DataFrame({"chave": gdf["chave"], "nome": gdf["nome"],
                                     "contagem": gdf["valor"], "populacao": gdf["populacao"],
                                     "indicador": gdf["indicador"]})
            dir_.download_button("Baixar todas as unidades (CSV)", csv_bytes(completo),
                                 f"mapa_{nivel}.csv")

            ano_pop = int(pop["ano_pop"].max()) if tem_pop and "ano_pop" in pop else "?"
            if origem_dados == "srag":
                origem = "SIVEP-Gripe (OpenDataSUS)"
            elif origem_dados == "leitos":
                comp = lt_m["competencia"].dropna().astype(str).max() if "competencia" in lt_m else "?"
                origem = f"CNES (DATASUS), competência {comp}"
            else:
                origem = "SIH/SUS (DATASUS)"
            if tipo not in ("contagem",):
                origem += f"; IBGE, estimativas populacionais {ano_pop}"
            origem += "; malha municipal e regiões de saúde 2023 (IPEA/geobr)"
            if fonte == "demo":
                origem = "DADOS FICTÍCIOS (modo demo); " + origem
            periodo_txt = ("sem recorte temporal (competência mais recente)" if tipo == "leitos"
                           else f"período de {p_ini:%d/%m/%Y} a {p_fim:%d/%m/%Y}")
            fora = fora_do_mapa(contagem, geo)
            nota = (f"Unidade de análise: {nivel_rot.lower()}; {periodo_txt}. O mapa mostra a UF inteira "
                    f"e ignora o filtro de municípios. {estilo.fmt_int(fora)} {rot_cont.lower()} "
                    "ficaram fora do mapa (código de município fora da malha: outras UFs ou inválido)")
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
        c1.metric("Internações", f"{len(sih_f):,}".replace(",", "."))
        c2.metric("Óbitos", f"{int(sih_f['morte'].sum()):,}".replace(",", "."))
        c3.metric("Letalidade hospitalar", f"{100 * sih_f['morte'].mean():.1f}%")
        c4.metric("Permanência média", f"{sih_f['dias_perm'].mean():.1f} dias")
        st.caption("Filtro de municípios = **residência** do paciente; o ranking pode usar "
                   "residência ou hospital. UF = local do hospital/arquivo. Meses finais "
                   "ocultos por incompletude (barra lateral).")

        ser = (sih_f.assign(semana=semana(sih_f["dt_inter"]))
               .groupby(["semana", "grupo"]).size().reset_index(name="internacoes"))
        st.plotly_chart(px.line(ser, x="semana", y="internacoes", color="grupo",
                                title="Internações por semana"), width="stretch")
        st.download_button("Baixar série semanal (CSV)", csv_bytes(ser), "serie_semanal_sih.csv")

        a, b = st.columns(2)
        g = a.selectbox("Sazonalidade do grupo", sorted(sih_f["grupo"].unique()))
        z = sih_f[sih_f["grupo"] == g]
        pv = (z.assign(ano=z["dt_inter"].dt.year, mes=z["dt_inter"].dt.month)
              .pivot_table(index="ano", columns="mes", values="uf", aggfunc="size", fill_value=0)
              .reindex(columns=range(1, 13), fill_value=0))
        a.plotly_chart(px.imshow(pv.values, x=MESES, y=[str(i) for i in pv.index], aspect="auto",
                                 color_continuous_scale="Reds", labels=dict(color="Internações")),
                       width="stretch")

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
        if metrica == "Internações":
            top, col, ttl = por_mun.nlargest(15, "internacoes"), "internacoes", "Internações"
        else:
            min_pop = b.slider("População mínima do município", 0, 100_000, 20_000, 5_000,
                               help="Taxas de municípios pequenos oscilam muito.")
            top = por_mun[por_mun["populacao"] >= min_pop].nlargest(15, "taxa")
            col, ttl = "taxa", "Taxa por 100 mil hab./ano"
        b.plotly_chart(px.bar(top, x=col, y="municipio", orientation="h",
                              title=f"Top municípios ({base}) — {ttl}")
                       .update_yaxes(autorange="reversed"), width="stretch")
        st.download_button("Baixar tabela por município (CSV)", csv_bytes(por_mun), "sih_por_municipio.csv")

# ------------------------------------------------------------------- aba 2
with t2:
    if srag_f.empty:
        st.info("Sem dados de SRAG para os filtros atuais.")
    else:
        ser = (srag_f.assign(semana=semana(srag_f["dt_notific"]))
               .groupby(["semana", "agente"]).size().reset_index(name="casos"))
        st.plotly_chart(px.area(ser, x="semana", y="casos", color="agente",
                                title="Casos de SRAG por agente (semana de notificação)"),
                        width="stretch")
        pct_nao_esp = 100 * (srag_f["agente"] == "Não especificado").mean()
        st.caption(f"{pct_nao_esp:.0f}% dos casos estão como 'Não especificado' (classificação final "
                   "sem agente definido) — é uma característica dos dados do SIVEP-Gripe.")
        a, b = st.columns(2)
        resumo = srag_f.groupby("agente").agg(casos=("agente", "size"), pct_uti=("uti", "mean"),
                                              pct_obito=("obito", "mean"),
                                              idade_mediana=("idade", "median")).reset_index()
        resumo["pct_uti"] = (100 * resumo["pct_uti"]).round(1)
        resumo["pct_obito"] = (100 * resumo["pct_obito"]).round(1)
        resumo["idade_mediana"] = resumo["idade_mediana"].round(1)
        a.subheader("Gravidade por agente")
        a.dataframe(resumo, hide_index=True, width="stretch")
        a.download_button("Baixar resumo (CSV)", csv_bytes(resumo), "srag_resumo.csv")
        faixas = pd.cut(srag_f["idade"], [0, 2, 12, 18, 40, 60, 80, 200], right=False,
                        labels=["0-1", "2-11", "12-17", "18-39", "40-59", "60-79", "80+"])
        fx = srag_f.assign(faixa=faixas).groupby(["faixa", "agente"], observed=True).size().reset_index(name="casos")
        b.plotly_chart(px.bar(fx, x="faixa", y="casos", color="agente", title="Faixa etária (anos)"),
                       width="stretch")

# ------------------------------------------------------------------- aba 3
with t3:
    st.markdown(
        "Estimativa **grosseira** de pacientes internados ao mesmo tempo (ocupação média = "
        "admissões/dia × permanência média). Os dados são da região inteira; use a participação "
        "para aproximar a demanda de **um** hospital.")
    if sih_f.empty:
        st.info("Sem dados do SIH para os filtros atuais.")
    else:
        padrao = [g for g in ISOLAMENTO_PADRAO if g in sih_f["grupo"].unique()]
        iso = st.multiselect("Grupos que exigem isolamento (você define)",
                             sorted(sih_f["grupo"].unique()), default=padrao)
        share = st.slider("Participação do seu hospital na região (%)", 0.1, 100.0, 5.0, 0.1)
        if iso:
            z = sih_f[sih_f["grupo"].isin(iso)]
            adm = z.assign(semana=semana(z["dt_inter"])).groupby("semana").size()
            perm = z["dias_perm"].mean()
            censo = (adm * perm / 7) * share / 100
            p90, pico = censo.quantile(0.9), censo.max()
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Permanência média", f"{perm:.1f} dias")
            c2.metric("Ocupação média", f"{censo.mean():.2f}")
            c3.metric("Ocupação P90", f"{p90:.2f}")
            c4.metric("Salas p/ cobrir P90", math.ceil(p90) if p90 > 0 else 0)
            st.plotly_chart(px.line(censo.reset_index(name="pacientes"), x="semana", y="pacientes",
                                    title="Pacientes simultâneos estimados (semanal)"), width="stretch")
            st.caption(f"Pico semanal estimado: {pico:.2f}. Ponto de partida de dimensionamento; não "
                       "substitui dados do próprio hospital nem a norma aplicável "
                       "(ex.: RDC 50/ANVISA, ABNT NBR 7256).")

# ------------------------------------------------------------------- aba 4
with t4:
    if leitos.empty:
        st.info("Sem dados de leitos. Rode `python collect_cnes.py`.")
    else:
        lt = leitos[leitos["uf"].isin(uf_sel)]
        if mun_sel:
            lt = lt[lt["municipio"].isin(mun_sel)]
        comp = lt["competencia"].dropna().astype(str).max() if "competencia" in lt else "?"
        st.caption(f"CNES, competência {comp}. Leitos existentes e leitos SUS por tipo.")
        c1, c2, c3 = st.columns(3)
        c1.metric("Estabelecimentos com leitos", f"{lt['cnes'].nunique():,}".replace(",", "."))
        c2.metric("Leitos existentes", f"{int(lt['qt_exist'].sum()):,}".replace(",", "."))
        c3.metric("Leitos SUS", f"{int(lt['qt_sus'].sum()):,}".replace(",", "."))
        por_tipo = (lt.assign(tipo=lt["tp_leito"].map(TIPOS_LEITO).fillna(lt["tp_leito"].astype(str)))
                    .groupby("tipo")[["qt_exist", "qt_sus"]].sum().reset_index())
        st.plotly_chart(px.bar(por_tipo, x="tipo", y=["qt_exist", "qt_sus"], barmode="group",
                               labels={"value": "leitos", "variable": ""}, title="Leitos por tipo"),
                        width="stretch")
        if LEITOS_ISOLAMENTO_CODLEITO:
            iso_l = lt[lt["codleito"].isin(LEITOS_ISOLAMENTO_CODLEITO)]
            st.metric("Leitos de isolamento (códigos configurados)", int(iso_l["qt_exist"].sum()))
        else:
            st.info("Para contar leitos de isolamento, preencha `LEITOS_ISOLAMENTO_CODLEITO` em "
                    "`config.py` com os códigos da tabela de leitos do CNES.")
        top = (lt.groupby("municipio")["qt_exist"].sum().nlargest(15).reset_index())
        st.plotly_chart(px.bar(top, x="qt_exist", y="municipio", orientation="h",
                               title="Municípios com mais leitos existentes").update_yaxes(autorange="reversed"),
                        width="stretch")
