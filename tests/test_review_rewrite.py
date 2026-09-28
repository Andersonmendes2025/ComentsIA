from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import main
from models import Review, db


def test_rewrite_button_calls_existing_suggestion_endpoint():
    template = (Path(__file__).resolve().parents[1] / "templates" / "reviews.html").read_text(encoding="utf-8")
    assert "fetch('/suggest_reply'" in template
    assert "data.suggested_reply" in template
    assert "fetch('/generate_reply'" not in template
    assert any(rule.rule == "/suggest_reply" for rule in main.app.url_map.iter_rules())


def test_rewrite_ifood_review_returns_suggestion_without_publishing(monkeypatch):
    main.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    ai = MagicMock()
    ai.with_options.return_value.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="Obrigado por contar como foi sua experiência!"))]
    )
    monkeypatch.setattr(main, "client", ai)
    monkeypatch.setattr(main, "get_user_settings", lambda _: {
        "business_name": "Loja Teste", "manager_name": "", "contact_info": "",
        "default_greeting": "", "default_closing": "", "gbp_tone": "amigavel",
        "idioma_resposta": "Português (Brasil)", "contexto_personalizado": "Informação interna",
    })

    with main.app.app_context():
        review = Review(user_id="rewrite_test_user", source="ifood", reviewer_name="Riverson",
                        rating=5, text="Do além", replied=True, reply="Resposta antiga")
        db.session.add(review)
        db.session.commit()
        review_id = review.id

    with main.app.test_client() as browser:
        with browser.session_transaction() as session:
            session["credentials"] = {"token": "test"}
            session["user_info"] = {"id": "rewrite_test_user"}
        response = browser.post("/suggest_reply", json={
            "review_id": review_id, "tone": "amigavel", "idioma": "auto",
            "hiper_compreensiva": False, "consideracoes": "",
        })

    assert response.status_code == 200
    assert response.json == {
        "success": True,
        "suggested_reply": "Obrigado por contar como foi sua experiência!",
    }
    prompt = ai.with_options.return_value.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "Informação interna" not in prompt
    with main.app.app_context():
        assert db.session.get(Review, review_id).reply == "Resposta antiga"
        db.session.delete(db.session.get(Review, review_id))
        db.session.commit()
