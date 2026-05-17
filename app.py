import streamlit as st
import pandas as pd
import numpy as np
import requests
import datetime
import pytz
from datetime import datetime, timezone
import plotly.graph_objects as go
import plotly.express as px
from google.cloud import bigquery
import os
from google.oauth2 import service_account
from streamlit_javascript import st_javascript

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Theme Park Analytics", layout="wide")

# Autenticação
def get_bq_client():
    json_path = "theme-park-queue-data-f2e1d4785d38.json"
    if os.path.exists(json_path):
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = json_path
        return bigquery.Client()
    else:
        try:
            if "gcp_service_account" in st.secrets:
                info = dict(st.secrets["gcp_service_account"])
                key = info["private_key"].strip().replace("\\n", "\n")
                if key.startswith('"') and key.endswith('"'):
                    key = key[1:-1]
                info["private_key"] = key
                credentials = service_account.Credentials.from_service_account_info(info)
                return bigquery.Client(credentials=credentials, project=info["project_id"])
        except st.errors.StreamlitSecretNotFoundError:
            raise RuntimeError(
                "Nenhum método de autenticação encontrado. "
                "Crie o arquivo JSON local ou configure os Secrets no Streamlit Cloud."
            )

client = get_bq_client()

# CSS Customizado (Simplificado e limpo das regras conflitantes)
st.markdown("""
    <style>
    rect.heatmaplayer-rect {
        rx: 6 !important;
        ry: 6 !important;
    }
    
    /* === BLOQUEIO DO TECLADO NO DROPDOWN === */
    /* Desativa a digitação e esconde o cursor piscante no selectbox */
    .stSelectbox input {
        caret-color: transparent !important; /* Esconde o cursor de texto */
    }
    
    /* Faz o campo de texto ignorar o foco direto que puxa o teclado, 
       mas permite que o clique passe para a caixinha abrir as opções */
    .stSelectbox div[role="combobox"] input {
        inputmode: none !important; /* Diz ao navegador para não abrir o teclado */
        pointer-events: none !important; /* Impede o foco direto no texto */
    }
    
    /* Garante que a caixinha inteira continue clicável para abrir o menu */
    .stSelectbox div[role="combobox"] {
        cursor: pointer !important;
    }
    
    @media (max-width: 600px) {
        .main .block-container {
            padding: 0.5rem !important;
        }
        .js-plotly-plot .plotly .cursor-pointer {
            font-size: 10px !important;
        }
        .stSelectbox label {
            display: none !important;
        }
    }
    </style>
    """, unsafe_allow_html=True)

# --- FUNÇÕES DE DADOS ---
@st.cache_data(ttl=86400)
def get_available_parks():
    query = "SELECT DISTINCT park_id, park_name FROM `theme-park-queue-data.theme_park_queues.historical-data` ORDER BY park_name"
    return client.query(query).to_dataframe()

@st.cache_data(ttl=3600, show_spinner=False)
def get_hourly_averages(park_id, timezone):
    query = f"""
    SELECT 
        CASE 
            WHEN ride_name IN ('Big Tower', 'BIG TOWER', 'big tower') THEN 'Big Drop'
            ELSE ride_name 
        END as name,
        EXTRACT(HOUR FROM DATETIME(timestamp_utc, '{timezone}')) as hora_cheia,
        AVG(wait_time) as wait_time
    FROM `theme-park-queue-data.theme_park_queues.historical-data`
    WHERE park_id = {park_id}
      AND wait_time > 0
      AND EXTRACT(HOUR FROM DATETIME(timestamp_utc, '{timezone}')) BETWEEN 8 AND 22
    GROUP BY name, hora_cheia
    ORDER BY name, hora_cheia
    """
    return client.query(query).to_dataframe()

@st.cache_data(ttl=3600, show_spinner=False)
def get_daily_averages(park_id, timezone):
    query = f"""
    SELECT 
        DATE(timestamp_utc, '{timezone}') as data_local,
        EXTRACT(YEAR FROM DATETIME(timestamp_utc, '{timezone}')) as ano_registro,
        ROUND(AVG(wait_time), 0) as wait_time
    FROM `theme-park-queue-data.theme_park_queues.historical-data`
    WHERE park_id = {park_id}
      AND wait_time > 0
    GROUP BY data_local, ano_registro
    ORDER BY data_local
    """
    df = client.query(query).to_dataframe()
    if df.empty: 
        return pd.DataFrame(), []
        
    anos_disponiveis = sorted(df['ano_registro'].unique().tolist())
    df['data_local'] = pd.to_datetime(df['data_local'])
    df['date'] = df['data_local']
    df['year'] = df['ano_registro']
    df['month'] = df['date'].dt.month
    df['day'] = df['date'].dt.day
    df['day_of_week'] = df['date'].dt.day_name()
    df['week_of_year'] = df['date'].dt.isocalendar().week
    df.loc[(df['month'] == 1) & (df['week_of_year'] > 50), 'week_of_year'] = 0
    return df, anos_disponiveis

@st.cache_data(ttl=3600, show_spinner=False)
def get_daily_heatmap_data(park_id, timezone, data_selecionada, intervalo_minutos):
    bloco = intervalo_minutos
    query = f"""
    WITH dados_indexados AS (
        SELECT 
            CASE 
                WHEN ride_name IN ('Big Tower', 'BIG TOWER', 'big tower') THEN 'Big Drop'
                ELSE ride_name 
            END as name,
            wait_time,
            EXTRACT(HOUR FROM DATETIME(timestamp_utc, '{timezone}')) as hora,
            EXTRACT(MINUTE FROM DATETIME(timestamp_utc, '{timezone}')) as minuto
        FROM `theme-park-queue-data.theme_park_queues.historical-data`
        WHERE park_id = {park_id}
          AND DATE(timestamp_utc, '{timezone}') = '{data_selecionada}'
          AND EXTRACT(HOUR FROM DATETIME(timestamp_utc, '{timezone}')) BETWEEN 8 AND 22
    )
    SELECT 
        name,
        hora,
        DIV(minuto, {bloco}) * {bloco} as minuto_bloco,
        ROUND(AVG(wait_time), 0) as wait_time_medio
    FROM dados_indexados
    GROUP BY name, hora, minuto_bloco
    ORDER BY name, hora, minuto_bloco
    """
    df = client.query(query).to_dataframe()
    return df

@st.cache_data(ttl=60)
def get_live_data(park_id):
    url = f"https://queue-times.com/parks/{park_id}/queue_times.json"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        rides = []
        for land in data.get('lands', []):
            for ride in land.get('rides', []):
                rides.append(ride)
        for ride in data.get('rides', []):
            rides.append(ride)
        return rides
    except:
        return []

# --- CONTROLE DE NAVEGAÇÃO / SESSÃO ---
if "park_id" not in st.session_state:
    st.session_state.park_id = None
if "park_name" not in st.session_state:
    st.session_state.park_name = None
if "ano_sel" not in st.session_state:
    st.session_state.ano_sel = datetime.now().year
    
# --- TELA INICIAL COM DOCUMENTAÇÃO COMPLETA ---
if st.session_state.park_id is None:
    st.markdown("# 🎡 Theme Park Data Intelligence")
    st.caption("Desenvolvido por **Luis Fernando Melnek Tacla** | Versão 1.1 | 2026")
    st.markdown("---")

    st.markdown("### 🚀 Iniciar Análise")
    df_parks = get_available_parks() 
    
    if not df_parks.empty:
        selected_park_name = st.selectbox(
            "Escolha um Parque para abrir o Dashboard:", 
            ["Selecione um destino..."] + df_parks['park_name'].tolist()
        )
        
        if selected_park_name != "Selecione um destino...":
            row = df_parks[df_parks['park_name'] == selected_park_name].iloc[0]
            st.session_state.park_id = row['park_id']
            st.session_state.park_name = row['park_name']
            st.rerun()
            
    st.markdown("---")

    col_doc, col_action = st.columns([2.5, 1], gap="large")

    with col_doc:
        st.markdown("## 1. Introdução e Contexto Histórico")
        st.write("""
        Este projeto nasceu em 2023 da necessidade de entender o comportamento das filas e a lotação do **Beto Carrero World (BCW)**. 
        Inicialmente, a abordagem era manual e reativa: os dados eram extraídos do site *Thrill-Data* por meio de downloads mensais e 
        individuais por atração. A análise ocorria em notebooks Jupyter, resultando em relatórios estáticos e apresentações de gráficos 
        fixos, sem interatividade.
        
        Em meados de 2025, devido a mudanças na política de acesso da fonte original, o projeto passou por uma reestruturação completa, 
        evoluindo para um **pipeline de dados automatizado, escalável e dinâmico**, utilizando infraestrutura em nuvem e ferramentas 
        modernas de *Data Engineering*.
        """)

        st.markdown("## 2. Arquitetura Técnica e Pipeline de Dados")
        st.write("A arquitetura atual foi projetada para ser resiliente e independente de intervenção manual:")
        st.markdown("""
        * **Fonte de Dados:** Integração direta com a API do `Queue-Times.com`, que fornece dados em tempo real baseados nos aplicativos oficiais dos parques.
        * **Processamento (ETL):** Utilização de funções **AWS Lambda** que executam rotinas periódicas. A função consome a API, normaliza os dados para um esquema padrão e os organiza.
        * **Armazenamento:**
            * **GitHub:** Atua como repositório de backup e histórico em formato `.csv`.
            * **Google BigQuery:** Warehouse analítico onde os dados são indexados para consultas rápidas e análise de grandes volumes históricos.
        * **Visualização:** Dashboard interativo desenvolvido em **Streamlit**, permitindo consultas dinâmicas e cruzamento de dados em tempo real.
        """)

        st.markdown("## 3. Descrição das Funcionalidades")
        data = {
            "Funcionalidade": ["⚡ Monitoramento em Tempo Real", "📊 Movimento por Atração", "📅 Calendário de Lotação"],
            "Descrição Técnica": [
                "Status atual, Top 4 esperas e gráfico de evolução temporal.",
                "Gráfico de barras segmentado por janelas horárias (ex: 10h-11h).",
                "Mapa de calor (Heatmap) anual de lotação diária."
            ],
            "Lógica dos Valores": [
                "Dados via GET API. Gráfico compara o dia atual para indicar tendência (Alta/Baixa).",
                "Agrupamento de milhões de registros. Algoritmo destaca os 3 horários de pico histórico.",
                "Média aritmética das atrações mecânicas. Escala de cores calibrada por quartis."
            ]
        }
        st.table(data)

        st.markdown("## 4. Tratamentos Específicos e Qualidade (BCW)")
        st.write("""Como o **Beto Carrero World** é o *home-park* do projeto, ele recebeu uma camada adicional de curadoria:""")
        st.markdown("""
        * **Normalização de Nomes:** Ajuste de caixa alta (ex: `SPIN BLAST` → `Spin Blast`) e unificação de marcas (ex: `Big Tower` → `Big Drop`).
        * **Limpeza de Outliers:** Filtros para ignorar erros de digitação de operadores (ex: esperas de 990 min).
        * **Filtro de Operação:** Remoção de períodos em que o parque estava fechado, evitando distorções nas médias reais.
        * **Seleção de IDs:** Consideração exclusiva de **atrações mecânicas**, excluindo shows e zoológico dos cálculos de lotação.
        """)

        st.markdown("## 5. Próximos Passos")
        st.markdown("""
        * Expansão da limpeza de dados para parques internacionais (Disney, Universal, etc.).
        * Implementação de modelos de **Machine Learning** para predição de filas futuras.
        """)
        
        st.caption("Documentação gerada para suporte ao Dashboard de Inteligência de Parques Temáticos.")
        
        st.markdown("## 6. Histórico de Versões (Changelog)")
        with st.expander("🔍 Clique para ver as notas de versão", expanded=False): 
            st.markdown("""
            ### **Versão 1.1** *(Atual)*
            * **⚡ Otimização de Performance:** Reestruturação do pipeline de comunicação com o Google BigQuery, migrando agregações pesadas para o lado do servidor. Redução de 95% no tráfego de dados e carregamento instantâneo.
            * **🌡️ Análise Diária e Heatmap Dinâmico:** Evolução da aba principal para permitir a consulta de datas passadas. Criação de um Heatmap de lotação por atração com quebra de tempo configurável (15m, 30m, 1h).
            * **🚫 Detecção de Paradas Técnicas:** Inteligência visual no Heatmap diário para aplicar transparência em blocos onde as atrações estavam fechadas ou em manutenção (fila = 0), evitando distorções na leitura.
            * **📱 UX Responsiva Avançada:** Implementação de transposição automática de matriz (linhas por colunas) via CSS para smartphones. Nomes das atrações movidos para o topo do gráfico no mobile para facilitar a leitura.
            * **🚀 Otimização de Fluxo (Mobile First):** Reposicionamento do seletor de parques para o topo absoluto da tela inicial, garantindo acesso imediato ao dashboard em telas menores sem necessidade de rolagem.
            * **📜 Notas de Versão:** Inclusão do painel de Changelog para rastreamento de melhorias.
            
            ---
            
            ### **Versão 1.0**
            * **🌍 Expansão Global:** Inclusão de suporte e mapeamento de fusos horários para novos parques internacionais (Disney, Universal, etc.).
            * **🔴 Hoje no Parque:** Criação da aba de monitoramento em tempo real com consumo via API e alertas de maiores filas atuais.
            * **📖 Documentação Integrada:** Implementação da tela inicial com contexto histórico e descrição técnica do pipeline de dados.
            
            ---
            
            ### **Versão 0.1** *(MVP - Lançamento Inicial)*
            * **🎡 Projeto Piloto:** Lançamento exclusivo para o parque *Beto Carrero World* (BCW).
            * **📊 Gráficos Analíticos:** Implementação das curvas de médias horárias históricas por atração.
            * **📅 Calendário de Lotação:** Desenvolvimento do Heatmap anual baseado em matrizes estatísticas de espera.
            """)

    with col_action:
        # Mantemos as informações adicionais e créditos aqui na barra lateral direita do desktop
        st.info("💡 **Dica:** O histórico do Beto Carrero World contém dados desde 2023 devido à migração do sistema legado.")
        st.markdown("Powered by [Queue-Times.com](https://queue-times.com/pt-BR)")

    st.stop()
    
# --- TELA DO DASHBOARD (PARQUE SELECIONADO) ---
with st.sidebar:
    st.markdown("---")
    st.markdown("### 👨‍💻 Desenvolvedor")
    st.write("**Luis Fernando Melnek Tacla**")
    st.markdown("[LinkedIn](https://www.linkedin.com/in/luis-fernando-melnek-tacla/) | [GitHub](https://github.com/LuisFTacla)")
    st.markdown('Powered by [Queue-Times.com](https://queue-times.com/pt-BR)')
    st.markdown("---")

if st.sidebar.button("⬅ Mudar de Parque"):
    st.session_state.park_id = None
    st.session_state.park_name = None
    st.rerun()

st.title(f"📊 {st.session_state.park_name}")

tz_map = {
    319: 'America/Sao_Paulo', 2: 'Europe/London', 4: 'Europe/Paris', 5: 'America/New_York',
    6: 'America/New_York', 7: 'America/New_York', 8: 'America/New_York', 9: 'Europe/Paris',
    15: 'America/New_York', 16: 'America/Los_Angeles', 17: 'America/Los_Angeles', 21: 'America/New_York',
    24: 'America/New_York', 28: 'Europe/Paris', 32: 'America/Los_Angeles', 61: 'America/Los_Angeles',
    64: 'America/New_York', 65: 'America/New_York', 66: 'America/Los_Angeles', 334: 'America/New_York'
}

current_tz = tz_map.get(st.session_state.park_id, 'UTC')

with st.spinner("🎢 Aguarde, estou buscando os dados do parque selecionado..."):
    df_horario = get_hourly_averages(st.session_state.park_id, current_tz)
    df_calendario, anos_disponiveis = get_daily_averages(st.session_state.park_id, current_tz)

def exibir_legenda_color_bar():
    fig = go.Figure(go.Heatmap(
        z=[[20, 30, 40, 50, 60]], colorscale='RdYlGn', reversescale=True, zmin=20, zmax=60, showscale=True, opacity=0,
        colorbar=dict(
            orientation='h', thickness=15, len=0.9, x=0.5, y=0.5, xanchor='center',
            tickvals=[20, 30, 40, 50, 60], ticktext=["Vazio", "Tranquilo", "Médio", "Movimentado", "Lotado"],
            title=dict(text="Tempo Médio de Espera (min)", font=dict(size=14), side='top')
        )
    ))
    fig.update_layout(height=100, margin=dict(l=10, r=10, t=55, b=0), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', xaxis=dict(showticklabels=False, showgrid=False, zeroline=False, fixedrange=True), yaxis=dict(showticklabels=False, showgrid=False, zeroline=False, fixedrange=True))
    return fig

def gerar_mes_plotly(df_espera, ano, mes_num):
    mes_data = df_espera[(df_espera['year'] == ano) & (df_espera['month'] == mes_num)].copy()
    if mes_data.empty: return None
    meses_nomes = {1:'Janeiro', 2:'Fevereiro', 3:'Março', 4:'Abril', 5:'Maio', 6:'Junho', 7:'Julho', 8:'Agosto', 9:'Setembro', 10:'Outubro', 11:'Novembro', 12:'Dezembro'}
    ordered_days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    labels_dias = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']
    def get_month_week(date):
        first_day = date.replace(day=1)
        return (date.day + first_day.weekday() - 1) // 7
    mes_data['week_of_month'] = mes_data['date'].apply(get_month_week)
    pivot_df = mes_data.pivot_table(values='wait_time', index='week_of_month', columns='day_of_week', aggfunc='mean')
    for day in ordered_days:
        if day not in pivot_df.columns: pivot_df[day] = np.nan
    pivot_df = pivot_df[ordered_days]
    for w in range(6):
        if w not in pivot_df.index: pivot_df.loc[w] = np.nan
    pivot_df = pivot_df.sort_index()
    text_matrix = []
    for week in pivot_df.index:
        row_text = []
        for day in ordered_days:
            date_row = mes_data[(mes_data['week_of_month'] == week) & (mes_data['day_of_week'] == day)]
            if not date_row.empty:
                d, w = date_row.iloc[0]['day'], date_row.iloc[0]['wait_time']
                row_text.append(f"{d:02d}<br><b>{int(w)}m</b>")
            else: row_text.append("")
        text_matrix.append(row_text)
    fig = go.Figure(data=go.Heatmap(z=pivot_df.values, x=labels_dias, y=list(range(6)), text=text_matrix, texttemplate="%{text}", textfont={"size": 10}, hoverinfo="none", colorscale='RdYlGn', reversescale=True, zmin=20, zmax=60, xgap=3, ygap=3, showscale=False))
    fig.update_layout(title=dict(text=meses_nomes[mes_num], x=0.5, xanchor='center'), height=300, yaxis=dict(autorange='reversed', showgrid=False, zeroline=False, showticklabels=False, fixedrange=True), xaxis=dict(showgrid=False, zeroline=False, fixedrange=True), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(l=5, r=5, t=40, b=20))
    return fig

# --- RENDERIZAÇÃO DAS TABS ---
if not df_calendario.empty:
    tab1, tab2, tab3 = st.tabs(["🔴 Hoje no Parque", "📊 Movimento por Atração", "📅 Calendário de Lotação"])

    # --- TAB 1: ANÁLISE DIÁRIA COM HEATMAP ---
    with tab1:
        st.subheader(f"📅 Análise Diária de Filas - {st.session_state.park_name}")
        
        # Leitura da largura da janela via JS direto no Python (Seguro e Responsivo)
        largura_tela = st_javascript("window.innerWidth")
        
        # Fallback de segurança caso o JS demore um milissegundo para responder no primeiro carregamento
        if largura_tela is None or largura_tela == 0:
            largura_tela = 1000 

        tz_alvo = pytz.timezone(current_tz)
        hoje_local = datetime.now(tz_alvo).date()
        
        data_sel = st.date_input(
            "Selecione o dia para análise:", 
            hoje_local, 
            max_value=hoje_local,
            format="DD/MM/YYYY" 
        )

        st.divider()

        # --- SEÇÃO TEMPO REAL (APENAS SE FOR HOJE) ---
        is_hoje = (data_sel == hoje_local)
        
        if is_hoje:
            st.markdown("### ⏱️ Status em Tempo Real (Agora)")
            live_rides = get_live_data(st.session_state.park_id)        
            
            if live_rides:
                df_live = pd.DataFrame(live_rides)
                df_live['name'] = df_live['name'].str.title()
                
                if st.session_state.park_id == 319:
                    bcw_mechanical_ids = [11329, 11366, 11332, 11340, 11330, 11328, 11373, 11326, 13872, 11368, 11367, 11444, 11358, 12325, 12326, 11327, 11335, 11336, 11338, 11344, 11459, 11334, 15407, 11331]
                    df_live = df_live[df_live['id'].isin(bcw_mechanical_ids)]
                
                df_live['status_display'] = df_live.apply(
                    lambda x: "🔴 Fechado" if not x['is_open'] or x['wait_time'] == 0 else f"🟢 {int(x['wait_time'])} min", 
                    axis=1
                )
                
                rides_abertos = df_live[df_live['is_open']].sort_values('wait_time', ascending=False)
                if not rides_abertos.empty:
                    st.markdown("##### 🔥 Maiores filas agora:")
                    cols = st.columns(4)
                    top_4 = rides_abertos.head(4)
                    for i, (idx, ride) in enumerate(top_4.iterrows()):
                        with cols[i]:
                            st.metric(label=ride['name'], value=f"{int(ride['wait_time'])} min")
                
                df_live['real_is_open'] = (df_live['is_open'] == True) & (df_live['wait_time'] > 0)
                total_abertas = df_live['real_is_open'].sum()
                total_fechadas = len(df_live) - total_abertas
                st.caption(f"✅ {total_abertas} atrações abertas | ❌ {total_fechadas} atrações fechadas")
                
                with st.expander("🔍 Ver todas as atrações e status detalhado", expanded=False):
                    df_display = df_live.sort_values(['real_is_open', 'wait_time'], ascending=[False, False])
                    st.dataframe(
                        df_display[['name', 'status_display']],
                        column_config={"name": "Atração", "status_display": "Tempo de Fila"},
                        hide_index=True, use_container_width=True
                    )
            else:
                st.error("Não foi possível conectar com a API de tempos de fila agora.")
            
            st.divider()

        # --- GRÁFICO DE LINHA (EVOLUÇÃO DO DIA SELECIONADO) ---
        st.markdown(f"### 📈 Evolução Geral das Filas - {data_sel.strftime('%d/%m/%Y')}")
        
        query_dia = f"""
            SELECT 
                EXTRACT(HOUR FROM DATETIME(timestamp_utc, '{current_tz}')) as hora,
                EXTRACT(MINUTE FROM DATETIME(timestamp_utc, '{current_tz}')) as minuto,
                wait_time
            FROM `theme-park-queue-data.theme_park_queues.historical-data`
            WHERE park_id = {st.session_state.park_id}
            AND DATE(timestamp_utc, '{current_tz}') = '{data_sel}'
            ORDER BY hora, minuto
        """
        df_dia = client.query(query_dia).to_dataframe()

        if not df_dia.empty:
            df_dia['horario'] = df_dia['hora'].astype(str).str.zfill(2) + ":" + df_dia['minuto'].astype(str).str.zfill(2)
            evolucao_dia = df_dia.groupby('horario')['wait_time'].mean().reset_index()
            
            fig_evolucao = px.line(
                evolucao_dia, x='horario', y='wait_time',
                labels={'wait_time': 'Tempo de Fila Médio (min)', 'horario': 'Hora do Dia'},
                template="plotly_white"
            )
            fig_evolucao.update_traces(line_color='#ef233c', line_width=3)
            st.plotly_chart(fig_evolucao, use_container_width=True)
        else:
            st.info(f"Nenhum registro histórico coletado para o dia {data_sel.strftime('%d/%m/%Y')}.")

        st.divider()

        # --- SEÇÃO DO HEATMAP COM O SELETOR DE INTERVALO ACOPLADO ---
        col_titulo_heat, col_sel_heat = st.columns([1.8, 1])
        
        with col_titulo_heat:
            st.markdown(f"### 🌡️ Heatmap de Lotação por Atração")
            
        with col_sel_heat:
            opcao_intervalo = st.selectbox(
                "Intervalo do Heatmap:",
                options=["1 Hora", "30 Minutos", "15 Minutos"],
                index=0,
                label_visibility="collapsed"
            )
            mapa_minutos = {"1 Hora": 60, "30 Minutos": 30, "15 Minutos": 15}
            minutos_sel = mapa_minutos[opcao_intervalo]
        
        df_heat_raw = get_daily_heatmap_data(st.session_state.park_id, current_tz, data_sel, minutos_sel)
        
        if not df_heat_raw.empty:
            df_heat_raw['label_tempo'] = (
                df_heat_raw['hora'].astype(str).str.zfill(2) + ":" + 
                df_heat_raw['minuto_bloco'].astype(str).str.zfill(2)
            )
            
            df_pivot_heat = df_heat_raw.pivot(
                index='name', 
                columns='label_tempo', 
                values='wait_time_medio'
            )
            df_pivot_heat = df_pivot_heat.reindex(sorted(df_pivot_heat.columns), axis=1)
            df_pivot_heat = df_pivot_heat.reindex(sorted(df_pivot_heat.index), axis=0)
            df_pivot_heat = df_pivot_heat.applymap(lambda x: None if pd.isna(x) or x <= 0 else x)
            
            # Decisão puramente em Python controlando qual gráfico construir
            if largura_tela > 600:
                # --- VERSÃO DESKTOP (NORMAL) ---
                fig_desktop = go.Figure(data=go.Heatmap(
                    z=df_pivot_heat.values, x=df_pivot_heat.columns, y=df_pivot_heat.index,
                    colorscale='RdYlGn', reversescale=True, zmin=10, zmax=90, xgap=2, ygap=2, connectgaps=False,
                    hovertemplate="Atração: %{y}<br>Horário: %{x}<br>Espera: %{z} min<extra></extra>",
                    showscale=False
                ))
                altura_desktop = max(400, len(df_pivot_heat) * 22)
                fig_desktop.update_layout(
                    paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                    height=altura_desktop, margin=dict(l=180, r=20, t=10, b=40),
                    dragmode=False,
                    xaxis=dict(tickangle=-45, fixedrange=True),
                    yaxis=dict(fixedrange=True)
                )
                st.plotly_chart(fig_desktop, use_container_width=True, config={'displayModeBar': False})
            else:
                # --- VERSÃO MOBILE (INVERTIDA / TRANSPOSTA) ---
                df_pivot_mobile = df_pivot_heat.T 
                fig_mobile = go.Figure(data=go.Heatmap(
                    z=df_pivot_mobile.values, x=df_pivot_mobile.columns, y=df_pivot_mobile.index,
                    colorscale='RdYlGn', reversescale=True, zmin=10, zmax=90, xgap=2, ygap=2, connectgaps=False,
                    hovertemplate="Horário: %{y}<br>Atração: %{x}<br>Espera: %{z} min<extra></extra>",
                    showscale=False
                ))
                
                altura_mobile = max(500, len(df_pivot_mobile) * 28)
                fig_mobile.update_layout(
                    paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                    height=altura_mobile, 
                    # Invertemos aqui: 140px de margem no topo (t) para caber os nomes, e apenas 20px embaixo (b)
                    margin=dict(l=60, r=10, t=140, b=20), 
                    dragmode=False,
                    xaxis=dict(
                        tickangle=-90, 
                        tickfont=dict(size=10), 
                        fixedrange=True,
                        side='top'  # 🌟 ESTA LINHA JOGA OS NOMES DAS ATRAÇÕES PARA CIMA!
                    ),
                    yaxis=dict(
                        autorange='reversed', 
                        tickfont=dict(size=11), 
                        fixedrange=True
                    )
                )
                st.plotly_chart(fig_mobile, use_container_width=True, config={'displayModeBar': False})
            
        else:
            st.info("Não há dados de atrações suficientes para gerar o heatmap deste dia.")

    # --- ABA 2: MOVIMENTO HISTÓRICO ---
    with tab2:
        if not df_horario.empty:
            atracao = st.selectbox("Selecione a Atração:", sorted(df_horario['name'].unique()))
            media_h = df_horario[df_horario['name'] == atracao].sort_values('hora_cheia')
            
            cores = ['#0068c9'] * len(media_h)
            if len(media_h) >= 3:
                top_3_indices = media_h['wait_time'].nlargest(3).index
                for idx in top_3_indices:
                    pos = media_h.index.get_loc(idx)
                    cores[pos] = '#ef233c'
                    
            fig_bar = px.bar(
                media_h, x='hora_cheia', y='wait_time', template="plotly_white", 
                labels={'hora_cheia': 'Horário (h)', 'wait_time': 'Espera Média Histórica Total (min)'}
            )
            fig_bar.update_traces(marker_color=cores)
            st.plotly_chart(fig_bar, use_container_width=True)
        else:
            st.info("Nenhum registro histórico de coletas encontrado para estruturar as médias de atrações.")

    # --- ABA 3: CALENDÁRIO DE LOTAÇÃO ---
    with tab3:
        if anos_disponiveis:
            if st.session_state.ano_sel not in anos_disponiveis:
                st.session_state.ano_sel = anos_disponiveis[-1]

            st.markdown("### 📅 Calendário de Lotação")
            
            cols = st.columns(len(anos_disponiveis))
            for idx, ano in enumerate(anos_disponiveis):
                with cols[idx]:
                    if st.button(str(ano), use_container_width=True, 
                                type="primary" if st.session_state.ano_sel == ano else "secondary"):
                        st.session_state.ano_sel = ano
                        st.rerun()
            
            st.plotly_chart(exibir_legenda_color_bar(), use_container_width=True, config={'displayModeBar': False})

            for i in range(1, 13, 2):
                c1, c2 = st.columns(2)
                with c1:
                    f = gerar_mes_plotly(df_calendario, st.session_state.ano_sel, i)
                    if f: st.plotly_chart(f, use_container_width=True, config={'displayModeBar': False})
                with c2:
                    if i+1 <= 12:
                        f2 = gerar_mes_plotly(df_calendario, st.session_state.ano_sel, i+1)
                        if f2: st.plotly_chart(f2, use_container_width=True, config={'displayModeBar': False})
else:
    st.info("Aguardando dados ou parque sem registros no período selecionado.")