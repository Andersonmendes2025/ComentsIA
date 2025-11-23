import os
import stripe
from datetime import timedelta, datetime

from flask import Blueprint, request, jsonify, session, redirect
from models import db, PaymentTransaction, UserSettings
from admin import STRIPE_PRICE_IDS, agora_brt

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

stripe_bp = Blueprint("stripe_bp", __name__, url_prefix="/stripe")


# -----------------------
# HELPERS
# -----------------------

def _get_domain_url() -> str:
    """Retorna DOMAIN_URL sem barra no final."""
    base = os.getenv("DOMAIN_URL", "").rstrip("/")
    if not base:
        # fallback pra dev local
        base = "http://localhost:5000"
    return base


def _get_or_create_stripe_customer(settings: UserSettings, email: str) -> str:
    """
    Cria ou reutiliza um Customer no Stripe e salva o ID em UserSettings.
    """
    if settings.stripe_customer_id:
        return settings.stripe_customer_id

    customer = stripe.Customer.create(
        email=email,
        metadata={"user_id": settings.user_id}
    )
    settings.stripe_customer_id = customer.id
    db.session.commit()
    return customer.id


def _plano_from_product_key(product_key: str) -> str:
    """
    Converte chave stripe para plano interno:
    - pro_mensal → pro
    - pro_anual → pro
    - business_mensal → business
    - business_anual → business
    """
    if product_key.startswith("pro"):
        return "pro"
    if product_key.startswith("business"):
        return "business"
    return "free"


def _duracao_dias_from_product_key(product_key: str) -> int:
    """
    Define duração em dias pra plano_ate, se quiser manter.
    (Opcional — você também pode confiar só no Stripe)
    """
    if product_key.endswith("_anual"):
        return 365
    return 30  # default mensal

def usar_credito_retro(user_id, period):
    retro_key = f"retro_{period}"

    tx = (
        PaymentTransaction.query
        .filter_by(
            user_id=user_id,
            plan_key=retro_key,
            status="paid",
            consumido=False
        )
        .order_by(PaymentTransaction.paid_at.desc())
        .first()
    )

    if tx:
        tx.consumido = True
        db.session.commit()
        return True

    return False

def usuario_tem_credito_retro(user_id, period):
    retro_key = f"retro_{period}"

    return (
        PaymentTransaction.query.filter_by(
            user_id=user_id,
            plan_key=retro_key,
            status="paid",
            consumido=False
        ).first()
        is not None
    )

# -----------------------
# CHECKOUT (PLANOS + RETRO)
# -----------------------

@stripe_bp.route("/checkout/<product_key>", methods=["POST"])
def create_checkout(product_key):
    """
    Checkout para:
      - Planos recorrentes (pro_mensal, pro_anual, business_mensal, business_anual)
      - Sincronizações retroativas (retro_30, retro_60, ...), modo=payment
    """

    user_info = session.get("user_info") or {}
    user_id = user_info.get("id")
    email = user_info.get("email")

    if not user_id or not email:
        return jsonify({"success": False, "message": "Faça login novamente."}), 401

    price_id = STRIPE_PRICE_IDS.get(product_key)
    if not price_id:
        return jsonify({"success": False, "message": "Produto/plano inválido."}), 400

    settings = UserSettings.query.filter_by(user_id=user_id).first()
    if not settings:
        settings = UserSettings(user_id=user_id)
        db.session.add(settings)
        db.session.commit()

    domain = _get_domain_url()

    try:
        # --------- SINCRONIZAÇÃO RETROATIVA (ONE SHOT PAYMENT) ----------
        if product_key.startswith("retro_"):
            checkout = stripe.checkout.Session.create(
                mode="payment",
                success_url=(
                    f"{domain}/stripe/success?"
                    "session_id={CHECKOUT_SESSION_ID}"
                    "&next=/auto/configurar"
                ),
                cancel_url=f"{domain}/stripe/cancel",
                customer_email=email,
                line_items=[{"price": price_id, "quantity": 1}],
                allow_promotion_codes=True,
            )

            tx = PaymentTransaction(
                user_id=user_id,
                plan_key=product_key,
                amount_cents=0,
                status="pending",
                external_id=checkout.id,
            )
            db.session.add(tx)
            db.session.commit()

            return jsonify({"success": True, "checkout_url": checkout.url})

        # --------- PLANOS RECORRENTES (SUBSCRIPTION) ----------
        # Gera/recupera Customer no Stripe
        customer_id = _get_or_create_stripe_customer(settings, email)

        checkout = stripe.checkout.Session.create(
            mode="subscription",
            success_url=(
                f"{domain}/stripe/success?"
                "session_id={CHECKOUT_SESSION_ID}"
                "&next=/planos"
            ),
            cancel_url=f"{domain}/stripe/cancel",
            customer=customer_id,
            line_items=[{"price": price_id, "quantity": 1}],
            allow_promotion_codes=True,  # cupom
        )

        tx = PaymentTransaction(
            user_id=user_id,
            plan_key=product_key,
            amount_cents=0,
            status="pending",
            external_id=checkout.id,
        )
        db.session.add(tx)
        db.session.commit()

        return jsonify({"success": True, "checkout_url": checkout.url})

    except Exception as e:
        # Log real no console/backend, front recebe msg genérica
        return jsonify({"success": False, "message": str(e)}), 400


# -----------------------
# SUCCESS & CANCEL
# -----------------------

@stripe_bp.route("/success")
def success():
    """
    Callback após o Stripe redirecionar de volta.
    Serve tanto p/ subscriptions quanto p/ pagamentos one-shot.
    """
    session_id = request.args.get("session_id")
    next_url = request.args.get("next") or "/dashboard"

    if not session_id:
        # Se por algum motivo vier sem, só manda pra página padrão
        return redirect(next_url)

    try:
        checkout = stripe.checkout.Session.retrieve(session_id)

        # Localiza transação que criamos com external_id = checkout.id
        tx = PaymentTransaction.query.filter_by(external_id=checkout.id).first()
        if not tx:
            # Falha silenciosa – volta pra tela
            return redirect(next_url)

        # Valor cobrado (serve pra payment e subscription)
        amount_total = checkout.amount_total or 0

        tx.status = "paid"
        tx.amount_cents = amount_total
        tx.paid_at = agora_brt()

        settings = UserSettings.query.filter_by(user_id=tx.user_id).first()

        # 1) Pagamento único retroativo
        if tx.plan_key.startswith("retro_"):
            # Não altera plano nem subscription, só marca pago
            db.session.commit()
            return redirect(next_url)

        # 2) Assinatura (Subscription)
        subscription_id = checkout.subscription
        if subscription_id and settings:
            sub = stripe.Subscription.retrieve(subscription_id)

            # Seta dados no UserSettings
            settings.stripe_subscription_id = sub.id
            if sub.items.data:
                settings.stripe_subscription_item_id = sub.items.data[0].id

            # Atualiza plano interno
            settings.plano = _plano_from_product_key(tx.plan_key)

            # Se quiser manter plano_ate baseado na data de renovação atual:
            try:
                period_end_ts = sub.current_period_end  # epoch
                period_end_dt = datetime.utcfromtimestamp(period_end_ts)
                # Se quiser em BRT:
                settings.plano_ate = period_end_dt  # ou converter para BRT se seu campo usa timezone
            except Exception:
                # Fallback: mantém lógica antiga (30 ou 365 dias a partir de agora)
                dias = _duracao_dias_from_product_key(tx.plan_key)
                settings.plano_ate = agora_brt() + timedelta(days=dias)

        db.session.commit()
        return redirect(next_url)

    except Exception:
        # Qualquer erro, redireciona mesmo assim
        return redirect(next_url)


@stripe_bp.route("/cancel")
def cancel():
    """
    Usuário cancelou o checkout no Stripe.
    Só devolve pra /planos ou página desejada.
    """
    next_url = request.args.get("next") or "/planos"
    return redirect(next_url)


# -----------------------
# UPGRADE DE PLANO (PRORATION)
# -----------------------

@stripe_bp.route("/upgrade/<new_plan_key>", methods=["POST"])
def upgrade_plan(new_plan_key):
    """
    Faz upgrade de plano usando proration do Stripe.
    Exemplo de new_plan_key:
      - "pro_mensal" → upgrade para Pro mensal
      - "business_mensal" → upgrade para Business mensal
      - "pro_anual", "business_anual" etc.
    """

    user_info = session.get("user_info") or {}
    user_id = user_info.get("id")
    if not user_id:
        return jsonify({"success": False, "message": "Faça login novamente."}), 401

    price_id = STRIPE_PRICE_IDS.get(new_plan_key)
    if not price_id:
        return jsonify({"success": False, "message": "Plano inválido."}), 400

    settings = UserSettings.query.filter_by(user_id=user_id).first()
    if not settings or not settings.stripe_subscription_id:
        return jsonify({
            "success": False,
            "message": "Nenhuma assinatura ativa encontrada para upgrade."
        }), 400

    try:
        sub = stripe.Subscription.retrieve(settings.stripe_subscription_id)

        # Usa o subscription_item salvo, ou pega o primeiro
        item_id = settings.stripe_subscription_item_id
        if not item_id and sub.items.data:
            item_id = sub.items.data[0].id

        if not item_id:
            return jsonify({
                "success": False,
                "message": "Item da assinatura não encontrado."
            }), 400

        # Atualiza assinatura com proration
        updated = stripe.Subscription.modify(
            settings.stripe_subscription_id,
            items=[{
                "id": item_id,
                "price": price_id,
            }],
            proration_behavior="create_prorations",
        )

        # Atualiza info local
        settings.plano = _plano_from_product_key(new_plan_key)
        try:
            period_end_ts = updated.current_period_end
            period_end_dt = datetime.utcfromtimestamp(period_end_ts)
            settings.plano_ate = period_end_dt
        except Exception:
            dias = _duracao_dias_from_product_key(new_plan_key)
            settings.plano_ate = agora_brt() + timedelta(days=dias)

        # Se item mudou, atualiza também
        if updated.items.data:
            settings.stripe_subscription_item_id = updated.items.data[0].id

        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Upgrade realizado com sucesso! O Stripe cobrará apenas a diferença proporcional."
        })

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 400


# -----------------------
# CHECK PAGO (RETRO_XX)
# -----------------------
@stripe_bp.route("/check_paid/<period>", methods=["GET"])
def check_paid(period):
    user_id = session.get("user_info", {}).get("id")
    if not user_id:
        return jsonify({"paid": False}), 401

    retro_key = f"retro_{period}"

    tx = (
        PaymentTransaction.query
        .filter_by(
            user_id=user_id,
            plan_key=retro_key,
            status="paid",
            consumido=False    # 🔥 obrigando crédito não usado
        )
        .order_by(PaymentTransaction.paid_at.desc())
        .first()
    )

    return jsonify({"paid": bool(tx)})
# -----------------------
# WEBHOOK — RENEGAÇÃO AUTOMÁTICA DO STRIPE
# -----------------------

@stripe_bp.route("/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")
    endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET")  # coloque isso no .env

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    # -------------------------
    # Pagamento de assinatura OK
    # -------------------------
    if event["type"] == "invoice.payment_succeeded":
        invoice = event["data"]["object"]
        subscription_id = invoice.get("subscription")

        if subscription_id:
            settings = UserSettings.query.filter_by(
                stripe_subscription_id=subscription_id
            ).first()

            if settings:
                sub = stripe.Subscription.retrieve(subscription_id)

                # Atualizar plano até a nova data de renovação
                period_end_ts = sub.current_period_end
                settings.plano_ate = datetime.utcfromtimestamp(period_end_ts)

                # Garantir que o plano interno está correto
                item = sub["items"]["data"][0]
                price_id = item["price"]["id"]

                for key, pid in STRIPE_PRICE_IDS.items():
                    if pid == price_id:
                        settings.plano = _plano_from_product_key(key)

                db.session.commit()

    # -------------------------
    # Pagamento FALHOU
    # -------------------------
    if event["type"] == "invoice.payment_failed":
        invoice = event["data"]["object"]
        subscription_id = invoice.get("subscription")

        if subscription_id:
            settings = UserSettings.query.filter_by(
                stripe_subscription_id=subscription_id
            ).first()

            if settings:
                # Quando falha, deixamos plano_ate como está.
                # Ao expirar a data, o app bloqueia automaticamente.
                pass

    # -------------------------
    # Assinatura cancelada pelo Stripe
    # -------------------------
    if event["type"] == "customer.subscription.deleted":
        subscription = event["data"]["object"]
        subscription_id = subscription["id"]

        settings = UserSettings.query.filter_by(
            stripe_subscription_id=subscription_id
        ).first()

        if settings:
            # Bloquear imediatamente
            settings.plano = "free"
            settings.plano_ate = agora_brt()  # expira agora
            settings.stripe_subscription_id = None
            settings.stripe_subscription_item_id = None

            db.session.commit()

    return jsonify({"status": "ok"})
