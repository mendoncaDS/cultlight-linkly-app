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

# Função para buscar todos os links rastreados
def fetch_tracked_links():
    endpoint = f"{BASE_URL}/workspace/{WORKSPACE_ID}/links/export"
    params = {
        "api_key": API_KEY
    }

    try:
        response = requests.get(endpoint, params=params, timeout=10)
        response.raise_for_status()  # Levanta uma exceção para erros HTTP
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Erro ao buscar links rastreados: {e}")
        return []

# Função para buscar cliques de um link em um intervalo de datas
def fetch_clicks_for_link(link_id, start_date, end_date):
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

# Função para inicializar o estado da sessão com todos os dados
def initialize_session_state():
    if "tracked_links" not in st.session_state:
        with st.spinner("Carregando dados... Isso pode levar alguns instantes na primeira vez."):
            st.session_state.tracked_links = fetch_tracked_links()

    if "analytics_data" not in st.session_state:
        st.session_state.analytics_data = {}
        with st.spinner("Carregando análises... Isso pode levar alguns instantes na primeira vez."):
            for link in st.session_state.tracked_links:
                link_id = link["id"]
                # Busca análises para o último ano (ou um intervalo razoável)
                start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
                end_date = datetime.now().strftime("%Y-%m-%d")
                st.session_state.analytics_data[link_id] = fetch_clicks_for_link(link_id, start_date, end_date)

# Aplicativo Streamlit
def main():
    st.title("Links Rastreados do Linkly")
    st.write("Este aplicativo exibe a lista de links rastreados do Linkly com análises para um intervalo de datas selecionado.")

    # Inicializa o estado da sessão (busca dados apenas uma vez)
    initialize_session_state()

    # Verifica se uma página de URL individual deve ser exibida
    if "selected_link" in st.session_state:
        render_individual_url_page(st.session_state.selected_link)
    else:
        render_main_page()

# Função para renderizar a página principal
def render_main_page():
    # Seletor de intervalo de datas
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Data Inicial", datetime.now() - timedelta(days=30))
    with col2:
        end_date = st.date_input("Data Final", datetime.now())

    # Prepara os dados para a tabela
    table_data = []
    for link in st.session_state.tracked_links:
        link_id = link["id"]
        link_name = link["name"]

        # Filtra os cliques para o intervalo de datas selecionado (localmente)
        clicks_data = st.session_state.analytics_data.get(link_id, [])
        filtered_clicks = [
            data_point for data_point in clicks_data
            if start_date <= datetime.strptime(data_point["t"], "%Y-%m-%d").date() <= end_date
        ]
        total_clicks = sum(data_point["y"] for data_point in filtered_clicks)

        table_data.append({
            "Nome": link_name,
            "Cliques (Intervalo Selecionado)": total_clicks,
            "Total de Cliques": link["clicks_count"]
        })

    # Converte para DataFrame
    df = pd.DataFrame(table_data)

    # Renderiza a tabela
    st.write("### Links Rastreados")
    st.dataframe(
        df,
        column_config={
            "Nome": "Nome",
            "Cliques (Intervalo Selecionado)": "Cliques (Intervalo Selecionado)",
            "Total de Cliques": "Total de Cliques"
        },
        hide_index=True,
        use_container_width=True
    )

    # Adiciona um seletor para nomes de URL e um botão para navegar para a página individual do URL
    with st.form("url_selector_form"):
        selected_link_name = st.selectbox(
            "Selecione um URL para ver detalhes",
            options=[link["name"] for link in st.session_state.tracked_links]
        )
        submit_button = st.form_submit_button("Ver Detalhes")

    # Manipula o envio do formulário
    if submit_button:
        selected_link = next(
            (link for link in st.session_state.tracked_links if link["name"] == selected_link_name),
            None
        )
        if selected_link:
            st.session_state.selected_link = selected_link["id"]
            st.rerun()  # Reinicia o aplicativo para renderizar a página individual do URL

def preprocess_clicks_data(clicks_data, start_date, end_date):
    """
    Preprocessa os dados de cliques para garantir um intervalo de datas consistente com datas ausentes preenchidas com zero.
    """
    # Cria um intervalo de datas da data inicial até a data final
    date_range = pd.date_range(start=start_date, end=end_date, freq="D")

    # Converte os dados de cliques para um DataFrame
    clicks_df = pd.DataFrame(clicks_data)

    # Se não houver dados, retorna um DataFrame com zero cliques para todo o intervalo de datas
    if clicks_df.empty:
        return pd.DataFrame({
            "Data": date_range,
            "Cliques": 0
        })

    # Converte a coluna "t" para datetime e renomeia para "Data"
    clicks_df["Data"] = pd.to_datetime(clicks_df["t"])
    clicks_df = clicks_df.rename(columns={"y": "Cliques"})

    # Mescla os dados de cliques com o intervalo de datas completo
    full_df = pd.DataFrame({"Data": date_range})
    merged_df = pd.merge(full_df, clicks_df[["Data", "Cliques"]], on="Data", how="left")

    # Preenche cliques ausentes com 0
    merged_df["Cliques"] = merged_df["Cliques"].fillna(0)

    return merged_df

def render_individual_url_page(link_id):
    st.title("Detalhes do URL Rastreado")

    # Adiciona um dropdown para selecionar um URL diferente
    selected_link_name = st.selectbox(
        "Selecione um URL para ver detalhes",
        options=[link["name"] for link in st.session_state.tracked_links],
        index=[link["id"] for link in st.session_state.tracked_links].index(link_id)  # Define o link atual como padrão
    )

    # Se o usuário selecionar um URL diferente, atualiza o estado da sessão e reinicia o aplicativo
    if selected_link_name:
        selected_link = next(
            (link for link in st.session_state.tracked_links if link["name"] == selected_link_name),
            None
        )
        if selected_link and selected_link["id"] != link_id:
            st.session_state.selected_link = selected_link["id"]
            st.rerun()  # Reinicia o aplicativo para atualizar a página com as análises do novo URL

    # Encontra os detalhes do link
    link = next((link for link in st.session_state.tracked_links if link["id"] == link_id), None)
    if not link:
        st.error("Link não encontrado!")
        return

    # Exibe o URL e o nome do link
    st.write(f"**Nome:** {link['name']}")
    st.write(f"**URL:** {link['url']}")

    # Seletor de intervalo de datas para a página individual
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Data Inicial", datetime.now() - timedelta(days=30), key="individual_start_date")
    with col2:
        end_date = st.date_input("Data Final", datetime.now(), key="individual_end_date")

    # Busca e preprocessa as análises para o intervalo de datas selecionado
    clicks_data = st.session_state.analytics_data.get(link_id, [])
    plot_data = preprocess_clicks_data(clicks_data, start_date, end_date)

    # Exibe o gráfico de linhas
    st.write("### Cliques ao Longo do Tempo")
    st.line_chart(plot_data, x="Data", y="Cliques")

    # Adiciona um botão "Voltar para a Página Principal"
    if st.button("Voltar para a Página Principal"):
        del st.session_state.selected_link  # Limpa o link selecionado
        st.rerun()  # Reinicia o aplicativo para retornar à página principal

# Executa o aplicativo Streamlit
if __name__ == "__main__":
    main()