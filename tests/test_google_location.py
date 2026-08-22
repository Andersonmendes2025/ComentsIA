# -*- coding: utf-8 -*-
import pytest
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app as flask_app
from models import db, User, UserSettings, GoogleLocation, Review


@pytest.fixture
def client():
    flask_app.config['TESTING'] = True
    flask_app.config['WTF_CSRF_ENABLED'] = False
    
    with flask_app.test_client() as client:
        with flask_app.app_context():
            yield client


def test_remover_ficha_google_preserva_registro_e_avaliacoes(client):
    """
    Regressao: a rota apagava a ficha e, antes disso, zerava o
    google_location_id de todas as avaliacoes dela. Isso perdia as
    configuracoes (tom de voz, contexto, nome do gerente, saudacao) e
    desvinculava o historico — e nem removia em definitivo, porque a proxima
    sincronizacao com a API do Google recriava a ficha zerada.

    Agora a remocao e suave: a linha fica, marcada como inativa, e as
    avaliacoes continuam ligadas a ela.
    """
    test_user_id = "test_user_del_loc"

    with flask_app.app_context():
        user = User.query.filter_by(id=test_user_id).first()
        if not user:
            user = User(id=test_user_id, email="test_loc@example.com")
            db.session.add(user)

        Review.query.filter_by(user_id=test_user_id).delete()
        GoogleLocation.query.filter_by(user_id=test_user_id).delete()
        db.session.commit()

        loc = GoogleLocation(
            user_id=test_user_id,
            account_id="accounts/123",
            location_id="loc_to_delete_999",
            location_name="Loja Para Deletar",
            is_active=True,
            tone="luxo",
            manager_name="Anderson",
            contexto_personalizado="Hotel executivo no centro.",
        )
        db.session.add(loc)
        db.session.commit()

        loc_id = loc.id

        rev = Review(
            user_id=test_user_id,
            reviewer_name="Cliente Teste",
            text="Ótimo lugar",
            google_location_id=loc_id
        )
        db.session.add(rev)
        db.session.commit()

    with client.session_transaction() as sess:
        sess['credentials'] = {'id_token': 'fake'}
        sess['user_info'] = {'id': test_user_id, 'email': 'test_loc@example.com'}

    res = client.post('/auto/location/loc_to_delete_999/delete', json={})
    assert res.status_code == 200
    assert res.get_json()['success'] is True

    with flask_app.app_context():
        ficha = GoogleLocation.query.filter_by(
            user_id=test_user_id, location_id="loc_to_delete_999"
        ).first()
        assert ficha is not None, "a ficha foi apagada; reativar criaria um registro zerado"
        assert ficha.is_active is False

        # Configuracoes do cliente continuam ali para quando ele reativar.
        assert ficha.tone == "luxo"
        assert ficha.manager_name == "Anderson"
        assert ficha.contexto_personalizado == "Hotel executivo no centro."

        review = Review.query.filter_by(user_id=test_user_id, reviewer_name="Cliente Teste").first()
        assert review is not None
        assert review.google_location_id == ficha.id, "avaliacao foi desvinculada da ficha"


def test_acao_excluir_em_escolher_ficha_tambem_e_suave(client):
    """
    O mesmo criterio vale para a acao 'excluir' do seletor de fichas, que era
    um segundo caminho para o mesmo delete destrutivo.
    """
    test_user_id = "test_user_excluir_acao"

    with flask_app.app_context():
        user = User.query.filter_by(id=test_user_id).first()
        if not user:
            user = User(id=test_user_id, email="test_excluir@example.com")
            db.session.add(user)

        Review.query.filter_by(user_id=test_user_id).delete()
        GoogleLocation.query.filter_by(user_id=test_user_id).delete()
        db.session.commit()

        loc = GoogleLocation(
            user_id=test_user_id,
            account_id="accounts/456",
            location_id="loc_acao_excluir_888",
            location_name="Ficha Via Acao",
            is_active=True,
            tone="empatico",
        )
        db.session.add(loc)
        db.session.commit()
        loc_id = loc.id

        rev = Review(
            user_id=test_user_id,
            reviewer_name="Cliente Acao",
            text="Muito bom",
            google_location_id=loc_id
        )
        db.session.add(rev)
        db.session.commit()

    with client.session_transaction() as sess:
        sess['credentials'] = {'id_token': 'fake'}
        sess['user_info'] = {'id': test_user_id, 'email': 'test_excluir@example.com'}

    res = client.post('/auto/locations', data={
        'location_id': 'loc_acao_excluir_888',
        'action': 'excluir',
    })
    assert res.status_code == 200
    assert res.get_json()['success'] is True

    with flask_app.app_context():
        ficha = GoogleLocation.query.filter_by(
            user_id=test_user_id, location_id="loc_acao_excluir_888"
        ).first()
        assert ficha is not None
        assert ficha.is_active is False
        assert ficha.tone == "empatico"

        review = Review.query.filter_by(user_id=test_user_id, reviewer_name="Cliente Acao").first()
        assert review.google_location_id == ficha.id
