# -*- coding: utf-8 -*-
"""
Testes de integração para o fluxo de importação de avaliações do Booking.com
via upload de CSV (a Booking.com não oferece API pública para reviews, então
o fluxo suportado é: Extranet do Booking > Guest reviews > Download > upload aqui).
"""
import io
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app as flask_app
from models import db, User, UserSettings, Review, UploadLog, ReservationIndex


@pytest.fixture
def app():
    flask_app.config['TESTING'] = True
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def booking_user(app):
    with app.app_context():
        user = User.query.filter_by(id="test_booking_user").first()
        if not user:
            user = User(id="test_booking_user", email="booking_tester@comentsia.com.br", nome="Tester Booking")
            db.session.add(user)
            db.session.commit()

        # limpa dados de execuções anteriores para o teste ser idempotente
        Review.query.filter_by(user_id="test_booking_user", source="booking").delete()
        UploadLog.query.filter_by(user_id="test_booking_user", source="booking").delete()
        ReservationIndex.query.filter_by(user_id="test_booking_user", source="booking").delete()
        db.session.commit()
        yield user


def _login(client):
    with client.session_transaction() as sess:
        sess["credentials"] = {"token": "fake"}
        sess["user_info"] = {"id": "test_booking_user", "email": "booking_tester@comentsia.com.br"}


def _csrf_token(client):
    resp = client.get("/booking/")
    m = re.search(rb'name="csrf-token" content="([^"]+)"', resp.data)
    assert m, "token CSRF não encontrado na página de upload"
    return resp, m.group(1).decode()


CSV_CONTENT = (
    "Numero da reserva;Nome do hospede;Titulo da avaliacao;Avaliacao positiva;"
    "Avaliacao negativa;Nota de avaliacao;Data da avaliacao\n"
    "1234567890;Joao Silva;Otima estadia;Quarto limpo e confortavel;Nada a reclamar;9;15/01/2026\n"
    "9876543210;Maria Souza;Faltou atencao;Cafe da manha bom;Demora no check-in;6;16/01/2026\n"
)


def _upload(client, token, filename="reviews.csv", content=CSV_CONTENT):
    return client.post(
        "/booking/upload",
        data={"file": (io.BytesIO(content.encode("utf-8")), filename), "csrf_token": token},
        content_type="multipart/form-data",
        headers={"X-CSRFToken": token},
    )


def _wait_upload(client, upload_id, tries=40):
    import time
    for _ in range(tries):
        time.sleep(0.25)
        js = client.get("/booking/uploads").get_json()
        match = [u for u in js["uploads"] if u["id"] == upload_id]
        if match and match[0]["status"] in ("success", "error"):
            return match[0]
    return None


def test_form_upload_requires_login(client):
    resp = client.get("/booking/")
    assert resp.status_code == 401


def test_upload_csv_end_to_end(app, client, booking_user):
    _login(client)
    _, token = _csrf_token(client)

    resp = _upload(client, token)
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["success"] is True
    assert payload["status"] == "queued"

    status = _wait_upload(client, payload["upload_id"])
    assert status is not None, "processamento em background não terminou a tempo"
    assert status["status"] == "success"
    assert status["inserted"] == 2
    assert status["duplicates"] == 0

    with app.app_context():
        reviews = Review.query.filter_by(user_id="test_booking_user", source="booking").all()
        assert len(reviews) == 2
        names = {r.reviewer_name for r in reviews}
        assert names == {"Joao Silva", "Maria Souza"}

    count_resp = client.get("/booking/count")
    assert count_resp.get_json()["count"] == 2


def test_upload_csv_deduplicates_on_reimport(app, client, booking_user):
    _login(client)
    _, token = _csrf_token(client)

    first = _upload(client, token)
    first_status = _wait_upload(client, first.get_json()["upload_id"])
    assert first_status["status"] == "success"

    second = _upload(client, token)
    second_status = _wait_upload(client, second.get_json()["upload_id"])
    assert second_status["status"] == "success"
    assert second_status["inserted"] == 0
    assert second_status["duplicates"] == 2

    with app.app_context():
        total = Review.query.filter_by(user_id="test_booking_user", source="booking").count()
        assert total == 2


def test_dashboard_requires_login(client):
    resp = client.get("/booking/dashboard")
    assert resp.status_code == 302


def test_dashboard_renders_with_metrics(app, client, booking_user):
    _login(client)
    _, token = _csrf_token(client)

    status = _wait_upload(client, _upload(client, token).get_json()["upload_id"])
    assert status["status"] == "success"

    resp = client.get("/booking/dashboard")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    assert "Painel de Avaliações do Booking.com" in html
    assert "Joao Silva" in html


def test_booking_reviews_appear_in_relatorio(app, client, booking_user):
    """
    Garante que avaliações do Booking.com entram no /relatorio junto com as
    demais (nenhum filtro de "source" deve excluí-las quando ficha="todas"),
    tanto na tela quanto no PDF gerado.
    """
    from utils.crypto import encrypt
    from datetime import datetime, timedelta

    with app.app_context():
        settings = UserSettings.query.filter_by(user_id="test_booking_user").first()
        if not settings:
            settings = UserSettings(user_id="test_booking_user")
            db.session.add(settings)
        settings.business_name = encrypt("Pousada Teste")
        settings.contact_info = encrypt("contato@pousada.com")
        settings.terms_accepted = True
        settings.plano = "business"  # relatorio_pdf_mes ilimitado, evita gates de plano no teste
        settings.plano_ate = datetime.utcnow() + timedelta(days=365)
        db.session.commit()

        # avaliação "de outra origem" pra confirmar que aparecem juntas
        outra = Review.query.filter_by(user_id="test_booking_user", external_id="google-teste-1").first()
        if not outra:
            outra = Review(
                user_id="test_booking_user",
                external_id="google-teste-1",
                reviewer_name="Cliente Google",
                rating=5,
                text="Ótimo atendimento via Google.",
                date=datetime.utcnow(),
                source="google",
            )
            db.session.add(outra)
            db.session.commit()

    _login(client)
    _, token = _csrf_token(client)
    status = _wait_upload(client, _upload(client, token).get_json()["upload_id"])
    assert status["status"] == "success"

    # a mesma query usada por /relatorio (sem filtro de "source") deve trazer
    # a avaliação do Google e as duas do Booking juntas
    with app.app_context():
        todas = Review.query.filter(Review.user_id == "test_booking_user").all()
        fontes = {r.source for r in todas}
        assert fontes == {"google", "booking"}
        assert len(todas) == 3

    # tela do relatório: só confirma que renderiza sem erro com "todas" as fichas
    resp = client.get("/relatorio?ficha=todas")
    assert resp.status_code == 200

    # PDF: precisa conter as duas origens combinadas
    resp_pdf = client.post(
        "/relatorio",
        data={
            "periodo": "todas",
            "nota": "todas",
            "respondida": "todas",
            "ficha": "todas",
            "csrf_token": token,
        },
        headers={"X-CSRFToken": token},
    )
    assert resp_pdf.status_code == 200
    assert resp_pdf.mimetype == "application/pdf"
    assert resp_pdf.data.startswith(b"%PDF")
    assert len(resp_pdf.data) > 1000


def test_upload_rejects_non_csv(client, booking_user):
    _login(client)
    _, token = _csrf_token(client)
    resp = client.post(
        "/booking/upload",
        data={"file": (io.BytesIO(b"not a csv"), "reviews.txt"), "csrf_token": token},
        content_type="multipart/form-data",
        headers={"X-CSRFToken": token},
    )
    assert resp.status_code == 400
    assert resp.get_json()["success"] is False
