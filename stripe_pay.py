import os
import stripe
from datetime import datetime, timedelta
import logging

from flask import Blueprint, request, jsonify, session, redirect, url_for, flash, current_app
from models import db, PaymentTransaction, UserSettings
from admin import STRIPE_PRICE_IDS, agora_brt

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# ⚠️ Configure aqui o ID do Preço do Slot Extra no Stripe
STRIPE_ADDON_PRICE_ID = os.getenv("STRIPE_ADDON_PRICE_ID", "price_SEU_ID_AQUI")
STRIPE_PRICE_ADDON_IFOOD = os.getenv("STRIPE_PRICE_ADDON_IFOOD", "price_1U4qebHdM7mYgSGKImuFU85G")
STRIPE_PROD_ADDON_IFOOD = os.getenv("STRIPE_PROD_ADDON_IFOOD", "prod_V50fovspMA5NmF")
STRIPE_PRICE_ADDON_MERCADOLIVRE = os.getenv("STRIPE_PRICE_ADDON_MERCADOLIVRE", "price_1U6JcmHdM7mYgSGKhx3gi9ha")
STRIPE_PROD_ADDON_MERCADOLIVRE = os.getenv("STRIPE_PROD_ADDON_MERCADOLIVRE", "prod_V6WgBfKchC5hek")

stripe_bp = Blueprint("stripe_bp", __name__, url_prefix="/stripe")

# -----------------------
# HELPERS GERAIS
# -----------------------

def _safe_next_url(url: str, default: str = "/dashboard") -> str:
    """Sanitiza o parâmetro de redirecionamento para prevenir Open Redirect (CWE-601).
    Aceita apenas caminhos relativos internos (começam com '/' mas não com '//').
    """
    if url and isinstance(url, str) and url.startswith("/") and not url.startswith("//"):
        return url
    return default



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
# 🍔 ADD-ON IFOOD & MERCADO LIVRE (R$ 30,00/MÊS)
# -----------------------

@stripe_bp.route("/addon/ifood/checkout", methods=["POST", "GET"])
def checkout_addon_ifood():
    """Inicia o checkout Stripe para o Add-on de automação iFood usando o mesmo checkout unificado."""
    user_info = session.get("user_info") or {}
    user_id = user_info.get("id") or user_info.get("email")
    email = user_info.get("email") or "cliente@comentsia.com.br"

    if not user_id:
        flash("Faça login para assinar o Add-on do iFood.", "warning")
        return redirect(url_for("authorize"))

    settings = UserSettings.query.filter_by(user_id=str(user_id)).first()
    if not settings:
        settings = UserSettings(user_id=str(user_id))
        db.session.add(settings)
        db.session.commit()

    customer_id = _get_or_create_stripe_customer(settings, email)
    domain = _get_domain_url()

    try:
        checkout = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="subscription",
            customer=customer_id,
            line_items=[{"price": STRIPE_PRICE_ADDON_IFOOD, "quantity": 1}],
            success_url=f"{domain}/stripe/addon/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{domain}/integracoes?status=addon_ifood_cancel",
            metadata={
                "type": "addon_ifood",
                "user_id": str(user_id)
            },
            client_reference_id=str(user_id)
        )
        return redirect(checkout.url, code=303)
    except Exception as e:
        logging.exception("Erro ao criar checkout Stripe para addon iFood: %s", e)
        flash(f"Erro ao iniciar pagamento com Stripe: {str(e)}", "danger")
        return redirect("/integracoes")


@stripe_bp.route("/addon/ifood/cancel", methods=["POST"])
def cancelar_addon_ifood():
    """Cancela o add-on do iFood ao final do período já pago (mantém acesso até lá)."""
    user_info = session.get("user_info") or {}
    user_id = user_info.get("id") or user_info.get("email")
    if not user_id:
        return jsonify({"success": False, "error": "Usuário não logado"}), 401

    settings = UserSettings.query.filter_by(user_id=str(user_id)).first()
    if not settings or not settings.addon_ifood_subscription_id:
        return jsonify({"success": False, "error": "Nenhum add-on do iFood ativo."}), 400

    try:
        stripe.Subscription.modify(settings.addon_ifood_subscription_id, cancel_at_period_end=True)
        return jsonify({"success": True, "message": "Add-on do iFood será cancelado ao final do período já pago."})
    except Exception as e:
        logging.exception("Erro ao cancelar addon iFood: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@stripe_bp.route("/addon/mercadolivre/checkout", methods=["POST", "GET"])
def checkout_addon_mercadolivre():
    """Inicia o checkout Stripe para o Add-on do Mercado Livre usando o mesmo checkout."""
    user_info = session.get("user_info") or {}
    user_id = user_info.get("id") or user_info.get("email")
    email = user_info.get("email") or "cliente@comentsia.com.br"

    if not user_id:
        flash("Faça login para assinar o Add-on do Mercado Livre.", "warning")
        return redirect(url_for("authorize"))

    settings = UserSettings.query.filter_by(user_id=str(user_id)).first()
    if not settings:
        settings = UserSettings(user_id=str(user_id))
        db.session.add(settings)
        db.session.commit()

    customer_id = _get_or_create_stripe_customer(settings, email)
    domain = _get_domain_url()

    try:
        checkout = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="subscription",
            customer=customer_id,
            line_items=[{"price": STRIPE_PRICE_ADDON_MERCADOLIVRE, "quantity": 1}],
            success_url=f"{domain}/stripe/addon/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{domain}/integracoes?status=addon_ml_cancel",
            metadata={
                "type": "addon_mercadolivre",
                "user_id": str(user_id)
            },
            client_reference_id=str(user_id)
        )
        return redirect(checkout.url, code=303)
    except Exception as e:
        logging.exception("Erro ao criar checkout Stripe para addon Mercado Livre: %s", e)
        flash(f"Erro ao iniciar pagamento com Stripe: {str(e)}", "danger")
        return redirect("/integracoes")


@stripe_bp.route("/addon/mercadolivre/cancel", methods=["POST"])
def cancelar_addon_mercadolivre():
    """Cancela o add-on do Mercado Livre ao final do período já pago (mantém acesso até lá)."""
    user_info = session.get("user_info") or {}
    user_id = user_info.get("id") or user_info.get("email")
    if not user_id:
        return jsonify({"success": False, "error": "Usuário não logado"}), 401

    settings = UserSettings.query.filter_by(user_id=str(user_id)).first()
    if not settings or not settings.addon_mercadolivre_subscription_id:
        return jsonify({"success": False, "error": "Nenhum add-on do Mercado Livre ativo."}), 400

    try:
        stripe.Subscription.modify(settings.addon_mercadolivre_subscription_id, cancel_at_period_end=True)
        return jsonify({"success": True, "message": "Add-on do Mercado Livre será cancelado ao final do período já pago."})
    except Exception as e:
        logging.exception("Erro ao cancelar addon Mercado Livre: %s", e)
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
    

@stripe_bp.route("/checkout/adicionar-ficha", methods=["POST"])
def checkout_adicionar_ficha():
    user_info = session.get("user_info", {})
    user_id = user_info.get("id")
    email = user_info.get("email")
    settings = UserSettings.query.filter_by(user_id=user_id).first()
    
    price_id = os.getenv("STRIPE_ADDON_PRICE_ID") 

    # Garante que o cliente existe no Stripe
    customer_id = _get_or_create_stripe_customer(settings, email)

    # 🚀 GERA A SESSÃO DO CHECKOUT NO STRIPE
    checkout = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=_get_domain_url() + "/auto/locations",
        cancel_url=_get_domain_url() + "/auto/locations",
        client_reference_id=user_id
    )
    
    # 🚀 CORREÇÃO AQUI: Em vez de jsonify, usamos redirect para forçar o navegador a ir pro Stripe
    return redirect(checkout.url, code=303)


@stripe_bp.route("/success")
def success():
    session_id = request.args.get("session_id")
    next_url = _safe_next_url(request.args.get("next"), "/dashboard")

    if not session_id:
        return redirect(next_url)

    try:
        checkout = stripe.checkout.Session.retrieve(session_id)

        # 🔒 VALIDAÇÃO DE PAGAMENTO: só ativa o plano se o pagamento estiver confirmado
        payment_ok = (
            checkout.get("payment_status") == "paid"
            or checkout.get("status") == "complete"
        )
        if not payment_ok:
            logging.warning("[stripe] Tentativa de acesso a /success com checkout não pago: %s", session_id)
            flash("O pagamento ainda não foi confirmado. Se já finalizou, aguarde alguns instantes.", "warning")
            return redirect(next_url)

        tx = PaymentTransaction.query.filter_by(external_id=checkout.id).first()
        if not tx:
            return redirect(next_url)

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
            except Exception:
                settings.plano_ate = agora_brt() + timedelta(days=30)

        db.session.commit()
        return redirect(next_url)

    except Exception:
        logging.exception("[stripe] Erro ao processar /success para session_id=%s", session_id)
        return redirect(next_url)


@stripe_bp.route("/addon/success")
def addon_success():
    """
    Destino único do checkout dos add-ons (iFood e Mercado Livre). Só ativa o
    add-on depois de confirmar com a própria Stripe que o pagamento foi
    concluído — nunca confia em parâmetros de URL sozinhos (isso permitia
    ativar o add-on de graça só visitando a URL de sucesso manualmente).
    """
    session_id = request.args.get("session_id")
    if not session_id:
        flash("Sessão de pagamento inválida.", "danger")
        return redirect(url_for("integracoes"))

    try:
        checkout = stripe.checkout.Session.retrieve(session_id)

        payment_ok = (
            checkout.get("payment_status") == "paid"
            or checkout.get("status") == "complete"
        )
        if not payment_ok:
            logging.warning("[stripe] Tentativa de acesso a /addon/success com checkout não pago: %s", session_id)
            flash("O pagamento ainda não foi confirmado. Se já finalizou, aguarde alguns instantes.", "warning")
            return redirect(url_for("integracoes"))

        addon_type = (checkout.get("metadata") or {}).get("type")
        user_id = (checkout.get("metadata") or {}).get("user_id") or checkout.get("client_reference_id")
        if not user_id:
            return redirect(url_for("integracoes"))

        settings = UserSettings.query.filter_by(user_id=str(user_id)).first()
        if not settings:
            return redirect(url_for("integracoes"))

        subscription_id = checkout.get("subscription")
        until = None
        if subscription_id:
            try:
                sub = stripe.Subscription.retrieve(subscription_id)
                until = datetime.utcfromtimestamp(sub.current_period_end)
            except Exception:
                pass

        if addon_type == "addon_ifood":
            settings.has_addon_ifood = True
            settings.addon_ifood_subscription_id = subscription_id
            settings.addon_ifood_until = until
            db.session.commit()
            flash("🎉 Add-on do iFood ativado com sucesso!", "success")
        elif addon_type == "addon_mercadolivre":
            settings.has_addon_mercadolivre = True
            settings.addon_mercadolivre_subscription_id = subscription_id
            settings.addon_mercadolivre_until = until
            db.session.commit()
            flash("🎉 Add-on do Mercado Livre ativado com sucesso!", "success")
        else:
            logging.warning("[stripe] /addon/success com metadata.type desconhecido: %r", addon_type)

        return redirect(url_for("integracoes"))

    except Exception:
        logging.exception("[stripe] Erro ao processar /addon/success para session_id=%s", session_id)
        flash("Não foi possível confirmar o pagamento agora. Se o valor foi cobrado, entre em contato com o suporte.", "danger")
        return redirect(url_for("integracoes"))


@stripe_bp.route("/cancel")
def cancel():
    next_url = _safe_next_url(request.args.get("next"), "/dashboard")
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
    # ⚠️ Isentar CSRF via csrf.exempt() em main.py após registrar o blueprint
    # A segurança aqui é garantida pela validação da assinatura Stripe-Signature abaixo

    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")
    endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except Exception as e:
        # Se a assinatura não bater ou o payload estiver errado, retorna 400
        return jsonify({"error": str(e)}), 400

    # 🚀 O BLOCO NOVO FICA AQUI:
    # ✅ Pagamento de fatura de assinatura (renovação/mensalidade ou compra de slot extra)
    if event["type"] == "invoice.payment_succeeded":
        invoice = event["data"]["object"]
        sub_id = invoice.get("subscription")
        customer_id = invoice.get("customer")

        if customer_id:
            settings = UserSettings.query.filter_by(stripe_customer_id=customer_id).first()
            if settings:
                # Se for a assinatura principal, atualiza a validade do plano
                if sub_id and settings.stripe_subscription_id == sub_id:
                    sub = stripe.Subscription.retrieve(sub_id)
                    settings.plano_ate = datetime.utcfromtimestamp(sub.current_period_end)

                # 🔄 CONTA TODOS OS SLOTS EXTRAS ATIVOS DO CLIENTE
                # Isso impede erros caso o slot extra seja uma assinatura separada no Stripe
                subs = stripe.Subscription.list(customer=customer_id, status="active")
                addon_qty = 0
                has_ifood = False
                has_ml = False
                for s in subs.auto_paging_iter():
                    for item in s["items"]["data"]:
                        if item.price.id == STRIPE_ADDON_PRICE_ID:
                            addon_qty += item.quantity
                        if item.price.id == STRIPE_PRICE_ADDON_IFOOD:
                            has_ifood = True
                            settings.addon_ifood_subscription_id = s.id
                            try:
                                settings.addon_ifood_until = datetime.utcfromtimestamp(s.current_period_end)
                            except Exception:
                                pass
                        if item.price.id == STRIPE_PRICE_ADDON_MERCADOLIVRE:
                            has_ml = True
                            settings.addon_mercadolivre_subscription_id = s.id
                            try:
                                settings.addon_mercadolivre_until = datetime.utcfromtimestamp(s.current_period_end)
                            except Exception:
                                pass

                settings.gbp_slots_extras = addon_qty
                if has_ifood:
                    settings.has_addon_ifood = True
                if has_ml:
                    settings.has_addon_mercadolivre = True
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

        # Checa se a assinatura cancelada foi a do iFood
        settings_ifood = UserSettings.query.filter_by(addon_ifood_subscription_id=sub_id).first()
        if settings_ifood:
            settings_ifood.has_addon_ifood = False
            settings_ifood.addon_ifood_subscription_id = None
            db.session.commit()

        # Checa se a assinatura cancelada foi a do Mercado Livre
        settings_ml = UserSettings.query.filter_by(addon_mercadolivre_subscription_id=sub_id).first()
        if settings_ml:
            settings_ml.has_addon_mercadolivre = False
            settings_ml.addon_mercadolivre_subscription_id = None
            db.session.commit()
    # ❌ Pagamento Falhou (Dispara e-mail Imediato de falha no cartão)
    if event["type"] == "invoice.payment_failed":
        invoice = event["data"]["object"]
        customer_id = invoice.get("customer")
        ext_id = invoice.get("id")

        if customer_id:
            settings = UserSettings.query.filter_by(stripe_customer_id=customer_id).first()
            if settings:
                from admin import _send_billing_email
                from models import BillingEvent, db
                
                # Registra o evento de falha no banco
                ev = BillingEvent.query.filter_by(event="payment_failed", external_id=ext_id).first()
                if not ev:
                    ev = BillingEvent(user_id=settings.user_id, event="payment_failed", external_id=ext_id)
                    db.session.add(ev)
                    db.session.commit()
                
                # Dispara e-mail no minuto em que o Stripe avisar que recusou
                if not getattr(ev, 'handled_immediate', False):
                    _send_billing_email(settings.user_id, "billing_failed_immediate", ev.id)
                    ev.handled_immediate = True
                    db.session.commit()
    # Stripe só precisa saber que você recebeu o evento
    return jsonify({"status": "ok"})