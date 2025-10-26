import logging
import time

# Assumindo que 'create_app' e 'register_gbp_cron' estão em 'main.py'
from main import create_app, register_gbp_cron, scheduler 

# Configuração básica de log para vermos o output no Render
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# 1. Cria a aplicação
app = create_app()

# 2. Inicia o contexto da aplicação (obrigatório para DB e GBP)
with app.app_context():
    # 3. Registra os jobs
    register_gbp_cron(scheduler, app)
    
    # 4. Inicia o agendador
    try:
        scheduler.start()
        logger.info("✅ APScheduler iniciado e rodando em Background.")
    except Exception as e:
        logger.error(f"❌ Falha ao iniciar APScheduler: {e}")

    # 5. Mantém o processo do worker rodando 24/7
    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Worker desligado.")
        # O scheduler será desligado pelo SystemExit, mas desligamos o app.context