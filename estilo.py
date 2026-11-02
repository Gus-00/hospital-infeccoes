"""Estilo do painel: paleta, tema plotly, legendas de figura e formatação pt-BR."""
import plotly.graph_objects as go
import plotly.io as pio

from config import GRUPOS_CID

# Paleta categórica (ordem fixa; a cor segue a entidade, nunca o ranking)
CATEGORICA = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
              "#e87ba4", "#008300", "#6250d6", "#e34948"]
# Escala sequencial de uma só matiz, clara para escura (mapas, heatmap)
SEQUENCIAL = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5",
              "#256abf", "#184f95", "#0d366b"]
# Categorias "desconhecidas" nunca usam cor da paleta
CINZA_DESCONHECIDO = "#898781"
CINZA_INVESTIGACAO = "#c3c2b7"

# Tons de tinta
TINTA = "#1d2a33"
TINTA_SECUNDARIA = "#52514e"
TINTA_EIXO = "#898781"
GRADE = "#e1e0d9"
FUNDO = "#ffffff"

FONTE = "IBM Plex Sans, Segoe UI, sans-serif"

# Cor por grupo de CID: posição em GRUPOS_CID -> slot da paleta
CORES_GRUPO: dict[str, str] = {
    grupo: CATEGORICA[i] for i, grupo in enumerate(GRUPOS_CID)}

CORES_AGENTE: dict[str, str] = {
    "Influenza": CATEGORICA[0],
    "COVID-19": CATEGORICA[1],
    "Outro vírus respiratório": CATEGORICA[2],
    "Outro agente": CATEGORICA[6],  # violeta: evita amarelo ao lado de laranja
    "Não especificado": CINZA_DESCONHECIDO,
    "Em investigação": CINZA_INVESTIGACAO,
}
ORDEM_AGENTE = list(CORES_AGENTE)  # desconhecidos por último

# Numeração fixa das figuras: não muda com filtros nem abas
FIGURAS: dict[str, tuple[int, str]] = {
    "mapa": (1, "Distribuição espacial do indicador selecionado"),
    "sih_serie": (2, "Internações por semana epidemiológica, por grupo de causa"),
    "sih_sazonal": (3, "Sazonalidade mensal das internações"),
    "sih_ranking": (4, "Municípios com maior indicador"),
    "srag_serie": (5, "Casos de SRAG por agente, por semana epidemiológica de notificação"),
    "srag_idade": (6, "Casos de SRAG por faixa etária e agente"),
    "iso_censo": (7, "Pacientes simultâneos estimados nos grupos de isolamento"),
    "leitos_tipo": (8, "Leitos existentes e SUS por tipo"),
    "leitos_mun": (9, "Municípios com mais leitos existentes"),
}


def _com_ponto(texto: str) -> str:
    texto = texto.strip()
    return texto if texto.endswith(".") else texto + "."


def legenda(id_fig: str, fonte: str, nota: str | None = None) -> str:
    numero, titulo = FIGURAS[id_fig]
    txt = f"**Figura {numero}.** {_com_ponto(titulo)} Fonte: {_com_ponto(fonte)}"
    if nota:
        txt += f" Nota: {_com_ponto(nota)}"
    return txt


def fmt_int(n) -> str:
    return f"{n:,.0f}".replace(",", ".")


def fmt_dec(x, casas: int = 1) -> str:
    return f"{x:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def config_plotly(nome_arquivo: str) -> dict:
    return {
        "displaylogo": False,
        "modeBarButtonsToRemove": ["select2d", "lasso2d"],
        "toImageButtonOptions": {"format": "svg", "filename": nome_arquivo,
                                 "width": 1200, "height": 700, "scale": 1},
    }


def _registrar_template() -> None:
    eixo = dict(linecolor=CINZA_INVESTIGACAO, ticks="outside",
                tickcolor=CINZA_INVESTIGACAO, zeroline=False)
    pio.templates["artigo"] = go.layout.Template(layout=dict(
        font=dict(family=FONTE, size=13, color=TINTA),
        title=dict(font=dict(size=15), x=0, xanchor="left"),
        paper_bgcolor=FUNDO,
        plot_bgcolor=FUNDO,
        xaxis=dict(showgrid=False, **eixo),
        yaxis=dict(showgrid=True, gridcolor=GRADE, gridwidth=1, **eixo),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left",
                    x=0, borderwidth=0, bgcolor="rgba(0,0,0,0)"),
        colorway=CATEGORICA,
        margin=dict(l=48, r=16, t=48, b=40),
        separators=",.",
        hoverlabel=dict(bgcolor=FUNDO, bordercolor=CINZA_INVESTIGACAO,
                        font=dict(family=FONTE, color=TINTA)),
    ), data=dict(
        scatter=[go.Scatter(line=dict(width=2))],
        scattergl=[go.Scattergl(line=dict(width=2))],
    ))
    pio.templates.default = "plotly_white+artigo"


_registrar_template()
