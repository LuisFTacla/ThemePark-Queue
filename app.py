import streamlit as st
import pandas as pd
import numpy as np
import requests
import datetime
from datetime import datetime, timezone
import plotly.graph_objects as go
import plotly.express as px
from google.cloud import bigquery
import os
from google.oauth2 import service_account

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Theme Park Analytics", layout="wide")

# Autenticação
# Função para autenticação híbrida
def get_bq_client():
    # 1. Tenta carregar das Secrets do Streamlit (Produção)
    if "gcp_service_account" in st.secrets:
        info = st.secrets["gcp_service_account"]
        credentials = service_account.Credentials.from_service_account_info(info)
        return bigquery.Client(credentials=credentials, project=info["project_id"])
    
    # 2. Se não achar as Secrets, usa o arquivo local (Desenvolvimento)
    else:
        # Aqui ele vai procurar o arquivo que está na sua pasta
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "theme-park-queue-data-f2e1d4785d38.json"
        return bigquery.Client()

# Agora o client é criado automaticamente conforme o ambiente
client = get_bq_client()

# CSS Customizado
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

# --- FUNÇÕES DE DADOS ---

@st.cache_data(ttl=86400) # Cache de 24h para a lista de parques
def get_available_parks():
    query = "SELECT DISTINCT park_id, park_name FROM `theme-park-queue-data.theme_park_queues.historical-data` ORDER BY park_name"
    return client.query(query).to_dataframe()

@st.cache_data(ttl=3600, show_spinner=False) # Cache de 1h para os dados do parque
def load_park_data(park_id, timezone):
    query = f"""
    SELECT 
        CASE 
            WHEN ride_name IN ('Big Tower', 'BIG TOWER', 'big tower') THEN 'Big Drop'
            ELSE ride_name 
        END as name,
        wait_time,
        EXTRACT(HOUR FROM DATETIME(timestamp_utc, '{timezone}')) as hora_cheia,
        DATE(timestamp_utc, '{timezone}') as data_local,
        EXTRACT(YEAR FROM DATETIME(timestamp_utc, '{timezone}')) as ano_registro
    FROM `theme-park-queue-data.theme_park_queues.historical-data`
    WHERE park_id = {park_id}
    """
    df = client.query(query).to_dataframe()
    if df.empty: return None, None, []
    
    # Extrair anos únicos para os botões dinâmicos
    anos_disponiveis = sorted(df['ano_registro'].unique().tolist())
    
    print(anos_disponiveis)

    df['data_local'] = pd.to_datetime(df['data_local'])
    espera_media = df[df['wait_time'] > 0].groupby('data_local')['wait_time'].mean().reset_index()
    espera_media['wait_time'] = espera_media['wait_time'].round(0).astype(int)
    espera_media['date'] = espera_media['data_local']
    espera_media['year'] = espera_media['date'].dt.year
    espera_media['month'] = espera_media['date'].dt.month
    espera_media['day'] = espera_media['date'].dt.day
    espera_media['day_of_week'] = espera_media['date'].dt.day_name()
    espera_media['week_of_year'] = espera_media['date'].dt.isocalendar().week
    
    # Ajuste virada de ano
    espera_media.loc[(espera_media['month'] == 1) & (espera_media['week_of_year'] > 50), 'week_of_year'] = 0
    
    return df, espera_media, anos_disponiveis

@st.cache_data(ttl=60)
def get_live_data(park_id):
    url = f"https://queue-times.com/parks/{park_id}/queue_times.json"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        
        rides = []
        # A API pode ter 'lands' ou 'rides' na raiz
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
    
# --- TELA INICIAL (SELEÇÃO) ---

# --- TELA INICIAL COM DOCUMENTAÇÃO COMPLETA ---

if st.session_state.park_id is None:
    # Título Principal com estilo
    st.markdown("# 🎡 Theme Park Data Intelligence")
    st.caption("Desenvolvido por **Luis Fernando Melnek Tacla** | Versão 1.0 | 2026")
    st.markdown("---")

    # Layout: Documentação na esquerda (maior) e Seleção na direita (sticky)
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
        # Tabela de funcionalidades
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
        st.write("""
        Como o **Beto Carrero World** é o *home-park* do projeto, ele recebeu uma camada adicional de curadoria:
        """)
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

    with col_action:
        st.markdown("### 🚀 Iniciar Análise")
        # Aqui você mantém seu código de busca e selectbox
        df_parks = get_available_parks() 
        
        if not df_parks.empty:
            selected_park_name = st.selectbox(
                "Escolha um Parque:", 
                ["Selecione um destino..."] + df_parks['park_name'].tolist()
            )
            
            if selected_park_name != "Selecione um destino...":
                row = df_parks[df_parks['park_name'] == selected_park_name].iloc[0]
                st.session_state.park_id = row['park_id']
                st.session_state.park_name = row['park_name']
                st.rerun()
        
        st.divider()
        st.info("💡 **Dica:** O histórico do Beto Carrero World contém dados desde 2023 devido à migração do sistema legado.")
        st.markdown("Powered by [Queue-Times.com](https://queue-times.com/pt-BR)")

    st.stop()
    
# --- TELA DO DASHBOARD (PARQUE SELECIONADO) ---
with st.sidebar:
    st.markdown("---")
    st.markdown("### 👨‍💻 Desenvolvedor")
    st.write("**Luis Fernando Melnek Tacla**")
    st.markdown("[LinkedIn](https://www.linkedin.com/in/luis-fernando-melnek-tacla/) | [GitHub](https://github.com/LuisFTacla)")
    st.markdown(
        'Powered by [Queue-Times.com](https://queue-times.com/pt-BR)'
    )
    st.markdown("---")

# Botão para voltar
if st.sidebar.button("⬅ Mudar de Parque"):
    st.session_state.park_id = None
    st.session_state.park_name = None
    st.rerun()

st.title(f"📊 {st.session_state.park_name}")

# Mapeamento de fusos (necessário para a query)
# Adicione aqui os fusos conforme os parques que você cadastrou
tz_map = {
    319: 'America/Sao_Paulo',
    2: 'Europe/London',
    4: 'Europe/Paris',
    5: 'America/New_York',
    6: 'America/New_York',
    7: 'America/New_York',
    8: 'America/New_York',
    9: 'Europe/Paris',
    15: 'America/New_York',
    16: 'America/Los_Angeles',
    17: 'America/Los_Angeles',
    21: 'America/New_York',
    24: 'America/New_York',
    28: 'Europe/Paris',
    32: 'America/Los_Angeles',
    61: 'America/Los_Angeles',
    64: 'America/New_York',
    65: 'America/New_York',
    66: 'America/Los_Angeles',
    334: 'America/New_York'
}

current_tz = tz_map.get(st.session_state.park_id, 'UTC')

with st.spinner("🎢 Aguarde, estou buscando os dados do parque selecionado..."):
    df_bruto, df_calendario, anos_disponiveis = load_park_data(st.session_state.park_id, current_tz)

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
            x=0.5, y=0.5,
            xanchor='center',
            tickvals=[20, 30, 40, 50, 60],
            ticktext=["Vazio", "Tranquilo", "Médio", "Movimentado", "Lotado"],
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

if df_bruto is not None:
    tab1, tab2, tab3 = st.tabs(["🔴 Hoje no Parque", "📊 Movimento por Atração", "📅 Calendário de Lotação"])

    with tab1:
        st.subheader(f"⏱️ Filas em Tempo Real - {st.session_state.park_name}")
        live_rides = get_live_data(st.session_state.park_id)        
        
        if live_rides:
            df_live = pd.DataFrame(live_rides)
            
            df_live['name'] = df_live['name'].str.title()
            
            correcoes_nomes = {
                "TURBO DRIVE": "Turbo Drive",
                "SUPER SOAKER SPLASH": "Super Soaker Splash",
                "SPIN BLAST": "Spin Blast"
            }
            
            if st.session_state.park_id == 319:
                bcw_mechanical_ids = [11329, 11366, 11332, 11340, 11330, 11328, 11373, 11326, 13872, 11368, 11367, 11444, 11358, 12325, 12326, 11327, 11335, 11336, 11338, 11344, 11459, 11334, 15407, 11331]
                df_live = df_live[df_live['id'].isin(bcw_mechanical_ids)]
            
            df_live['status_display'] = df_live.apply(
                lambda x: "🔴 Fechado" if not x['is_open'] or x['wait_time'] == 0 else f"🟢 {int(x['wait_time'])} min", 
                axis=1
            )
            # --- CARDS DE TEMPO REAL ---
            # Filtramos apenas os que estão abertos para os destaques
            rides_abertos = df_live[df_live['is_open']].sort_values('wait_time', ascending=False)
            
            if not rides_abertos.empty:
                st.markdown("##### 🔥 Maiores filas agora:")
                cols = st.columns(4)
                top_4 = rides_abertos.head(4)
                
                for i, (idx, ride) in enumerate(top_4.iterrows()):
                    with cols[i]:
                        st.metric(label=ride['name'], value=f"{int(ride['wait_time'])} min")
            
            st.divider()

            # --- GRÁFICO DE LINHA (DIA ATUAL) ---
            st.markdown("### 📈 Evolução das Filas Hoje")
            
            # Aqui buscamos os dados do dia atual que já estão no BigQuery
            hoje_utc = datetime.now(timezone.utc).date()
            query_hoje = f"""
                SELECT 
                    EXTRACT(HOUR FROM DATETIME(timestamp_utc, '{current_tz}')) as hora,
                    EXTRACT(MINUTE FROM DATETIME(timestamp_utc, '{current_tz}')) as minuto,
                    wait_time
                FROM `theme-park-queue-data.theme_park_queues.historical-data`
                WHERE park_id = {st.session_state.park_id}
                AND DATE(timestamp_utc, '{current_tz}') = CURRENT_DATE('{current_tz}')
                ORDER BY hora, minuto
            """
            df_hoje = client.query(query_hoje).to_dataframe()

            if not df_hoje.empty:
                df_hoje['horario'] = df_hoje['hora'].astype(str).str.zfill(2) + ":" + df_hoje['minuto'].astype(str).str.zfill(2)
                evolucao_dia = df_hoje.groupby('horario')['wait_time'].mean().reset_index()
                
                fig_evolucao = px.line(
                    evolucao_dia, 
                    x='horario', 
                    y='wait_time',
                    title=f"Tempo médio de fila no Parque - {datetime.now().strftime('%d/%m/%Y')}",
                    labels={'wait_time': 'Tempo de Fila Médio (min)', 'horario': 'Hora do Dia'},
                    template="plotly_white"
                )
                fig_evolucao.update_traces(line_color='#ef233c', line_width=3)
                st.plotly_chart(fig_evolucao, use_container_width=True)
            else:
                st.info("Os dados de evolução do dia começarão a aparecer assim que a primeira coleta de hoje for processada.")

            # --- PROCESSAMENTO REFINADO ---
            # Consideramos aberta apenas a atração que tem is_open=True E wait_time > 0
            # No BCW, como is_open é sempre True, o wait_time é quem manda.
            df_live['real_is_open'] = (df_live['is_open'] == True) & (df_live['wait_time'] > 0)

            # Resumo estatístico corrigido
            total_abertas = df_live['real_is_open'].sum()
            total_fechadas = len(df_live) - total_abertas

            # Exibição do resumo
            st.caption(f"✅ {total_abertas} {('atração aberta' if total_abertas == 1 else 'atrações abertas')} | ❌ {total_fechadas} {('atração fechada' if total_fechadas == 1 else 'atrações fechadas')}")

            # --- AJUSTE NA TABELA DETALHADA ---
            with st.expander("🔍 Ver todas as atrações e status detalhado", expanded=False):
                # Usamos real_is_open para ordenar: quem tem fila fica no topo
                df_display = df_live.sort_values(['real_is_open', 'wait_time'], ascending=[False, False])
                
                st.dataframe(
                    df_display[['name', 'status_display']],
                    column_config={
                        "name": "Atração",
                        "status_display": "Tempo de Fila"
                    },
                    hide_index=True,
                    use_container_width=True
                )
                
        else:
            st.error("Não foi possível conectar com a API de tempos de fila agora.")
    with tab2:
        atracao = st.selectbox("Selecione a Atração:", sorted(df_bruto['name'].unique()))
        df_bar = df_bruto[(df_bruto['name'] == atracao) & (df_bruto['wait_time'] > 0)]
        media_h = df_bar.groupby('hora_cheia')['wait_time'].mean().reset_index()
        media_h = media_h.sort_values('hora_cheia')
        cores = ['#0068c9'] * len(media_h)
        if len(media_h) >= 3:
            top_3_indices = media_h['wait_time'].nlargest(3).index
            for idx in top_3_indices:
                pos = media_h.index.get_loc(idx)
                cores[pos] = '#ef233c'
        fig_bar = px.bar(media_h, x='hora_cheia', y='wait_time', template="plotly_white", labels={'hora_cheia': 'Horário (h)', 'wait_time': 'Espera Média (min)'})
        fig_bar.update_traces(marker_color=cores)
        st.plotly_chart(fig_bar, use_container_width=True)
    with tab3:
        if anos_disponiveis:
            # Se o ano selecionado não existir nos dados desse parque, 
            # define o ano mais recente como padrão
            if st.session_state.ano_sel not in anos_disponiveis:
                st.session_state.ano_sel = anos_disponiveis[-1]

            st.markdown("### 📅 Calendário de Lotação")
            
            # Criamos as colunas dinamicamente baseado na quantidade de anos
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