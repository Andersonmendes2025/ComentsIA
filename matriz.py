import pytz
import json
from datetime import datetime
from functools import wraps
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, session, flash, jsonify
)
from sqlalchemy import func
from models import db, Review, UserSettings, FilialVinculo
from utils.crypto import decrypt
from openai import OpenAI
from dotenv import load_dotenv
import os
from models import UserSettings
load_dotenv()

matriz_bp = Blueprint("matriz", __name__, url_prefix="/matriz")
BRT = pytz.timezone("America/Sao_Paulo")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))



# ---------- FUNÇÕES DE UTILIDADE ----------

def agora_brt():
    return datetime.now(BRT)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "credentials" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

def require_login():
    if "credentials" not in session or "user_info" not in session:
        flash("Você precisa estar logado.", "warning")
        return False
    return True

def get_current_user_id():
    ui = session.get("user_info") or {}
    return ui.get("id")

def get_context_user_id():
    return session.get("viewing_filial") or get_current_user_id()

def is_parent_of(parent_user_id: str, child_user_id: str) -> bool:
    return (
        FilialVinculo.query.filter_by(
            parent_user_id=parent_user_id, child_user_id=child_user_id
        ).first() is not None
    )

def get_filiais_ids(parent_user_id: str):
    return [
        v.child_user_id
        for v in FilialVinculo.query.filter_by(parent_user_id=parent_user_id, status="aceito").all()
    ]


def get_user_settings_safe(user_id: str):
    return UserSettings.query.filter_by(user_id=user_id).first() or None

def get_business_display_name(user_id: str) -> str:
    s = UserSettings.query.filter_by(user_id=user_id).first()
    if not s:
        return user_id
    name_enc = getattr(s, "business_name", None)
    if not name_enc:
        return user_id
    try:
        name = decrypt(name_enc)
        return name or user_id
    except Exception:
        return name_enc or user_id


# ---------- MÉTRICAS ----------

def compute_metrics_for_user(user_id: str):
    q = Review.query.filter_by(user_id=user_id)
    total = q.count()
    if total == 0:
        return {
            "user_id": user_id,
            "total_reviews": 0,
            "avg_rating": 0.0,
            "responded": 0,
            "response_rate": 0.0,
            "last_review_at": None,
        }

    avg_rating = db.session.query(func.avg(Review.rating)).filter(
        Review.user_id == user_id
    ).scalar() or 0.0
    responded = q.filter(Review.replied.is_(True)).count()
    response_rate = (responded / total) * 100 if total else 0.0
    last_review = q.order_by(Review.date.desc()).first()
    last_dt = last_review.date.astimezone(BRT) if last_review and last_review.date else None

    return {
        "user_id": user_id,
        "total_reviews": total,
        "avg_rating": round(float(avg_rating), 2),
        "responded": responded,
        "response_rate": round(response_rate, 1),
        "last_review_at": last_dt,
    }

def compute_aggregate_metrics(user_ids):
    total_reviews = 0
    responded = 0
    weighted_sum = 0.0
    last_dt = None
    per_branch = []
    for uid in user_ids:
        m = compute_metrics_for_user(uid)
        per_branch.append(m)
        total_reviews += m["total_reviews"]
        responded += m["responded"]
        weighted_sum += m["avg_rating"] * m["total_reviews"]
        if m["last_review_at"] and (last_dt is None or m["last_review_at"] > last_dt):
            last_dt = m["last_review_at"]

    avg_rating = (weighted_sum / total_reviews) if total_reviews else 0.0
    response_rate = (responded / total_reviews * 100) if total_reviews else 0.0
    return {
        "total_reviews": total_reviews,
        "avg_rating": round(avg_rating, 2),
        "responded": responded,
        "response_rate": round(response_rate, 1),
        "last_review_at": last_dt,
        "per_branch": per_branch,
    }


# ---------- ROTAS PRINCIPAIS ----------

@matriz_bp.route("/")
def matriz_home():
    return redirect(url_for("matriz.dashboard"))

@matriz_bp.route("/dashboard")
def dashboard():
    if not require_login():
        return redirect(url_for("authorize"))

    parent_id = get_current_user_id()
    filiais_ids = get_filiais_ids(parent_id)

    matriz_metrics = compute_metrics_for_user(parent_id)
    aggregate_ids = [parent_id] + filiais_ids
    aggregate = compute_aggregate_metrics(aggregate_ids)

    filiais_info = []
    for fid in filiais_ids:
        nome = get_business_display_name(fid)
        filiais_info.append({
            "user_id": fid,
            "display_name": nome or fid,
            "metrics": next((m for m in aggregate["per_branch"] if m["user_id"] == fid), None),
        })

    return render_template(
        "matriz_dashboard.html",
        parent_id=parent_id,
        aggregate=aggregate,
        filiais=filiais_info,
        matriz_metrics=matriz_metrics,
        now=agora_brt()
    )


@matriz_bp.route("/filiais")
def filiais():
    if not require_login():
        return redirect(url_for("authorize"))

    parent_id = get_current_user_id()
    filiais_ids = get_filiais_ids(parent_id)
    aggregate = compute_aggregate_metrics(filiais_ids) if filiais_ids else None

    filiais_info = []
    for fid in filiais_ids:
        nome = get_business_display_name(fid)
        filiais_info.append({
            "user_id": fid,
            "display_name": nome or fid,
            "metrics": compute_metrics_for_user(fid),
        })

    return render_template("matriz_filiais.html", parent_id=parent_id, aggregate=aggregate, filiais=filiais_info, now=agora_brt())


# ---------- VÍNCULO E ACESSO ----------

@matriz_bp.route("/entrar/<path:filial_id>", methods=["POST", "GET"])
def entrar_filial(filial_id):
    if not require_login():
        return redirect(url_for("authorize"))

    parent_id = get_current_user_id()
    if not is_parent_of(parent_id, filial_id):
        flash("Você não tem permissão para acessar esta filial.", "danger")
        return redirect(url_for("matriz.dashboard"))

    session["viewing_filial"] = filial_id
    session["filial_name"] = get_business_display_name(filial_id)
    session["matriz_back_url"] = url_for("matriz.dashboard")
    flash(f"Você está visualizando a filial {session['filial_name']}.", "info")
    return redirect(url_for("index"))

@matriz_bp.route("/sair-filial", methods=["POST", "GET"])
def sair_filial():
    session.pop("viewing_filial", None)
    session.pop("filial_name", None)
    session.pop("matriz_back_url", None)
    flash("Você voltou para a conta matriz.", "success")
    return redirect(url_for("matriz.dashboard"))

@matriz_bp.route("/vincular", methods=["POST"])
def vincular_filial():
    if not require_login():
        return jsonify(success=False, error="Não autenticado."), 401

    parent_id = get_current_user_id()
    child_id = request.form.get("child_user_id", "").strip()

    if not child_id:
        return jsonify(success=False, error="Informe o ID da filial."), 400
    if child_id == parent_id:
        return jsonify(success=False, error="Não é possível vincular a si mesmo."), 400

    # 🔒 Verifica se a conta existe
    from models import User
    child_user = User.query.get(child_id)
    if not child_user:
        return jsonify(success=False, error="Essa conta ainda não existe. Peça para o responsável fazer login primeiro."), 400

    # Verifica se já houve vínculo antes
    vinc = FilialVinculo.query.filter_by(parent_user_id=parent_id, child_user_id=child_id).first()

    if vinc:
        if vinc.status == "pendente":
            return jsonify(success=True, message="Convite já enviado. Aguardando aceite da filial.")
        elif vinc.status == "aceito":
            return jsonify(success=True, message="Filial já vinculada.")
        else:
            vinc.status = "pendente"
            vinc.data_convite = agora_brt()
            vinc.data_aceite = None
            db.session.commit()
            return jsonify(success=True, message="Convite reenviado com sucesso.")
    else:
        novo_vinculo = FilialVinculo(
            parent_user_id=parent_id,
            child_user_id=child_id,
            status="pendente",
            data_convite=agora_brt()
        )
        db.session.add(novo_vinculo)
        db.session.commit()
        return jsonify(success=True, message="Convite enviado com sucesso.")


@matriz_bp.route("/desvincular", methods=["POST"])
def desvincular_filial():
    if not require_login():
        return jsonify(success=False, error="Não autenticado."), 401

    parent_id = get_current_user_id()
    child_id = request.form.get("child_user_id", "").strip()

    if not child_id:
        return jsonify(success=False, error="Informe o ID da filial."), 400

    vinc = FilialVinculo.query.filter_by(parent_user_id=parent_id, child_user_id=child_id).first()

    if not vinc or vinc.status != 'aceito':
        return jsonify(success=False, error="Essa filial ainda não está vinculada."), 400

    # Em vez de deletar, marca como desvinculado
    vinc.status = "desvinculado"
    vinc.data_aceite = None
    db.session.commit()
    return jsonify(success=True, message="Filial desvinculada com sucesso.")


# ---------- ANÁLISE COM IA ----------

@matriz_bp.route("/analyze_reviews", methods=["POST"])
def analyze_reviews_filial():
    user_info = session.get("user_info", {})
    matriz_id = user_info.get("id")
    filial_id = request.args.get("filial_id")

    if not filial_id:
        return jsonify({"success": False, "error": "ID da filial não informado."})

    if not is_parent_of(matriz_id, filial_id):
        return jsonify({"success": False, "error": "Filial não vinculada a esta conta matriz."})

    user_reviews = Review.query.filter_by(user_id=filial_id).order_by(Review.date.desc()).all()
    if not user_reviews:
        return jsonify({"success": False, "error": "A filial não possui avaliações."})

    resumo = "\n".join([
        f"{r.reviewer_name} ({r.rating} estrelas): {r.text}" for r in user_reviews
    ])

    prompt = f"""
Você é um analista de satisfação do cliente. Analise as avaliações abaixo e gere um resumo útil para gestores.

Tarefas:
 Primeiro parágrafo: PONTOS POSITIVOS.
 Segundo parágrafo: PONTOS NEGATIVOS.
 Terceiro parágrafo: ANALISE GERAL.
Com linguagem clara, sem repetir palavras dos comentários.
Evite emojis e seja objetivo.
Avaliações:
{resumo}
"""

    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Você é um analista de avaliações de clientes."},
                {"role": "user", "content": prompt},
            ],
        )
        response_text = completion.choices[0].message.content.strip()
        return jsonify({"success": True, "analysis": response_text})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ---------- CONTEXT PROCESSOR ----------

@matriz_bp.app_context_processor
def inject_globals_matriz():
    viewing_filial = session.get("viewing_filial") is not None
    filial_name = session.get("filial_name")
    matriz_back_url = url_for("matriz.sair_filial") if viewing_filial else None

    return dict(
        viewing_filial=viewing_filial,
        filial_name=filial_name,
        matriz_back_url=matriz_back_url,
        now=agora_brt(),
    )

@matriz_bp.route("/convites")
def ver_convites():
    if not require_login():
        return redirect(url_for("authorize"))

    user_id = get_current_user_id()
    convites_raw = FilialVinculo.query.filter_by(child_user_id=user_id, status='pendente').all()

    convites = []
    for convite in convites_raw:
        parent_id = convite.parent_user_id
        settings = UserSettings.query.filter_by(user_id=parent_id).first()

        try:
            nome_matriz = decrypt(settings.business_name) if settings and settings.business_name else parent_id
        except Exception:
            nome_matriz = parent_id

        convites.append({
            "id": convite.id,
            "nome_matriz": nome_matriz,
            "data_convite": convite.data_convite,
        })

    return render_template("convites.html", convites=convites)


@matriz_bp.route("/convites/aceitar/<int:vinculo_id>")
def aceitar_convite(vinculo_id):
    if not require_login():
        return redirect(url_for("authorize"))

    user_id = get_current_user_id()
    convite = FilialVinculo.query.get_or_404(vinculo_id)

    if convite.child_user_id != user_id:
        flash("Você não tem permissão para aceitar este convite.", "danger")
        return redirect(url_for("matriz.ver_convites"))


    if convite.status == "aceito":
        flash("Você já aceitou esse convite anteriormente.", "info")
        return redirect(url_for("matriz.ver_convites"))


    convite.status = 'aceito'
    convite.data_aceite = agora_brt()
    db.session.commit()
    flash("Convite aceito com sucesso!", "success")
    return redirect(url_for("matriz.ver_convites"))




@matriz_bp.route("/convites/recusar/<int:vinculo_id>", methods=["POST"])
def recusar_convite(vinculo_id):
    if not require_login():
        return redirect(url_for("authorize"))

    user_id = get_current_user_id()
    convite = FilialVinculo.query.get_or_404(vinculo_id)

    if convite.child_user_id != user_id:
        flash("Você não tem permissão para recusar este convite.", "danger")
        return redirect(url_for("matriz.ver_convites"))

    db.session.delete(convite)
    db.session.commit()
    flash("Convite recusado com sucesso.", "info")
    return redirect(url_for("matriz.ver_convites"))
