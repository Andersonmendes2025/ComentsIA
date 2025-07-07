import time
import requests
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By

def iniciar_bot_google(user_info=None, modo_teste=False):
    import undetected_chromedriver as uc
    import time
    import requests
    from selenium.webdriver.common.by import By

    print("🚀 Iniciando o robô com navegador stealth...")
    driver = uc.Chrome(headless=False)
    driver.get("https://business.google.com/")

    print("🔑 Aguarde o login manual (você tem 60 segundos)...")
    time.sleep(60)

    driver.get("https://business.google.com/reviews")
    time.sleep(5)

    reviews = driver.find_elements(By.CSS_SELECTOR, '[data-review-id]')
    print(f"📋 {len(reviews)} avaliações encontradas.")

    if modo_teste and len(reviews) == 0:
        print("⚠️ Nenhuma avaliação real encontrada. Inserindo simulação...")
        reviews = ["fake1", "fake2"]  # Apenas para iterar

    for r in reviews:
        try:
            if modo_teste and r == "fake1":
                nome = "João Teste"
                nota = "5"
                texto = "Muito bom o atendimento"
                data = "há 3 dias"
            elif modo_teste and r == "fake2":
                nome = "Ana Cliente"
                nota = "4"
                texto = "Serviço de qualidade!"
                data = "há 1 semana"
            else:
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
            user_id = user_info.get('id') if user_info else None

            payload = {
                'reviewer_name': nome,
                'rating': int(nota),
                'text': texto,
                'user_id': user_id

            }

            try:
                response = requests.post("https://comentsia.onrender.com/add_review", data=payload)
                if response.status_code == 200:
                    print("✅ Enviado com sucesso para o backend.")
                else:
                    print(f"⚠️ Falha ao enviar: {response.status_code} - {response.text}")
            except Exception as req_err:
                print("❌ Erro na requisição:", req_err)

        except Exception as err:
            print("⚠️ Erro ao extrair uma avaliação:", err)

    print("✅ Fim da execução do robô.")
    return driver
executar_robo_com_google_login = iniciar_bot_google


# Se quiser testar direto rodando python selenium_script.py
if __name__ == "__main__":
    iniciar_bot_google(modo_teste=True)
