import streamlit as st
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import pandas as pd
import re
import requests
from datetime import datetime
import time

# Função para buscar dados do CNPJ via BrasilAPI
def buscar_dados_cnpj(cnpj):
    url = f"https://brasilapi.com.br/api/cnpj/v1/{cnpj}"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()

        socios = [f"{socio['nome_socio']} - {socio['qualificacao_socio']}" for socio in data.get('qsa', [])]
        socios_str = " | ".join(socios) if socios else "Não encontrado"

        regime_tributario = "Não encontrado"
        data_opcao_regime = "Não encontrado"

        if data.get("opcao_pelo_simples"):
            regime_tributario = "Simples Nacional"
            data_opcao_regime = data.get("data_opcao_pelo_simples", "Não encontrado")
        elif data.get("regime_tributario"):
            regimes = data["regime_tributario"]
            regime_tributario = regimes[-1]['forma_de_tributacao']
            for i in range(len(regimes) - 2, -1, -1):
                if regimes[i]['forma_de_tributacao'] != regime_tributario:
                    data_opcao_regime = str(regimes[i + 1]['ano'])
                    break
            else:
                data_opcao_regime = str(regimes[0]['ano'])

        situacao_cadastral = data.get("descricao_situacao_cadastral", "Não encontrado")

        return socios_str, regime_tributario, situacao_cadastral, data_opcao_regime

    return "Não encontrado", "Não encontrado", "Não encontrado", "Não encontrado"

# Função auxiliar para obter atributo com retry para stale elements
def get_attribute_with_retry(element, attribute, retries=3):
    for _ in range(retries):
        try:
            return element.get_attribute(attribute)
        except:
            time.sleep(1)  # Pequena pausa antes de tentar novamente
    raise Exception(f"Falha ao obter o atributo '{attribute}' após {retries} tentativas")

# Configuração do WebDriver para Streamlit Cloud
def setup_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    service = Service('/usr/bin/chromedriver')
    return webdriver.Chrome(service=service, options=options)

# Interface do Streamlit
st.title("Coleta de Dados de Empresas no Google Maps")

# Campos de entrada
cidade = st.text_input("Cidade", value="Alfenas")
estado = st.text_input("Estado", value="MG")
ramo = st.text_input("Ramo", value="indústria")
qtd_empresas = st.number_input("Quantidade de empresas ativas desejadas", min_value=1, value=5)
filtro_regime_tributario = st.selectbox("Filtro de regime tributário", ["todos", "Simples Nacional", "Lucro Presumido", "Lucro Real"])

# Inicializar o driver no session_state
if 'driver' not in st.session_state:
    st.session_state.driver = setup_driver()

driver = st.session_state.driver

# Botão para iniciar a coleta
if st.button("Iniciar Coleta"):
    # Acessar o Google Maps
    driver.get(f"https://www.google.com/maps/search/{ramo}+perto+de+{cidade}+{estado}")

    # Aguardar o carregamento inicial da página
    WebDriverWait(driver, 10).until(
        lambda d: d.execute_script('return document.readyState') == 'complete'
    )

    # Aguardar o painel de resultados
    try:
        painel_resultados = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, '//div[@role="feed"]'))
        )
    except:
        st.error("Painel de resultados não encontrado no Google Maps.")
        driver.quit()
        st.stop()

    lista_empresas = []
    empresas_coletadas = set()
    rolagem = 0

    # Loop para coletar empresas
    while len(lista_empresas) < qtd_empresas:
        try:
            empresas = WebDriverWait(driver, 10).until(
                EC.presence_of_all_elements_located((By.CLASS_NAME, "hfpxzc"))
            )
        except:
            st.write("Nenhum resultado adicional encontrado.")
            break

        for empresa in empresas:
            try:
                nome_empresa = get_attribute_with_retry(empresa, "aria-label")
                if nome_empresa in empresas_coletadas:
                    continue
                empresas_coletadas.add(nome_empresa)

                driver.execute_script("arguments[0].click();", empresa)
                WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.XPATH, "//button[contains(@aria-label, 'Telefone')]//div"))
                )

                telefone = "Não encontrado"
                try:
                    telefone_elem = driver.find_element(By.XPATH, "//button[contains(@aria-label, 'Telefone')]//div")
                    telefone_raw = telefone_elem.text.strip()
                    telefone = re.sub(r"[^\d\(\)\-\s]", "", telefone_raw).strip()
                except:
                    pass

                # Abrir nova aba para buscar CNPJ
                driver.execute_script("window.open('https://www.google.com','_blank');")
                driver.switch_to.window(driver.window_handles[-1])

                cnpj = "Não encontrado"
                try:
                    search_box = WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located((By.NAME, "q"))
                    )
                    search_box.clear()
                    search_box.send_keys(f"CNPJ {nome_empresa} {cidade}")
                    search_box.send_keys(Keys.RETURN)

                    resultados = WebDriverWait(driver, 5).until(
                        EC.presence_of_all_elements_located((By.XPATH, "//span[contains(text(),'CNPJ')]"))
                    )
                    for resultado in resultados:
                        match = re.search(r"\d{2}\.?\d{3}\.?\d{3}/\d{4}-\d{2}", resultado.text)
                        if match:
                            cnpj = match.group(0).replace(".", "").replace("/", "").replace("-", "")
                            break
                except Exception as e:
                    st.write(f"Erro ao buscar CNPJ para {nome_empresa}: {e}")

                driver.close()
                driver.switch_to.window(driver.window_handles[0])

                if cnpj == "Não encontrado":
                    continue

                socios, regime_tributario, situacao_cadastral, data_opcao_regime = buscar_dados_cnpj(cnpj)

                if situacao_cadastral != "ATIVA":
                    st.write(f"Empresa '{nome_empresa}' removida por não estar ativa ({situacao_cadastral}).")
                    continue

                if filtro_regime_tributario.lower() != "todos" and regime_tributario.lower() != filtro_regime_tributario.lower():
                    st.write(f"Empresa '{nome_empresa}' ignorada por ser do regime '{regime_tributario}'.")
                    continue

                lista_empresas.append({
                    "Nome": nome_empresa,
                    "Telefone": telefone,
                    "CNPJ": cnpj,
                    "Sócios": socios,
                    "Regime Tributário": regime_tributario,
                    "Data da Opção pelo Regime Atual": data_opcao_regime,
                    "Situação Cadastral": situacao_cadastral
                })

                st.write(f"✔ Empresa válida adicionada: {nome_empresa} - {cnpj}")
                if len(lista_empresas) >= qtd_empresas:
                    break

            except Exception as e:
                st.write(f"Erro ao processar empresa: {e}")
                continue

        if len(lista_empresas) < qtd_empresas:
            rolagem += 1
            st.write(f"Rolando resultados (tentativa {rolagem})...")
            for _ in range(2):
                driver.execute_script("arguments[0].scrollTop += arguments[0].scrollHeight / 3", painel_resultados)
                time.sleep(1)

    # Salvar resultados em Excel
    if lista_empresas:
        agora = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        df = pd.DataFrame(lista_empresas)
        df.to_excel(f"empresas_coletadas_{cidade}_{ramo}_{agora}.xlsx", index=False)
        st.success("Consulta finalizada com sucesso. Resultados salvos no Excel.")

        # Exibir tabela interativa
        st.subheader("Resultados Coletados")
        st.dataframe(df)
    else:
        st.warning("Nenhuma empresa válida encontrada.")

# Fechar o driver ao final da sessão
if st.button("Finalizar e Limpar"):
    try:
        driver.quit()
        del st.session_state.driver
        st.success("Driver finalizado e sessão limpa.")
    except Exception as e:
        st.error(f"Erro ao tentar fechar o driver: {e}")