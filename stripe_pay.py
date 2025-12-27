import os
import stripe
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, session, redirect, url_for, flash
from models import db, PaymentTransaction, UserSettings
from admin import STRIPE_PRICE_IDS, agora_brt

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# ⚠️ Configure aqui o ID do Preço do Slot Extra no Stripe
STRIPE_ADDON_PRICE_ID = os.getenv("STRIPE_ADDON_PRICE_ID", "price_SEU_ID_AQUI")

stripe_bp = Blueprint("stripe_bp", __name__, url_prefix="/stripe")

# -----------------------
# HELPERS GERAIS
# -----------------------

def _get_domain_url() -> str:
    domain = os.getenv("DOMAIN_URL")
    if domain and domain.strip():
        return domain.rstrip("/")
    return "http://localhost:5000"

def _get_or_create_stripe_customer(settings: UserSettings, email: str) -> str:
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
    if product_key.startswith("pro"): return "pro"
    if product_key.startswith("business"): return "business"
    return "free"

def _duracao_dias_from_product_key(product_key: str) -> int:
    if product_key.endswith("_anual"): return 365
    return 30

# -----------------------
# HELPERS DE CRÉDITO RETROATIVO (RESTAURADOS)
# -----------------------

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
# 🔄 LÓGICA DE ADD-ON (ASSINATURA)
# -----------------------

@stripe_bp.route("/addon/add", methods=["POST"])
def adicionar_slot_ao_plano():
    """Adiciona 1 slot extra à assinatura existente."""
    user_info = session.get("user_info")
    if not user_info:
        return jsonify({"success": False, "error": "Usuário não logado"}), 401
    
    user_id = user_info.get("id")
    settings = UserSettings.query.filter_by(user_id=user_id).first()

    if not settings or not settings.stripe_subscription_id:
        return jsonify({"success": False, "error": "Necessário plano ativo."}), 400

    try:
        sub = stripe.Subscription.retrieve(settings.stripe_subscription_id)
        addon_item = None
        for item in sub['items']['data']:
            if item.price.id == STRIPE_ADDON_PRICE_ID:
                addon_item = item
                break
        
        if addon_item:
            stripe.SubscriptionItem.modify(
                addon_item.id,
                quantity=addon_item.quantity + 1,
                proration_behavior='always_invoice'
            )
        else:
            stripe.SubscriptionItem.create(
                subscription=sub.id,
                price=STRIPE_ADDON_PRICE_ID,
                quantity=1,
                proration_behavior='always_invoice'
            )

        settings.gbp_slots_extras = (settings.gbp_slots_extras or 0) + 1
        db.session.commit()

        return jsonify({"success": True, "message": "Slot ativado com sucesso!"})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@stripe_bp.route("/addon/remove", methods=["POST"])
def remover_slot_do_plano():
    """Remove 1 slot extra da assinatura."""
    user_info = session.get("user_info")
    if not user_info:
        return jsonify({"success": False, "error": "Usuário não logado"}), 401
    
    user_id = user_info.get("id")
    settings = UserSettings.query.filter_by(user_id=user_id).first()

    if not settings or not settings.stripe_subscription_id:
        return jsonify({"success": False, "error": "Assinatura não encontrada."}), 400

    if (settings.gbp_slots_extras or 0) <= 0:
        return jsonify({"success": False, "error": "Sem slots extras para cancelar."}), 400

    try:
        sub = stripe.Subscription.retrieve(settings.stripe_subscription_id)
        addon_item = None
        for item in sub['items']['data']:
            if item.price.id == STRIPE_ADDON_PRICE_ID:
                addon_item = item
                break
        
        if not addon_item:
            settings.gbp_slots_extras = 0
            db.session.commit()
            return jsonify({"success": True, "message": "Sincronizado."})

        if addon_item.quantity > 1:
            stripe.SubscriptionItem.modify(
                addon_item.id, quantity=addon_item.quantity - 1, proration_behavior='none'
            )
        else:
            stripe.SubscriptionItem.delete(addon_item.id, proration_behavior='none')

        settings.gbp_slots_extras = max(0, (settings.gbp_slots_extras or 0) - 1)
        db.session.commit()

        return jsonify({"success": True, "message": "Slot extra cancelado."})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# -----------------------
# ❌ CANCELAMENTO GERAL
# -----------------------

@stripe_bp.route("/subscription/cancel", methods=["POST"])
def cancelar_assinatura_geral():
    user_info = session.get("user_info")
    if not user_info:
        return jsonify({"success": False, "error": "Usuário não logado"}), 401
    
    user_id = user_info.get("id")
    settings = UserSettings.query.filter_by(user_id=user_id).first()

    if not settings or not settings.stripe_subscription_id:
        return jsonify({"success": False, "error": "Nenhuma assinatura ativa."}), 400

    try:
        stripe.Subscription.modify(
            settings.stripe_subscription_id,
            cancel_at_period_end=True
        )
        flash("Assinatura cancelada. Acesso mantido até o fim do ciclo.", "info")
        return jsonify({"success": True, "message": "Cancelamento agendado."})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# -----------------------
# CHECKOUT PADRÃO (PLANOS / RETRO)
# -----------------------

@stripe_bp.route("/checkout/<product_key>", methods=["POST"])
def create_checkout(product_key):
    user_info = session.get("user_info") or {}
    user_id = user_info.get("id")
    email = user_info.get("email")
    data = request.get_json(silent=True) or {}
    next_url = data.get("next_url", "/dashboard")

    if not user_id or not email:
        return jsonify({"success": False, "message": "Faça login novamente."}), 401

    price_id = STRIPE_PRICE_IDS.get(product_key)
    if not price_id:
        return jsonify({"success": False, "message": "Plano inválido."}), 400

    settings = UserSettings.query.filter_by(user_id=user_id).first()
    if not settings:
        settings = UserSettings(user_id=user_id)
        db.session.add(settings)
        db.session.commit()

    domain = _get_domain_url()

    try:
        # Retroativo (One-shot)
        if product_key.startswith("retro_"):
            checkout = stripe.checkout.Session.create(
                mode="payment",
                success_url=f"{domain}/stripe/success?session_id={{CHECKOUT_SESSION_ID}}&next={next_url}",
                cancel_url=f"{domain}/stripe/cancel?next={next_url}",
                customer_email=email,
                line_items=[{"price": price_id, "quantity": 1}],
                allow_promotion_codes=True,
            )
            tx = PaymentTransaction(
                user_id=user_id, plan_key=product_key, amount_cents=0,
                status="pending", external_id=checkout.id
            )
            db.session.add(tx)
            db.session.commit()
            return jsonify({"success": True, "checkout_url": checkout.url})

        # Planos (Subscription)
        customer_id = _get_or_create_stripe_customer(settings, email)
        
        checkout = stripe.checkout.Session.create(
            mode="subscription",
            success_url=f"{domain}/stripe/success?session_id={{CHECKOUT_SESSION_ID}}&next={next_url}",
            cancel_url=f"{domain}/stripe/cancel?next={next_url}",
            customer=customer_id,
            line_items=[{"price": price_id, "quantity": 1}],
            allow_promotion_codes=True,
        )
        
        tx = PaymentTransaction(
            user_id=user_id, plan_key=product_key, amount_cents=0,
            status="pending", external_id=checkout.id
        )
        db.session.add(tx)
        db.session.commit()
        
        return jsonify({"success": True, "checkout_url": checkout.url})

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 400


@stripe_bp.route("/success")
def success():
    session_id = request.args.get("session_id")
    next_url = request.args.get("next") or "/dashboard"

    if not session_id: return redirect(next_url)

    try:
        checkout = stripe.checkout.Session.retrieve(session_id)
        tx = PaymentTransaction.query.filter_by(external_id=checkout.id).first()
        if not tx: return redirect(next_url)

        tx.status = "paid"
        tx.amount_cents = checkout.amount_total or 0
        tx.paid_at = agora_brt()

        settings = UserSettings.query.filter_by(user_id=tx.user_id).first()

        if tx.plan_key.startswith("retro_"):
            db.session.commit()
            return redirect(next_url)

        subscription_id = checkout.subscription
        if subscription_id and settings:
            sub = stripe.Subscription.retrieve(subscription_id)
            settings.stripe_subscription_id = sub.id
            if sub.items.data:
                settings.stripe_subscription_item_id = sub.items.data[0].id
            settings.plano = _plano_from_product_key(tx.plan_key)
            try:
                settings.plano_ate = datetime.utcfromtimestamp(sub.current_period_end)
            except:
                settings.plano_ate = agora_brt() + timedelta(days=30)

        db.session.commit()
        return redirect(next_url)

    except Exception:
        return redirect(next_url)

@stripe_bp.route("/cancel")
def cancel():
    next_url = request.args.get("next") or "/dashboard"
    return redirect(next_url)

@stripe_bp.route("/check_paid/<period>", methods=["GET"])
def check_paid(period):
    user_id = session.get("user_info", {}).get("id")
    if not user_id:
        return jsonify({"paid": False}), 401
    return jsonify({"paid": usuario_tem_credito_retro(user_id, period)})

# -----------------------
# WEBHOOK
# -----------------------
@stripe_bp.route("/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")
    endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except Exception as e:
        # Se a assinatura não bater ou o payload estiver errado, retorna 400
        return jsonify({"error": str(e)}), 400

    # ✅ Pagamento de fatura de assinatura (renovação/mensalidade/anual)
    if event["type"] == "invoice.payment_succeeded":
        invoice = event["data"]["object"]
        sub_id = invoice.get("subscription")

        if sub_id:
            settings = UserSettings.query.filter_by(stripe_subscription_id=sub_id).first()
            if settings:
                # Atualiza validade do plano com base no período atual da assinatura
                sub = stripe.Subscription.retrieve(sub_id)
                settings.plano_ate = datetime.utcfromtimestamp(sub.current_period_end)

                # 🔄 Sincroniza quantidade de ADD-ON (slots extras)
                addon_qty = 0
                for item in sub["items"]["data"]:
                    if item.price.id == STRIPE_ADDON_PRICE_ID:
                        addon_qty = item.quantity

                settings.gbp_slots_extras = addon_qty

                db.session.commit()

    # ❌ Assinatura cancelada (Stripe encerrou mesmo, não é só cancel_at_period_end)
    if event["type"] == "customer.subscription.deleted":
        sub_id = event["data"]["object"]["id"]
        settings = UserSettings.query.filter_by(stripe_subscription_id=sub_id).first()

        if settings:
            settings.plano = "free"
            settings.plano_ate = agora_brt()
            settings.stripe_subscription_id = None
            settings.stripe_subscription_item_id = None
            settings.gbp_slots_extras = 0
            db.session.commit()

    # Stripe só precisa saber que você recebeu o evento
    return jsonify({"status": "ok"})
