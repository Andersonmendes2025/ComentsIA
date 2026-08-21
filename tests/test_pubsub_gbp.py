# -*- coding: utf-8 -*-
"""
Testes do endpoint que recebe as notificacoes do Google Business Profile
via Pub/Sub (push).
"""
import base64
import json
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app as flask_app
from models import db, User, UserSettings, GoogleLocation

TOKEN = "token-de-teste-pubsub"
LOCATION_ID = "9988776655"
USER_ID = "test_pubsub_user"


@pytest.fixture
def app():
    flask_app.config['TESTING'] = True
    flask_app.config['WTF_CSRF_ENABLED'] = False
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def setup(app):
    with app.app_context():
        if not User.query.filter_by(id=USER_ID).first():
            db.session.add(User(id=USER_ID, email="pubsub@example.com"))

        if not UserSettings.query.filter_by(user_id=USER_ID).first():
            db.session.add(UserSettings(user_id=USER_ID, plano="pro"))

        GoogleLocation.query.filter_by(user_id=USER_ID).delete()
        db.session.add(GoogleLocation(
            user_id=USER_ID,
            account_id="accounts/111222333",
            location_id=LOCATION_ID,
            location_name="Hotel de Teste",
            is_active=True,
        ))
        db.session.commit()
        yield
        GoogleLocation.query.filter_by(user_id=USER_ID).delete()
        db.session.commit()


def _envelope(notification_type="NEW_REVIEW", location=f"locations/{LOCATION_ID}"):
    """Monta o envelope no formato que o Pub/Sub envia (dados em base64)."""
    payload = {
        "account": "accounts/111222333",
        "location": location,
        "notificationType": notification_type,
    }
    dados = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")
    return {
        "message": {"data": dados, "messageId": "msg-1"},
        "subscription": "projects/comentsia/subscriptions/comentsia-gbp-notifications-sub",
    }


def test_rejeita_token_invalido(client):
    """Sem o token secreto correto, ninguem consegue disparar sync."""
    res = client.post("/auto/pubsub/gbp/token-errado", json=_envelope())
    assert res.status_code == 403


def test_nova_avaliacao_agenda_sync(client):
    """Notificacao valida de avaliacao nova deve agendar o sync do dono da ficha."""
    with patch.dict(os.environ, {"PUBSUB_PUSH_TOKEN": TOKEN}), \
         patch("google_auto._sync_em_background") as mock_sync, \
         patch("main.scheduler.add_job") as mock_add_job:
        res = client.post(f"/auto/pubsub/gbp/{TOKEN}", json=_envelope())

    assert res.status_code == 204
    assert mock_add_job.called, "deveria ter agendado o sync"
    kwargs = mock_add_job.call_args.kwargs
    assert kwargs["args"] == [USER_ID], "sync deve ser do dono da ficha notificada"
    # nao pode rodar inline: a resposta ao Pub/Sub tem que ser rapida
    assert not mock_sync.called


def test_ignora_tipo_irrelevante(client):
    """Notificacao que nao e de avaliacao nao deve disparar nada."""
    with patch.dict(os.environ, {"PUBSUB_PUSH_TOKEN": TOKEN}), \
         patch("main.scheduler.add_job") as mock_add_job:
        res = client.post(f"/auto/pubsub/gbp/{TOKEN}", json=_envelope(notification_type="NEW_QUESTION"))

    assert res.status_code == 204
    assert not mock_add_job.called


def test_ignora_ficha_desconhecida(client):
    """Ficha que nao pertence a nenhum cliente daqui e ignorada sem erro."""
    with patch.dict(os.environ, {"PUBSUB_PUSH_TOKEN": TOKEN}), \
         patch("main.scheduler.add_job") as mock_add_job:
        res = client.post(f"/auto/pubsub/gbp/{TOKEN}", json=_envelope(location="locations/000000"))

    assert res.status_code == 204
    assert not mock_add_job.called


def test_payload_quebrado_nao_derruba(client):
    """Payload ilegivel responde 204 (reentregar nao conserta) em vez de 500."""
    with patch.dict(os.environ, {"PUBSUB_PUSH_TOKEN": TOKEN}):
        res = client.post(
            f"/auto/pubsub/gbp/{TOKEN}",
            json={"message": {"data": "isso-nao-e-base64-valido!!!"}},
        )
    assert res.status_code == 204
