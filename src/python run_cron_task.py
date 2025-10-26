import logging
from main import create_app # 👈 Assume que sua função de inicialização da app está em main.py
from google_auto import run_sync_for_user # 👈 Importa a função de sincronização

# Importa os modelos (necessário para consultas dentro do contexto)
from models import UserSettings # 👈 Assumindo que UserSettings está em models.py

# 1. Configurações básicas (Opcional, mas útil para o log do Cron Job)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

# 2. Inicializa a aplicação Flask (sem iniciar o servidor)
app = create_app()

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
            
            # CHAMA A FUNÇÃO DE SINCRONIZAÇÃO DIÁRIA
            # Nota: run_sync_for_user sincroniza APENAS o dia atual (do 00:00 BRT)
            total_processadas = run_sync_for_user(s.user_id) 
            
            logging.info(f"[CRON] ✅ {s.user_id}: {total_processadas} avaliações processadas.")
            total_geral += total_processadas
            
        logging.info(f"[CRON] ✅ Job diário concluído com sucesso. Total: {total_geral}")

    except Exception:
        logging.exception("[CRON] 💥 Job diário falhou.")
        # Se falhar, o Render irá registrar a saída de erro (exit code != 0)