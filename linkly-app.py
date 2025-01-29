import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import dotenv
import os

dotenv.load_dotenv()

# Substitua pela sua chave de API e ID do workspace
API_KEY = os.getenv("API_KEY")
WORKSPACE_ID = os.getenv("WORKSPACE_ID")
BASE_URL = "https://app.linklyhq.com/api/v1"

st.set_page_config(layout="wide")

# ------------------------------------------------------------------------------
#                               FUNÇÕES DE API
# ------------------------------------------------------------------------------
def fetch_tracked_links():
    """
    Busca todos os links rastreados.
    """
    endpoint = f"{BASE_URL}/workspace/{WORKSPACE_ID}/links/export"
    params = {"api_key": API_KEY}
    try:
        response = requests.get(endpoint, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Erro ao buscar links rastreados: {e}")
        return []


def fetch_clicks_for_link(link_id, start_date, end_date):
    """
    Busca cliques diários (tráfego) para um link em um intervalo de datas.
    """
    endpoint = f"{BASE_URL}/workspace/{WORKSPACE_ID}/clicks"
    params = {
        "api_key": API_KEY,
        "link_ids[]": link_id,
        "start": start_date,
        "end": end_date,
        "workspace_id": WORKSPACE_ID
    }
    try:
        response = requests.get(endpoint, params=params, timeout=10)
        response.raise_for_status()
        return response.json().get("traffic", [])
    except requests.exceptions.RequestException as e:
        st.error(f"Erro ao buscar análises para o link ID {link_id}: {e}")
        return []


# ------------------------------------------------------------------------------
#                           FUNÇÕES AUXILIARES
# ------------------------------------------------------------------------------
def initialize_session_state():
    """
    Inicializa o estado da sessão (tracked_links e analytics_data).
    Só é buscado uma vez para evitar re-buscar desnecessariamente.
    """
    if "tracked_links" not in st.session_state:
        with st.spinner("Carregando dados dos links..."):
            st.session_state.tracked_links = fetch_tracked_links()

    if "analytics_data" not in st.session_state:
        with st.spinner("Carregando dados de cliques..."):
            st.session_state.analytics_data = {}

            # Em vez de 1 ano, vamos pegar 10 anos atrás,
            # para garantir um histórico bem amplo.
            dez_anos_atras = (datetime.now() - timedelta(days=3650)).strftime("%Y-%m-%d")
            hoje = datetime.now().strftime("%Y-%m-%d")

            for link in st.session_state.tracked_links:
                link_id = link["id"]
                st.session_state.analytics_data[link_id] = fetch_clicks_for_link(
                    link_id,
                    dez_anos_atras,
                    hoje
                )


def preprocess_clicks_data_for_range(link_id, link_name, start_date, end_date):
    """
    Para um link_id e link_name, extrai os cliques diários no intervalo [start_date, end_date]
    e retorna um DataFrame com colunas ["Data", link_name].
    """
    # Todos os cliques foram obtidos em initialize_session_state (últimos 10 anos). Filtra localmente.
    all_clicks_data = st.session_state.analytics_data.get(link_id, [])
    date_range = pd.date_range(start=start_date, end=end_date, freq="D")

    if not all_clicks_data:
        return pd.DataFrame({"Data": date_range, link_name: 0})

    df = pd.DataFrame(all_clicks_data)
    df["Data"] = pd.to_datetime(df["t"])
    df = df.rename(columns={"y": link_name})

    full_df = pd.DataFrame({"Data": date_range})
    merged = pd.merge(full_df, df[["Data", link_name]], on="Data", how="left")
    merged[link_name] = merged[link_name].fillna(0)

    return merged


# ------------------------------------------------------------------------------
#                                APLICAÇÃO
# ------------------------------------------------------------------------------
def main():
    st.title("Links Rastreados do Linkly")

    # 1) Inicializa o estado da sessão
    initialize_session_state()

    # 2) Selecionar intervalo de datas
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Data Inicial", datetime.now() - timedelta(days=30))
    with col2:
        end_date = st.date_input("Data Final", datetime.now())

    # 3) Prepara dados para a tabela e armazena séries temporais para cada link
    table_rows = []
    link_time_series_map = {}  # nome_do_link -> DataFrame filtrado

    for link in st.session_state.tracked_links:
        link_id = link["id"]
        link_name = link["name"]
        link_url = link["url"]

        # Filtra os cliques no intervalo selecionado
        df_filtered = preprocess_clicks_data_for_range(link_id, link_name, start_date, end_date)
        total_clicks_in_range = df_filtered[link_name].sum()

        link_time_series_map[link_name] = df_filtered  # chave é o nome do link

        table_rows.append({
            "Nome": link_name,
            "Cliques (Intervalo Selecionado)": total_clicks_in_range,
            "Total de Cliques (Lifetime)": link["clicks_count"]  # obtido da API
        })

    # 4) Converte em DataFrame e adiciona linha de soma (Total de cliques)
    df_table = pd.DataFrame(table_rows)

    sum_of_all_clicks_range = df_table["Cliques (Intervalo Selecionado)"].sum()
    # Soma dos cliques de todos os links, para exibir como "lifetime"
    sum_of_all_lifetime_clicks = sum(
        link.get("clicks_count", 0) for link in st.session_state.tracked_links
    )

    sum_row = {
        "Nome": "Total de cliques",
        "Cliques (Intervalo Selecionado)": sum_of_all_clicks_range,
        "Total de Cliques (Lifetime)": sum_of_all_lifetime_clicks
    }
    df_table = pd.concat([df_table, pd.DataFrame([sum_row])], ignore_index=True)

    st.write("### Lista de Links")

    st.dataframe(df_table, hide_index=True, use_container_width=True)

    # 5) Multi-select para plotagem
    link_names = list(link_time_series_map.keys())
    plot_options = ["Total de cliques"] + link_names
    default_selection = ["Total de cliques"]

    selected_links = st.multiselect(
        "Selecione os links para plotar:",
        options=plot_options,
        default=default_selection
    )

    if not selected_links:
        st.info("Selecione ao menos um link para visualizar o gráfico.")
        return

    # 6) Monta o DataFrame final para o gráfico
    merged_plot_df = pd.DataFrame({"Data": pd.date_range(start=start_date, end=end_date, freq="D")})
    merged_plot_df.set_index("Data", inplace=True)

    def build_sum_of_all_links_df():
        # Soma em todas as colunas de todos os links do link_time_series_map
        big_df = pd.DataFrame({"Data": merged_plot_df.index}).reset_index(drop=True)

        for link_nm in link_time_series_map:
            big_df = pd.merge(big_df, link_time_series_map[link_nm], on="Data", how="left")

        numeric_cols = [col for col in big_df.columns if col != "Data"]
        big_df["Total de cliques"] = big_df[numeric_cols].sum(axis=1)

        return big_df[["Data", "Total de cliques"]]

    for sel in selected_links:
        if sel == "Total de cliques":
            sum_df = build_sum_of_all_links_df()
            sum_df.set_index("Data", inplace=True)
            merged_plot_df = merged_plot_df.join(sum_df, how="left")
        else:
            if sel in link_time_series_map:
                df_to_join = link_time_series_map[sel].copy()
                df_to_join.set_index("Data", inplace=True)
                merged_plot_df = merged_plot_df.join(df_to_join, how="left")

    # 7) Exibe o gráfico
    st.write("### Gráfico de Cliques")

    for col in merged_plot_df.columns:
        merged_plot_df[col] = merged_plot_df[col].fillna(0)

    st.line_chart(merged_plot_df)


# Executa a aplicação
if __name__ == "__main__":
    main()
