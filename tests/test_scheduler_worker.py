# -*- coding: utf-8 -*-
"""
Garante que o agendador interno realmente executa jobs dentro do worker.

Regressao real: sob gunicorn o modulo e carregado antes do worker nascer.
Threads nao sobrevivem ao fork, entao o worker herdava um agendador que se
dizia "rodando" mas sem thread viva. add_job() era aceito e o job nunca
executava — falha silenciosa que derrubou as notificacoes do Pub/Sub e os
jobs diarios (iFood, cobranca), sem gerar nenhum erro em log.
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import main as main_module
from main import app as flask_app, scheduler


@pytest.fixture
def client():
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


def test_detecta_thread_morta_do_fork():
    """
    O coracao da correcao: reconhecer que um agendador herdado do processo
    pai esta inutil aqui, mesmo dizendo que esta "rodando".

    Usa um agendador proprio para nao mexer no global da aplicacao.
    """
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.schedulers.base import STATE_RUNNING

    sched = BackgroundScheduler()

    # Antes de iniciar: sem thread viva.
    assert main_module._scheduler_tem_thread_viva(sched) is False

    sched.start()
    try:
        assert main_module._scheduler_tem_thread_viva(sched) is True

        # Simula o pos-fork: o estado diz "rodando", mas a thread nao veio junto.
        sched._thread = None
        sched._state = STATE_RUNNING
        assert sched.running is True, "o agendador ainda se diz rodando..."
        assert main_module._scheduler_tem_thread_viva(sched) is False, \
            "...mas a verificacao precisa enxergar que nao ha thread viva"
    finally:
        try:
            sched.shutdown(wait=False)
        except Exception:
            pass


def test_scheduler_vivo_apos_requisicao(client):
    """Depois de qualquer requisicao, o agendador tem que estar vivo no worker."""
    client.get("/")
    assert main_module._scheduler_tem_thread_viva(), \
        "o agendador deveria ter sido iniciado na primeira requisicao"


def test_job_agendado_realmente_executa(client):
    """
    O que de fato importa: agendar um job e ele RODAR.
    Antes o add_job era aceito e nada acontecia.
    """
    client.get("/")

    executou = []
    try:
        scheduler.add_job(
            id="teste_job_worker",
            func=lambda: executou.append(True),
            trigger="date",
            replace_existing=True,
        )

        for _ in range(50):  # ate ~5s
            if executou:
                break
            time.sleep(0.1)

        assert executou, "job agendado nao executou — agendador aceita mas nao roda"
    finally:
        try:
            scheduler.remove_job("teste_job_worker")
        except Exception:
            pass


def test_jobs_diarios_registrados():
    """Os jobs internos (Google, iFood, cobranca) precisam existir."""
    ids = {j.id for j in scheduler.get_jobs()}
    for esperado in ("gbp_daily_sync", "ifood_daily_sync", "billing_followups"):
        assert esperado in ids, f"job {esperado} nao registrado"
