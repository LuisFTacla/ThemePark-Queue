import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
import os

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Portfólio | Dashboard Beto Carrero", layout="wide")

# CSS para arredondar os cards individuais e remover fundos
st.markdown("""
    <style>
    rect.heatmaplayer-rect {
        rx: 6 !important;
        ry: 6 !important;
    }
    /* No Mobile, forçamos o texto a ser legível e ajustamos o padding */
    @media (max-width: 600px) {
        .main .block-container {
            padding: 0.5rem !important;
        }
        /* Força o tamanho do texto do Plotly no mobile */
        .js-plotly-plot .plotly .cursor-pointer {
            font-size: 10px !important;
        }
    }
    </style>
    """, unsafe_allow_html=True)

# --- CARREGAMENTO DE DADOS ---
@st.cache_data
def load_and_process_data():
    if not os.path.exists('consolidado-bcw.csv'):
        return None, None
    df = pd.read_csv('consolidado-bcw.csv')
    df['hora_cheia'] = pd.to_datetime(df['hora_local']).dt.hour
    
    espera_media = df[df['wait_time'] > 0].groupby('data_local')['wait_time'].mean().reset_index()
    espera_media['wait_time'] = espera_media['wait_time'].round(0).astype(int)
    espera_media['date'] = pd.to_datetime(espera_media['data_local'])
    espera_media['year'] = espera_media['date'].dt.year
    espera_media['month'] = espera_media['date'].dt.month
    espera_media['day'] = espera_media['date'].dt.day
    espera_media['day_of_week'] = espera_media['date'].dt.day_name()
    espera_media['week_of_year'] = espera_media['date'].dt.isocalendar().week
    espera_media.loc[(espera_media['month'] == 1) & (espera_media['week_of_year'] > 50), 'week_of_year'] = 0
    return df, espera_media

df_bruto, df_calendario = load_and_process_data()

# --- INICIALIZAÇÃO DO ESTADO ---
if "ano_sel" not in st.session_state:
    st.session_state.ano_sel = 2024

# --- FUNÇÃO DO CALENDÁRIO ---
def gerar_calendario_plotly(df_espera, ano_selecionado):
    espera = df_espera[df_espera['year'] == ano_selecionado].copy()
    if espera.empty: return None
    
    num_semanas = len(espera['week_of_year'].unique())
    altura_final = num_semanas * 55 + 150

    # Escala de 20 a 60 min
    z_min, z_max = 20, 60
    espera['week_of_year'] = espera['date'].apply(lambda x: x.strftime('%W')).astype(int)
    
    ordered_days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    labels_dias = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo']
    meses_abr = {1:'JAN', 2:'FEV', 3:'MAR', 4:'ABR', 5:'MAI', 6:'JUN', 7:'JUL', 8:'AGO', 9:'SET', 10:'OUT', 11:'NOV', 12:'DEZ'}
    
    pivot_df = espera.pivot_table(values='wait_time', index='week_of_year', columns='day_of_week', aggfunc='mean')
    for day in ordered_days:
        if day not in pivot_df.columns: pivot_df[day] = np.nan
    pivot_df = pivot_df[ordered_days]

    text_matrix = []
    for week in pivot_df.index:
        row_text = []
        for day in ordered_days:
            date_row = espera[(espera['week_of_year'] == week) & (espera['day_of_week'] == day)]
            if not date_row.empty:
                d, m, w = date_row.iloc[0]['day'], date_row.iloc[0]['month'], date_row.iloc[0]['wait_time']
                row_text.append(f"{d:02d} {meses_abr[m]}<br><b>{int(w)} min</b>")
            else: row_text.append("")
        text_matrix.append(row_text)

    fig = go.Figure(data=go.Heatmap(
        z=pivot_df.values, x=labels_dias, y=pivot_df.index,
        text=text_matrix, 
        texttemplate="%{text}", 
        textfont={"size": 15}, # Tamanho base bom para desktop
        hoverinfo="text",
        colorscale='RdYlGn', reversescale=True, zmin=20, zmax=60,
        xgap=4, ygap=4,
        colorbar=dict(
            title="Espera (min)", orientation='h', y=1.02, 
            x=0.5, xanchor='center', len=0.8,
            tickvals=[20, 30, 40, 50, 60],
            ticktext=["Parque vazio", "30", "40", "50", "Parque lotado"]
        )
    ))
    
    fig.update_layout(
        height=altura_final, # Altura fixa calculada no Python
        xaxis_side='top',
        yaxis=dict(
            autorange='reversed', showgrid=False, zeroline=False, 
            showticklabels=False,
            # REMOVEMOS o scaleanchor="x" para permitir que a altura 
            # seja controlada pelo 'height' que calculamos acima
        ),
        xaxis=dict(showgrid=False, zeroline=False, fixedrange=True),
        paper_bgcolor='rgba(0,0,0,0)', 
        plot_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=0, r=0, t=0, b=10),
    )
    return fig

# --- LAYOUT ---
if df_bruto is not None:
    tab1, tab2 = st.tabs(["📊 Movimento por Atração", "📅 Calendário Geral de Lotação"])

    with tab1:
        # Seu gráfico de barras...
        atracao = st.selectbox("Selecione a Atração:", sorted(df_bruto['name'].unique()))
        df_bar = df_bruto[(df_bruto['name'] == atracao) & (df_bruto['wait_time'] > 0)]
        media_h = df_bar.groupby('hora_cheia')['wait_time'].mean().reset_index()
        st.plotly_chart(px.bar(media_h, x='hora_cheia', y='wait_time', template="plotly_white", color_discrete_sequence=['#0068c9']), use_container_width=True)

    with tab2:
        st.header("Mapa de Calor de Lotação")
    
        # Verificação redundante para segurança
        if "ano_sel" not in st.session_state:
            st.session_state.ano_sel = 2024
        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("2023", use_container_width=True, type="primary" if st.session_state.ano_sel == 2023 else "secondary"):
                st.session_state.ano_sel = 2023
                st.rerun()
        with col2:
            if st.button("2024", use_container_width=True, type="primary" if st.session_state.ano_sel == 2024 else "secondary"):
                st.session_state.ano_sel = 2024
                st.rerun()

        fig_p = gerar_calendario_plotly(df_calendario, st.session_state.ano_sel)
        
        if fig_p:
            # AQUI ESTÁ O PULO DO GATO:
            # No mobile, o container_width=True vai espremer a largura, 
            # mas como tiramos o scaleanchor, a ALTURA continuará sendo 
            # os pixels que definimos (ex: 52 semanas * 55px = ~2800px de altura total)
            # Isso criará uma rolagem vertical natural no celular, o que é ÓTIMO para leitura.
            st.plotly_chart(fig_p, use_container_width=True, config={'displayModeBar': False})