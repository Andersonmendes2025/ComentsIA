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


def test_delete_google_location(client):
    test_user_id = "test_user_del_loc"
    
    # Cria usuário e ficha de teste
    with flask_app.app_context():
        user = User.query.filter_by(id=test_user_id).first()
        if not user:
            user = User(id=test_user_id, email="test_loc@example.com")
            db.session.add(user)
        
        # Limpa fichas antigas de teste
        GoogleLocation.query.filter_by(user_id=test_user_id).delete()
        db.session.commit()

        loc = GoogleLocation(
            user_id=test_user_id,
            account_id="accounts/123",
            location_id="loc_to_delete_999",
            location_name="Loja Para Deletar",
            is_active=False
        )
        db.session.add(loc)
        db.session.commit()
        
        loc_id = loc.id

        # Cria review associada
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

    # Testa endpoint de exclusão
    res = client.post('/auto/location/loc_to_delete_999/delete', json={})
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True

    # Verifica se a ficha foi excluída e a review foi desvinculada
    with flask_app.app_context():
        deleted_loc = GoogleLocation.query.filter_by(user_id=test_user_id, location_id="loc_to_delete_999").first()
        assert deleted_loc is None

        review = Review.query.filter_by(user_id=test_user_id, reviewer_name="Cliente Teste").first()
        assert review is not None
        assert review.google_location_id is None
