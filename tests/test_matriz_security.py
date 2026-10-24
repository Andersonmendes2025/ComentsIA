"""Regression checks for matriz/filial authorization and invitations."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from flask import Flask, session

import matriz


@pytest.fixture
def app():
    app = Flask("test_matriz_security")
    app.config.update(SECRET_KEY="test-only", TESTING=True)
    app.register_blueprint(matriz.matriz_bp)
    return app


def test_is_parent_of_requires_accepted_link():
    with patch.object(matriz.FilialVinculo, "query") as query:
        query.filter_by.return_value.first.return_value = object()
        assert matriz.is_parent_of("parent", "child") is True
        query.filter_by.assert_called_once_with(
            parent_user_id="parent", child_user_id="child", status="aceito"
        )


def test_is_parent_of_rejects_same_user_or_missing_ids():
    with patch.object(matriz.FilialVinculo, "query") as query:
        assert matriz.is_parent_of("same", "same") is False
        assert matriz.is_parent_of("", "child") is False
        assert matriz.is_parent_of("parent", "") is False
        query.filter_by.assert_not_called()


def test_stale_filial_context_is_cleared(app, monkeypatch):
    monkeypatch.setattr(matriz, "is_parent_of", lambda *_: False)
    with app.test_request_context("/matriz/"):
        session["user_info"] = {"id": "parent"}
        session["viewing_filial"] = "revoked-child"
        session["filial_name"] = "Former branch"
        session["matriz_back_url"] = "/matriz/dashboard"
        assert matriz.get_context_user_id() == "parent"
        assert "viewing_filial" not in session
        assert "filial_name" not in session
        assert "matriz_back_url" not in session


def test_accept_invite_cannot_be_called_by_get(app):
    response = app.test_client().get("/matriz/convites/aceitar/123")
    assert response.status_code == 405


@pytest.mark.parametrize("status", ["aceito", "desvinculado", "recusado"])
def test_accept_invite_refuses_nonpending_status(app, status):
    invitation = SimpleNamespace(
        child_user_id="child", parent_user_id="parent", status=status,
        data_aceite=None,
    )
    with (
        patch.object(matriz.FilialVinculo, "query") as query,
        patch.object(matriz.db.session, "commit") as commit,
    ):
        query.get_or_404.return_value = invitation
        with app.test_request_context("/matriz/convites/aceitar/7", method="POST"):
            session["credentials"] = {"token": "test-only"}
            session["user_info"] = {"id": "child"}
            response = matriz.aceitar_convite(7)
            assert response.status_code == 302
            assert invitation.status == status
            commit.assert_not_called()
