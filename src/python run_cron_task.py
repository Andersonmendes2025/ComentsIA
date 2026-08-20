import logging
from main import app # main.py não define create_app(); a instância já pronta é "app"
from google_auto import run_sync_last_48h # janela de 48h evita perder avaliações postadas fora do horário exato do cron

# Importa os modelos (necessário para consultas dentro do contexto)
from models import UserSettings # 👈 Assumindo que UserSettings está em models.py

# 1. Configurações básicas (Opcional, mas útil para o log do Cron Job)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

print("\n[CRON] ⚡ Iniciando Cron Job do Render...")

# 3. Força o Contexto da Aplicação (RESOLVE O PROBLEMA DE 'CONTEXTO INCORRETO')
with app.app_context():
    try:
        # Consulta todos os usuários com automação GBB ativada
        enabled_users = UserSettings.query.filter_by(gbp_auto_enabled=True).all()
        
        logging.info(f"[CRON] 🕐 Job diário iniciado — {len(enabled_users)} contas habilitadas.")
        
        total_geral = 0
        for s in enabled_users:
            logging.info(f"[CRON] ▶️ Rodando sync para user_id={s.user_id}")

            try:
                # Janela de 48h: pega qualquer avaliação postada desde a última
                # execução, mesmo que o cron tenha atrasado ou o dia tenha virado.
                total_processadas = run_sync_last_48h(s.user_id)
                logging.info(f"[CRON] ✅ {s.user_id}: {total_processadas} avaliações processadas.")
                total_geral += total_processadas
            except Exception:
                # Uma conta com erro nao pode travar a sincronizacao dos demais clientes.
                logging.exception(f"[CRON] 💥 Falha ao sincronizar user_id={s.user_id}. Pulando para o próximo.")

        logging.info(f"[CRON] ✅ Job diário concluído com sucesso. Total: {total_geral}")

    except Exception:
        logging.exception("[CRON] 💥 Job diário falhou.")
        # Se falhar, o Render irá registrar a saída de erro (exit code != 0)