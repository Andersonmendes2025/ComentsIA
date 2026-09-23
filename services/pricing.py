"""Catálogo único para exibição e checkout.

Valores conferidos no Stripe em 23/09/2026. O valor de um Price é imutável;
novos IDs configurados no ambiente são consultados no Stripe, sem reaproveitar
o valor de outro Price. Não utiliza tabelas locais editáveis como preço oficial.
"""
import json
import os
from functools import lru_cache
from pathlib import Path

import stripe

_PRICES = json.loads(Path(__file__).with_name("stripe_catalog.json").read_text(encoding="utf-8"))["prices"]
_ENV = {
    "pro": "STRIPE_PRICE_PRO_MENSAL",
    "pro_anual": "STRIPE_PRICE_PRO_ANUAL",
    "business": "STRIPE_PRICE_BUSINESS_MENSAL",
    "business_anual": "STRIPE_PRICE_BUSINESS_ANUAL",
    "addon_slot": "STRIPE_ADDON_PRICE_ID",
    "addon_ifood": "STRIPE_PRICE_ADDON_IFOOD",
    "addon_mercadolivre": "STRIPE_PRICE_ADDON_MERCADOLIVRE",
    **{f"retro_{days}": f"STRIPE_PRICE_RETRO_{days}" for days in (30, 60, 90, 180)},
}
_ALIASES = {"pro_mensal": "pro", "business_mensal": "business"}


def get_price_id(key):
    key = _ALIASES.get(key, key)
    return os.getenv(_ENV[key]) or _PRICES[key]["price_id"]


@lru_cache(maxsize=64)
def _retrieve_price(price_id):
    client = stripe.StripeClient(os.environ["STRIPE_SECRET_KEY"])
    price = client.v1.prices.retrieve(price_id)
    if not price.active or price.currency != "brl" or not isinstance(price.unit_amount, int):
        raise ValueError("Preço Stripe indisponível ou incompatível com o catálogo em BRL.")
    recurring = price.recurring
    return {
        "price_id": price.id, "price_cents": price.unit_amount,
        "currency": price.currency.upper(),
        "interval": recurring.interval if recurring else None,
    }


def get_price(key):
    key = _ALIASES.get(key, key)
    if key == "free":
        return {"price_cents": 0, "currency": "BRL", "interval": None}
    price_id = get_price_id(key)
    snapshot = _PRICES[key]
    price = dict(snapshot if price_id == snapshot["price_id"] else _retrieve_price(price_id))
    if price["interval"] != snapshot["interval"]:
        raise ValueError("Periodicidade Stripe incompatível com o plano configurado.")
    return price


def price_amount(key):
    cents = get_price(key)["price_cents"]
    return f"{cents // 100},{cents % 100:02d}"


def price_label(key):
    return f"R$ {price_amount(key)}"


def price_decimal(key):
    return price_amount(key).replace(",", ".")


def clear_price_cache():
    _retrieve_price.cache_clear()
