from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from main import app as flask_app, limiter
from models import User, UserSettings, db


@pytest.fixture
def app():
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    flask_app.config["RATELIMIT_ENABLED"] = False
    limiter.enabled = False
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


def test_pixel_is_gated_by_cookie_consent(client):
    response = client.get("/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "1158927779981712" in html
    assert "tracking-consent-banner" in html
    assert "comentsia_tracking_consent" in html
    assert "fbq('track', 'PageView')" in html
    assert "CompleteRegistration" in html
    assert '<script async src="https://connect.facebook.net' not in html


def test_complete_registration_is_queued_only_on_first_completion(app, client):
    user_id = "meta_registration@example.com"
    with app.app_context():
        UserSettings.query.filter_by(user_id=user_id).delete()
        User.query.filter_by(id=user_id).delete()
        db.session.add(User(id=user_id, email=user_id, nome="Meta Test"))
        db.session.add(
            UserSettings(
                user_id=user_id,
                plano="pro",
                plano_ate=datetime.utcnow() + timedelta(days=365),
                business_name="",
                terms_accepted=False,
            )
        )
        db.session.commit()

    with client.session_transaction() as session:
        session["credentials"] = {"token": "test"}
        session["user_info"] = {"id": user_id, "email": user_id, "name": "Meta Test"}

    payload = {
        "company_name": "Empresa Meta",
        "manager_name": "Gestor",
        "default_greeting": "Olá",
        "default_closing": "Obrigado",
        "contact_info": "contato@example.com",
        "terms_accepted": "on",
        "idioma_resposta": "Português (Brasil)",
        "gbp_tone": "profissional",
        "contexto_personalizado": "",
    }

    with patch("main.enviar_email"):
        response = client.post("/settings", data=payload)
    assert response.status_code == 302

    with client.session_transaction() as session:
        first_event_id = session.pop("meta_complete_registration_event_id", None)
    assert first_event_id

    with patch("main.enviar_email"):
        response = client.post("/settings", data=payload)
    assert response.status_code == 302

    with client.session_transaction() as session:
        assert session.get("meta_complete_registration_event_id") is None


def test_incomplete_registration_does_not_queue_event(app, client):
    user_id = "meta_incomplete@example.com"
    with app.app_context():
        UserSettings.query.filter_by(user_id=user_id).delete()
        User.query.filter_by(id=user_id).delete()
        db.session.add(User(id=user_id, email=user_id, nome="Incomplete"))
        db.session.add(UserSettings(user_id=user_id, business_name="", terms_accepted=False))
        db.session.commit()

    with client.session_transaction() as session:
        session["credentials"] = {"token": "test"}
        session["user_info"] = {"id": user_id, "email": user_id, "name": "Incomplete"}

    response = client.post("/settings", data={"company_name": "", "terms_accepted": "on"})
    assert response.status_code == 302

    with client.session_transaction() as session:
        assert session.get("meta_complete_registration_event_id") is None
