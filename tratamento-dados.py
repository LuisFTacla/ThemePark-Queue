import pandas as pd
import os
from pathlib import Path
from datetime import datetime, timedelta

# --- CONFIGURAÇÕES ---
REPO_ANTIGO = Path("../bcw-queue")
PARQUE_NOME = "beto_carrero_world"
PARQUE_ID_FOLDER = "beto_carrero_world" # Nome da pasta no novo repo
IDS_INTERESSE = [
    11329, # Autopista 
    11330, # Baby Elefante
    11340, # Barco Pirata
    13872, # Betinho Carrero 2D
    11459, # Big Drop
    11334, # Big Tower
    11366, # Carrossel Veneziano
    11344, # Ferrovia DinoMagic
    11327, # FireWhip
    11338, # Madagascar Crazy River Adventure
    11368, # DumDum
    11367, # Raskapuska
    11444, # Rebuliço
    11328, # Roda Gigante
    12325, # Spin Blast
    11335, # Star Mountain
    12326, # Super Soaker Splash
    11336, # Tchibum
    11332, # Tigor Mountain
    15407, # Turbo Drive
    11373, # Xicaras Malucas
    11326, # Pedalinho
]

# 1. Carregar Calendário
df_cal = pd.read_excel(REPO_ANTIGO / "calendario_operacao.xlsx")
df_cal['date'] = pd.to_datetime(df_cal['date']).dt.date

df_cal['park_opening_time'] = pd.to_datetime(df_cal['park_opening_time'], format='%H:%M:%S').dt.time
df_cal['park_closing_time'] = pd.to_datetime(df_cal['park_closing_time'], format='%H:%M:%S').dt.time

print("Calendário carregado com sucesso.")
print(df_cal.head())

def tratar_dados():
  data_path = REPO_ANTIGO / "data"
  
  for pasta_mes in sorted(data_path.iterdir()):
    if not pasta_mes.is_dir(): continue
    
    dados_do_mes_lista = []
    
    for arquivo in sorted(pasta_mes.glob("*.csv")):
      try:
        # sep=None com engine='python' detecta se é , ou ; sozinho
        df = pd.read_csv(arquivo, sep=None, engine='python', on_bad_lines='skip')
                
        if df.empty or 'id' not in df.columns:
          continue
      except Exception as e:
        print(f"Erro ao ler {arquivo.name}: {e}")
        continue
      
      # --- PASSO 1: Filtrar IDs de rides ---
      df = df[df['id'].isin(IDS_INTERESSE)]
      
      # --- PASSO 2: Ajustar data/hora para horário local ---
      df['last_updated_api'] = pd.to_datetime(df['last_updated_api'])- pd.Timedelta(hours=3)
      df['data_local'] = df['last_updated_api'].dt.date
      df['hora_local'] = df['last_updated_api'].dt.time
      
      # Merge com calendário para filtrar dias e horários
      df = df.merge(df_cal, left_on='data_local', right_on='date', how='left')
      
      # --- PASSO 3: Filtrar apenas horários em que o parque estava aberto ---
      df = df[df['park_open'] == True]
      
      # --- PASSO 4: Filtrar horários de operação ---
      df['park_opening_time'] = pd.to_datetime(df['park_opening_time'], format='%H:%M:%S').dt.time
      df['park_closing_time'] = pd.to_datetime(df['park_closing_time'], format='%H:%M:%S').dt.time
      
      df = df[(df['hora_local'] >= df['park_opening_time']) & (df['hora_local'] <= df['park_closing_time'])]
      
      # --- PASSO 5: wait_time 0 -> is_open False ---
      df.loc[df['wait_time'] == 0, 'is_open'] = False
      
      # --- PASSO 6: Remoção de Ruídos ---
      # Filtro simples: remover filas > 300 min ou negativas
      df = df[(df['wait_time'] >= 0) & (df['wait_time'] <= 300)]
      
      dados_do_mes_lista.append(df)
    
    if dados_do_mes_lista:
      df_final_mes = pd.concat(dados_do_mes_lista, ignore_index=True)
      salvar_novo_formato(df_final_mes, pasta_mes.name)
      
def salvar_novo_formato(df, nome_pasta_mes):
  ano, mes = nome_pasta_mes.split("-")
  
  destino = Path("data") / PARQUE_ID_FOLDER / ano
  destino.mkdir(parents=True, exist_ok=True)
  
  colunas_finais = ['id', 'name', 'is_open', 'wait_time', 'data_local', 'hora_local']
  df_save = df[colunas_finais]
  
  df_save.to_csv(destino / f"{mes}.csv", index=False)
  print(f"Processando: {ano}/{mes}")
        
if __name__ == "__main__":
  tratar_dados()