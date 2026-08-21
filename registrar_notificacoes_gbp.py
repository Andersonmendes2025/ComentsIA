# -*- coding: utf-8 -*-
"""
Registra o tópico Pub/Sub nas contas Google dos clientes JÁ existentes.

Clientes que conectarem o Google a partir de agora são registrados sozinhos
no /oauth2callback. Este script é só para quem já estava conectado antes.

Uso:
    python registrar_notificacoes_gbp.py            # registra todos
    python registrar_notificacoes_gbp.py --dry-run  # só mostra o que faria
    python registrar_notificacoes_gbp.py --user email@cliente.com

Requer a variável de ambiente GBP_PUBSUB_TOPIC, no formato:
    projects/<projeto>/topics/<topico>
"""
import argparse
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Não registra, só lista.")
    parser.add_argument("--user", help="Registra apenas este user_id/e-mail.")
    args = parser.parse_args()

    topico = os.getenv("GBP_PUBSUB_TOPIC")
    if not topico:
        print("ERRO: defina GBP_PUBSUB_TOPIC (ex: projects/comentsia/topics/comentsia-gbp-notifications)")
        return 1

    from main import app
    from models import UserSettings
    from google_auto import registrar_topico_pubsub

    with app.app_context():
        q = UserSettings.query.filter(UserSettings.google_refresh_token.isnot(None))
        if args.user:
            q = q.filter(UserSettings.user_id == args.user)
        clientes = q.all()

        print(f"Tópico: {topico}")
        print(f"Clientes com Google conectado: {len(clientes)}\n")

        if args.dry_run:
            for s in clientes:
                print(f"  [dry-run] registraria: {s.user_id} (plano={s.plano})")
            return 0

        ok_total = 0
        for s in clientes:
            print(f"--- {s.user_id} ---")
            try:
                for r in registrar_topico_pubsub(s.user_id, topico):
                    status = "OK " if r.get("ok") else "FALHA"
                    print(f"    [{status}] {r.get('conta', '?')} {r.get('status', '')} {r.get('erro', '')}")
                    if r.get("ok"):
                        ok_total += 1
            except Exception as e:
                print(f"    [ERRO] {e!r}")

        print(f"\nContas registradas com sucesso: {ok_total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
