import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
import os

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Dashboard Beto Carrero", layout="wide")

# CSS para arredondar os cards individuais e remover fundos
st.markdown("""
    <style>
    rect.heatmaplayer-rect {
        rx: 6 !important;
        ry: 6 !important;
    }
    @media (max-width: 600px) {
        .main .block-container {
            padding: 0.5rem !important;
        }
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
    
def exibir_legenda_color_bar():
    fig = go.Figure(go.Heatmap(
        z=[[20, 30, 40, 50, 60]],
        colorscale='RdYlGn', 
        reversescale=True, 
        zmin=20, 
        zmax=60,
        showscale=True,
        opacity=0,
        colorbar=dict(
            orientation='h',
            thickness=15,
            len=0.9,
            x=0.5,
            y=0.5,
            xanchor='center',
            tickvals=[20, 30, 40, 50, 60],
            ticktext=["Vazio (-20)", "30", "40", "50", "Lotado (+60)"],
            tickfont=dict(size=12),
            title=dict(
                text="Espera Média (minutos)",
                font=dict(size=14),
                side='top'
            )
        )
    ))
    fig.update_layout(
        height=100,
        margin=dict(l=10, r=10, t=55, b=0),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        xaxis=dict(showticklabels=False, showgrid=False, zeroline=False, fixedrange=True),
        yaxis=dict(showticklabels=False, showgrid=False, zeroline=False, fixedrange=True),
    )
    return fig

def gerar_mes_plotly(df_espera, ano, mes_num):
    mes_data = df_espera[(df_espera['year'] == ano) & (df_espera['month'] == mes_num)].copy()
    if mes_data.empty:
        return None

    meses_nomes = {1:'Janeiro', 2:'Fevereiro', 3:'Março', 4:'Abril', 5:'Maio', 6:'Junho', 
                  7:'Julho', 8:'Agosto', 9:'Setembro', 10:'Outubro', 11:'Novembro', 12:'Dezembro'}
    ordered_days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    labels_dias = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']

    def get_month_week(date):
        first_day = date.replace(day=1)
        first_weekday = first_day.weekday() 
        return (date.day + first_weekday - 1) // 7

    mes_data['week_of_month'] = mes_data['date'].apply(get_month_week)
    pivot_df = mes_data.pivot_table(values='wait_time', index='week_of_month', columns='day_of_week', aggfunc='mean')
    
    for day in ordered_days:
        if day not in pivot_df.columns: pivot_df[day] = np.nan
    pivot_df = pivot_df[ordered_days]
    
    for w in range(6):
        if w not in pivot_df.index:
            pivot_df.loc[w] = np.nan
    pivot_df = pivot_df.sort_index()

    text_matrix = []
    for week in pivot_df.index:
        row_text = []
        for day in ordered_days:
            date_row = mes_data[(mes_data['week_of_month'] == week) & (mes_data['day_of_week'] == day)]
            if not date_row.empty:
                d, w = date_row.iloc[0]['day'], date_row.iloc[0]['wait_time']
                row_text.append(f"{d:02d}<br><b>{int(w)} min</b>")
            else:
                row_text.append("")
        text_matrix.append(row_text)

    fig = go.Figure(data=go.Heatmap(
        z=pivot_df.values, x=labels_dias, y=list(range(6)),
        text=text_matrix, texttemplate="%{text}", textfont={"size": 12},
        hoverinfo="none",
        colorscale='RdYlGn', reversescale=True, zmin=20, zmax=60,
        xgap=3, ygap=3, showscale=False 
    ))

    fig.update_layout(
        title=dict(text=meses_nomes[mes_num], x=0.5, xanchor='center', font=dict(size=18)),
        height=350,
        xaxis_side='bottom',
        yaxis=dict(autorange='reversed', showgrid=False, zeroline=False, showticklabels=False, fixedrange=True),
        xaxis=dict(showgrid=False, zeroline=False, fixedrange=True, tickfont=dict(size=10)),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=5, r=5, t=40, b=20),
    )
    return fig

if df_bruto is not None:
    tab1, tab2 = st.tabs(["📊 Movimento por Atração", "📅 Calendário Geral de Lotação"])

    with tab1:
        atracao = st.selectbox("Selecione a Atração:", sorted(df_bruto['name'].unique()))
        df_bar = df_bruto[(df_bruto['name'] == atracao) & (df_bruto['wait_time'] > 0)]
        media_h = df_bar.groupby('hora_cheia')['wait_time'].mean().reset_index()
        
        # Lógica para destacar as 3 maiores barras
        # Criamos uma coluna de cor base: azul padrão
        media_h = media_h.sort_values('hora_cheia')
        cores = ['#0068c9'] * len(media_h)
        
        # Encontramos os índices dos 3 maiores valores
        if len(media_h) >= 3:
            top_3_indices = media_h['wait_time'].nlargest(3).index
            for idx in top_3_indices:
                # Localizamos a posição real no DataFrame ordenado para aplicar a cor
                pos = media_h.index.get_loc(idx)
                cores[pos] = '#ef233c' # Vermelho destaque

        fig_bar = px.bar(
            media_h, 
            x='hora_cheia', 
            y='wait_time', 
            template="plotly_white",
            labels={'hora_cheia': 'Horário (h)', 'wait_time': 'Tempo médio de fila (minutos)'}
        )
        fig_bar.update_traces(marker_color=cores)
        st.plotly_chart(fig_bar, use_container_width=True)

    with tab2:
        st.markdown("### 📅 Calendário de Lotação")
        
        # Texto explicativo para leigos
        st.info("""
        **Guia:** Cada quadrado representa um dia de operação do parque. \n 
        O número superior é o **dia do mês**. O valor inferior é o **tempo médio de espera** (em minutos), ou seja, quanto tempo em média um visitante precisou esperar na fila para usufruir de uma atração,
        considerando todas as atrações abertas do parque ao longo do respectivo dia.
        """)
        
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
        
        st.plotly_chart(exibir_legenda_color_bar(), use_container_width=True, config={'displayModeBar': False})

        for i in range(1, 13, 2):
            c1, c2 = st.columns(2)
            with c1:
                fig_mes = gerar_mes_plotly(df_calendario, st.session_state.ano_sel, i)
                if fig_mes:
                    st.plotly_chart(fig_mes, use_container_width=True, config={'displayModeBar': False})
            with c2:
                if i + 1 <= 12:
                    fig_mes_prox = gerar_mes_plotly(df_calendario, st.session_state.ano_sel, i + 1)
                    if fig_mes_prox:
                        st.plotly_chart(fig_mes_prox, use_container_width=True, config={'displayModeBar': False})