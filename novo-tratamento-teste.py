import pandas as pd
import numpy as np
import os
import glob
import unicodedata
from pathlib import Path
from datetime import datetime

# --- CONFIGURAÇÕES DE CAMINHOS ---
REPO_ANTIGO = Path("../bcw-queue")
DESTINO_BASE = Path("data/beto_carrero_world")
CALENDARIO_PATH = REPO_ANTIGO / "calendario_operacao.xlsx"

# --- DICIONÁRIOS MESTRES ---
# Mapeamento oficial de IDs e Nomes Padronizados
MAPA_MESTRE_IDS = {
    'Autopista (bate-bate)': 11329, 'Baby Elefante': 11330, 'Barco Pirata': 11340,
    'Betinho Carrero 2D': 13872, 'Big Tower': 11334, 'Carrossel Veneziano': 11366,
    'Ferrovia DinoMagic': 11344, 'FireWhip': 11327, 'Madagascar Crazy River Adventure!': 11338,
    'Montanha-russa Dum Dum': 11368, 'Raskapuska': 11367, 'Rebuliço': 11444,
    'Roda-Gigante': 11328, 'Spin Blast': 12325, 'Star Mountain': 11335,
    'Super Soaker Splash': 12326, 'Tchibum': 11336, 'Tigor Mountain': 11332,
    'Turbo Drive': 15407, 'Xícaras Malucas': 11373, 'Pedalinho': 11326, 'Big Drop': 11459
}

# De-Para para nomes variantes (Sinônimos e Erros)
SINONIMOS_RIDES = {
    'BETINHO CARRERO 4D': 'Betinho Carrero 2D',
    'REBULICO': 'Rebuliço',
    'XICARAS MALUCAS': 'Xícaras Malucas',
    'SPIN BLAST': 'Spin Blast',
    'SUPER SOAKER SPLASH': 'Super Soaker Splash',
    'TURBO DRIVE': 'Turbo Drive',
}

# --- FUNÇÕES DE APOIO ---

def normalizar_texto(texto):
    if pd.isna(texto): return ""
    nksf = unicodedata.normalize('NFKD', str(texto))
    return "".join([c for c in nksf if not unicodedata.combining(c)]).upper().strip()

def remover_acentos(txt):
    if not isinstance(txt, str): return txt
    return "".join(c for c in unicodedata.normalize('NFD', txt) 
                   if unicodedata.category(c) != 'Mn')

def carregar_calendario():
    print("Carregando calendário...")
    df_cal = pd.read_excel(CALENDARIO_PATH)
    df_cal['date'] = pd.to_datetime(df_cal['date']).dt.date
    return df_cal

# --- PROCESSADORES DE FONTES ESPECÍFICAS ---

def processar_fonte_recuperada_1():
    print("Processando Fonte Recuperada 1...")
    path = REPO_ANTIGO / "recovered_data/bcw_src1"
    files = glob.glob(str(path / "*.csv"))
    lista = []
    
    # Mapeamento específico para esta fonte
    mapa_atracao_src1 = {
        "REBULICO": (11444, "Rebuliço"),
        "SPIN BLAST": (12325, "Spin Blast"),
        "SUPER SOAKER SPLASH": (12326, "Super Soaker Splash"),
        "XICARAS MALUCAS": (11373, "Xícaras Malucas")
    }

    for f in files:
        df = pd.read_csv(f)
        df['ride_norm'] = df['Ride'].apply(normalizar_texto)
        df['id'] = df['ride_norm'].map(lambda x: mapa_atracao_src1.get(x, (None, None))[0])
        df['name'] = df['ride_norm'].map(lambda x: mapa_atracao_src1.get(x, (None, None))[1])
        
        df = df.dropna(subset=['id'])
        dt_col = pd.to_datetime(df['Date/Time'])
        df['data_local'] = dt_col.dt.date
        df['hora_local'] = dt_col.dt.time
        df['wait_time'] = df['Wait Time']
        df['is_open'] = True
        lista.append(df[['id', 'name', 'is_open', 'wait_time', 'data_local', 'hora_local']])
    
    return pd.concat(lista) if lista else pd.DataFrame()
  
def processar_fonte_recuperada_2(mapa_ids):
    print("Processando Fonte Recuperada 2...")
    path = REPO_ANTIGO / "recovered_data/bcw_src2/data-recovered-2.csv"
    if not path.exists(): return pd.DataFrame()
    df = pd.read_csv(path)
    
    # Esta fonte geralmente já tem ID e Name, mas vamos garantir a normalização
    df['name'] = df['name'].replace(SINONIMOS_RIDES)
    # Ajuste de data se necessário (assumindo que já possui data_local ou last_updated)
    if 'last_updated_api' in df.columns:
        dt = pd.to_datetime(df['last_updated_api'], errors='coerce') - pd.Timedelta(hours=3)
        df['data_local'] = dt.dt.date
        df['hora_local'] = dt.dt.time
    
    return df[['id', 'name', 'wait_time', 'data_local', 'hora_local']]

def processar_marco_2025(mapa_ids):
    print("Processando Março 2025...")
    path = REPO_ANTIGO / "recovered_data/bcw_25mar/wait_times_2025_03.csv"
    if not path.exists(): return pd.DataFrame()
    
    df = pd.read_csv(path)
    # Aplicar sinônimos antes
    df['ride_name'] = df['ride_name'].replace(SINONIMOS_RIDES)
    
    mapa_sem_acentos = {remover_acentos(k): v for k, v in mapa_ids.items()}
    
    def buscar_id(nome):
        if nome in mapa_ids: return mapa_ids[nome]
        nome_limpo = remover_acentos(nome)
        return mapa_sem_acentos.get(nome_limpo, None)

    df['id'] = df['ride_name'].apply(buscar_id)
    df['name'] = df['ride_name']
    df['data_local'] = pd.to_datetime(df['date']).dt.date
    df['hora_local'] = pd.to_datetime(df['time'], format='%H:%M:%S', errors='coerce').dt.time
    df['is_open'] = df['wait_time'].apply(lambda x: True if x >= 0 else False)
    
    return df.dropna(subset=['id'])[['id', 'name', 'is_open', 'wait_time', 'data_local', 'hora_local']]

# --- PIPELINE PRINCIPAL ---

def pipeline_unificada():
    df_cal = carregar_calendario()
    lista_consolidada = []
    
    ids_beto_carrero = list(MAPA_MESTRE_IDS.values())

    # 1. Dados da pasta /data padrão
    print("Processando arquivos da pasta /data...")
    data_path = REPO_ANTIGO / "data"
    for pasta_mes in sorted(data_path.iterdir()):
        if not pasta_mes.is_dir(): continue
        
        arquivos_beto = list(pasta_mes.glob("*betocarrero*.csv")) + \
                         list(pasta_mes.glob("*beto_carrero_world*.csv"))
                         
        arquivos_beto = list(set(arquivos_beto))
        
        print(f"Processando mês: {pasta_mes.name}")
        for arquivo in arquivos_beto:
            try:
                df = pd.read_csv(arquivo, sep=None, engine='python', on_bad_lines='skip')
                if 'id' not in df.columns: continue
                
                df = df[df['id'].isin(ids_beto_carrero)]
                
                df['last_updated_api'] = pd.to_datetime(df['last_updated_api'], errors='coerce') - pd.Timedelta(hours=3)
                df = df.dropna(subset=['last_updated_api'])
                df['data_local'] = df['last_updated_api'].dt.date
                df['hora_local'] = df['last_updated_api'].dt.time
                lista_consolidada.append(df[['id', 'name', 'wait_time', 'data_local', 'hora_local']])
            except: continue

    # 2. Adicionar Fontes Especiais
    lista_consolidada.append(processar_fonte_recuperada_1())
    lista_consolidada.append(processar_fonte_recuperada_2(MAPA_MESTRE_IDS)) # <--- ADICIONADO AQUI
    lista_consolidada.append(processar_marco_2025(MAPA_MESTRE_IDS))

    # 3. Consolidação e Limpeza de Duplicados
    print("Consolidando dados e removendo duplicados...")
    full_df = pd.concat(lista_consolidada, ignore_index=True)
    
    # Padronização de nomes (Case e Sinônimos)
    print("Padronizando nomes das atrações...")
    full_df['name'] = full_df['name'].apply(lambda x: SINONIMOS_RIDES.get(normalizar_texto(x), x))
    
    # ARREDONDAMENTO POR MINUTO para matar duplicatas 15:35:00 vs 15:35:12
    print("Arredondando timestamps para o minuto mais próximo...")
    full_df['dt_full'] = pd.to_datetime(full_df['data_local'].astype(str) + ' ' + full_df['hora_local'].astype(str))
    full_df['dt_minuto'] = full_df['dt_full'].dt.floor('min')
    
    antes = len(full_df)
    full_df = full_df.drop_duplicates(subset=['id', 'dt_minuto'], keep='first')
    print(f"Registros duplicados removidos: {antes - len(full_df)}")

    # 4. Filtros de Calendário e Negócio
    full_df = full_df.merge(df_cal, left_on='data_local', right_on='date', how='left')
    full_df = full_df[full_df['park_open'] == True]
    
    # Filtro de horários (Parque Aberto)
    # Convertendo colunas para garantir comparação
    full_df['park_opening_time'] = pd.to_datetime(full_df['park_opening_time'], format='%H:%M:%S', errors='coerce').dt.time
    full_df['park_closing_time'] = pd.to_datetime(full_df['park_closing_time'], format='%H:%M:%S', errors='coerce').dt.time
    
    mask_horario = (full_df['hora_local'] >= full_df['park_opening_time']) & \
                   (full_df['hora_local'] <= full_df['park_closing_time'])
    full_df = full_df[mask_horario]

    # Regras de wait_time
    full_df.loc[full_df['wait_time'] == 0, 'is_open'] = False
    full_df.loc[full_df['wait_time'] > 0, 'is_open'] = True
    full_df = full_df[(full_df['wait_time'] >= 0) & (full_df['wait_time'] <= 300)]

    # 5. Salvamento Organizado
    print("Salvando arquivos finais...")
    colunas_finais = ['id', 'name', 'is_open', 'wait_time', 'data_local', 'hora_local']
    
    # Agrupar por ano e mês para salvar
    full_df['year'] = pd.to_datetime(full_df['data_local']).dt.year
    full_df['month'] = pd.to_datetime(full_df['data_local']).dt.month
    
    for (ano, mes), grupo in full_df.groupby(['year', 'month']):
        dir_ano = DESTINO_BASE / str(ano)
        dir_ano.mkdir(parents=True, exist_ok=True)
        nome_arquivo = f"{str(mes).zfill(2)}.csv"
        grupo[colunas_finais].to_csv(dir_ano / nome_arquivo, index=False)
        print(f"Finalizado: {ano}/{str(mes).zfill(2)}")

if __name__ == "__main__":
    pipeline_unificada()