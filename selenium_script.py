import time
import requests
import chromedriver_autoinstaller
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

def iniciar_bot_google(user_info=None):
    # Instala automaticamente o ChromeDriver
    chromedriver_autoinstaller.install()

    # Configurações do navegador
    chrome_options = Options()
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_experimental_option("detach", True)

    # Inicia o navegador
    driver = webdriver.Chrome(options=chrome_options)

    # Etapa 1 – Acessa o Google Business
    driver.get("https://business.google.com/")
    print("🔑 Aguarde o usuário fazer login manualmente...")

    time.sleep(60)  # login manual

    # Etapa 2 – Vai para aba de avaliações
    try:
        driver.get("https://business.google.com/reviews")
        time.sleep(10)
    except Exception as e:
        print("❌ Erro ao acessar a aba de avaliações:", e)
        return

    # Etapa 3 – Captura e envia avaliações
    try:
        reviews = driver.find_elements(By.CSS_SELECTOR, '[data-review-id]')
        print(f"📋 {len(reviews)} avaliações encontradas.")

        for r in reviews:
            try:
                nome = r.find_element(By.CSS_SELECTOR, '.TSUbDb').text
                nota_element = r.find_element(By.CSS_SELECTOR, '[aria-label*="estrela"]')
                nota = nota_element.get_attribute("aria-label").split()[0]
                texto = r.find_element(By.CSS_SELECTOR, '.review-full-text, .Jtu6Td').text
                data = r.find_element(By.CSS_SELECTOR, '.dehysf').text

                print("\n🗣️ Avaliação capturada:")
                print(f"👤 Nome: {nome}")
                print(f"⭐ Nota: {nota}")
                print(f"📅 Data: {data}")
                print(f"💬 Texto: {texto}")

                # Envia para o backend Flask
                payload = {
                    'reviewer_name': nome,
                    'rating': int(nota),
                    'text': texto
                }

                try:
                    response = requests.post("http://localhost:8000/add_review", data=payload)
                    if response.status_code == 200:
                        print("✅ Enviado com sucesso para o backend.")
                    else:
                        print(f"⚠️ Falha ao enviar: {response.status_code} - {response.text}")
                except Exception as req_err:
                    print("❌ Erro na requisição para o backend:", req_err)

            except Exception as err:
                print("⚠️ Erro ao extrair uma avaliação:", err)

    except Exception as e:
        print("❌ Falha ao capturar avaliações:", e)

    print("✅ Fim da execução do robô.")
    return driver
