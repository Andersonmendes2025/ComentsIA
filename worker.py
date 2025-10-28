import logging
import sys
from main import app
from google_auto import UserSettings, run_sync_last_48h

# Configura logs no Render
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def executar_fluxo():
    """Executa o fluxo de sincronização do GBP para todos os usuários ativos."""
    with app.app_context():
        try:
            enabled = UserSettings.query.filter_by(gbp_auto_enabled=True).all()
            if not enabled:
                logger.info("⚠️ Nenhum usuário com automação ativa. Encerrando.")
                return

            total_global = 0
            logger.info(f"🚀 Iniciando sincronização GBP (últimas 48h) para {len(enabled)} usuários...")

            for s in enabled:
                logger.info(f"▶️ Executando sync para user_id={s.user_id}")
                total = run_sync_last_48h(s.user_id)
                total_global += total
                logger.info(f"✅ {s.user_id}: {total} avaliações processadas.")

            logger.info(f"🎯 Execução concluída. Total geral: {total_global} avaliações processadas.")
        except Exception as e:
            logger.exception(f"💥 Erro durante execução do worker: {e}")

if __name__ == "__main__":
    modo = sys.argv[1] if len(sys.argv) > 1 else "auto"

    if modo == "auto":
        logger.info("🕐 Rodando em modo automático (Render Cron Job diário).")
        executar_fluxo()

    elif modo == "manual":
        logger.info("⚡ Execução manual iniciada.")
        executar_fluxo()

    else:
        logger.warning(f"❓ Modo '{modo}' não reconhecido. Use 'manual' ou 'auto'.")
