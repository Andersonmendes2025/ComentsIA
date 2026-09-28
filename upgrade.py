from flask import Blueprint, render_template, session, redirect, url_for, flash
from models import UserSettings
from admin import STRIPE_PRICE_IDS

upgrade_bp = Blueprint("upgrade", __name__, url_prefix="/upgrade")

PLANOS_INFO = {
    "free": {
        "title": "Plano Gratuito",
        "beneficios": [
            "Responder avaliações manualmente",
            "Sugestões básicas de IA",
            "Dashboard simples",
            "Sem automação Google",
            "Sem relatórios PDF",
            "Sem sincronização histórica",
            "Sem caixa de contexto",
            "Sem caixa de considerações",
            "Sem respostas hiper-compreensivas",
            "Sem filiais",
        ]
    },
    "pro_mensal": {
        "title": "Pro Mensal",
        "beneficios": [
            "Dashboard completo",
            "Automação Google",
            "2 respostas hiper/dia",
            "Caixa de contexto (tom da IA)",
            "Caixa de considerações",
            "Relatório PDF mensal",
            "Sem marca d’água",
            "Sincronização histórica (paga)",
        ]
    },
    "pro_anual": {
        "title": "Pro Anual",
        "beneficios": [
            "Tudo do Pro Mensal",
            "Sincronização histórica de até 90 dias (GRÁTIS)",
            "Economia anual",
            "Suporte prioritário",
        ]
    },
    "business": {
        "title": "Business",
        "beneficios": [
            "Tudo do Pro",
            "Até 5 filiais inclusas",
            "Painel Matriz + Filiais",
            "Permissões por equipe",
            "Relatórios avançados",
            "Suporte Premium",
        ]
    }
}


@upgrade_bp.route("/")
def upgrade_page():
    user = session.get("user_info") or {}
    user_id = user.get("id")

    if not user_id:
        flash("Faça login novamente.", "danger")
        return redirect(url_for("authorize"))

    settings = UserSettings.query.filter_by(user_id=user_id).first()

    if not settings:
        flash("Erro ao carregar seus dados.", "danger")
        return redirect("/dashboard")

    plano_atual = settings.plano

    if plano_atual == "free":
        planos_exibir = ["pro_mensal", "pro_anual", "business"]

    elif plano_atual == "pro":
        planos_exibir = ["pro_anual", "business"]

    elif plano_atual == "pro_anual":
        planos_exibir = ["business"]

    else:
        planos_exibir = []

    return render_template(
        "upgrade.html",
        plano_atual=plano_atual,
        planos_info=PLANOS_INFO,
        planos_exibir=planos_exibir,
        stripe_products=STRIPE_PRICE_IDS
    )
