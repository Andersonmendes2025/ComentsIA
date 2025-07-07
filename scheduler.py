from apscheduler.schedulers.background import BackgroundScheduler
from selenium_script import iniciar_bot_google

def agendar_robos():
    scheduler = BackgroundScheduler()

    # Executa todo dia às 03:00
    scheduler.add_job(func=iniciar_bot_google, trigger='cron', hour=3, minute=0)

    scheduler.start()
    print("⏰ Robô agendado para rodar todos os dias às 03:00 da manhã.")
