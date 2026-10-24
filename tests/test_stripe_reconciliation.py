from datetime import datetime
from types import SimpleNamespace

from models import UserSettings, db
from stripe_pay import (
    _invoice_subscription_id,
    _subscription_period_end,
    reconcile_main_subscriptions,
)


def test_reads_period_end_from_modern_subscription_item():
    subscription = {
        "items": {"data": [{"current_period_end": 1794348985}]},
    }

    assert _subscription_period_end(subscription) == datetime(2026, 11, 10, 22, 16, 25)


def test_reads_subscription_id_from_modern_invoice_parent():
    invoice = {
        "parent": {
            "subscription_details": {"subscription": "sub_modern"},
        },
    }

    assert _invoice_subscription_id(invoice) == "sub_modern"


def test_reconcile_updates_expired_local_plan(monkeypatch):
    from main import app

    with app.app_context():
        settings = UserSettings(
            user_id="stripe-reconcile@example.com",
            plano="pro",
            plano_ate=datetime(2026, 9, 10),
            stripe_subscription_id="sub_active",
        )
        db.session.add(settings)
        db.session.commit()

        subscription = SimpleNamespace(
            status="active",
            items=SimpleNamespace(
                data=[SimpleNamespace(id="si_active", current_period_end=1794348985)]
            ),
        )
        monkeypatch.setattr(
            "stripe_pay.stripe.Subscription.retrieve",
            lambda subscription_id: subscription,
        )

        result = reconcile_main_subscriptions(settings.user_id)
        db.session.refresh(settings)

        assert result == {"updated": 1, "failed": 0}
        assert settings.plano_ate == datetime(2026, 11, 10, 22, 16, 25)
        assert settings.stripe_subscription_item_id == "si_active"
