import streamlit as st
import pandas as pd
import plotly.express as px

# Configuração da página
st.set_page_config(page_title="Portfolio - Beto Carrero World", layout="wide")

@st.cache_data
def load_data():
    # Carrega o arquivo unificado
    df = pd.read_csv('consolidado-bcw.csv')
    # Converte para datetime e extrai apenas a hora cheia
    df['hora_cheia'] = pd.to_datetime(df['hora_local']).dt.hour
    return df

df = load_data()

st.title("🎢 Dashboard de Tempo de Fila")
st.markdown("Análise histórica das atrações (2023-2024)")

# 1. Seletor de Atração
atracoes = sorted(df['name'].unique())
selecionada = st.selectbox("Escolha a atração para visualizar o movimento médio:", atracoes)

# 2. Processamento para o Gráfico
# Filtramos a atração e apenas onde wait_time > 0 para a média real
df_plot = df[(df['name'] == selecionada) & (df['wait_time'] > 0)]

# Agrupamos por hora (10 às 18) e tiramos a média
media_por_hora = df_plot.groupby('hora_cheia')['wait_time'].mean().reset_index()
media_por_hora['wait_time'] = media_por_hora['wait_time'].round(0)

# 3. Criação do Gráfico de Barras (Plotly)
fig = px.bar(
    media_por_hora,
    x='hora_cheia',
    y='wait_time',
    text='wait_time',
    labels={'hora_cheia': 'Faixa Horária (Início)', 'wait_time': 'Média de Fila (min)'},
    title=f"Média de Espera por Hora: {selecionada}"
)

# Ajustes no visual do gráfico
fig.update_traces(marker_color='#0068c9', textposition='outside')
fig.update_layout(
    xaxis=dict(tickmode='linear', tick0=10, dtick=1, range=[9.5, 18.5]),
    yaxis=dict(title="Minutos"),
    hovermode="x"
)

st.plotly_chart(fig, use_container_width=True)