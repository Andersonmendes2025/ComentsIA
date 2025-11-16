# --- std/3rd-party ---
# --- LOGGING GLOBAL (colocar antes de qualquer outro import) ---
import logging
import sys
from flask_apscheduler import APScheduler
class ColorFormatter(logging.Formatter):
    COLORS = {
        "DEBUG": "\033[37m",  # cinza
        "INFO": "\033[36m",  # ciano
        "WARNING": "\033[33m",  # amarelo
        "ERROR": "\033[31m",  # vermelho
        "CRITICAL": "\033[41m",  # vermelho fundo
    }
    RESET = "\033[0m"

    def format(self, record):
        color = self.COLORS.get(record.levelname, self.RESET)
        message = super().format(record)
        return f"{color}{message}{self.RESET}"


handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(
    ColorFormatter("%(asctime)s [%(levelname)s] [%(name)s] %(message)s")
)

logging.basicConfig(level=logging.DEBUG, handlers=[handler], force=True)
sys.stdout.reconfigure(line_buffering=True)

import base64
import io
import json
import logging
import os
import sys
from collections import Counter
from datetime import datetime, timedelta
from functools import wraps

import flask
from apscheduler.schedulers.background import BackgroundScheduler

from google_auto import google_auto_bp, register_gbp_cron

sys.stdout.reconfigure(line_buffering=True)

import logging

# Google / OpenAI
import google.oauth2.credentials
import google_auth_oauthlib.flow
import numpy as np
import pandas as pd
import pytz
import sentry_sdk
from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager, current_user, login_user, logout_user
from flask_migrate import Migrate, upgrade
from flask_sqlalchemy import SQLAlchemy  # (se não usar diretamente, pode remover)
from flask_talisman import Talisman
from flask_wtf.csrf import CSRFError, CSRFProtect, generate_csrf
from googleapiclient.discovery import build
from markupsafe import Markup
from openai import OpenAI
from sentry_sdk.integrations.flask import FlaskIntegration
from sqlalchemy import desc, or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

# --- app modules ---
from admin import (
    admin_bp,
    get_plan_display_name,
    get_plan_duration_days,
    get_plan_prices,
    get_pricing_catalog,
    seed_roles_permissions,
    user_can,
)
from auto_reply_setup import auto_reply_bp
from email_utils import (
    enviar_email,
    montar_email_boas_vindas,
    montar_email_conta_apagada,
)
from matriz import matriz_bp
from models import (
    ConsideracoesUso,
    FilialVinculo,
    RelatorioHistorico,
    RespostaEspecialUso,
    Review,
    User,
    UserSettings,
    db,
)
from relatorio import RelatorioAvaliacoes
from routes_metrics import metrics_bp
from utils.crypto import decrypt, encrypt

# -------------------------------------------------------------------
# LOG / ENV
# -------------------------------------------------------------------


# Exibir tudo no console em tempo real
logging.basicConfig(
    level=logging.DEBUG,
    stream=sys.stdout,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
sys.stdout.reconfigure(line_buffering=True)


# -------------------------------------------------------------------
# SENTRY (sem PII por padrão)
# -------------------------------------------------------------------
sentry_sdk.init(
    dsn=os.getenv("SENTRY_DSN"),
    integrations=[FlaskIntegration()],
    send_default_pii=False,  # 🔒 não enviar PII por padrão
    traces_sample_rate=0.2,  # redução razoável em dev
)

# -------------------------------------------------------------------
# FLASK APP
# -------------------------------------------------------------------
app = Flask(__name__)


if os.getenv("WORKER_ROLE") == "1":
    from booking import _get_scheduler

    _get_scheduler()

# Sessão e DB
app.secret_key = os.getenv("FLASK_SECRET_KEY")
db_url = os.getenv("DATABASE_URL", "")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config.update(
    SQLALCHEMY_DATABASE_URI=db_url,
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    MAX_CONTENT_LENGTH=512 * 1024,  # 🔒 limite global de upload 512KB
    # Cookies de sessão seguros
    SESSION_COOKIE_SECURE=(os.getenv("FLASK_ENV") == "production"),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",  # bom para OAuth
)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = "authorize"
from flask_login import current_user


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(user_id)


@login_manager.unauthorized_handler
def _unauth():
    return redirect(url_for("authorize"))


# 👉 primeiro inicializa DB e Migrate
db.init_app(app)
migrate = Migrate(app, db)

scheduler = BackgroundScheduler()
scheduler.start()

app.register_blueprint(google_auto_bp)
# 👉 depois registra os blueprints
app.register_blueprint(admin_bp)
scheduler = APScheduler()
scheduler.init_app(app)

register_gbp_cron(scheduler, app)
# 👉 só então roda o seed (dentro do app_context)
from sqlalchemy import inspect

with app.app_context():
    insp = inspect(db.engine)
    if insp.has_table("roles"):
        seed_roles_permissions()
    else:
        app.logger.info("Seed pulado: tabela 'roles' ainda não existe.")


# CSRF global
csrf = CSRFProtect(app)

# -------------------------------------------------------------------
# Security Headers (CSP) com Talisman
# 👉 HTTPS forçado só em produção para não quebrar desenvolvimento
# -------------------------------------------------------------------
csp_policy = {
    "default-src": "'self'",
    "script-src": [
        "'self'",
        "https://cdn.jsdelivr.net",
        "https://www.googletagmanager.com",
        "https://www.google-analytics.com",
        "'unsafe-inline'",  # se você tiver scripts inline (GA, etc.)
    ],
    "style-src": [
        "'self'",
        "https://cdn.jsdelivr.net",
        "'unsafe-inline'",  # se usa <style> inline/Bootstrap
    ],
    "img-src": [
        "'self'",
        "data:",
        "https://lh3.googleusercontent.com",
        "https://www.google-analytics.com",
    ],
    "font-src": ["'self'", "https://cdn.jsdelivr.net"],
    "connect-src": ["'self'", "https://www.google-analytics.com"],
    "frame-ancestors": "'none'",
}
use_https = os.getenv("FLASK_ENV") == "production"
Talisman(
    app,
    content_security_policy=csp_policy,
    force_https=use_https,
    strict_transport_security=use_https,
)

# -------------------------------------------------------------------
# Blueprints
# -------------------------------------------------------------------
app.register_blueprint(auto_reply_bp)
app.register_blueprint(matriz_bp)

# -------------------------------------------------------------------
# OpenAI Client
# -------------------------------------------------------------------
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# -------------------------------------------------------------------
# Planos (inalterado)
# -------------------------------------------------------------------
PLANOS = {
    "free": {
        "nome": "Gratuito",
        "preco": 0,
        "avaliacoes_mes": 20,
        "hiper_dia": 0,
        "consideracoes_dia": 0,
        "relatorio_pdf_mes": 0,
        "api": False,
        "dashboard": "simples",
        "suporte": "básico",
        "marca_dagua": True,
    },
    "pro": {
        "nome": "Pro",
        "preco": 49.99,
        "avaliacoes_mes": 200,
        "hiper_dia": 2,
        "consideracoes_dia": 2,
        "relatorio_pdf_mes": 1,
        "api": False,
        "dashboard": "completo",
        "suporte": "prioritário",
        "marca_dagua": False,
    },
    "pro_anual": {
        "nome": "Pro Anual",
        "preco": 499.00,
        "avaliacoes_mes": 200,
        "hiper_dia": 2,
        "consideracoes_dia": 2,
        "relatorio_pdf_mes": 1,
        "api": False,
        "dashboard": "completo",
        "suporte": "prioritário",
        "marca_dagua": False,
        "anual": True,
    },
    "business": {
        "nome": "Business",
        "preco": 79.99,
        "avaliacoes_mes": None,
        "hiper_dia": None,
        "consideracoes_dia": None,
        "relatorio_pdf_mes": None,
        "api": True,
        "dashboard": "avançado",
        "suporte": "vip",
        "marca_dagua": False,
    },
    "business_anual": {
        "nome": "Business Anual",
        "preco": 799.00,
        "avaliacoes_mes": None,
        "hiper_dia": None,
        "consideracoes_dia": None,
        "relatorio_pdf_mes": None,
        "api": True,
        "dashboard": "avançado",
        "suporte": "vip",
        "marca_dagua": False,
        "anual": True,
    },
}

ADMIN_EMAILS = ["anderson.mendesdossantos011@gmail.com", "comentsia.2025@gmail.com"]
PLANO_EQUIVALENTES = {
    "pro": ["pro", "pro_anual"],
    "business": ["business", "business_anual"],
}

# -------------------------------------------------------------------
# OAuth Google (inalterado)
# -------------------------------------------------------------------
CLIENT_SECRETS_FILE = "/etc/secrets/client_secrets.json"
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/business.manage",
]
ACCOUNT_MGMT = ("mybusinessaccountmanagement", "v1")
BUSINESS_INFO = ("mybusinessbusinessinformation", "v1")
VERIFICATIONS = ("mybusinessverifications", "v1")


# -------------------------------------------------------------------
# Rate Limiter unificado (com fallback sem Redis)
# -------------------------------------------------------------------
def get_user_or_ip():
    user_info = session.get("user_info")
    if user_info and user_info.get("id"):
        return f"user:{user_info['id']}"
    return get_remote_address()


storage_uri = os.getenv("REDIS_URL", "memory://")
limiter = Limiter(
    key_func=get_user_or_ip,
    app=app,
    storage_uri=storage_uri,
    default_limits=["200 per day", "50 per hour"],
)


# -------------------------------------------------------------------
# Helpers iniciais
# -------------------------------------------------------------------
def agora_brt():
    return datetime.now(pytz.timezone("America/Sao_Paulo"))


def analisar_pontos_mais_mencionados(comentarios):
    if not comentarios:
        return []
    palavras = " ".join(comentarios).split()
    contagem = Counter(palavras)
    stop = {"a", "o", "de", "e", "que", "para", "em", "com", "na", "no"}
    contagem = {k: v for k, v in contagem.items() if k.lower() not in stop}
    return Counter(contagem).most_common(5)


def is_pro(user_id):
    return get_user_plan(user_id) in PLANO_EQUIVALENTES["pro"]


def is_business(user_id):
    return get_user_plan(user_id) in PLANO_EQUIVALENTES["business"]


def calcular_media(avaliacoes):
    return round(sum(avaliacoes) / len(avaliacoes), 2) if avaliacoes else 0.0


# --- HARDENED HELPERS (seguro e resiliente) ---


# Função para confirmar aceitação dos termos
def require_terms_accepted(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_info = session.get("user_info")
        if not user_info:
            return redirect(url_for("authorize"))
        user_id = user_info.get("id")
        settings = get_user_settings(user_id)
        # Se faltar algum campo obrigatório, manda para settings
        if not (
            settings.get("business_name")
            and settings.get("contact_info")
            and settings.get("terms_accepted", False)
        ):
            flash(
                "Complete seu cadastro inicial e aceite os Termos e Condições para acessar esta funcionalidade.",
                "warning",
            )
            return redirect(url_for("settings"))
        return f(*args, **kwargs)

    return decorated_function


def contar_avaliacoes_mes(user_id):
    inicio_mes = agora_brt().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return Review.query.filter(
        Review.user_id == user_id, Review.date >= inicio_mes
    ).count()


def contar_relatorios_mes(user_id):
    inicio_mes = agora_brt().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return RelatorioHistorico.query.filter(
        RelatorioHistorico.user_id == user_id,
        RelatorioHistorico.data_criacao >= inicio_mes,
    ).count()


def get_data_hoje_brt():
    """Retorna a data atual no fuso de São Paulo (sem hora)."""
    return datetime.now(pytz.timezone("America/Sao_Paulo")).date()


def usuario_pode_usar_resposta_especial(user_id):
    hoje = get_data_hoje_brt()
    plano = get_user_plan(user_id)
    hiper_limite = PLANOS.get(plano, {}).get("hiper_dia")
    if hiper_limite is None:
        return True  # Ilimitado no Business
    uso = RespostaEspecialUso.query.filter_by(user_id=user_id, data_uso=hoje).first()
    return not uso or (uso.quantidade_usos or 0) < hiper_limite


def atingiu_limite_avaliacoes_mes(user_id):
    plano = get_user_plan(user_id)
    limite = PLANOS.get(plano, {}).get("avaliacoes_mes")
    if not limite:  # None = ilimitado ou 0/False
        return False
    inicio_mes = agora_brt().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    avals_mes = Review.query.filter(
        Review.user_id == user_id, Review.date >= inicio_mes
    ).count()
    return avals_mes >= limite


def registrar_uso_resposta_especial(user_id):
    hoje = get_data_hoje_brt()
    uso = RespostaEspecialUso.query.filter_by(user_id=user_id, data_uso=hoje).first()
    if not uso:
        uso = RespostaEspecialUso(user_id=user_id, data_uso=hoje, quantidade_usos=1)
        db.session.add(uso)
    else:
        uso.quantidade_usos = (uso.quantidade_usos or 0) + 1
    db.session.commit()


def _tz_aware_compare(dt):
    """Garante comparação consistente com agora_brt() mesmo se dt vier sem tz."""
    if not dt:
        return None
    now = agora_brt()
    if dt.tzinfo is None:
        # força mesmo fuso para evitar comparação naive/aware
        return dt.replace(tzinfo=now.tzinfo)
    return dt


def get_user_plan(user_id):
    """Retorna o plano atual; se vencido e não for 'free', rebaixa para 'free' e persiste."""
    settings = UserSettings.query.filter_by(user_id=user_id).first()
    if not settings:
        return "free"

    plano = settings.plano if settings.plano in PLANOS else "free"
    if plano != "free":
        plano_ate = _tz_aware_compare(settings.plano_ate)
        if plano_ate and plano_ate < agora_brt():
            # expirada: rebaixa para free e salva
            settings.plano = "free"
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                logging.warning(f"[plan] falha ao persistir rebaixamento de plano: {e}")
            return "free"
    return plano


def get_plan_limits(user_id):
    plano = get_user_plan(user_id)
    return PLANOS.get(plano, PLANOS["free"])


def plano_ativo(user_id):
    """
    True se o usuário possui um plano ativo (não expirado).
    'free' é sempre considerado ativo.
    """
    settings = UserSettings.query.filter_by(user_id=user_id).first()
    if not settings:
        return False

    plano = settings.plano if settings.plano in PLANOS else "free"
    if plano == "free":
        return True

    plano_ate = _tz_aware_compare(settings.plano_ate)
    if not plano_ate:
        return False
    return plano_ate >= agora_brt()


def require_plano_ativo(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_info = session.get("user_info", {})
        user_id = user_info.get("id")
        if not user_id or not plano_ativo(user_id):
            flash("Seu plano venceu! Renove para continuar usando.", "warning")
            return redirect(url_for("planos"))
        return f(*args, **kwargs)

    return decorated_function


# Projeção de nota para 30 dias (defensivo contra NaN/erros)
def calcular_projecao(notas, datas):
    try:
        if datas and len(datas) > 1:
            primeira_data = min(datas)
            # evita datas None
            base = [d for d in datas if d is not None]
            if not base:
                return calcular_media(notas)
            x = np.array([(d - primeira_data).days for d in base], dtype=float).reshape(
                -1, 1
            )
            y = np.array(notas, dtype=float)

            # sanity check
            if x.size == 0 or y.size == 0 or np.isnan(y).any():
                return calcular_media(notas)

            coef = np.polyfit(x.flatten(), y, 1)
            projecao_dia = float(np.max(x)) + 30.0
            projecao_30_dias = float(coef[0]) * projecao_dia + float(coef[1])
            # clamp 0..5
            return max(0.0, min(5.0, projecao_30_dias))
    except Exception as e:
        logging.warning(f"[projection] falha na projeção: {e}")
    return calcular_media(notas)


def _build_services(credentials):
    acct_api = build(*ACCOUNT_MGMT, credentials=credentials)
    info_api = build(*BUSINESS_INFO, credentials=credentials)
    rev_api = build(*VERIFICATIONS, credentials=credentials)
    return acct_api, info_api, rev_api


def get_user_reviews(user_id):
    """Avaliações do usuário (mais recentes primeiro)."""
    return (
        Review.query.filter(Review.user_id == user_id).order_by(desc(Review.date)).all()
    )


def get_user_settings(user_id):
    """Configurações do usuário com defaults estáveis e descriptografia segura."""
    from utils.crypto import decrypt

    defaults = {
        "business_name": "",
        "default_greeting": "Olá,",
        "default_closing": "Agradecemos seu feedback!",
        "contact_info": "Entre em contato pelo telefone (00) 0000-0000 ou email@exemplo.com",
        "terms_accepted": False,
        "logo": None,
        "manager_name": "",
    }

    settings = UserSettings.query.filter_by(user_id=user_id).first()
    if not settings:
        return defaults

    try:
        return {
            "business_name": (
                decrypt(settings.business_name) if settings.business_name else ""
            ),
            "default_greeting": settings.default_greeting
            or defaults["default_greeting"],
            "default_closing": settings.default_closing or defaults["default_closing"],
            "contact_info": (
                decrypt(settings.contact_info)
                if settings.contact_info
                else defaults["contact_info"]
            ),
            "terms_accepted": bool(settings.terms_accepted),
            "logo": settings.logo,
            "manager_name": (
                decrypt(settings.manager_name) if settings.manager_name else ""
            ),
            "gbp_tone": settings.gbp_tone or "neutro", 
            "contexto_personalizado": settings.contexto_personalizado or "", # 👈 adicione esta linha
        }
    except Exception as e:
        logging.warning(
            f"[decrypt] erro ao descriptografar settings de user {user_id}: {e}"
        )
        return defaults


from flask_wtf import CSRFProtect
from markupsafe import escape

# Certifique-se de inicializar no setup do app:
# csrf = CSRFProtect(app)


def save_user_settings(user_id, settings_data):
    from utils.crypto import encrypt  # seguro no escopo

    # Normalizar checkbox/string em booleano
    terms_accepted_raw = settings_data.get("terms_accepted")
    terms_accepted = str(terms_accepted_raw).lower() in ["true", "on", "1"]

    # Criptografar campos sensíveis
    encrypted_name = encrypt(settings_data.get("business_name") or "")
    encrypted_contact = encrypt(settings_data.get("contact_info") or "")
    encrypted_manager = encrypt(settings_data.get("manager_name") or "")

    existing = UserSettings.query.filter_by(user_id=user_id).first()

    if existing:

        # Campos SEMPRE enviados
        existing.business_name = encrypted_name
        existing.default_greeting = settings_data.get("default_greeting", "Olá,")
        existing.default_closing = settings_data.get("default_closing", "Agradecemos seu feedback!")
        existing.contact_info = encrypted_contact
        existing.terms_accepted = terms_accepted
        existing.manager_name = encrypted_manager

        # Apenas atualiza SE o campo foi enviado no POST
        if "contexto_personalizado" in settings_data:
            existing.contexto_personalizado = (settings_data["contexto_personalizado"] or "")[:500]

        # Atualiza logo apenas se vier no POST
        if "logo" in settings_data and settings_data["logo"]:
            existing.logo = settings_data["logo"]

    else:
        new_settings = UserSettings(
            user_id=user_id,
            business_name=encrypted_name,
            default_greeting=settings_data.get("default_greeting", "Olá,"),
            default_closing=settings_data.get("default_closing", "Agradecemos seu feedback!"),
            contact_info=encrypted_contact,
            terms_accepted=terms_accepted,
            logo=settings_data.get("logo"),
            manager_name=encrypted_manager,
            contexto_personalizado=(settings_data.get("contexto_personalizado") or "")[:500],
        )
        db.session.add(new_settings)

    db.session.commit()



@app.route("/planos", methods=["GET", "POST"])
def planos():
    user_info = session.get("user_info", {})
    user_id = user_info.get("id") if user_info else None

    # Catálogo centralizado de planos (inclui preços para o template)
    catalog = (
        get_pricing_catalog()
    )  # ex.: {"free": {...}, "pro": {...}, "pro_anual": {...}, ...}

    if request.method == "POST":
        if not user_id:
            flash("Você precisa estar logado para alterar o plano.", "warning")
            return redirect(url_for("authorize"))

        novo_plano = (request.form.get("plano") or "").strip()

        # valida contra o catálogo vindo do admin.py
        if not novo_plano or novo_plano not in catalog:
            flash("Plano inválido.", "danger")
            return redirect(url_for("planos"))

        settings = UserSettings.query.filter_by(user_id=user_id).first()
        if not settings:
            flash("Configurações do usuário não encontradas.", "danger")
            return redirect(url_for("planos"))

        if settings.plano == novo_plano:
            flash(f"Você já está no plano {get_plan_display_name(novo_plano)}.", "info")
            return redirect(url_for("planos"))

        # aplica o novo plano
        settings.plano = novo_plano

        # validade centralizada (0 = sem validade para 'free')
        dias_validade = get_plan_duration_days(novo_plano)
        settings.plano_ate = (
            None if dias_validade == 0 else agora_brt() + timedelta(days=dias_validade)
        )

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash("Erro ao salvar alterações. Tente novamente.", "danger")
            return redirect(url_for("planos"))

        flash(
            f"Plano alterado para {get_plan_display_name(novo_plano)} com sucesso!",
            "success",
        )
        return redirect(url_for("index"))

    # GET
    user_plano = get_user_plan(user_id) if user_id else "free"

    # Passa o catálogo completo (com preços centralizados) para o template
    # Cada item do catalog deve ter, por exemplo:
    #   {"nome": "Pro", "period": "monthly", "price_cents": 9900, "features": {...}, ...}
    return render_template(
        "planos.html",
        planos=catalog,
        user_plano=user_plano,
    )


# main.py (Adicione esta função, por exemplo, após calcular_projecao)

# ... (restante dos helpers)


def calcular_metricas_reviews(reviews: list) -> dict:
    """
    Calcula as métricas chave (KPIs) com base em uma lista de objetos Review.
    """
    total = len(reviews)
    if total == 0:
        return {
            "total": 0,
            "respondidas": 0,
            "pendentes": 0,
            "media": "0.0",
            "percent_respondidas": "0.0",
        }

    responded = 0
    ratings = []

    for review in reviews:
        if getattr(review, "replied", False):
            responded += 1

        # Coleta apenas ratings numéricos válidos
        rating_value = getattr(review, "rating", None)
        if rating_value is not None:
            try:
                ratings.append(float(rating_value))
            except (ValueError, TypeError):
                pass

    pendentes = total - responded

    # Média robusta (arredondada para 1 casa decimal para exibição)
    total_validos = len(ratings)
    avg_rating = round(sum(ratings) / total_validos, 1) if total_validos > 0 else 0.0

    # Porcentagem de respondidas
    percent_respondidas = round((responded / total) * 100, 1) if total > 0 else 0.0

    return {
        "total": total,
        "respondidas": responded,
        "pendentes": pendentes,
        "media": f"{avg_rating:.1f}",  # Formato string para 1 casa decimal
        "percent_respondidas": f"{percent_respondidas:.1f}",
    }


@app.route("/")
def index():
    """Página inicial do aplicativo com resumo das avaliações."""
    if "credentials" not in flask.session:
        return render_template("index.html", logged_in=False, now=datetime.now())

    user_info = flask.session.get("user_info") or {}
    user_id = user_info.get("id")
    if not user_id:
        # Sessão estranha: força sair
        return redirect(url_for("logout"))

    # Buscar configurações do usuário
    user_settings = get_user_settings(user_id)

    # Verificar preenchimento obrigatório + termos
    if (
        not user_settings.get("business_name")
        or not user_settings.get("contact_info")
        or not user_settings.get("terms_accepted", False)
    ):
        return redirect(url_for("settings"))

    user_reviews = get_user_reviews(user_id)

    # (mantém fluxo/variáveis caso o template use)
    total_reviews = len(user_reviews)
    responded_reviews = sum(1 for review in user_reviews if review.replied)
    pending_reviews = total_reviews - responded_reviews
    avg_rating = (
        round(sum((r.rating or 0) for r in user_reviews) / total_reviews, 1)
        if total_reviews
        else 0.0
    )

    return render_template(
        "index.html",
        logged_in=True,
        user=user_info,
        now=datetime.now(),
        reviews=user_reviews,
        # se o template usar:
        total_reviews=total_reviews,
        responded_reviews=responded_reviews,
        pending_reviews=pending_reviews,
        avg_rating=avg_rating,
    )


@app.route("/get_avaliacoes_count")
def get_avaliacoes_count():
    user_info = session.get("user_info") or {}
    user_id = user_info.get("id")
    if not user_id:
        return jsonify(success=False, error="Usuário não autenticado")

    count = max(0, contar_avaliacoes_mes(user_id))
    plano = get_user_plan(user_id)
    limite = PLANOS.get(plano, {}).get("avaliacoes_mes", 0)
    # None = ilimitado
    restantes = None if limite is None else max(0, limite - count)

    return jsonify(success=True, usados=count, restantes=restantes)


@app.route("/get_relatorios_count")
def get_relatorios_count():
    user_info = session.get("user_info") or {}
    user_id = user_info.get("id")
    if not user_id:
        return jsonify(success=False, error="Usuário não autenticado")

    count = max(0, contar_relatorios_mes(user_id))
    plano = get_user_plan(user_id)
    limite = PLANOS.get(plano, {}).get("relatorio_pdf_mes", 0)
    restantes = None if limite is None else max(0, limite - count)

    return jsonify(success=True, usados=count, restantes=restantes)


@app.errorhandler(429)
def ratelimit_handler(e):
    if (
        request.accept_mimetypes.accept_json
        and not request.accept_mimetypes.accept_html
    ):
        return (
            jsonify(
                error="Você está fazendo requisições rápidas demais. Tente novamente em instantes."
            ),
            429,
        )

    flash(
        "Você está fazendo ações rápidas demais. Aguarde um pouco e tente novamente.",
        "warning",
    )
    # Evita redirect em cascata se não houver referrer
    destino = request.referrer
    if not destino:
        destino = url_for("index")
    return redirect(destino), 429


@app.context_processor
def inject_can():
    def can(perm: str, mode: str = "read") -> bool:
        """Usa a sessão para checar se o usuário atual possui a permissão."""
        uid = (session.get("user_info") or {}).get("id")
        if not uid:
            return False
        try:
            return user_can(uid, perm, mode)
        except Exception:
            return False

    return dict(can=can)


from flask import session, url_for


@app.context_processor
def inject_admin_nav():
    uid = (session.get("user_info") or {}).get("id")
    links = []
    if uid:

        def add_link(perm, mode, url, icon, label):
            try:
                if user_can(uid, perm, mode):
                    links.append({"url": url, "icon": icon, "label": label})
            except Exception:
                pass

        # mapeie aqui suas telas ↔ permissões
        add_link(
            "dashboard.view",
            "read",
            url_for("admin.dashboard"),
            "bi-speedometer2",
            "Dashboard",
        )  # NOVO
        add_link(
            "tickets.view",
            "read",
            url_for("admin.tickets_board"),
            "bi-life-preserver",
            "Tickets",
        )
        add_link(
            "finance.view",
            "read",
            url_for("admin.dashboard"),
            "bi-cash-coin",
            "Financeiro",
        )
        add_link(
            "emails.view",
            "read",
            url_for("admin.broadcast"),
            "bi-megaphone",
            "Disparo de E-mails",
        )
        add_link(
            "access.manage_roles",
            "write",
            url_for("admin.access"),
            "bi-people-gear",
            "Papéis & Permissões",
        )
        add_link("pricing.view", "read", url_for("admin.pricing"), "bi-tags", "Pricing")
        add_link(
            "coupons.view",
            "read",
            url_for("admin.coupons"),
            "bi-ticket-perforated",
            "Cupons",
        )
        add_link(
            "finance.view",
            "read",
            url_for("admin.finance_items"),
            "bi-receipt",
            "Impostos & Custos",
        )

    # has_admin = True quando houver ao menos um link autorizado
    return dict(admin_links=links, has_admin=bool(links))


@app.context_processor
def inject_user_flags():
    user_info = session.get("user_info") or {}
    email = (user_info.get("email") or "").strip().lower()
    admin_emails_norm = [e.strip().lower() for e in ADMIN_EMAILS]
    is_admin = email in admin_emails_norm

    logged_in = ("credentials" in session) and bool(user_info.get("id"))

    # helpers para o template
    def is_pro_plan(plan: str) -> bool:
        return plan in PLANO_EQUIVALENTES.get("pro", [])

    def is_business_plan(plan: str) -> bool:
        return plan in PLANO_EQUIVALENTES.get("business", [])

    return dict(
        is_admin=is_admin,
        logged_in=logged_in,
        user=user_info,
        is_pro_plan=is_pro_plan,
        is_business_plan=is_business_plan,
    )


@app.route("/debug_historico")
def debug_historico():
    user_info = session.get("user_info") or {}
    email = (user_info.get("email") or "").strip().lower()
    # Somente seu e-mail (ou poderia usar is_admin)
    if email != "comentsia.2025@gmail.com":
        return "Acesso negado", 403

    historicos = RelatorioHistorico.query.order_by(RelatorioHistorico.id.desc()).all()
    # Retorna texto simples (mais seguro) — mantém funcionalidade
    linhas = [
        f"ID={h.id} | user={h.user_id} | nome={h.nome_arquivo} | criado={h.data_criacao}"
        for h in historicos
    ]
    return "\n".join(linhas), 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.route("/admin")
def admin_dashboard():
    user_info = session.get("user_info") or {}
    email = (user_info.get("email") or "").strip().lower()
    if email not in [e.strip().lower() for e in ADMIN_EMAILS]:
        flash("Acesso restrito ao administrador.", "danger")
        return redirect(url_for("index"))

    try:
        total_usuarios = UserSettings.query.count()
        total_avaliacoes = Review.query.count()
        total_respostas = Review.query.filter(Review.reply != "").count()
        total_relatorios = RelatorioHistorico.query.count()

        # date_trunc funciona no Postgres; se usar SQLite local, trate fallback
        usuarios_query = (
            db.session.query(
                db.func.date_trunc("month", UserSettings.created_at).label("mes"),
                db.func.count(UserSettings.id),
            )
            .filter(UserSettings.created_at != None)
            .group_by("mes")
            .order_by("mes")
            .all()
        )
        meses = [mes.strftime("%m/%Y") for mes, _ in usuarios_query]
        qtds = [qtd for _, qtd in usuarios_query]
        usuarios_por_mes = {"meses": meses, "qtds": qtds}

        top_empresas = (
            db.session.query(UserSettings.business_name, db.func.count(Review.id))
            .join(Review, UserSettings.user_id == Review.user_id)
            .group_by(UserSettings.business_name)
            .order_by(db.func.count(Review.id).desc())
            .limit(5)
            .all()
        )

    except Exception:
        # Não vaza erro, mantém painel acessível sem dados agregados
        total_usuarios = total_avaliacoes = total_respostas = total_relatorios = 0
        usuarios_por_mes = {"meses": [], "qtds": []}
        top_empresas = []
        flash("Não foi possível carregar todas as métricas agora.", "warning")

    return render_template(
        "admin_dashboard.html",
        total_usuarios=total_usuarios,
        total_avaliacoes=total_avaliacoes,
        total_respostas=total_respostas,
        total_relatorios=total_relatorios,
        top_empresas=top_empresas,
        usuarios_por_mes=usuarios_por_mes,
        now=datetime.now(),
    )


@app.route("/privacy-policy")
def privacy_policy():
    return render_template("privacy-policy.html")


@app.route("/quem-somos")
def quem_somos():
    return render_template("quem-somos.html")


from math import isnan


def get_current_user_id():
    return (session.get("user_info") or {}).get("id")


# main.py

# IMPORTANTE: Garanta que a função calcular_metricas_reviews(reviews)
# e as funções auxiliares (como get_user_reviews, get_user_plan, etc.)
# estejam definidas ANTES desta função.


@app.route("/relatorio", methods=["GET", "POST"])
@require_terms_accepted
@require_plano_ativo
@limiter.limit("5/minute")
def gerar_relatorio():
    # --- 1. AUTENTICAÇÃO E VARIÁVEIS ESSENCIAIS (Definidas ANTES de qualquer GET/POST) ---

    # Autenticação e obtenção do user_id
    if "credentials" not in flask.session:
        flash("Você precisa estar logado para gerar o relatório.", "warning")
        return redirect(url_for("authorize"))

    user_info = flask.session.get("user_info") or {}
    user_id = user_info.get("id")
    if not user_id:
        flash("Sessão inválida. Faça login novamente.", "warning")
        return redirect(url_for("logout"))

    # Configurações e Plano
    user_settings = get_user_settings(user_id)
    plano = get_user_plan(user_id)
    relatorio_limite = PLANOS.get(plano, {}).get("relatorio_pdf_mes", 0)

    # Cálculo do limite (necessário para o GET e POST)
    limite_atingido = False
    if relatorio_limite is not None and relatorio_limite > 0:
        inicio_mes = agora_brt().replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        rels_mes = RelatorioHistorico.query.filter(
            RelatorioHistorico.user_id == user_id,
            RelatorioHistorico.data_criacao >= inicio_mes,
        ).count()
        if rels_mes >= relatorio_limite:
            limite_atingido = True

    logging.debug("[RELATÓRIO] user_id=%s, plano=%s", user_id, plano)

    # --- 2. MÉTODO GET (VISUALIZAÇÃO DA PÁGINA) ---
    if request.method == "GET":
        # 1. Busca os dados brutos (Reviews)
        user_reviews = get_user_reviews(user_id)

        # 2. Calcula as métricas
        # ASSUMINDO que calcular_metricas_reviews está definida
        metrics = calcular_metricas_reviews(user_reviews)

        return render_template(
            "relatorio.html",
            PLANOS=PLANOS,
            user_plano=plano,
            user_settings=user_settings,
            reviews=user_reviews,
            metrics=metrics,
            limite_relatorio_atingido=limite_atingido,
        )

    # --- 3. MÉTODO POST (GERAÇÃO DE PDF) ---
    # O código abaixo é executado APENAS se request.method == "POST"

    # Validação do limite/plano
    if relatorio_limite == 0:
        flash(
            "Baixar relatórios em PDF está disponível apenas no plano PRO ou superior.",
            "warning",
        )
        return redirect(url_for("relatorio"))

    if limite_atingido:
        flash(
            f"Você já atingiu o limite mensal de download de relatórios em PDF do seu plano ({relatorio_limite} por mês).",
            "warning",
        )
        return redirect(url_for("relatorio"))

    # Filtros (com whitelists)
    periodo = (request.form.get("periodo") or "90dias").strip()
    nota = (request.form.get("nota") or "todas").strip()
    respondida = (request.form.get("respondida") or "todas").strip()

    PERIODOS_OK = {"90dias", "6meses", "1ano", "todas"}
    NOTAS_OK = {"todas", "1", "2", "3", "4", "5"}
    RESP_OK = {"todas", "sim", "nao"}

    if periodo not in PERIODOS_OK or nota not in NOTAS_OK or respondida not in RESP_OK:
        flash("Parâmetros de filtro inválidos.", "danger")
        return redirect(url_for("relatorio"))

    logging.info(
        "[RELATÓRIO] Filtros: periodo=%s, nota=%s, respondida=%s",
        periodo,
        nota,
        respondida,
    )

    # Busca e normaliza timezone
    avaliacoes_query = Review.query.filter_by(user_id=user_id).all()
    logging.debug("[RELATÓRIO] Avaliações encontradas: %d", len(avaliacoes_query))

    avaliacoes = []
    agora = agora_brt()
    for av in avaliacoes_query:
        data_av = av.date
        if not data_av:
            continue

        if data_av.tzinfo is None:
            data_av = data_av.replace(tzinfo=agora.tzinfo)
        else:
            data_av = data_av.astimezone(agora.tzinfo)

        diff_days = (agora - data_av).days

        # Lógica de filtro re-aplicada (APENAS para o PDF)
        if nota != "todas" and str(av.rating) != nota:
            continue
        if respondida == "sim" and not av.replied:
            continue
        if respondida == "nao" and av.replied:
            continue
        if periodo == "90dias" and diff_days > 90:
            continue
        if periodo == "6meses" and diff_days > 180:
            continue
        if periodo == "1ano" and diff_days > 365:
            continue

        avaliacoes.append(
            {
                "data": data_av,
                "nota": av.rating,
                "texto": av.text or "",
                "respondida": 1 if av.replied else 0,
                "tags": getattr(av, "tags", "") or "",
            }
        )

    logging.debug("[RELATÓRIO] Avaliações após filtro: %d", len(avaliacoes))

    if not avaliacoes:
        flash("Nenhuma avaliação encontrada para os filtros escolhidos.", "info")
        return redirect(url_for("relatorio"))

    # Média robusta (cálculo de média para o corpo do PDF)
    notas = [
        a.get("nota") for a in avaliacoes if isinstance(a.get("nota"), (int, float))
    ]
    media_atual = calcular_media(notas) if notas else 0.0
    if isinstance(media_atual, float) and isnan(media_atual):
        media_atual = 0.0

    rel = RelatorioAvaliacoes(
        avaliacoes, media_atual=media_atual, settings=user_settings
    )

    nome_arquivo = f"relatorio_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
    br_tz = pytz.timezone("America/Sao_Paulo")
    data_criacao = datetime.now(br_tz)

    try:
        buffer = io.BytesIO()
        rel.gerar_pdf(buffer)
        buffer.seek(0)
        pdf_bytes = buffer.getvalue()

        historico = RelatorioHistorico(
            user_id=user_id,
            filtro_periodo=periodo,
            filtro_nota=nota,
            filtro_respondida=respondida,
            nome_arquivo=nome_arquivo,
            arquivo_pdf=pdf_bytes,
            data_criacao=data_criacao,
        )
        db.session.add(historico)
        db.session.commit()
        logging.info(
            "[RELATÓRIO] Histórico salvo ID=%s arquivo=%s", historico.id, nome_arquivo
        )

        # Download
        return send_file(
            io.BytesIO(pdf_bytes),
            as_attachment=True,
            download_name=nome_arquivo,
            mimetype="application/pdf",
        )
    except Exception as e:
        db.session.rollback()
        logging.exception("ERRO AO GERAR/ENVIAR PDF")
        flash("Erro ao gerar o relatório. Tente novamente em instantes.", "danger")
        return redirect(url_for("index"))


@app.route("/delete_account", methods=["POST"])
@require_terms_accepted
@limiter.limit("3/minute")
def delete_account():
    if "credentials" not in session:
        return jsonify({"success": False, "error": "Você precisa estar logado."})

    user_info = session.get("user_info") or {}
    user_id = user_info.get("id")
    email_destino = (user_info.get("email") or "").strip()

    if not user_id:
        return jsonify({"success": False, "error": "Sessão inválida."})

    # Opcional: confirme intenção (mantive fluxo sem exigir confirmação)
    # if request.form.get("confirm") != "yes": ...

    # Tenta enviar o e-mail ANTES, mas não bloqueia exclusão se falhar
    try:
        if email_destino:
            html = montar_email_conta_apagada(user_info.get("name") or email_destino)
            enviar_email(
                destinatario=email_destino,
                assunto="Sua conta no ComentsIA foi excluída",
                corpo_html=html,
            )
            logging.info(
                "Delete account: e-mail de exclusão emitido para %s", email_destino
            )
    except Exception:
        logging.warning(
            "Falha ao enviar e-mail de exclusão para %s", email_destino, exc_info=True
        )

    # Deleta dados do usuário (somente do próprio user_id da sessão)
    try:
        Review.query.filter_by(user_id=user_id).delete()
        UserSettings.query.filter_by(user_id=user_id).delete()
        RelatorioHistorico.query.filter_by(user_id=user_id).delete()
        db.session.commit()
    except Exception:
        db.session.rollback()
        logging.exception("Falha ao excluir dados do usuário %s", user_id)
        return jsonify(
            {
                "success": False,
                "error": "Não foi possível concluir a exclusão. Tente novamente.",
            }
        )

    # Limpa sessão
    session.clear()
    return jsonify({"success": True})


@app.route("/historico_relatorios")
@require_terms_accepted
def historico_relatorios():
    if "credentials" not in flask.session:
        return redirect(url_for("authorize"))

    user_info = flask.session.get("user_info") or {}
    user_id = user_info.get("id")
    if not user_id:
        flash("Sessão inválida. Faça login novamente.", "warning")
        return redirect(url_for("logout"))

    brt = pytz.timezone("America/Sao_Paulo")
    historicos = (
        RelatorioHistorico.query.filter_by(user_id=user_id)
        .order_by(RelatorioHistorico.id.desc())
        .all()
    )

    # Atributos temporários para o template
    for rel in historicos:
        try:
            dt = rel.data_criacao
            if dt and dt.tzinfo is None:
                dt = dt.replace(tzinfo=brt)
            else:
                dt = dt.astimezone(brt) if dt else None
            rel.data_criacao_local = dt.strftime("%d/%m/%Y") if dt else ""
        except Exception:
            rel.data_criacao_local = ""
        rel.numero = rel.id

    return render_template("historico_relatorios.html", historicos=historicos)


from werkzeug.exceptions import NotFound


@app.route("/download_relatorio/<int:relatorio_id>")
@limiter.limit("10/minute")
def download_relatorio(relatorio_id: int):
    try:
        relatorio = RelatorioHistorico.query.get_or_404(relatorio_id)
    except NotFound:
        flash("Relatório não encontrado.", "danger")
        return redirect(url_for("historico_relatorios"))

    user_info = session.get("user_info") or {}
    if not user_info or relatorio.user_id != user_info.get("id"):
        flash("Acesso negado.", "danger")
        return redirect(url_for("historico_relatorios"))

    pdf = relatorio.arquivo_pdf
    if not pdf:
        flash("Arquivo não encontrado.", "danger")
        return redirect(url_for("historico_relatorios"))

    filename = (relatorio.nome_arquivo or f"relatorio_{relatorio.id}.pdf").strip()
    if not filename.lower().endswith(".pdf"):
        filename += ".pdf"

    # send_file já define headers de download; BytesIO evita tocar disco
    return send_file(
        io.BytesIO(pdf),
        as_attachment=True,
        download_name=filename,
        mimetype="application/pdf",
        max_age=0,  # evita cache indesejado
        conditional=True,
        etag=True,
    )


@app.route("/deletar_relatorio/<int:relatorio_id>", methods=["POST"])
@limiter.limit("10/minute")
def deletar_relatorio(relatorio_id: int):
    try:
        relatorio = RelatorioHistorico.query.get_or_404(relatorio_id)
    except NotFound:
        flash("Relatório não encontrado.", "danger")
        return redirect(url_for("historico_relatorios"))

    user_info = session.get("user_info") or {}
    if not user_info or relatorio.user_id != user_info.get("id"):
        flash("Acesso negado.", "danger")
        return redirect(url_for("historico_relatorios"))

    try:
        db.session.delete(relatorio)
        db.session.commit()
        flash("Relatório excluído com sucesso.", "success")
    except Exception:
        db.session.rollback()
        logging.exception("Falha ao excluir relatório %s", relatorio_id)
        flash("Não foi possível excluir o relatório. Tente novamente.", "danger")

    return redirect(url_for("historico_relatorios"))


@app.route("/robots.txt")
def robots():
    return app.send_static_file("robots.txt")


@app.route("/sitemap.xml")
def sitemap():
    return app.send_static_file("sitemap.xml")


@app.route("/terms", methods=["GET", "POST"])
def terms():
    if request.method == "POST":
        user_info = flask.session.get("user_info") or {}
        user_id = user_info.get("id")
        if not user_id:
            flash("Sessão expirada. Faça login novamente.", "warning")
            return redirect(url_for("authorize"))

        terms_accepted = request.form.get("terms_accepted")
        if not terms_accepted:
            flash(
                "Você precisa aceitar os Termos e Condições para continuar.", "warning"
            )
            return redirect(url_for("terms"))

        try:
            settings_data = get_user_settings(user_id)
            settings_data["terms_accepted"] = True
            save_user_settings(user_id, settings_data)
            session["terms_accepted"] = True
        except Exception:
            logging.exception("Falha ao salvar aceitação de termos para %s", user_id)
            flash(
                "Não foi possível registrar sua aceitação agora. Tente novamente.",
                "danger",
            )
            return redirect(url_for("terms"))

        return redirect(url_for("settings"))

    # GET
    user_info = flask.session.get("user_info") or {}
    user_name = user_info.get("name") or "Usuário"
    user_email = user_info.get("email") or "Email não informado"

    # Estes campos de empresa não existem na sessão por padrão; mantive fallback
    company_name = user_info.get("business_name") or "Nome da Empresa Não Informado"
    company_email = user_info.get("business_email") or "E-mail Não Informado"

    current_date = datetime.now().strftime("%d/%m/%Y")
    return render_template(
        "terms.html",
        user_name=user_name,
        user_email=user_email,
        company_name=company_name,
        company_email=company_email,
        current_date=current_date,
    )


@app.route("/authorize")
@limiter.limit("15/minute")
def authorize():
    try:
        redirect_uri = url_for("oauth2callback", _external=True)
        flow = build_flow(redirect_uri=redirect_uri)
        # 👇 aqui é onde forçamos sempre gerar novo refresh_token
        authorization_url, state = flow.authorization_url(
            access_type="offline",            # pede refresh_token
            include_granted_scopes="true",    # mantém escopos já concedidos
            prompt="consent"                  # força reconsentimento
        )
        session["state"] = state
        return redirect(authorization_url)
    except Exception:
        logging.exception("Falha ao iniciar OAuth")
        flash("Não foi possível iniciar o login no momento. Tente novamente.", "danger")
        return redirect(url_for("index"))


@app.template_filter("initial")
def initial_filter(value):
    s = (value or "").strip()
    return s[0].upper() if s else "C"  # "C" de Cliente


@app.route("/delete_review", methods=["POST"])
@limiter.limit("20/minute")
def delete_review():
    if "credentials" not in flask.session:
        return jsonify({"success": False, "error": "Usuário não autenticado"})

    user_info = flask.session.get("user_info") or {}
    user_id = user_info.get("id")
    if not user_id:
        return jsonify({"success": False, "error": "Usuário não identificado"})

    data = request.get_json(silent=True) or {}
    review_id = data.get("review_id")
    try:
        review_id = int(review_id)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "ID da avaliação inválido"})

    review = Review.query.filter_by(id=review_id, user_id=user_id).first()
    if not review:
        return jsonify({"success": False, "error": "Avaliação não encontrada"})

    try:
        db.session.delete(review)
        db.session.commit()
        return jsonify({"success": True})
    except Exception:
        db.session.rollback()
        logging.exception("Falha ao deletar review %s do user %s", review_id, user_id)
        return jsonify({"success": False, "error": "Erro ao excluir avaliação"})


# Deleta respostas
# main.py


@app.route("/delete_reply", methods=["POST"])
@limiter.limit("30/minute")
def delete_reply():
    user_info = flask.session.get("user_info") or {}
    user_id = user_info.get("id")
    if not user_id:
        return jsonify({"success": False, "error": "Usuário não identificado"}), 401

    data = request.get_json(silent=True) or {}
    review_id = data.get("review_id")
    try:
        review_id = int(review_id)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "ID da avaliação inválido"}), 400

    review = Review.query.filter_by(id=review_id, user_id=user_id).first()
    if not review:
        return jsonify({"success": False, "error": "Avaliação não encontrada"}), 404

    # 🚨 LÓGICA PRINCIPAL: Tentar excluir no Google PRIMEIRO

    # Verifica se é uma review sincronizada do Google e se já tem resposta
    if review.source == "google" and review.external_id and review.replied:

        # NOTE: Assumimos que gbp_excluir_resposta está disponível e recebe o user_id e external_id
        from google_auto import gbp_excluir_resposta

        logging.info(
            "Tentando deletar resposta no Google para review %s", review.external_id
        )

        try:
            excluido_no_google = gbp_excluir_resposta(user_id, review.external_id)
        except Exception:
            logging.exception("Erro ao chamar gbp_excluir_resposta")
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Erro interno ao tentar comunicação com Google.",
                    }
                ),
                500,
            )

        if not excluido_no_google:
            # Se a API do Google falhar (400, 403, etc.), não altera localmente.
            logging.warning(
                "Falha na exclusão da resposta do Google. Permissão negada ou erro de API."
            )
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Falha na exclusão no Google Business Profile (GBP). Verifique as permissões da conta.",
                    }
                ),
                500,
            )

    review.reply = ""
    review.replied = False

    try:
        db.session.commit()
        logging.info("Resposta localmente excluída para review %s", review_id)
        return jsonify({"success": True, "message": "Resposta excluída com sucesso."})
    except Exception:
        db.session.rollback()
        logging.exception("delete_reply: erro ao persistir exclusão localmente")
        return (
            jsonify(
                {"success": False, "error": "Erro ao limpar a resposta localmente."}
            ),
            500,
        )


@app.route("/suggest_reply", methods=["POST"])
@limiter.limit("15/minute")
def suggest_reply():
    if "credentials" not in flask.session:
        return jsonify({"success": False, "error": "Usuário não autenticado"})

    user_info = flask.session.get("user_info") or {}
    user_id = user_info.get("id")
    if not user_id:
        return jsonify({"success": False, "error": "Usuário não identificado"})

    data = request.get_json(silent=True) or {}
    review_text = (data.get("review_text") or "").strip()
    reviewer_name = (data.get("reviewer_name") or "Cliente").strip()
    tone = (data.get("tone") or "profissional").strip().lower()

    # rating seguro (1..5)
    try:
        star_rating = int(data.get("star_rating", 5))
    except (TypeError, ValueError):
        star_rating = 5
    star_rating = max(1, min(5, star_rating))

    if not review_text:
        return jsonify({"success": False, "error": "Texto da avaliação não fornecido"})

    # limitar tamanho para evitar prompt injection gigante / custos
    MAX_LEN = 2000
    if len(review_text) > MAX_LEN:
        review_text = review_text[:MAX_LEN]

    # Buscar configurações do usuário do banco de dados
    settings = get_user_settings(user_id)

    TONE_OK = {
        "profissional": "Use linguagem formal e respeitosa.",
        "amigavel": "Use uma linguagem calorosa, sutilmente informal e amigável.",
        "empatico": "Demonstre empatia e compreensão genuína.",
        "entusiasmado": "Use uma linguagem animada e positiva.",
        "formal": "Use uma linguagem formal e estruturada.",
    }
    tone_instruction = TONE_OK.get(tone, TONE_OK["profissional"])

    manager = (settings.get("manager_name") or "").strip()
    business = (settings.get("business_name") or "").strip()
    assinatura = f"{business}\n{manager}" if manager else business

    # 1. 📝 INICIALIZAÇÃO E INCLUSÃO DO CONTEXTO PERSONALIZADO (CMNTS)
    prompt = "" # Inicializa a variável prompt
    
    if settings.get("contexto_personalizado"):
        contexto = settings["contexto_personalizado"].strip()
        prompt += "####\n"
        prompt += "🚨 INSTRUÇÃO CRÍTICA (CONTEXTO DA EMPRESA - CMNTS):\n"
        prompt += "VOCÊ DEVE USAR ESTA INFORMAÇÃO COM PRIORIDADE ABSOLUTA. ELA DEFINE O TOM (INFORMAL) E O ALCANCE DOS SERVIÇOS (SOMENTE PEÇAS/NÃO MANUTENÇÃO).\n"
        prompt += f"CONTEXTO ESPECÍFICO: {contexto}\n"
        prompt += "####\n\n"
        # Adiciona o contexto e uma instrução forte para a IA
        prompt += f"INSTRUÇÃO CRÍTICA: O contexto da empresa abaixo é PRIORIDADE MÁXIMA na personalização da resposta.\nContexto da empresa: {contexto}\n\n"
    
    # 2. 📝 Adiciona o restante das instruções e dados
    prompt += f"""
Você é um assistente especializado em atendimento ao cliente e deve escrever uma resposta personalizada para uma avaliação recebida por "{business}".

Avaliação recebida:
- Nome do cliente: {reviewer_name}
- Nota: {star_rating} estrelas
- Texto: "{review_text}"

Instruções:
- Comece com: "{settings['default_greeting']} {reviewer_name},"
- Siga este tom: {tone_instruction}
- Comente os pontos mencionados, usando palavras diferentes
- Se a nota for de 1 a 3, demonstre empatia, peça desculpas e ofereça uma solução
- Se a nota for de 4 ou 5, agradeça e convide para retornar
- Finalize com: "{settings['default_closing']}"
- Inclua as informações de contato: "{settings['contact_info']}"
- Assine ao final exatamente assim, cada item em uma linha:
{assinatura}
- Não use cargos, não use "Atenciosamente", apenas os nomes.
- A resposta deve ter entre 3 e 5 frases, ser personalizada e evitar frases genéricas, trevessao ou cacteres especiais, deve ser a mais proxima de uma escrita Humana possivel.
"""

    try:
        completion = client.with_options(timeout=30.0).chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "Você é um assistente cordial, objetivo e empático para atendimento ao cliente.",
                },
                {"role": "user", "content": prompt},
            ],
        )
        suggested_reply = (completion.choices[0].message.content or "").strip()
        if not suggested_reply:
            return jsonify(
                {"success": False, "error": "Não foi possível gerar a resposta agora."}
            )
        return jsonify({"success": True, "suggested_reply": suggested_reply})
    except Exception:
        logging.exception("Erro na API OpenAI em suggest_reply")
        return jsonify(
            {
                "success": False,
                "error": "Erro ao gerar a resposta. Tente novamente mais tarde.",
            }
        )


@app.template_filter("formatar_data_brt")
def formatar_data_brt(data):
    try:
        if not data:
            return ""
        fuso = pytz.timezone("America/Sao_Paulo")
        # Se vier naive, assume que já é BRT; se tiver tz, converte
        if getattr(data, "tzinfo", None) is None:
            data = data.replace(tzinfo=fuso)
        else:
            data = data.astimezone(fuso)
        return data.strftime("%d/%m/%Y às %H:%M")
    except Exception:
        logging.exception("Falha ao formatar data: %r", data)
        return ""


@app.route("/get_hiper_count")
@limiter.limit("10 per minute")
def get_hiper_count():
    if "credentials" not in session:
        return jsonify(success=False, error="Não autenticado.")

    user_info = session.get("user_info") or {}
    user_id = user_info.get("id")
    if not user_id:
        return jsonify(success=False, error="Usuário não identificado.")

    plano = get_user_plan(user_id)
    try:
        hiper_limite = PLANOS.get(plano, {}).get("hiper_dia")
        # None = ilimitado; para o widget, trate como 0 restantes = “não aplicável”
        if hiper_limite is None:
            return jsonify(success=True, usos_restantes_hiper=None)

        usos_hoje = RespostaEspecialUso.query.filter_by(
            user_id=user_id, data_uso=get_data_hoje_brt()
        ).first()

        usados = usos_hoje.quantidade_usos if usos_hoje else 0
        restantes = max(0, int(hiper_limite) - int(usados))
        return jsonify(success=True, usos_restantes_hiper=restantes)
    except Exception:
        logging.exception("Erro ao calcular hiper_count para %s", user_id)
        return jsonify(success=False, error="Falha ao obter contagem.")


@app.template_filter("b64encode")
def b64encode_filter(data):
    try:
        if not data:
            return ""
        return Markup(base64.b64encode(data).decode("utf-8"))
    except Exception:
        logging.exception(
            "Falha ao b64encode dados (len=%s)", getattr(data, "__len__", lambda: "?")()
        )
        return ""


def usuario_pode_usar_consideracoes(user_id):
    hoje = get_data_hoje_brt()
    plano = get_user_plan(user_id)
    cons_limite = PLANOS.get(plano, {}).get("consideracoes_dia")
    if cons_limite is None:
        return True  # ilimitado
    uso = ConsideracoesUso.query.filter_by(user_id=user_id, data_uso=hoje).first()
    usados = uso.quantidade_usos if uso else 0
    try:
        return usados < int(cons_limite)
    except Exception:
        logging.exception("Valor inválido para consideracoes_dia em plano %s", plano)
        return False


def registrar_uso_consideracoes(user_id):
    hoje = get_data_hoje_brt()
    uso = ConsideracoesUso.query.filter_by(user_id=user_id, data_uso=hoje).first()
    try:
        if not uso:
            uso = ConsideracoesUso(user_id=user_id, data_uso=hoje, quantidade_usos=1)
            db.session.add(uso)
        else:
            uso.quantidade_usos = int(uso.quantidade_usos or 0) + 1
        db.session.commit()
    except Exception:
        db.session.rollback()
        logging.exception("Falha ao registrar uso de considerações para %s", user_id)


@app.route("/oauth2callback")
@app.route("/oauth2callback")
def oauth2callback():
    # 1) Anti-CSRF / state
    session_state = session.get("state")
    req_state = request.args.get("state")
    if not session_state or session_state != req_state:
        flash("Sessão inválida. Por favor, inicie o login novamente.", "danger")
        return redirect(url_for("authorize"))

    redirect_uri = url_for("oauth2callback", _external=True)
    try:
        flow = build_flow(state=session_state, redirect_uri=redirect_uri)
    except Exception:
        logging.exception("Falha ao construir o fluxo OAuth")
        flash("Não foi possível iniciar o login. Tente novamente.", "danger")
        return redirect(url_for("authorize"))

    # 2) Troca código por token
    try:
        flow.fetch_token(authorization_response=request.url)
        credentials = flow.credentials
    except Exception as e:
        logging.exception("Erro ao obter token: %s", e)
        flash("Erro ao obter token. Tente novamente.", "danger")
        return redirect(url_for("authorize"))

    # Armazene só o necessário na sessão
    session["credentials"] = credentials_to_dict(credentials)

    # 3) Dados do usuário pelo Google People API
    try:
        user_info = get_user_info(credentials)
    except Exception as e:
        logging.exception("Erro ao obter informações do usuário: %s", e)
        flash("Erro ao obter dados do Google. Tente novamente.", "danger")
        return redirect(url_for("logout"))

    user_email = (user_info.get("email") or "").strip().lower()
    user_name = (user_info.get("name") or "").strip()
    user_picture = user_info.get("picture") or user_info.get("photo") or ""
    if not user_email:
        flash("Não foi possível obter seu e-mail do Google.", "danger")
        return redirect(url_for("logout"))

    user_id = user_email  # já normalizado
    logging.info("Usuário autenticado: %s", user_id)

    # Fortalece a sessão e garante o id
    user_info["id"] = user_id
    try:
        getattr(session, "cycle_key", lambda: None)()
    except Exception:
        pass
    session["user_info"] = user_info
    session.permanent = True

    # 4) GET-or-CREATE USER
    try:
        user = User.query.get(user_id)
        if not user:
            user = User(
                id=user_id,
                email=user_email,
                nome=user_name,
                foto_url=user_picture,
                criado_em=agora_brt(),
            )
            db.session.add(user)
            db.session.commit()
    except IntegrityError:
        db.session.rollback()
        user = User.query.get(user_id)
        if not user:
            logging.exception("IntegrityError e usuário ausente (%s)", user_id)
            flash("Problema ao criar usuário. Tente novamente.", "danger")
            return redirect(url_for("logout"))
    except SQLAlchemyError as e:
        db.session.rollback()
        logging.exception("Erro de banco ao registrar usuário: %s", e)
        flash("Erro interno ao registrar sua conta. Tente novamente.", "danger")
        return redirect(url_for("logout"))

    # 5) Configurações padrão + refresh_token
    try:
        settings = UserSettings.query.filter_by(user_id=user_id).first()
        if not settings:
            settings = UserSettings(user_id=user_id)
            settings.business_name = ""
            settings.default_greeting = "Olá,"
            settings.default_closing = "Agradecemos seu feedback!"
            settings.contact_info = (
                "Entre em contato pelo telefone (00) 0000-0000 ou email@exemplo.com"
            )
            db.session.add(settings)

        # ✅ salva o refresh_token se existir
        if credentials.refresh_token:
            settings.google_refresh_token = credentials.refresh_token

        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        logging.exception("Erro ao salvar configurações padrão/refresh_token: %s", e)
        flash("Erro interno ao preparar sua conta. Tente novamente.", "danger")
        return redirect(url_for("logout"))

    # 6) Done
    return redirect(url_for("reviews"))


def build_flow(state=None, redirect_uri=None):
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("Credenciais OAuth do Google ausentes.")

    client_config = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "redirect_uris": [
                redirect_uri or "https://comentsia.com.br/oauth2callback"
            ],
        }
    }

    return google_auth_oauthlib.flow.Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        state=state,
        redirect_uri=redirect_uri or "https://comentsia.com.br/oauth2callback",
    )


def ativar_ou_alterar_plano(user_id, novo_plano):
    settings = UserSettings.query.filter_by(user_id=user_id).first()
    if not settings:
        settings = UserSettings(user_id=user_id)
        db.session.add(settings)

    settings.plano = novo_plano
    dias_validade = 365 if str(novo_plano).endswith("_anual") else 30
    settings.plano_ate = agora_brt() + timedelta(days=dias_validade)

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        logging.exception("Falha ao ativar/alterar plano para %s", user_id)
        raise


def credentials_to_dict(credentials):
    """Converte credenciais em dict minimizado para sessão (sem client_secret)."""
    return {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "scopes": (
            list(credentials.scopes) if getattr(credentials, "scopes", None) else []
        ),
        # não armazenamos client_id/secret na sessão (estão no servidor via env)
        "expiry": (
            getattr(credentials, "expiry", None).isoformat()
            if getattr(credentials, "expiry", None)
            else None
        ),
    }


# --- helper: reatribui reviews do Booking que ficaram sem dono para o usuário atual ---
def claim_booking_anonymous_for(user_id: str) -> int:
    if not user_id:
        return 0
    q = Review.query.filter(
        (Review.source == "booking") & (Review.user_id.in_([None, "anonymous"]))
    )
    updated = q.update({Review.user_id: user_id}, synchronize_session=False)
    db.session.commit()
    return updated


def get_user_info(credentials):
    """
    Obtém informações do usuário via Google People API.
    """
    try:
        people_service = build("people", "v1", credentials=credentials)
        profile = (
            people_service.people()
            .get(resourceName="people/me", personFields="names,emailAddresses,photos")
            .execute()
        )

        email_addresses = profile.get("emailAddresses") or []
        if not email_addresses or not email_addresses[0].get("value"):
            raise ValueError("Não foi possível obter o e-mail do usuário.")

        user_email = email_addresses[0]["value"]
        name = (profile.get("names") or [{}])[0].get("displayName", "")
        photo_url = (profile.get("photos") or [{}])[0].get("url", "")

        return {
            "id": user_email,
            "email": user_email,
            "name": name,
            "photo": photo_url,
            "picture": photo_url,  # normaliza para quem usa 'picture'
        }
    except Exception as e:
        raise RuntimeError(f"Erro ao obter informações do usuário: {e}")


@app.context_processor
def inject_csrf_token():
    # permite usar {{ csrf_token() }} em qualquer template
    return dict(csrf_token=generate_csrf)


@app.route("/logout")
def logout():
    """Encerra a sessão do usuário."""
    try:
        # Evita reuso de sessão antiga (se disponível no Flask)
        getattr(flask.session, "cycle_key", lambda: None)()
    except Exception:
        pass

    flask.session.clear()
    return flask.redirect(url_for("index"))


@app.route("/reviews")
@limiter.limit("5 per minute")
@require_terms_accepted
def reviews():
    """Página de visualização e gerenciamento de avaliações."""
    if "credentials" not in session:
        return redirect(url_for("authorize"))

    user_info = session.get("user_info") or {}
    user_id = user_info.get("id")
    if not user_id:
        flash("Sessão inválida. Faça login novamente.", "danger")
        return redirect(url_for("logout"))

    # Logs enxutos (sem listar IDs de outros usuários)
    logging.debug("reviews: user_id=%s", user_id)
    try:
        adotadas = claim_booking_anonymous_for(user_id)
        if adotadas:
            app.logger.info(
                "Booking: %s avaliações adotadas para user_id=%s", adotadas, user_id
            )
    except Exception as e:
        app.logger.warning("Falha ao adotar reviews anônimas do Booking: %s", e)

    user_reviews = get_user_reviews(user_id)
    logging.debug("reviews: qnt_avaliacoes=%d", len(user_reviews))

    # 🚨 CORREÇÃO: DEFINIR user_plano ANTES DE USÁ-LO
    user_plano = get_user_plan(user_id)

    return render_template(
        "reviews.html",
        reviews=user_reviews,
        user=user_info,
        now=datetime.now(),
        PLANOS=PLANOS,
        user_plano=user_plano,  # Agora 'user_plano' está definido
    )


# -- quem é o usuário atual (para blueprints como o booking.py) --
def get_current_user_id():
    info = session.get("user_info") or {}
    return info.get("id")


# -- usado em booking.py para barrar acesso de quem não está logado --
def require_login():
    return ("credentials" in session) and bool(get_current_user_id())


@app.route("/add_review", methods=["GET", "POST"])
@limiter.limit("15 per minute")
@require_terms_accepted
@require_plano_ativo
def add_review():
    """Adiciona avaliação manualmente ou via robô; aplica limites do plano; gera resposta opcional com IA."""
    if "credentials" not in session:
        return redirect(url_for("authorize"))

    user_info = session.get("user_info") or {}
    user_id = user_info.get("id")
    if not user_id:
        flash("Erro ao identificar usuário. Por favor, faça login novamente.", "danger")
        return redirect(url_for("logout"))

    if request.method == "GET":
        return render_template(
            "add_review.html",
            user=user_info,
            now=datetime.now(),
            user_plano=get_user_plan(user_id),
            PLANOS=PLANOS,
        )

    # ————— POST —————
    # Aceita form ou JSON com fallback
    payload = request.get_json(silent=True) or request.form

    reviewer_name = (payload.get("reviewer_name") or "Cliente Anônimo").strip()[:120]
    # rating: força int entre 1 e 5
    try:
        rating = int(payload.get("rating", 5))
    except (TypeError, ValueError):
        rating = 5
    rating = max(1, min(5, rating))

    text = (payload.get("text") or "").strip()
    # Limites defensivos de tamanho para evitar abusos
    if len(text) > 5000:
        text = text[:5000]

    hiper_compreensiva = str(payload.get("hiper_compreensiva", "")).lower() in {
        "on",
        "true",
        "1",
    }
    consideracoes = (payload.get("consideracoes") or "").strip()
    if len(consideracoes) > 1500:
        consideracoes = consideracoes[:1500]

    # BLOQUEIO POR PLANO - Limite de avaliações/mês
    if atingiu_limite_avaliacoes_mes(user_id):
        msg = "Você atingiu o limite de avaliações do seu plano este mês."
        if request.is_json:
            return jsonify({"success": False, "error": msg}), 403
        flash(msg, "warning")
        return redirect(url_for("reviews"))

    # BLOQUEIO POR PLANO - Resposta hiper
    if hiper_compreensiva and not usuario_pode_usar_resposta_especial(user_id):
        msg = "Você atingiu o limite diário de respostas hiper compreensivas do seu plano."
        if request.is_json:
            return jsonify({"success": False, "error": msg}), 403
        flash(msg, "warning")
        return redirect(url_for("add_review"))

    # Verifica duplicata simples (mesmo user, nome e texto)
    existente = Review.query.filter_by(
        user_id=user_id, reviewer_name=reviewer_name, text=text
    ).first()
    if existente:
        msg = "Avaliação já existente. Ignorada."
        logging.info("add_review: duplicata ignorada (user=%s)", user_id)
        if request.is_json:
            return jsonify({"success": True, "message": msg})
        flash(msg, "info")
        return redirect(url_for("reviews"))

    # Configurações do usuário para template/assinatura
    settings = get_user_settings(user_id)
    manager = (settings.get("manager_name") or "").strip()
    business = (settings.get("business_name") or "").strip()
    assinatura = f"{business}\n{manager}".strip() if manager else business

    # 1. ✅ CORREÇÃO: Inicializa o prompt e adiciona o contexto PRIMEIRO
    prompt = ""

    if settings.get("contexto_personalizado"):
        contexto = settings["contexto_personalizado"].strip()
        # Adiciona o contexto no INÍCIO do prompt com uma instrução forte
        prompt += "🚨 INSTRUÇÃO CRÍTICA: O contexto da empresa abaixo é PRIORIDADE MÁXIMA na personalização da resposta.\n"
        prompt += f"Contexto da empresa: {contexto}\n\n"
        prompt += "INSTRUÇÃO CRÍTICA: Use o contexto da empresa fornecido acima com PRIORIDADE MÁXIMA."
        prompt += "\n\n"
    # 2. ✅ Continua o prompt com o texto principal, usando +=
    # O restante do prompt agora usa += para garantir que o contexto não seja apagado.
    prompt += (
        f"Você é um assistente especializado em atendimento ao cliente e deve escrever "
        f'uma resposta personalizada para uma avaliação recebida por "{business}".\n'
        f"Avaliação recebida:\n"
        f"- Nome do cliente: {reviewer_name}\n"
        f"- Nota: {rating} estrelas\n"
        f'- Texto: "{text}"\n'
    )

    if consideracoes:
        prompt += (
            "\nIMPORTANTE: O usuário forneceu as seguintes considerações para personalizar a resposta. "
            "Use essas informações com prioridade:\n"
            f'"{consideracoes}"\n'
        )
        registrar_uso_consideracoes(user_id)

    prompt += (
        "\nInstruções:\n"
        f'- Comece com: "{settings["default_greeting"]} {reviewer_name},"'
        "\n- Use palavras naturais e humanas, evite jargões."
        "\n- Comente os pontos mencionados, usando palavras diferentes."
        "\n- Se a nota for de 1 a 3, demonstre empatia, peça desculpas e ofereça uma solução."
        "\n- Se a nota for de 4 ou 5, agradeça e convide para retornar."
        f'\n- Finalize com: "{settings["default_closing"]}"'
        f'\n- Inclua as informações de contato: "{settings["contact_info"]}"'
        "\n- Assine ao final exatamente assim, cada item em uma linha:"
        f"\n{assinatura}"
        '\n- Não use cargos, não use "Atenciosamente", apenas os nomes.'
        "\n- A resposta deve ter entre 3 e 5 frases, ser personalizada e evitar frases genéricas, uso de travessoes e texto com caracteriscas mais humanas possiveis."
    )

    if hiper_compreensiva:
        prompt += (
            "\n\nGere uma resposta mais longa, empática e detalhada. Use de 10 a 15 frases. "
            "Mostre escuta ativa, reconhecimento das críticas e profissionalismo elevado. "
            "Responda cuidadosamente aos principais pontos levantados pelo cliente."
        )

    # Geração de resposta (melhor tratamento de erro)
    resposta_gerada = ""
    try:
        completion = client.with_options(timeout=30.0).chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "Você é um assistente cordial, objetivo e empático para atendimento ao cliente.",
                },
                {"role": "user", "content": prompt},
            ],  # defensivo
        )
        resposta_gerada = (completion.choices[0].message.content or "").strip()
    except Exception:
        logging.exception("add_review: falha ao gerar resposta automática")

    # Não marcar como 'replied' se a IA falhar
    replied_flag = bool(resposta_gerada)

    # Persistência
    try:
        new_review = Review(
            user_id=user_id,
            reviewer_name=reviewer_name,
            rating=rating,
            text=text,
            date=agora_brt(),
            reply=resposta_gerada,
            replied=replied_flag,
        )
        db.session.add(new_review)

        if hiper_compreensiva and replied_flag:
            # só registra uso se de fato gerou algo
            registrar_uso_resposta_especial(user_id)

        db.session.commit()
        logging.info(
            "add_review: review salva (user=%s, replied=%s)", user_id, replied_flag
        )
    except SQLAlchemyError:
        db.session.rollback()
        logging.exception("add_review: erro ao salvar avaliação")
        if request.is_json:
            return (
                jsonify({"success": False, "error": "Erro ao salvar a avaliação."}),
                500,
            )
        flash("Erro ao salvar a avaliação.", "danger")
        return redirect(url_for("reviews"))

    if request.is_json:
        return jsonify({"success": True, "replied": replied_flag})
    else:
        flash("Avaliação adicionada com sucesso!", "success")
        return redirect(url_for("reviews"))
    
@app.route("/save_reply", methods=["POST"])
@limiter.limit("10 per minute")
def save_reply():
    """Salva a resposta para uma avaliação no banco de dados."""
    if "credentials" not in flask.session:
        return jsonify({"success": False, "error": "Usuário não autenticado"}), 401

    user_info = flask.session.get("user_info") or {}
    user_id = user_info.get("id")
    if not user_id:
        return jsonify({"success": False, "error": "Usuário não identificado"}), 401

    data = request.get_json(silent=True) or {}
    try:
        review_id = int(data.get("review_id"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "review_id inválido"}), 400

    reply_text = (data.get("reply_text") or "").strip()
    if not reply_text:
        return jsonify({"success": False, "error": "Parâmetros inválidos"}), 400

    # Limite defensivo (evita abuso / payloads gigantes)
    if len(reply_text) > 5000:
        reply_text = reply_text[:5000]

    review = Review.query.filter_by(id=review_id, user_id=user_id).first()
    if not review:
        return jsonify({"success": False, "error": "Avaliação não encontrada"}), 404

    review.reply = reply_text
    review.replied = True

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        logging.exception("save_reply: erro ao persistir resposta")
        return jsonify({"success": False, "error": "Erro ao salvar a resposta."}), 500

    return jsonify({"success": True})


@app.route("/dashboard")
@require_terms_accepted
@require_plano_ativo
def dashboard():
    """Página de dashboard com análise de avaliações, adaptada ao plano."""
    if "credentials" not in flask.session:
        return flask.redirect(url_for("authorize"))

    user_info = flask.session.get("user_info") or {}
    user_id = user_info.get("id")
    if not user_id:
        flash("Erro ao identificar usuário. Por favor, faça login novamente.", "danger")
        return redirect(url_for("logout"))

    plano = get_user_plan(user_id)
    user_reviews = get_user_reviews(user_id)

    if not user_reviews:
        flash("Adicione algumas avaliações para visualizar o dashboard.", "info")
        return redirect(url_for("add_review"))

    total_reviews = len(user_reviews)

    # --- média robusta (usa apenas ratings numéricos) ---
    ratings = []
    for r in user_reviews:
        try:
            if r.rating is None:
                continue
            ratings.append(float(r.rating))
        except (TypeError, ValueError):
            continue
    avg_rating = round(sum(ratings) / len(ratings), 2) if ratings else 0.0

    # --- distribuição por estrelas 1..5 (agrupa decimais) ---
    rating_distribution = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for r in user_reviews:
        try:
            val = float(r.rating)
            star = int(val)  # 4.3 -> 4
            star = min(5, max(1, star))
            rating_distribution[star] += 1
        except (TypeError, ValueError):
            continue

    responded_reviews = sum(
        1 for r in user_reviews if bool(getattr(r, "replied", False))
    )
    percent_responded = (
        (responded_reviews * 100.0 / total_reviews) if total_reviews else 0.0
    )

    rating_distribution_values = [
        rating_distribution[1],
        rating_distribution[2],
        rating_distribution[3],
        rating_distribution[4],
        rating_distribution[5],
    ]

    return render_template(
        "dashboard.html",
        total_reviews=total_reviews,
        avg_rating=avg_rating,  # já arredondado
        rating_distribution=rating_distribution,
        rating_distribution_values=rating_distribution_values,
        percent_responded=round(percent_responded, 1),
        reviews=user_reviews,
        user=user_info,
        user_plano=plano,
        PLANOS=PLANOS,
        now=datetime.now(),
    )


from flask_wtf.csrf import CSRFError


@app.errorhandler(CSRFError)
def handle_csrf(e):
    if request.accept_mimetypes.accept_json:
        return (
            jsonify(
                success=False,
                error="CSRF inválido ou sessão expirada. Recarregue a página e tente novamente.",
            ),
            400,
        )
    flash("Sua sessão expirou. Recarregue a página e tente novamente.", "warning")
    return redirect(request.referrer or url_for("index"))


@app.route("/analyze_reviews", methods=["POST"])
def analyze_reviews():
    if "credentials" not in flask.session:
        return jsonify({"success": False, "error": "Usuário não autenticado"}), 401

    user_info = flask.session.get("user_info") or {}
    user_id = user_info.get("id")
    
    # 1. Busca settings AQUI
    settings = get_user_settings(user_id)
    
    # Validação do ID (Melhoria de segurança/lógica)
    if not user_id:
        return jsonify({"success": False, "error": "Usuário não identificado"}), 401

    user_reviews = get_user_reviews(user_id)
    if not user_reviews:
        return (
            jsonify({"success": False, "error": "Nenhuma avaliação para analisar."}),
            400,
        )

    # Constrói resumo, mas limita tamanho para não estourar tokens
    lines = [
        f"{(r.reviewer_name or 'Cliente').strip()[:80]} ({r.rating} estrelas): {(r.text or '').strip()}"
        for r in user_reviews
    ]
    resumo = "\n".join(lines)
    if len(resumo) > 8000:
        resumo = resumo[:8000]

    # 2. 💡 CORREÇÃO: Inicializa 'prompt' e adiciona o contexto ANTES
    prompt = "" 

    if settings.get("contexto_personalizado"):
        contexto = settings["contexto_personalizado"].strip()
        # Adiciona a caixa de contexto na frente
        prompt += f"INFORMAÇÃO CRÍTICA: Use o seguinte contexto da empresa para guiar sua análise:\nContexto da empresa: {contexto}\n\n" 

    # 3. Adiciona as instruções principais (sem redefinir 'prompt = f"""')
    prompt += f"""
Você é um analista de satisfação do cliente. Analise as avaliações abaixo e gere um resumo útil para gestores.

Tarefas:
    Primeiro paragrafo liste os principais elogios em PONTOS POSITIVOS .
    Segundo paragrafo recorrentes ou oportunidades de melhoria em PONTOS NEGATIVOS .
    Escreva um parágrafo claro em ANALISE GERAL, com tom profissional, respeitoso e construtivo.
    Escreva cada topico em uma linha.
    Revise cuidadosamente a ortografia, acentuação e gramática do texto antes de finalizar.
Use português formal e fluente, sem erros nem regionalismos.

Evite qualquer caractere especial como travessões (—), aspas curvas (“ ”) ou reticências estilizadas (…).
Use apenas caracteres simples (por exemplo, '-' em vez de '—').

Garanta que todo o texto siga normas ortográficas do português do Brasil (novo acordo ortográfico)
e mantenha formatação limpa, sem símbolos estranhos ou emojis.
Avaliações:
{resumo}

Responda apenas os seguintes campos:
    Nao cite todos os comentarios, apenas os mais importantes e com palavras diferentes ou mais profissionais do que foram usadas no comentario. 
    Sem caracteres especiais, um texto de facil compreenção mas completo.
    Escolhe os tres pontos principais e diga o primeiro segundo e terceiro em grau de importancia na interveçao
"""
    # ... (restante do código que chama a API da OpenAI)
    
    try:
        completion = client.with_options(timeout=30.0).chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "Você é um analista de avaliações de clientes.",
                },
                {"role": "user", "content": prompt},
            ],
        )
        # ... (tratamento da resposta)
        response_text = (completion.choices[0].message.content or "").strip()

        # Tenta JSON; se falhar, retorna como texto
        try:
            analysis = json.loads(response_text)
            return jsonify({"success": True, "analysis": analysis})
        except json.JSONDecodeError:
            return jsonify({"success": True, "raw_analysis": response_text})
    except Exception as e:
        logging.exception("analyze_reviews: falha na IA")
        return (
            jsonify({"success": False, "error": f"Erro na análise com IA: {str(e)}"}),
            500,
        )



@app.route("/settings", methods=["GET", "POST"])
def settings():
    """Configurações do aplicativo."""
    if "credentials" not in flask.session:
        return flask.redirect(url_for("authorize"))

    user_info = flask.session.get("user_info") or {}
    user_id = user_info.get("id")
    if not user_id:
        flash("Erro ao identificar usuário. Por favor, faça login novamente.", "danger")
        return redirect(url_for("logout"))

    if request.method == "POST":
        # Coleta dados do formulário com limites defensivos
        def cap(s, n): return (s or "").strip()[:n]

        settings_data = {
            "business_name": cap(request.form.get("company_name"), 200),
            "default_greeting": cap(request.form.get("default_greeting"), 120) or "Olá,",
            "default_closing": cap(request.form.get("default_closing"), 240) or "Agradecemos seu feedback!",
            "contact_info": cap(request.form.get("contact_info"), 500),
            "terms_accepted": request.form.get("terms_accepted"),
            "manager_name": cap(request.form.get("manager_name"), 200),
        }

        # Logo (imagem) — valida extensão, mimetype e tamanho
        ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg"}
        ALLOWED_MIMETYPES = {"image/png", "image/jpeg"}
        MAX_LOGO_SIZE = 500 * 1024  # 500 KB

        def allowed_file(filename):
            return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

        logo_file = request.files.get("logo")
        logo_bytes = None
        if logo_file and logo_file.filename:
            if not allowed_file(logo_file.filename):
                flash("Formato de imagem não suportado. Só PNG e JPG!", "danger")
                return redirect(url_for("settings"))
            if (logo_file.mimetype or "").lower() not in ALLOWED_MIMETYPES:
                flash("Tipo de arquivo inválido.", "danger")
                return redirect(url_for("settings"))
            logo_file.seek(0, 2)
            file_size = logo_file.tell()
            logo_file.seek(0)
            if file_size > MAX_LOGO_SIZE:
                flash("Logo muito grande! Limite: 500KB.", "danger")
                return redirect(url_for("settings"))
            logo_bytes = logo_file.read()
        settings_data["logo"] = logo_bytes

        if not settings_data["terms_accepted"]:
            flash("Você precisa aceitar os Termos e Condições para continuar.", "warning")
            return redirect(url_for("settings"))

        # Salva as configurações com try/except
        try:
            save_user_settings(user_id, settings_data)
        except Exception:
            db.session.rollback()
            logging.exception("settings: erro ao salvar configurações")
            flash("Erro ao salvar as configurações.", "danger")
            return redirect(url_for("settings"))

        # Envia e-mail de boas-vindas (idempotente)
        try:
            existing_settings = UserSettings.query.filter_by(user_id=user_id).first()
            if existing_settings and not getattr(existing_settings, "email_boas_vindas_enviado", False):
                nome_do_usuario = (
                    (existing_settings.manager_name or "")
                    or (existing_settings.business_name or "")
                    or user_info.get("name")
                    or "Usuário"
                )
                html = montar_email_boas_vindas(nome_do_usuario)
                email_destino = user_info.get("email")
                if email_destino:
                    try:
                        enviar_email(
                            destinatario=email_destino,
                            assunto="Seja bem-vindo ao ComentsIA! 🚀",
                            corpo_html=html,
                        )
                        existing_settings.email_boas_vindas_enviado = True
                        db.session.commit()
                    except Exception:
                        db.session.rollback()
                        logging.exception("settings: falha ao enviar e-mail de boas-vindas")
        except Exception:
            logging.exception("settings: erro ao marcar e-mail de boas-vindas")

        session["terms_accepted"] = True
        flash("Configurações salvas com sucesso!", "success")
        return redirect(url_for("index"))

    current_settings = get_user_settings(user_id)
    return render_template(
        "settings.html",
        settings=current_settings,
        user=user_info,
        now=datetime.now(),
    )
@app.route("/settings/contexto", methods=["POST"])
@require_terms_accepted
@require_plano_ativo
def salvar_contexto_ia():
    """Salva o Contexto da IA (somente planos Pro e Business)."""
    if "credentials" not in flask.session:
        return redirect(url_for("authorize"))

    user_info = flask.session.get("user_info") or {}
    user_id = user_info.get("id")
    if not user_id:
        return jsonify({"error": "Sessão inválida. Faça login novamente."}), 401

    # 🔹 Determina o plano real via função central
    plano = get_user_plan(user_id)
    plano_normalizado = (plano or "").strip().lower()

    # 🔹 Usa tua própria tabela de equivalentes
    planos_pro = PLANO_EQUIVALENTES.get("pro", [])
    planos_business = PLANO_EQUIVALENTES.get("business", [])

    # 🔒 Bloqueia apenas se o plano atual não estiver entre os planos pagos
    if plano_normalizado not in planos_pro + planos_business:
        return jsonify({
            "error": "🔒 Este recurso está disponível apenas nos planos Pro e Business."
        }), 403

    # 🔹 Captura e valida o texto do contexto
    contexto = (request.form.get("contexto_personalizado") or "").strip()[:500]
    if not contexto:
        return jsonify({"error": "O campo de contexto não pode estar vazio."}), 400

    # 🔹 Atualiza no banco de dados
    try:
        settings = UserSettings.query.filter_by(user_id=user_id).first()
        if not settings:
            settings = UserSettings(user_id=user_id)
            db.session.add(settings)

        settings.contexto_personalizado = contexto
        db.session.commit()

        logging.info(f"[IA CONTEXTO] Contexto salvo com sucesso para user_id={user_id}")
        return jsonify({"success": True, "message": "Contexto salvo com sucesso!"})

    except Exception as e:
        db.session.rollback()
        logging.exception(f"[IA CONTEXTO] Erro ao salvar contexto para user_id={user_id}: {e}")
        return jsonify({"error": "Erro ao salvar contexto. Tente novamente mais tarde."}), 500

@app.route("/logo")
def logo():
    """Retorna o logo do usuário autenticado como binário com mimetype correto e cache seguro."""
    if "credentials" not in flask.session:
        return "", 401

    user_info = flask.session.get("user_info") or {}
    user_id = user_info.get("id")
    if not user_id:
        return "", 401

    settings = UserSettings.query.filter_by(user_id=user_id).first()
    if not settings or not settings.logo:
        # Sem logo cadastrado
        return "", 204

    # Detecta tipo por magic bytes
    logo_bytes = settings.logo
    mimetype = "application/octet-stream"
    ext = "bin"
    try:
        if logo_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            mimetype, ext = "image/png", "png"
        elif logo_bytes.startswith(b"\xff\xd8"):
            mimetype, ext = "image/jpeg", "jpg"
    except Exception:
        logging.exception("logo: falha ao inspecionar magic bytes")

    # ETag simples baseada no tamanho e primeiros bytes (evita recalcular hash grande)
    etag = f'W/"{len(logo_bytes)}-{logo_bytes[:8].hex()}"'
    resp = flask.make_response(
        send_file(
            io.BytesIO(logo_bytes),
            mimetype=mimetype,
            as_attachment=False,
            download_name=f"logo.{ext}",
        )
    )
    resp.headers["ETag"] = etag
    # Cache curto do lado do cliente; ajuste conforme sua política
    resp.headers["Cache-Control"] = "private, max-age=300"
    return resp


@app.route("/teste-limite")
@limiter.limit("5 per minute")
def teste_limite():
    return "Acesso liberado!"


@app.route("/apply_template", methods=["POST"])
def apply_template():
    """Aplica o template de saudação e contato à resposta."""
    if "credentials" not in flask.session:
        return jsonify({"success": False, "error": "Usuário não autenticado"}), 401

    user_info = flask.session.get("user_info") or {}
    user_id = user_info.get("id")
    if not user_id:
        return jsonify({"success": False, "error": "Usuário não identificado"}), 401

    data = request.get_json(silent=True) or {}
    reply_text = (data.get("reply_text") or "").strip()
    if not reply_text:
        return jsonify({"success": False, "error": "Texto da resposta ausente"}), 400

    # Limite defensivo
    if len(reply_text) > 5000:
        reply_text = reply_text[:5000]

    settings = get_user_settings(user_id)  # já lida com defaults/erros

    # Normaliza quebras e remove espaços excedentes de borda
    body = "\n".join(line.rstrip() for line in reply_text.splitlines()).strip()

    formatted_reply = (
        f"{settings['default_greeting']}\n\n"
        f"{body}\n\n"
        f"{settings['default_closing']}\n"
        f"{settings['contact_info']}"
    )

    return jsonify({"success": True, "formatted_reply": formatted_reply})


import os


# Aplica as migrações automaticamente no Render (RENDER=true)
# Aplica as migrações automaticamente no Render (RENDER=true)
def aplicar_migracoes():
    """Executa o upgrade do banco se estiver no Render ou no modo principal."""
    with app.app_context():
        try:
            logging.info("📦 Aplicando migrações...")
            upgrade()
            logging.info("✅ Migrações aplicadas com sucesso.")
        except Exception as e:
            logging.exception("⚠️ Erro ao aplicar migrações: %s", e)


# Executa upgrade automaticamente se estiver no Render
# Executa upgrade automaticamente se estiver no Render
if os.environ.get("RENDER") == "true" and __name__ == "__main__":
    aplicar_migracoes()

import atexit


def _flush_logs():
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass


atexit.register(_flush_logs)

if __name__ == "__main__":
    import pytz
    import atexit
    from apscheduler.schedulers.background import BackgroundScheduler

    # Ambiente local
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    aplicar_migracoes()

    host = os.getenv("FLASK_RUN_HOST", "127.0.0.1")
    port = int(os.getenv("FLASK_RUN_PORT", "8000"))
    debug = os.getenv("FLASK_DEBUG", "1") == "1"

    # --- Inicia o scheduler (cron diário do Google) ---
    scheduler = BackgroundScheduler(timezone=pytz.timezone("America/Sao_Paulo"))
    scheduler.start()

    try:
        from google_auto import register_gbp_cron
        register_gbp_cron(scheduler, app)
        print("[gbp] ⏰ Job diário do Google registrado com sucesso!")
    except Exception as e:
        import logging
        logging.exception(f"[gbp] Falha ao registrar job diário: {e}")

    # Fecha o scheduler ao encerrar o app
    atexit.register(lambda: scheduler.shutdown(wait=False))

    # --- Executa o servidor Flask ---
    print(f"🚀 Servidor Flask rodando em http://{host}:{port}")
    app.run(host=host, port=port, debug=False, use_reloader=False)
