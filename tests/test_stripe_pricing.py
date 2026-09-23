from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from services import pricing


@pytest.mark.parametrize('key,cents', [
    ('pro', 4999), ('pro_anual', 54999), ('business', 7999),
    ('business_anual', 89999), ('addon_slot', 2999), ('addon_ifood', 2990),
    ('addon_mercadolivre', 2990), ('retro_30', 1900), ('retro_60', 3499),
    ('retro_90', 5999), ('retro_180', 9999),
])
def test_verified_stripe_amounts(monkeypatch, key, cents):
    monkeypatch.delenv(pricing._ENV[key], raising=False)
    assert pricing.get_price(key)['price_cents'] == cents
    assert pricing.price_amount(key) == f'{cents // 100},{cents % 100:02d}'


def test_new_price_id_is_retrieved_not_given_old_amount(monkeypatch):
    pricing.clear_price_cache()
    monkeypatch.setenv('STRIPE_PRICE_PRO_MENSAL', 'price_new')
    monkeypatch.setenv('STRIPE_SECRET_KEY', 'sk_test_dummy')
    client = MagicMock()
    client.v1.prices.retrieve.return_value = SimpleNamespace(
        id='price_new', active=True, currency='brl', unit_amount=6123,
        recurring=SimpleNamespace(interval='month'),
    )
    monkeypatch.setattr(pricing.stripe, 'StripeClient', lambda _: client)
    assert pricing.get_price_id('pro_mensal') == 'price_new'
    assert pricing.price_label('pro') == 'R$ 61,23'
    assert pricing.price_label('pro_mensal') == 'R$ 61,23'
    client.v1.prices.retrieve.assert_called_once_with('price_new')
    pricing.clear_price_cache()


@pytest.mark.parametrize('lang', ['pt_BR', 'pt_PT', 'en', 'es'])
def test_public_pages_show_exact_prices_and_currency(lang):
    from main import app
    with app.test_client() as client:
        home = client.get('/?lang=' + lang).get_data(as_text=True)
        plans = client.get('/planos?lang=' + lang).get_data(as_text=True)
    for value in ('R$ 49,99', 'R$ 79,99'):
        assert value in home
        assert value in plans
    assert 'R$ 549,99' in plans
    assert 'R$ 899,99' in plans
    assert '€ 549' not in plans
    assert '"price": "549.99"' not in plans  # JSON-LD lista planos mensais.
    assert '"price": "49.99"' in plans
