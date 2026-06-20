from __future__ import annotations
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from models import UserSettings, GoogleLocation
import pytz
import requests
from urllib.parse import quote
from typing import Optional, Tuple
from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask import render_template_string
from flask import session
from flask_wtf.csrf import generate_csrf

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from models import (
    Review,
    UserSettings,
    GoogleLocation,
    db,
)
from admin import get_historical_sync_prices

SLOT_FREE_COOLDOWN_DAYS = 90  # trava pra trocar a ficha grátis

def _get_gbp_limits(settings: Optional[UserSettings]) -> dict:
    """
    Retorna:
      - base_slots: 1 para planos Pro/Business
      - extra_slots: slots adicionais comprados (gbp_slots_extras)
      - total_slots: base + extra
    """
    if not settings:
        return {"base_slots": 0, "extra_slots": 0, "total_slots": 0}

    plano = (settings.plano or "free").lower().strip()

    # Só Pro e Business têm 1 slot incluído
    if not (plano.startswith("pro") or plano.startswith("business")):
        return {"base_slots": 0, "extra_slots": 0, "total_slots": 0}

    extra = settings.gbp_slots_extras or 0  # pode crescer ilimitado
    base = 1                                # ✅ 1 slot incluso

    return {
        "base_slots": base,
        "extra_slots": extra,
        "total_slots": base + extra,
    }


# --- Configuração do Blueprint ---
google_auto_bp = Blueprint("google_auto", __name__, url_prefix="/auto")
GBP_SCOPE = "https://www.googleapis.com/auth/business.manage"

RATING_MAP = {
    "ONE": 1,
    "TWO": 2,
    "THREE": 3,
    "FOUR": 4,
    "FIVE": 5,
}


def converter_nota_gbp_para_int(rating_str: Optional[str]) -> int:
    if not rating_str:
        return 0
    return RATING_MAP.get(rating_str.upper(), 0)


def _now_brt() -> datetime:
    return datetime.now(pytz.timezone("America/Sao_Paulo"))

def get_current_user_id():
    user_info = session.get("user_info")
    if not user_info:
        return None
    return user_info.get("id")

def _get_session_credentials() -> Optional[Credentials]:
    creds_dict = session.get("credentials")
    if not creds_dict:
        return None
    try:
        creds = Credentials(
            token=creds_dict.get("token"),
            refresh_token=creds_dict.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.getenv("GOOGLE_CLIENT_ID"),
            client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
            scopes=[GBP_SCOPE],
        )
        if not creds.valid or creds.expired:
            creds.refresh(Request())
        return creds
    except Exception:
        logging.exception("[gbp] Falha ao reconstruir credenciais da sessão")
        return None
def _extract_id(resource: Optional[str]) -> Optional[str]:
    if not resource:
        return None
    return resource.split("/")[-1].strip()
 
def gbp_list_locations(user_id):
    credentials = _get_persisted_credentials(user_id)
    # Reutiliza a função robusta de listagem
    accounts = _list_all_accounts(credentials)
    return _list_all_locations(credentials, accounts)

@google_auto_bp.route("/locations", methods=["GET", "POST"])
def escolher_ficha_google():
    user_id = get_current_user_id()
    if not user_id:
        return redirect(url_for("authorize"))

    PRECO_ADDON_FMT = "29,90"  # só pra exibir no front

    settings = UserSettings.query.filter_by(user_id=user_id).first()
    limits = _get_gbp_limits(settings)
    base_slots = limits["base_slots"]
    extra_slots = limits["extra_slots"]
    total_slots = limits["total_slots"]

    # ------------------------ POST: ATIVAR / DESATIVAR FICHA ------------------------
    if request.method == "POST":
        location_id = _extract_id(request.form.get("location_id"))
        action = (request.form.get("action") or "ativar").lower()

        # 1. Busca a ficha alvo
        ficha_alvo = GoogleLocation.query.filter_by(
            user_id=user_id,
            location_id=location_id,
        ).first()

        if not ficha_alvo:
            return jsonify({"success": False, "error": "Ficha inválida."}), 400

        # 2. DESATIVAR
        if action == "desativar":
            if not ficha_alvo.is_active:
                return jsonify({"success": True, "message": "Ficha já está inativa."})

            ficha_alvo.is_active = False
            # opcional: limpar timestamp de ativação, se houver
            if hasattr(ficha_alvo, "activated_at"):
                ficha_alvo.activated_at = None

            db.session.commit()
            return jsonify({"success": True, "message": "Ficha desativada."})

        # 3. ATIVAR (padrão)
        if ficha_alvo.is_active:
            return jsonify({"success": True, "message": "Ficha já está ativa."})

        # verifica se o plano tem direito a slot
        if total_slots <= 0:
            return jsonify({
                "success": False,
                "error": "Seu plano atual não inclui slots de ficha ativa no Google. Assine o plano Pro ou Business para ativar.",
            }), 403

        # conta quantas já estão ativas
        fichas_ativas_count = GoogleLocation.query.filter_by(
            user_id=user_id,
            is_active=True,
        ).count()

        # se já está usando todos os slots, precisa comprar add-on
            # 4. Se já está usando todos os slots
        # Se já está usando todos os slots
        if fichas_ativas_count >= total_slots:
            plano_atual = (settings.plano if settings else "free").lower()
            
            # 4.1 Se for Free, manda pra tela de planos fazer o upgrade principal
            if plano_atual == "free":
                return jsonify({
                    "success": False,
                    "upgrade_required": True,
                    "upgrade_url": url_for("planos"),
                    "message": "Para ativar automação, contrate um plano Pro ou Business.",
                }), 402

            # 4.2 Se for Pro/Business, abre o Modal para comprar o Slot Extra
            return jsonify({
                "success": False,
                "payment_required": True,
                "message": "Você já atingiu o limite de fichas. Contrate um slot extra.",
                "price_fmt": PRECO_ADDON_FMT,
                "location_name": ficha_alvo.location_name,
            }), 402

            # 4.2. Há assinatura Stripe → front mostra modal de slot extra (add-on)
            return jsonify({
                "success": False,
                "payment_required": True,
                "message": "Você já está usando todos os seus slots de ficha ativa.",
                "price_fmt": PRECO_ADDON_FMT,
                "location_name": ficha_alvo.location_name,
            }), 402


        # tem slot livre → ativa a ficha
        ficha_alvo.is_active = True
        if hasattr(ficha_alvo, "activated_at"):
            ficha_alvo.activated_at = _now_brt()
        db.session.commit()

        return jsonify({"success": True})

    # ------------------------ GET: LISTAR FICHAS ------------------------
    fichas = GoogleLocation.query.filter_by(user_id=user_id).all()
    ativas = sum(1 for f in fichas if f.is_active)

    return render_template(
        "google_locations.html",
        fichas=fichas,
        ativas_count=ativas,
        total_slots=total_slots,
        base_slots=base_slots,
        extra_slots=extra_slots,
        settings=settings,
    )



@google_auto_bp.route("/cron/run_gbp_48h/<token>", methods=["GET", "POST"])
def cron_run_gbp_48h(token):
    expected = os.getenv("CRON_SECRET_TOKEN")
    if not expected or token != expected:
        return jsonify({"success": False, "error": "Acesso negado"}), 403

    try:
        enabled = UserSettings.query.filter_by(gbp_auto_enabled=True).all()
        total = 0
        for s in enabled:
            total += run_sync_last_48h(s.user_id)

        return jsonify({
            "success": True,
            "message": "Cron executado com sucesso",
            "total_processadas": total
        }), 200

    except Exception as e:
        logging.exception("[gbp] Erro no cron 48h")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

    
@google_auto_bp.route("/google/locations/sync", methods=["POST"])
def sync_google_locations():
    user_id = get_current_user_id()

    creds = _get_persisted_credentials(user_id) or _get_session_credentials()
    if not creds:
        return jsonify({"success": False, "error": "Sem credenciais"}), 401

    accounts = _list_all_accounts(creds)
    locations = _list_all_locations(creds, accounts)

    for loc in locations:
        account_ref = loc.get("account_name")          # "accounts/123" OU "userAccounts/456"
        location_ref = loc.get("location_name")        # "locations/999"
        location_id = _extract_id(location_ref)        # "999"

        if not account_ref or not location_id:
            continue

        exists = GoogleLocation.query.filter_by(user_id=user_id, location_id=location_id).first()

        if not exists:
            db.session.add(GoogleLocation(
                user_id=user_id,
                account_id=account_ref,                # salva REF completa
                location_id=location_id,               # salva só o id
                location_name=loc.get("location_title"),
            ))
        else:
            # importante: atualiza account_id antigo (numeric) para account_ref completo
            if exists.account_id != account_ref:
                exists.account_id = account_ref
            if exists.location_name != loc.get("location_title"):
                exists.location_name = loc.get("location_title")

    db.session.commit()
    return jsonify({"success": True})



def _get_persisted_credentials(user_id: str) -> Optional[Credentials]:
    try:
        settings = UserSettings.query.filter_by(user_id=user_id).first()
        refresh_token_antigo = getattr(settings, "google_refresh_token", None)
        
        if not settings or not refresh_token_antigo:
            return None
        
        creds = Credentials(
            token=None,
            refresh_token=refresh_token_antigo,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.getenv("GOOGLE_CLIENT_ID"),
            client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
            scopes=[GBP_SCOPE],
        )
        
        creds.refresh(Request())
        
        if creds.refresh_token and creds.refresh_token != refresh_token_antigo:
            settings.google_refresh_token = creds.refresh_token
            db.session.commit() 
            logging.info(f"[gbp] ✅ NOVO Refresh Token capturado e salvo para {user_id}.")
            
        return creds
        
    except Exception:
        logging.exception("[gbp] Falha ao reconstruir credenciais. Token revogado.")
        return None

def _make_auth_headers(creds: Credentials) -> dict:
    if creds and creds.valid and creds.token:
        return {"Authorization": f"Bearer {creds.token}"}
    return {}


def _first_account_name(creds: Credentials) -> Optional[str]:
    """Obtém a conta principal do Google Business."""
    try:
        headers = _make_auth_headers(creds)
        url = "https://mybusinessaccountmanagement.googleapis.com/v1/accounts"
        resp = requests.get(url, headers=headers, timeout=10)

        if resp.status_code != 200:
            return None

        data = resp.json()
        accounts = data.get("accounts", [])
        if not accounts:
            return None

        # Prioriza LOCATION_GROUP
        location_groups = [a for a in accounts if a.get("type") == "LOCATION_GROUP"]
        personal_accounts = [a for a in accounts if a.get("type") == "USER_ACCOUNT"]

        if location_groups:
            return location_groups[0].get("name")
        if personal_accounts:
            return personal_accounts[0].get("name")

        return None

    except Exception:
        return None


def _first_location_name(creds: Credentials, account_name: str) -> Optional[str]:
    """Obtém a primeira ficha usando API V1 corretamente formatada."""
    try:
        if not account_name:
            return None

        headers = _make_auth_headers(creds)
        
        account_id = account_name.split("/")[-1]  

        account_id = account_name.split("/")[-1]
        url_v1 = f"https://mybusinessbusinessinformation.googleapis.com/v1/accounts/{account_id}/locations"

        params = {"readMask": "name,title"}

        resp = requests.get(url_v1, headers=headers, params=params, timeout=10)

        if resp.status_code == 200:
            data = resp.json()
            locs = data.get("locations", [])
            if locs:
                return locs[0].get("name")

        return None

    except Exception:
        return None


def _list_all_accounts(creds: Credentials) -> List[str]:
    headers = _make_auth_headers(creds)
    url = "https://mybusinessaccountmanagement.googleapis.com/v1/accounts"

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            accounts = data.get("accounts", [])

            location_groups = [a for a in accounts if a.get("type") == "LOCATION_GROUP"]
            personal_accounts = [a for a in accounts if a.get("type") == "USER_ACCOUNT"]

            ordered = location_groups + personal_accounts

            return [a.get("name") for a in ordered if a.get("name")]

    except Exception:
        pass

    return []


@google_auto_bp.route("/debug-accounts")
def debug_accounts():
    return jsonify({"message": "Use logs para debug"})

# ---------------------------------------------------------
# 🚨 CORREÇÃO CRÍTICA API V1 (Reviews)
# ---------------------------------------------------------
def _list_reviews(creds: Credentials, account_ref: str, location_ref: str) -> List[Dict]:
    """
    Lista reviews (com paginação) na API v4.
    account_ref pode ser: "accounts/123" ou "123"
    location_ref pode ser: "locations/999" ou "999"
    """
    try:
        headers = _make_auth_headers(creds)

        if "/" not in account_ref:
            account_ref = f"accounts/{account_ref}"
        if "/" not in location_ref:
            location_ref = f"locations/{location_ref}"

        acc = _ensure_account_ref(account_ref)                  # accounts/...
        loc = _ensure_location_ref(_extract_id(location_ref) or location_ref)  # locations/...

        url = f"https://mybusiness.googleapis.com/v4/{acc}/{loc}/reviews"


        reviews_all: List[Dict] = []
        page_token: Optional[str] = None

        while True:
            params = {"pageSize": 50}
            if page_token:
                params["pageToken"] = page_token

            resp = requests.get(url, headers=headers, params=params, timeout=15)

            if resp.status_code != 200:
                logging.error(f"[gbp] Falha ao buscar reviews ({resp.status_code}) url={url} body={resp.text}")
                return []

            data = resp.json()
            reviews = data.get("reviews", []) or []
            reviews_all.extend(reviews)

            page_token = data.get("nextPageToken")
            if not page_token:
                break

        logging.info(f"[gbp] {len(reviews_all)} reviews encontradas (v4).")
        return reviews_all

    except Exception as e:
        logging.exception(f"[gbp] Erro ao listar avaliações: {e}")
        return []

@google_auto_bp.route("/debug/review_exists/<external_id>", methods=["GET"])
def debug_review_exists(external_id):
    user_id = get_current_user_id()

    data = _get_review_data_for_action(user_id, external_id)
    creds, account_ref, location_id = data

    reviews = _list_reviews(creds, account_ref, location_id)

    ext_raw = external_id
    ext = (external_id or "").strip()

    ids = {((rv.get("reviewId") or "").strip()) for rv in reviews}
    sample = list(ids)[:5]

    return jsonify({
        "ok": True,
        "account_ref": account_ref,
        "location_id": location_id,
        "qtd_reviews": len(reviews),
        "external_id_repr": repr(ext_raw),
        "external_id_stripped": ext,
        "sample_ids": sample,
        "sample_ids_repr": [repr(x) for x in sample],
        "exists": ext in ids,
    })
 
@google_auto_bp.route("/debug/db_locations", methods=["GET"])
def debug_db_locations():
    user_id = get_current_user_id()
    locs = GoogleLocation.query.filter_by(user_id=user_id).all()
    return jsonify({
        "user_id": user_id,
        "count": len(locs),
        "locs": [{
            "id": gl.id,
            "location_id": gl.location_id,
            "account_id": gl.account_id,
            "name": gl.location_name,
            "is_active": gl.is_active
        } for gl in locs]
    })
 
def _already_saved(user_id: str, review_id: str) -> bool:
    return (
        db.session.query(Review.id)
        .filter_by(user_id=user_id, external_id=review_id)
        .first()
        is not None
    )

# ---------------------------------------------------------
# 🚨 CORREÇÃO CRÍTICA API V1 (Publish Reply)
# ---------------------------------------------------------
def _ensure_account_ref(account_ref: str) -> str:
    if not account_ref:
        return account_ref
    return account_ref if account_ref.startswith(("accounts/", "userAccounts/")) else f"accounts/{account_ref}"

def _ensure_location_ref(location_ref: str) -> str:
    if not location_ref:
        return location_ref
    # aceita "1349..." ou "locations/1349..."
    return location_ref if location_ref.startswith("locations/") else f"locations/{location_ref}"

def _find_review_parent_for_user(
    creds: Credentials,
    user_id: str,
    review_id: str,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Procura em QUAL ficha ativa (account_id + location_id) essa review existe.
    Retorna (account_ref, location_id) se achar.
    """
    try:
        fichas = GoogleLocation.query.filter_by(user_id=user_id, is_active=True).all()
        if not fichas:
            return None, None

        for gl in fichas:
            if not gl.account_id or not gl.location_id:
                continue

            # chama a API para ver se a review está nessa ficha
            reviews = _list_reviews(creds, gl.account_id, gl.location_id)
            if not reviews:
                continue

            for r in reviews:
                if r.get("reviewId") == review_id:
                    return gl.account_id, gl.location_id

        return None, None
    except Exception:
        logging.exception("[gbp] Erro no _find_review_parent_for_user")
        return None, None


def _publish_reply(
    creds: Credentials,
    account_ref: str,
    location_ref: str,
    review_id: str,
    reply_text: str,
    user_id_for_fallback: Optional[str] = None,
) -> bool:
    """
    Publica reply via v4 (updateReply).
    Estratégia:
    1) PUT /v4/{acc}/{loc}/reviews/{rid}/reply
    2) PUT /v4/{name=acc/loc/reviews/rid}/reply   (mesma API, outra montagem)
    3) Se 404 e tiver user_id_for_fallback: procura a ficha correta e tenta de novo.
    """
    try:
        headers = _make_auth_headers(creds)
        payload = {"comment": reply_text}

        acc1 = _ensure_account_ref(account_ref)
        loc1 = _ensure_location_ref(_extract_id(location_ref) or location_ref)

        rid_safe = quote(review_id, safe="")

        def _put_by_parts(acc: str, loc: str):
            url = f"https://mybusiness.googleapis.com/v4/{acc}/{loc}/reviews/{rid_safe}/reply"
            return requests.put(url, headers=headers, json=payload, timeout=15), url

        def _put_by_name(acc: str, loc: str):
            # name = accounts/*/locations/*/reviews/*
            name = f"{acc}/{loc}/reviews/{rid_safe}"
            url = f"https://mybusiness.googleapis.com/v4/{name}/reply"
            return requests.put(url, headers=headers, json=payload, timeout=15), url

        # 1) tenta por partes
        resp, url = _put_by_parts(acc1, loc1)
        if resp.status_code == 200:
            logging.info(f"[gbp] ✅ Reply publicado (review={review_id}).")
            return True

        # 2) tenta por name (mesma API)
        resp_name, url_name = _put_by_name(acc1, loc1)
        if resp_name.status_code == 200:
            logging.info(f"[gbp] ✅ Reply publicado (name) (review={review_id}).")
            return True

        # 3) fallback: só faz sentido em 404
        if (resp.status_code == 404 or resp_name.status_code == 404) and user_id_for_fallback:
            logging.warning(f"[gbp] 404 ao publicar. Procurando ficha correta... review={review_id}")

            new_acc, new_loc_id = _find_review_parent_for_user(creds, user_id_for_fallback, review_id)
            if new_acc and new_loc_id:
                acc2 = _ensure_account_ref(new_acc)
                loc2 = _ensure_location_ref(new_loc_id)

                resp2, url2 = _put_by_parts(acc2, loc2)
                if resp2.status_code == 200:
                    logging.info(f"[gbp] ✅ Reply publicado após fallback (review={review_id}).")
                    return True

                resp2b, url2b = _put_by_name(acc2, loc2)
                if resp2b.status_code == 200:
                    logging.info(f"[gbp] ✅ Reply publicado (name) após fallback (review={review_id}).")
                    return True

                logging.error(f"[gbp] ❌ Falha publish fallback ({resp2.status_code}) url={url2} body={resp2.text}")
                logging.error(f"[gbp] ❌ Falha publish fallback-name ({resp2b.status_code}) url={url2b} body={resp2b.text}")
                return False

        logging.error(f"[gbp] ❌ Falha publish parts ({resp.status_code}) url={url} body={resp.text}")
        logging.error(f"[gbp] ❌ Falha publish name ({resp_name.status_code}) url={url_name} body={resp_name.text}")
        return False

    except Exception:
        logging.exception("[gbp] ❌ Erro inesperado no publish")
        return False


# ---------------------------------------------------------
# ✅ SUA FUNÇÃO DE SALVAR NO BANCO (MANTIDA IGUAL)
# ---------------------------------------------------------
def _upsert_review(
    user_id: str,
    r: Dict,
    reply_text: str,
    location_name: Optional[str] = None,
) -> None:
    """
    Salva ou atualiza uma avaliação automática do Google no banco.

    Regras:
    - Preserva respostas existentes (existing.reply / existing.replied).
    - Só grava reply se ainda NÃO estava replied e reply_text veio preenchido.
    - VINCULA a ficha correta via Review.google_location_id usando GoogleLocation (FK).
    - Normaliza location_id: aceita "locations/123" ou "123".
    """

    rid = r.get("reviewId")
    if not rid:
        logging.warning("[gbp] Review recebida sem reviewId — ignorando.")
        return

    # ---- Helpers locais ----
    def _extract_location_id(loc: Optional[str]) -> Optional[str]:
        if not loc:
            return None
        # Pode vir "locations/123", "accounts/.../locations/123" ou só "123"
        return loc.split("/")[-1].strip() if "/" in loc else loc.strip()

    tz_brt = pytz.timezone("America/Sao_Paulo")

    # ---- Extrai dados básicos ----
    star_str = r.get("starRating")
    stars = converter_nota_gbp_para_int(star_str)
    text = r.get("comment") or ""
    name = (r.get("reviewer") or {}).get("displayName") or "Cliente"
    create_time = r.get("createTime")

    # Data (sempre em BRT)
    dt = _now_brt()
    if create_time:
        try:
            dt_utc = datetime.fromisoformat(create_time.replace("Z", "+00:00"))
            dt = dt_utc.astimezone(tz_brt)
        except Exception:
            pass

    # ---- 🔗 Vínculo com GoogleLocation ----
    db_location_id = None
    loc_id = _extract_location_id(location_name)
    if loc_id:
        ficha_db = (
            GoogleLocation.query
            .filter(
                GoogleLocation.user_id == user_id,
                GoogleLocation.location_id.in_([loc_id, f"locations/{loc_id}"])
            )
            .first()
        )

        if ficha_db:
            db_location_id = ficha_db.id

    try:
        existing = Review.query.filter_by(user_id=user_id, external_id=rid).first()

        if existing:
            # Atualiza campos "do Google"
            existing.rating = stars
            existing.text = text
            existing.source = "google"
            existing.reviewer_name = name
            existing.date = dt

            # Mantém location_name por compatibilidade (pode ser "locations/123")
            if location_name:
                existing.location_name = location_name

            # Vincula FK se achou a ficha (não sobrescreve com None)
            if db_location_id and existing.google_location_id != db_location_id:
                existing.google_location_id = db_location_id


            # ✅ Preserva resposta existente: só grava reply se ainda não replied
            if not existing.replied and reply_text:
                existing.reply = reply_text
                existing.replied = True

            if hasattr(existing, "is_auto"):
                existing.is_auto = True
            if hasattr(existing, "auto_origin"):
                existing.auto_origin = "gbp"

            db.session.commit()
            return

        # Não existe no BD ainda → cria
        review_data = {
            "user_id": user_id,
            "source": "google",
            "external_id": rid,
            "reviewer_name": name,
            "rating": stars,
            "text": text,
            "reply": reply_text,
            "replied": bool(reply_text),
            "date": dt,
            "location_name": location_name,            # compat
            "google_location_id": db_location_id,      # FK certo
            "is_auto": True,
            "auto_origin": "gbp",
        }

        review = Review(**review_data)
        db.session.add(review)
        db.session.commit()

    except Exception as e:
        db.session.rollback()
        logging.exception(f"[gbp] ❌ Erro ao salvar review {rid}: {e}")
@google_auto_bp.route("/debug/review_find_any/<external_id>", methods=["GET"])
def debug_review_find_any(external_id):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"ok": False, "error": "no user"}), 401

    creds = _get_persisted_credentials(user_id) or _get_session_credentials()
    if not creds:
        return jsonify({"ok": False, "error": "no creds"}), 401

    rid = quote(external_id, safe="")

    accounts = _list_all_accounts(creds)
    all_locations = _list_all_locations(creds, accounts)

    for loc in all_locations:
        account_ref = loc.get("account_name")
        location_ref = loc.get("location_name")   # "locations/..."
        location_id = _extract_id(location_ref)

        if not account_ref or not location_id:
            continue

        reviews = _list_reviews(creds, account_ref, location_id)
        if any((r.get("reviewId") == external_id) for r in (reviews or [])):
            return jsonify({
                "ok": True,
                "found": True,
                "account_ref": account_ref,
                "location_ref": f"locations/{location_id}",
                "location_title": loc.get("location_title"),
            })

    return jsonify({"ok": True, "found": False})
def _persist_account_fix(user_id: str, location_id: str, account_ref: str) -> None:
    try:
        loc_id = _extract_id(location_id) or location_id
        gl = GoogleLocation.query.filter(
            GoogleLocation.user_id == user_id,
            GoogleLocation.location_id.in_([loc_id, f"locations/{loc_id}"])
        ).first()

        if gl and gl.account_id != account_ref:
            gl.account_id = account_ref
            db.session.commit()
            logging.info(f"[gbp] 🔧 Corrigido account_id da location {loc_id} -> {account_ref}")
    except Exception:
        db.session.rollback()
        logging.exception("[gbp] Falha ao persistir account fix")

@google_auto_bp.route("/configurar", methods=["GET", "POST"])
def configurar_automacao_google():
    user_info = session.get("user_info") or {}
    user_id = user_info.get("id")
    if not user_id:
        flash("Faça login novamente.", "danger")
        return redirect(url_for("authorize"))

    settings = UserSettings.query.filter_by(user_id=user_id).first()
    if not settings:
        settings = UserSettings(user_id=user_id)
        db.session.add(settings)
        db.session.commit()

    if settings.plano == "free":
        flash("Seu plano atual não inclui automação do Google.", "danger")
        return redirect(url_for("planos"))

    if request.method == "POST":
        wants_to_enable = request.form.get("ativar") is not None
        
        if wants_to_enable:
            ficha_ativa = GoogleLocation.query.filter_by(user_id=user_id, is_active=True).first()
            if not ficha_ativa:
                flash("⚠️ Selecione uma ficha do Google primeiro.", "warning")
                return redirect(url_for("google_auto.configurar_automacao_google"))

        settings.gbp_auto_enabled = wants_to_enable
        settings.gbp_tone = request.form.get("tone")
        db.session.commit()
        
        msg = "Automação ativada!" if wants_to_enable else "Automação desligada."
        flash(msg, "success" if wants_to_enable else "info")
        return redirect(url_for("google_auto.configurar_automacao_google"))

    from admin import get_historical_sync_prices
    historical = get_historical_sync_prices()
    ficha_ativa = GoogleLocation.query.filter_by(user_id=user_id, is_active=True).first()

    return render_template(
        "configurar_automacao_google.html",
        settings=settings,
        historical=historical,
        ficha_ativa=ficha_ativa 
    )

def _generate_reply_for(user_id: str, stars: int, text: str, reviewer_name: str, is_hiper_enabled: bool, location_db_obj: Optional[GoogleLocation] = None) -> str:
    try:
        from main import client as openai_client
        from main import get_user_settings

        settings = get_user_settings(user_id)

        def pick(field_ficha, key_global):
            if location_db_obj and getattr(location_db_obj, field_ficha, None):
                return getattr(location_db_obj, field_ficha)
            return settings.get(key_global, "")

        business_name = pick("business_name", "business_name")
        manager_name = pick("manager_name", "manager_name")
        contact_info = pick("contact_info", "contact_info")
        greeting = pick("default_greeting", "default_greeting")
        closing = pick("default_closing", "default_closing")
        contexto = pick("contexto_personalizado", "contexto_personalizado")

        tone = settings.get("gbp_tone")
        tone_instruction = {
            "empatico": "Demonstre empatia e cuidado.",
            "profissional": "Mantenha tom neutro e educado.",
        }.get(tone, "Seja cordial e útil.")

        assinatura = business_name
        if manager_name:
            assinatura += f"\n{manager_name}"

        prompt = ""
        if contexto:
            prompt += f"🚨 INSTRUÇÃO DE CONTEXTO DA LOJA: {contexto}\n\n"

        prompt += f"""
Você é um assistente de atendimento ao cliente da empresa "{business_name}".
Avaliação recebida:
- Nome: {reviewer_name}
- Nota: {stars} estrelas
- Texto: "{text}"

Responda começando com: "{greeting} {reviewer_name},"
- {tone_instruction}
- Reescreva com naturalidade
- Feche com "{closing}"
- Contato: {contact_info}
- Assine:
{assinatura}
"""
        if is_hiper_enabled:
            prompt += "\n\n**Gere uma resposta mais longa, empática e detalhada.**"

        cp = openai_client.with_options(timeout=30.0).chat.completions.create(
            model="gpt-4o-mini", # Use um modelo válido
            messages=[
                {"role": "system", "content": "Você é um assistente cordial e empático."},
                {"role": "user", "content": prompt},
            ],
        )
        return (cp.choices[0].message.content or "").strip()
    except Exception:
        logging.exception("[gbp] Falha na geração da resposta com IA")
        return "Obrigado pelo seu feedback! Estamos sempre à disposição."


@google_auto_bp.route("/location/<path:location_id>/settings", methods=["GET", "POST"])
def configurar_ficha_especifica(location_id):
    user_id = get_current_user_id()
    if not user_id:
        return redirect(url_for("authorize"))

    # ✅ Normaliza: pode vir "locations/123" ou só "123"
    location_id_norm = _extract_id(location_id) or location_id

    ficha = GoogleLocation.query.filter_by(
        user_id=user_id,
        location_id=location_id_norm
    ).first()

    if not ficha:
        flash("Ficha não encontrada.", "danger")
        return redirect(url_for("google_auto.escolher_ficha_google"))

    if request.method == "POST":
        ficha.business_name = request.form.get("business_name") or None
        ficha.manager_name = request.form.get("manager_name") or None
        ficha.contact_info = request.form.get("contact_info") or None
        ficha.default_greeting = request.form.get("default_greeting") or None
        ficha.default_closing = request.form.get("default_closing") or None
        ficha.contexto_personalizado = request.form.get("contexto_personalizado") or None

        db.session.commit()
        flash(f"Configurações da unidade '{ficha.location_name}' salvas!", "success")
        return redirect(url_for("google_auto.escolher_ficha_google"))

    from main import get_user_settings
    global_settings = get_user_settings(user_id)

    return render_template(
        "google_location_settings.html",
        ficha=ficha,
        global_settings=global_settings,
    )

def run_sync_for_user(user_id: str) -> int:
    try:
        from main import (
            registrar_uso_resposta_especial,
            usuario_pode_usar_resposta_especial,
        )
    except ImportError:
        def usuario_pode_usar_resposta_especial(uid): return False
        def registrar_uso_resposta_especial(uid): pass

    logging.info(f"[gbp] ▶️ Sync iniciado para user_id={user_id}")

    creds = _get_persisted_credentials(user_id) or _get_session_credentials()
    if not creds:
        logging.warning("[gbp] Sem credenciais")
        return 0

    fichas_ativas = GoogleLocation.query.filter_by(user_id=user_id, is_active=True).all()
    if not fichas_ativas:
        logging.info("[gbp] Nenhuma ficha ativa")
        return 0

    # só IDs (sem "locations/")
    location_ids_ativas = {f.location_id for f in fichas_ativas}

    accounts = _list_all_accounts(creds)
    all_locations = _list_all_locations(creds, accounts)

    tz_brt = pytz.timezone("America/Sao_Paulo")
    agora = datetime.now(tz_brt)
    inicio_dia = agora.replace(hour=0, minute=0, second=0, microsecond=0)

    total_processadas = 0

    for loc in all_locations:
        account_ref = loc.get("account_name")      # "accounts/..." ou "userAccounts/..."
        location_ref = loc.get("location_name")    # "locations/..."
        location_id = _extract_id(location_ref)    # só o id

        if not account_ref or not location_id:
            continue

        if location_id not in location_ids_ativas:
            continue

        ficha_db = GoogleLocation.query.filter_by(user_id=user_id, location_id=location_id).first()

        reviews = _list_reviews(creds, account_ref, location_id)
        if not reviews:
            continue

        for r in reviews:
            rid = r.get("reviewId")
            if not rid:
                continue

            # ✅ não processa se já tem reply no Google
            google_replied = bool((r.get("reviewReply") or {}).get("comment"))
            if google_replied:
                continue

            # ✅ não processa se já existe localmente e está replied
            review_local = Review.query.filter_by(user_id=user_id, external_id=rid).first()
            if review_local and getattr(review_local, "replied", False):
                continue

            # ✅ se já salvou no BD (mesmo sem replied), não duplica
            if _already_saved(user_id, rid):
                continue

            # filtro: só hoje (BRT)
            create_time = r.get("createTime")
            if create_time:
                try:
                    dt_utc = datetime.fromisoformat(create_time.replace("Z", "+00:00"))
                    dt_brt = dt_utc.astimezone(tz_brt)
                    if dt_brt < inicio_dia:
                        continue
                except Exception:
                    pass

            stars = converter_nota_gbp_para_int(r.get("starRating"))
            text = r.get("comment") or ""
            name = (r.get("reviewer") or {}).get("displayName") or "Cliente"

            is_hiper = stars in (1, 2) and usuario_pode_usar_resposta_especial(user_id)

            reply = _generate_reply_for(
                user_id=user_id,
                stars=stars,
                text=text,
                reviewer_name=name,
                is_hiper_enabled=is_hiper,
                location_db_obj=ficha_db,
            )

            _upsert_review(
                user_id=user_id,
                r=r,
                reply_text=reply,
                location_name=location_ref,  # mantém "locations/xxx"
            )

            ok = _publish_reply(
                creds=creds,
                account_ref=account_ref,
                location_ref=location_id,   # pode ser só id
                review_id=rid,
                reply_text=reply,
                user_id_for_fallback=user_id,  # 👈 isso aqui
            )

            if ok:
                _update_local_reply_status(user_id, rid, reply, True)
                if is_hiper:
                    registrar_uso_resposta_especial(user_id)

            total_processadas += 1

    return total_processadas


def _update_local_reply_status(user_id: str, external_id: str, reply_text: Optional[str], is_auto: bool = True) -> bool:
    try:
        review = Review.query.filter_by(user_id=user_id, external_id=external_id).first()
        if not review:
            return False

        review.reply = reply_text
        review.replied = bool(reply_text)

        if hasattr(review, "is_auto"):
            review.is_auto = is_auto
        if hasattr(review, "auto_origin"):
            review.auto_origin = "gbp"

        db.session.commit()
        return True

    except Exception:
        db.session.rollback()
        return False


def register_gbp_cron(scheduler, app):
    import pytz
    def _gbp_job():
        with app.app_context():
            try:
                enabled = UserSettings.query.filter_by(gbp_auto_enabled=True).all()
                for s in enabled:
                    run_sync_for_user(s.user_id)
            except Exception:
                logging.exception("[gbp] 💥 Job diário falhou.")

    scheduler.add_job(
        id="gbp_daily_sync",
        func=_gbp_job,
        trigger="cron",
        hour=10,
        minute=15,
        timezone=pytz.timezone("America/Sao_Paulo"),
        replace_existing=True,
    )


@google_auto_bp.route("/excluir_reply/<external_id>", methods=["DELETE"])
def excluir_reply_auto(external_id):
    user_info = session.get("user_info") or {}
    user_id = user_info.get("id")
    if not user_id:
        return jsonify({"success": False, "message": "Usuário não autenticado"}), 401

    ok = gbp_excluir_resposta(user_id, external_id)

    if ok:
        _update_local_reply_status(user_id, external_id, None, False)
        return jsonify({"success": True, "message": "Resposta excluída com sucesso!"})
    else:
        return jsonify({"success": False, "message": "Erro ao excluir resposta no Google."}), 500


@google_auto_bp.route("/test-cron-google")
def test_cron_google():
    user_info = session.get("user_info") or {}
    user_id = user_info.get("id")
    if not user_id:
        return "Sem usuário logado", 401
    run_sync_for_user(user_id)
    return "Sincronização forçada concluída!"


@google_auto_bp.route("/test-token")
def test_token():
    from google.oauth2.credentials import Credentials
    creds_dict = session.get("credentials")
    if not creds_dict:
        return "❌ Nenhum token encontrado na sessão.", 401
    creds = Credentials(**creds_dict)
    scopes = creds.scopes or []
    return f"<h3>🔍 Escopos ativos:</h3><pre>{'<br>'.join(scopes)}</pre>"


@google_auto_bp.route("/editar_reply/<external_id>", methods=["POST"])
def editar_reply_auto(external_id):
    user_info = session.get("user_info") or {}
    user_id = user_info.get("id")
    if not user_id:
        return jsonify({"success": False, "message": "Usuário não autenticado"}), 401

    reply_text = request.json.get("reply_text")
    if not reply_text:
        return jsonify({"success": False, "message": "Texto de resposta ausente"}), 400

    data = _get_review_data_for_action(user_id, external_id)
    if not data or not data[0]: 
        return jsonify({"success": False, "message": "Falha ao obter dados da ficha."}), 400

    creds, account_name, location_name = data

    publicado = _publish_reply(
        creds,
        account_name,
        location_name,
        external_id,
        reply_text,
        user_id_for_fallback=user_id,  # 👈 ADD
    )


    if not publicado:
        return jsonify({"success": False, "message": "Falha na publicação do Google."}), 500

    _update_local_reply_status(user_id, external_id, reply_text, True)
    return jsonify({"success": True, "message": "Resposta atualizada com sucesso!"})

def _get_review_data_for_action(user_id: str, external_id: str):
    """
    Retorna (creds, account_id, location_id) usando o vínculo Review -> GoogleLocation.
    """
    review = Review.query.filter_by(user_id=user_id, external_id=external_id).first()
    if not review:
        return None, None, None

    # 1) melhor caminho: FK
    gl = None
    if review.google_location_id:
        gl = GoogleLocation.query.filter_by(id=review.google_location_id, user_id=user_id).first()

    # 2) fallback: tenta mapear por location_name antigo (se tiver review antiga)
    if not gl and review.location_name:
        # se location_name guardar "locations/123" ou só "123", normaliza:
        loc_id = review.location_name.split("/")[-1]
        gl = GoogleLocation.query.filter(
            GoogleLocation.user_id == user_id,
            GoogleLocation.location_id.in_([loc_id, f"locations/{loc_id}"])
        ).first()


    if not gl:
        logging.warning(f"[gbp] Sem GoogleLocation para review={external_id}.")
        return None, None, None

    creds = _get_persisted_credentials(user_id) or _get_session_credentials()
    if not creds:
        return None, None, None

    if not gl.account_id or not gl.location_id:
        return None, None, None

    return creds, gl.account_id, gl.location_id

@google_auto_bp.route("/debug/refresh_db", methods=["GET"])
def refresh_db_link():
    user_id = get_current_user_id()
    if not user_id:
        return redirect(url_for("authorize"))

    csrf = generate_csrf()
    html = """
    <!doctype html>
    <html>
      <head><meta charset="utf-8"><title>Refresh DB</title></head>
      <body style="font-family: Arial; padding: 20px;">
        <p>🔄 Atualizando banco com dados do Google... aguarde.</p>
        <form id="f" method="POST" action="{{ url_for('google_auto.refresh_db_run') }}">
          <input type="hidden" name="csrf_token" value="{{ csrf }}">
          <input type="hidden" name="hours" value="720">
          <input type="hidden" name="fix_external" value="1">
        </form>
        <script>document.getElementById('f').submit();</script>
      </body>
    </html>
    """
    return render_template_string(html, csrf=csrf)





def _parse_google_time(create_time: str | None) -> datetime | None:
    if not create_time:
        return None
    try:
        return datetime.fromisoformat(create_time.replace("Z", "+00:00"))
    except Exception:
        return None

@google_auto_bp.route("/debug/fix_external", methods=["POST"])
def debug_fix_external():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"ok": False, "error": "no user"}), 401

    data = request.get_json(silent=True) or {}
    old_id = (data.get("old_external_id") or "").strip()
    new_id = (data.get("new_external_id") or "").strip()

    if not old_id or not new_id:
        return jsonify({"ok": False, "error": "old_external_id e new_external_id obrigatórios"}), 400

    # segurança: não deixa sobrescrever se já existir new_id
    if Review.query.filter_by(user_id=user_id, external_id=new_id).first():
        return jsonify({"ok": False, "error": "new_external_id já existe no DB"}), 409

    r = Review.query.filter_by(user_id=user_id, external_id=old_id).first()
    if not r:
        return jsonify({"ok": False, "error": "old_external_id não encontrado"}), 404

    r.external_id = new_id
    db.session.commit()

    return jsonify({"ok": True, "fixed": True, "review_db_id": r.id, "external_id": r.external_id})
@google_auto_bp.route("/debug/db_reviews", methods=["GET"])
def debug_db_reviews():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"ok": False, "error": "no user"}), 401

    qs = (Review.query
          .filter_by(user_id=user_id, source="google")
          .order_by(Review.date.desc())
          .limit(20)
          .all())

    return jsonify({
        "ok": True,
        "count": len(qs),
        "reviews": [{
            "id": r.id,
            "external_id": r.external_id,
            "rating": r.rating,
            "reviewer_name": r.reviewer_name,
            "date": r.date.isoformat() if r.date else None,
            "google_location_id": getattr(r, "google_location_id", None),
            "location_name": getattr(r, "location_name", None),
            "text_head": (r.text or "")[:60],
        } for r in qs]
    })


def _norm_loc_id(x: str | None) -> str | None:
    if not x:
        return None
    return x.split("/")[-1].strip()



def _norm_text(s: str) -> str:
    return " ".join((s or "").strip().lower().split())

def refresh_db_from_google(user_id: str, lookback_hours: int = 720, fix_external_ids: bool = True) -> dict:
    """
    Atualiza o banco com os dados do Google:
    - Upsert em GoogleLocation (account_id/location_id normalizados)
    - Puxa reviews e upserta em Review (external_id = reviewId)
    - (opcional) tenta corrigir external_id errado por match (nome/nota/texto)
    """
    creds = _get_persisted_credentials(user_id) or _get_session_credentials()
    if not creds:
        return {"ok": False, "error": "Sem credenciais"}

    accounts = _list_all_accounts(creds)
    all_locations = _list_all_locations(creds, accounts)

    # --- 1) UPSERT LOCATIONS ---
    created_locs = 0
    updated_locs = 0

    for loc in all_locations:
        account_ref = loc.get("account_name")
        location_ref = loc.get("location_name")
        title = loc.get("location_title")

        loc_id = _norm_loc_id(location_ref)
        if not account_ref or not loc_id:
            continue

        gl = GoogleLocation.query.filter(
            GoogleLocation.user_id == user_id,
            GoogleLocation.location_id.in_([loc_id, f"locations/{loc_id}"])
        ).first()

        if not gl:
            gl = GoogleLocation(
                user_id=user_id,
                account_id=account_ref,
                location_id=loc_id,
                location_name=title or "Sem nome",
            )
            db.session.add(gl)
            created_locs += 1
        else:
            changed = False
            if gl.account_id != account_ref:
                gl.account_id = account_ref
                changed = True
            if gl.location_id != loc_id:
                gl.location_id = loc_id
                changed = True
            if title and gl.location_name != title:
                gl.location_name = title
                changed = True
            if changed:
                updated_locs += 1

    db.session.commit()

    # --- 2) PUXA REVIEWS E SALVA ---
    cutoff = None
    if lookback_hours and lookback_hours > 0:
        cutoff = datetime.now(pytz.UTC) - timedelta(hours=lookback_hours)

    fetched = 0
    inserted = 0
    updated = 0
    fixed_external = 0

    locs_db = GoogleLocation.query.filter_by(user_id=user_id).all()

    for gl in locs_db:
        if not gl.account_id or not gl.location_id:
            continue

        reviews = _list_reviews(creds, gl.account_id, gl.location_id) or []
        if not reviews:
            continue

        for r in reviews:
            rid = (r.get("reviewId") or "").strip()
            if not rid:
                continue

            dt_utc = _parse_google_time(r.get("createTime"))
            if cutoff and dt_utc and dt_utc < cutoff:
                continue

            fetched += 1

            # 1) Já existe por reviewId correto
            existing = Review.query.filter_by(user_id=user_id, external_id=rid).first()
            if existing:
                _upsert_review(
                    user_id=user_id,
                    r=r,
                    reply_text="",  # não sobrescreve reply
                    location_name=f"locations/{gl.location_id}",
                )
                updated += 1
                continue

            # 2) Tenta corrigir external_id errado (match por conteúdo)
            if fix_external_ids:
                stars = converter_nota_gbp_para_int(r.get("starRating"))
                name = ((r.get("reviewer") or {}).get("displayName") or "Cliente").strip()
                text_norm = _norm_text(r.get("comment") or "")

                cand_q = Review.query.filter_by(user_id=user_id, source="google") \
                    .filter(Review.rating == stars) \
                    .filter(Review.reviewer_name == name) \
                    .order_by(Review.date.desc())

                if hasattr(Review, "google_location_id") and gl.id:
                    cand_q = cand_q.filter(
                        (Review.google_location_id == gl.id) | (Review.google_location_id.is_(None))
                    )

                cand = cand_q.first()
                if cand:
                    cand_text_norm = _norm_text(cand.text or "")
                    if cand_text_norm == text_norm and cand.external_id != rid:
                        if not Review.query.filter_by(user_id=user_id, external_id=rid).first():
                            cand.external_id = rid
                            if hasattr(cand, "google_location_id"):
                                cand.google_location_id = gl.id
                            cand.location_name = f"locations/{gl.location_id}"
                            db.session.commit()
                            fixed_external += 1
                            continue

            # 3) Não existia -> insere novo
            _upsert_review(
                user_id=user_id,
                r=r,
                reply_text="",  # só salvar
                location_name=f"locations/{gl.location_id}",
            )
            inserted += 1

    return {
        "ok": True,
        "locations_created": created_locs,
        "locations_updated": updated_locs,
        "reviews_fetched": fetched,
        "reviews_inserted": inserted,
        "reviews_updated": updated,
        "reviews_external_fixed": fixed_external,
        "lookback_hours": lookback_hours,
    }

    

@google_auto_bp.route("/debug/refresh_db/run", methods=["GET"])
def debug_refresh_db_run():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"ok": False, "error": "no user"}), 401

    lookback_hours = int(request.args.get("lookback_hours", "720"))
    fix_external_ids = request.args.get("fix_external_ids", "1") == "1"

    res = refresh_db_from_google(
        user_id=user_id,
        lookback_hours=lookback_hours,
        fix_external_ids=fix_external_ids
    )
    return jsonify(res)

@google_auto_bp.route("/debug/fix_review_db/<int:db_review_id>", methods=["GET"])
def debug_fix_review_db(db_review_id: int):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"ok": False, "error": "no user"}), 401

    rv = Review.query.filter_by(id=db_review_id, user_id=user_id).first()
    if not rv:
        return jsonify({"ok": False, "error": "review db não encontrada"}), 404

    creds = _get_persisted_credentials(user_id) or _get_session_credentials()
    if not creds:
        return jsonify({"ok": False, "error": "Sem credenciais"}), 401

    target_stars = int(rv.rating or 0)
    target_name = (rv.reviewer_name or "").strip()
    target_text = _norm_text(rv.text or "")

    accounts = _list_all_accounts(creds)
    locs = _list_all_locations(creds, accounts)

    for loc in locs:
        account_ref = loc.get("account_name")
        location_ref = loc.get("location_name")
        loc_id = _norm_loc_id(location_ref)

        if not account_ref or not loc_id:
            continue

        reviews = _list_reviews(creds, account_ref, loc_id) or []
        for r in reviews:
            rid = (r.get("reviewId") or "").strip()
            if not rid:
                continue

            stars = converter_nota_gbp_para_int(r.get("starRating"))
            name = ((r.get("reviewer") or {}).get("displayName") or "Cliente").strip()
            text = _norm_text(r.get("comment") or "")

            if stars == target_stars and name == target_name and text == target_text:
                # garante GoogleLocation
                gl = GoogleLocation.query.filter_by(user_id=user_id, location_id=loc_id).first()
                if not gl:
                    gl = GoogleLocation(
                        user_id=user_id,
                        account_id=account_ref,
                        location_id=loc_id,
                        location_name=loc.get("location_title") or "Sem nome",
                    )
                    db.session.add(gl)
                    db.session.commit()
                else:
                    # atualiza account_id se mudou
                    if gl.account_id != account_ref:
                        gl.account_id = account_ref
                        db.session.commit()

                # evita conflito (se já existe review com esse rid)
                other = Review.query.filter_by(user_id=user_id, external_id=rid).first()
                if other and other.id != rv.id:
                    return jsonify({
                        "ok": False,
                        "error": "Já existe uma review no DB com esse reviewId do Google",
                        "google_reviewId": rid,
                        "db_existing_id": other.id,
                        "db_target_id": rv.id
                    }), 409

                rv.external_id = rid
                rv.location_name = f"locations/{loc_id}"
                if hasattr(rv, "google_location_id"):
                    rv.google_location_id = gl.id
                db.session.commit()

                return jsonify({
                    "ok": True,
                    "fixed": True,
                    "db_id": rv.id,
                    "new_external_id": rv.external_id,
                    "account_ref": account_ref,
                    "location_id": loc_id
                })

    return jsonify({"ok": True, "fixed": False, "error": "Não achei essa review no Google por match"}), 404



def _get_or_create_google_location(user_id: str, account_name: str, location_name: str, title: str | None = None) -> GoogleLocation:
    account_ref = account_name
    location_id = _extract_id(location_name)

    gl = GoogleLocation.query.filter(
        GoogleLocation.user_id == user_id,
        GoogleLocation.location_id.in_([location_id, f"locations/{location_id}"])
    ).first()

    if not gl:
        gl = GoogleLocation(
            user_id=user_id,
            account_id=account_ref,
            location_id=location_id,
            location_name=title,
        )
        db.session.add(gl)
    else:
        gl.account_id = account_ref
        if title:
            gl.location_name = title

    db.session.commit()
    return gl



# ---------------------------------------------------------
# 🚨 CORREÇÃO CRÍTICA API V1 (Delete Reply)
# ---------------------------------------------------------
def _delete_reply(creds: Credentials, account_ref: str, location_ref: str, review_id: str) -> bool:
    try:
        headers = _make_auth_headers(creds)

        account_ref = _ensure_account_ref(account_ref)
        location_ref = _ensure_location_ref(_extract_id(location_ref) or location_ref)

        rid_safe = quote(review_id, safe="")

        url = f"https://mybusiness.googleapis.com/v4/{account_ref}/{location_ref}/reviews/{rid_safe}/reply"
        resp = requests.delete(url, headers=headers, timeout=10)

        ok = resp.status_code in (200, 204)
        if not ok:
            logging.error(f"[gbp] ❌ Falha delete ({resp.status_code}) url={url} body={resp.text}")
        return ok
    except Exception:
        logging.exception("[gbp] delete_reply falhou")
        return False




def gbp_excluir_resposta(user_id: str, external_review_id: str) -> bool:
    try:
        data = _get_review_data_for_action(user_id, external_review_id)
        if not data or not data[0]:
            return False

        creds, account_name, location_name = data
        return _delete_reply(creds, account_name, location_name, external_review_id)

    except Exception:
        return False
    
@google_auto_bp.route("/debug-reviews")
def debug_reviews():
    return "Use logs"

@google_auto_bp.route("/test-cron-all")
def test_cron_all():
    from flask import current_app, session
    user_info = session.get("user_info") or {}
    if not user_info.get("id"):
        return "Acesso não autorizado.", 401

    with current_app.app_context():
        try:
            enabled = UserSettings.query.filter_by(gbp_auto_enabled=True).all()
            total_geral = 0
            for s in enabled:
                total_geral += run_sync_last_48h(s.user_id)
            return f"Teste de 48h concluído! Total: {total_geral}", 200
        except Exception as e:
            return f"Erro: {e}", 500

def _list_all_locations(creds: Credentials, accounts: List[str]) -> List[Dict]:
    all_locations = []
    headers = _make_auth_headers(creds)

    for account_name in accounts:
        is_user_account = account_name.startswith("userAccounts/")

        # ======================================================
        # 1️⃣ Tenta API V1 (somente LOCATION_GROUP)
        # ======================================================
        if not is_user_account:
            url_v1 = f"https://mybusinessbusinessinformation.googleapis.com/v1/{account_name}/locations"
            params = {"readMask": "name,title"}

            try:
                resp = requests.get(url_v1, headers=headers, params=params, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    locs = data.get("locations", [])
                    for loc in locs:
                        all_locations.append({
                            "account_name": account_name,
                            "location_name": loc.get("name"),
                            "location_title": loc.get("title") or "Sem nome"
                        })
                    continue  # Achou via V1 → pula V4
            except Exception:
                pass

        # ======================================================
        # 2️⃣ Tenta API V4 (FUNCIONA PARA USER_ACCOUNT E GRUPO)
        # ======================================================
        try:
            url_v4 = f"https://mybusiness.googleapis.com/v4/{account_name}/locations"
            resp2 = requests.get(url_v4, headers=headers, timeout=10)
            if resp2.status_code == 200:
                data2 = resp2.json()
                locs2 = data2.get("locations", [])
                for loc in locs2:
                    all_locations.append({
                        "account_name": account_name,
                        "location_name": loc.get("name"),
                        "location_title": loc.get("locationName") or loc.get("title") or "Sem nome"
                    })
        except Exception:
            pass

    # Remove duplicatas
    unique = {loc["location_name"]: loc for loc in all_locations}.values()
    return list(unique)


def run_sync_last_48h(user_id: str) -> int:
    try:
        from main import registrar_uso_resposta_especial, usuario_pode_usar_resposta_especial
    except ImportError:
        def usuario_pode_usar_resposta_especial(uid): return False
        def registrar_uso_resposta_especial(uid): pass

    logging.info(f"\n[gbp] ▶️ Iniciando sync (48h) para {user_id}")

    creds = _get_persisted_credentials(user_id) or _get_session_credentials()
    if not creds:
        logging.warning("[gbp] Sem credenciais")
        return 0

    fichas_ativas = GoogleLocation.query.filter_by(user_id=user_id, is_active=True).all()
    if not fichas_ativas:
        logging.info("[gbp] Nenhuma ficha ativa")
        return 0

    location_ids_ativas = {f.location_id for f in fichas_ativas}

    accounts = _list_all_accounts(creds)
    all_locations = _list_all_locations(creds, accounts)

    tz_brt = pytz.timezone("America/Sao_Paulo")
    agora = datetime.now(tz_brt)
    limite = agora - timedelta(hours=48)

    total = 0

    for loc in all_locations:
        account_ref = loc.get("account_name")
        location_ref = loc.get("location_name")
        location_id = _extract_id(location_ref)

        if not account_ref or not location_id:
            continue

        if location_id not in location_ids_ativas:
            continue

        ficha_db = GoogleLocation.query.filter_by(user_id=user_id, location_id=location_id).first()

        reviews = _list_reviews(creds, account_ref, location_id)
        if not reviews:
            continue

        for r in reviews:
            rid = r.get("reviewId")
            if not rid:
                continue

            # ✅ não processa se já tem reply no Google
            google_replied = bool((r.get("reviewReply") or {}).get("comment"))
            if google_replied:
                continue

            # ✅ não processa se já existe localmente e está replied
            review_local = Review.query.filter_by(user_id=user_id, external_id=rid).first()
            if review_local and getattr(review_local, "replied", False):
                continue

            # ✅ se já salvou no BD, não duplica
            if _already_saved(user_id, rid):
                continue

            create_time = r.get("createTime")
            if create_time:
                try:
                    dt = datetime.fromisoformat(create_time.replace("Z", "+00:00")).astimezone(tz_brt)
                    if dt < limite:
                        continue
                except Exception:
                    pass

            stars = converter_nota_gbp_para_int(r.get("starRating"))
            text = r.get("comment") or ""
            name = (r.get("reviewer") or {}).get("displayName") or "Cliente"

            is_hiper = stars in (1, 2) and usuario_pode_usar_resposta_especial(user_id)

            reply = _generate_reply_for(
                user_id=user_id,
                stars=stars,
                text=text,
                reviewer_name=name,
                is_hiper_enabled=is_hiper,
                location_db_obj=ficha_db,
            )

            _upsert_review(
                user_id=user_id,
                r=r,
                reply_text=reply,
                location_name=location_ref,
            )

            if _publish_reply(
                creds=creds,
                account_ref=account_ref,
                location_ref=location_id,
                review_id=rid,
                reply_text=reply,
                user_id_for_fallback=user_id,  # 👈 ADD
            ):
                _update_local_reply_status(user_id, rid, reply, True)
                if is_hiper:
                    registrar_uso_resposta_especial(user_id)

            total += 1

    return total



def run_sync_historical(user_id: str, period: str) -> int:
    try:
        from main import registrar_uso_resposta_especial, usuario_pode_usar_resposta_especial
    except ImportError:
        def usuario_pode_usar_resposta_especial(uid): return False
        def registrar_uso_resposta_especial(uid): pass

    logging.info(f"\n[gbp] ▶️ Sync histórica para {user_id} ({period})")

    creds = _get_persisted_credentials(user_id) or _get_session_credentials()
    if not creds:
        logging.warning("[gbp] Sem credenciais")
        return 0

    fichas_ativas = GoogleLocation.query.filter_by(user_id=user_id, is_active=True).all()
    if not fichas_ativas:
        logging.info("[gbp] Nenhuma ficha ativa")
        return 0

    # só IDs (sem "locations/")
    location_ids_ativas = {f.location_id for f in fichas_ativas}

    accounts = _list_all_accounts(creds)
    all_locations = _list_all_locations(creds, accounts)

    tz_brt = pytz.timezone("America/Sao_Paulo")
    agora = datetime.now(tz_brt)

    dias = None if period == "all" else int(period)
    limite = (agora - timedelta(days=dias)) if dias else None

    total = 0

    for loc in all_locations:
        account_ref = loc.get("account_name")      # "accounts/..." ou "userAccounts/..."
        location_ref = loc.get("location_name")    # "locations/..."
        location_id = _extract_id(location_ref)    # só o id

        if not account_ref or not location_id:
            continue

        # só processa se a ficha está ativa no seu DB
        if location_id not in location_ids_ativas:
            continue

        ficha_db = GoogleLocation.query.filter_by(user_id=user_id, location_id=location_id).first()

        reviews = _list_reviews(creds, account_ref, location_id)  # helper garante prefixos
        if not reviews:
            continue

        for r in reviews:
            rid = r.get("reviewId")
            if not rid:
                continue

            # pula se já está respondida no Google
            google_replied = bool((r.get("reviewReply") or {}).get("comment"))
            if google_replied:
                continue

            # pula se já respondida localmente
            review_local = Review.query.filter_by(user_id=user_id, external_id=rid).first()
            if review_local and getattr(review_local, "replied", False):
                continue

            # filtro por período (se não for "all")
            create_time = r.get("createTime")
            if limite and create_time:
                try:
                    dt = datetime.fromisoformat(create_time.replace("Z", "+00:00")).astimezone(tz_brt)
                    if dt < limite:
                        continue
                except Exception:
                    pass

            stars = converter_nota_gbp_para_int(r.get("starRating"))
            text = r.get("comment") or ""
            name = (r.get("reviewer") or {}).get("displayName") or "Cliente"

            is_hiper = stars in (1, 2) and usuario_pode_usar_resposta_especial(user_id)

            reply = _generate_reply_for(
                user_id=user_id,
                stars=stars,
                text=text,
                reviewer_name=name,
                is_hiper_enabled=is_hiper,
                location_db_obj=ficha_db,
            )

            _upsert_review(
                user_id=user_id,
                r=r,
                reply_text=reply,
                location_name=location_ref,  # mantém "locations/xxx" por compat
            )

            if _publish_reply(
                creds=creds,
                account_ref=account_ref,
                location_ref=location_id,
                review_id=rid,
                reply_text=reply,
                user_id_for_fallback=user_id,  # 👈 ADD
            ):
                _update_local_reply_status(user_id, rid, reply, True)
                if is_hiper:
                    registrar_uso_resposta_especial(user_id)

            total += 1

    return total


@google_auto_bp.route("/sync_historical/<period>", methods=["POST"])
def sync_historical(period):
    user_info = session.get("user_info") or {}
    user_id = user_info.get("id")
    if not user_id:
        return jsonify({"success": False, "message": "Usuário não autenticado."}), 401

    settings = UserSettings.query.filter_by(user_id=user_id).first()
    if settings and settings.plano == "free":
        return jsonify({"success": False, "message": "Plano Free não permite sync histórico."}), 402

    prices = get_historical_sync_prices()
    if period not in prices:
        return jsonify({"success": False, "message": "Período inválido."}), 400

    from stripe_pay import usar_credito_retro, usuario_tem_credito_retro
    if not usuario_tem_credito_retro(user_id, period):
        return jsonify({"success": False, "message": "Sem crédito para este período."}), 402

    price_cents = prices[period]["price_cents"]
    
    try:
        total = run_sync_historical(user_id, period)
        usar_credito_retro(user_id, period)
        return jsonify({
            "success": True, 
            "message": f"Sync concluído!", 
            "total_processadas": total,
            "price_cents": price_cents
        })
    except Exception as e:
        logging.exception(f"Erro sync histórico: {e}")
        return jsonify({"success": False, "message": "Erro interno."}), 500
    
    
RECONCILE_MIN_DAYS = 180  # ~6 meses

def reconcile_google_location(user_id: str, google_location_id: int, hard_delete: bool = True) -> dict:
    """
    Reconciliar UMA ficha:
    - busca reviews atuais no Google
    - upsert no BD (nota/texto/nome/data)
    - apaga do BD as reviews google que não existem mais no Google
    - limita 1x a cada 6 meses por ficha
    """

    # 1) pega ficha do BD e valida dono
    gl = GoogleLocation.query.filter_by(id=google_location_id, user_id=user_id).first()
    if not gl:
        return {"ok": False, "error": "Ficha não encontrada para este usuário."}

    # 2) trava 6 meses
        # 2) trava 6 meses
    now_utc = datetime.now(pytz.UTC)
    last = getattr(gl, "last_reconcile_at", None)

    if last:
        # normaliza timezone
        if last.tzinfo is None:
            last = pytz.UTC.localize(last)

        diff = now_utc - last
        if diff < timedelta(days=RECONCILE_MIN_DAYS):
            remaining = timedelta(days=RECONCILE_MIN_DAYS) - diff
            days_left = max(remaining.days, 0)
            return {
                "ok": False,
                "error": f"Reconcilição dessa ficha só pode rodar 1x a cada 6 meses. Faltam ~{days_left} dias."
            }


    # 3) credenciais
    creds = _get_persisted_credentials(user_id) or _get_session_credentials()
    if not creds:
        return {"ok": False, "error": "Sem credenciais Google."}

    if not gl.account_id or not gl.location_id:
        return {"ok": False, "error": "Ficha sem account_id/location_id no BD."}

    loc_id = str(gl.location_id).split("/")[-1].strip()

    # 4) puxa reviews do Google
    google_reviews = _list_reviews(creds, gl.account_id, loc_id) or []
    google_by_id = {}
    for r in google_reviews:
        rid = (r.get("reviewId") or "").strip()
        if rid:
            google_by_id[rid] = r

    google_ids = set(google_by_id.keys())

    # 5) pega reviews locais dessa ficha
    q_local = Review.query.filter_by(user_id=user_id, source="google")

    if hasattr(Review, "google_location_id"):
        q_local = q_local.filter(Review.google_location_id == gl.id)
    else:
        q_local = q_local.filter(Review.location_name == f"locations/{loc_id}")

    local_reviews = q_local.all()
    local_by_id = { (rv.external_id or "").strip(): rv for rv in local_reviews if rv.external_id }

    local_before = len(local_reviews)

    inserted = 0
    updated = 0
    deleted = 0

    # 6) UPSERT das reviews do Google
    for rid, r in google_by_id.items():
        existing = local_by_id.get(rid) or Review.query.filter_by(user_id=user_id, external_id=rid).first()

        # usa teu upsert (mas garantindo que atualize nota/texto etc)
        # IMPORTANTE: não sobrescrever resposta existente
        _upsert_review(
            user_id=user_id,
            r=r,
            reply_text="",  # não mexe em reply
            location_name=f"locations/{loc_id}",
        )

        if existing:
            updated += 1
        else:
            inserted += 1

        # garante vínculo com a ficha se existir coluna
        if existing and hasattr(existing, "google_location_id"):
            if existing.google_location_id != gl.id:
                existing.google_location_id = gl.id

    db.session.commit()

    # 7) DELETE: reviews locais que não existem mais no Google
    # (isso cobre review apagada e re-postada com novo id)
    to_delete = []
    for rv in local_reviews:
        rid = (rv.external_id or "").strip()
        if not rid:
            continue
        if rid not in google_ids:
            to_delete.append(rv)

    if to_delete:
        for rv in to_delete:
            if hard_delete:
                db.session.delete(rv)
            else:
                # se você preferir soft delete, crie campo status/deleted_on_google
                # rv.deleted_on_google = True
                pass
        db.session.commit()
        deleted = len(to_delete)

    # 8) marca última execução
    gl.last_reconcile_at = now_utc
    db.session.commit()

    return {
        "ok": True,
        "google_count": len(google_reviews),
        "local_before": local_before,
        "inserted": inserted,
        "updated": updated,
        "deleted": deleted,
        "google_location_id": gl.id,
        "location_id": loc_id,
        "account_id": gl.account_id,
        "ran_at": now_utc.isoformat(),
        "hard_delete": hard_delete,
    }


from datetime import datetime, timedelta
import pytz
from flask import jsonify, request
# já tem UserSettings, GoogleLocation, Review, db no arquivo


def _utcnow():
    return datetime.now(pytz.UTC)

@google_auto_bp.route("/google/reconcile/<int:google_location_id>", methods=["POST"])
def google_reconcile_location(google_location_id):
    # ✅ precisa estar logado (sessão)
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"ok": False, "error": "Usuário não autenticado"}), 401

    # ✅ só Business
    settings = UserSettings.query.filter_by(user_id=user_id).first()
    plano = ((settings.plano if settings else "free") or "free").lower().strip()
    if not plano.startswith("business"):
        return jsonify({"ok": False, "error": "Recurso disponível apenas no plano Business."}), 403


    # payload opcional
    hard_delete = True
    if request.is_json:
        hard_delete = bool(request.json.get("hard_delete", True))

    gl = GoogleLocation.query.filter_by(id=google_location_id, user_id=user_id).first()
    if not gl:
        return jsonify({"ok": False, "error": "Ficha não encontrada para este usuário."}), 404

    # ✅ trava 6 meses
    now_utc = _utcnow()
    last = getattr(gl, "last_reconcile_at", None)
    if last:
        if last.tzinfo is None:
            last = pytz.UTC.localize(last)
        if now_utc - last < timedelta(days=RECONCILE_MIN_DAYS):
            days_left = RECONCILE_MIN_DAYS - (now_utc - last).days
            return jsonify({
                "ok": False,
                "error": f"Essa ficha só pode reconciliar 1x a cada 6 meses. Faltam ~{days_left} dias."
            }), 429

    # ✅ credenciais
    creds = _get_persisted_credentials(user_id) or _get_session_credentials()
    if not creds:
        return jsonify({"ok": False, "error": "Sem credenciais Google."}), 401

    if not gl.account_id or not gl.location_id:
        return jsonify({"ok": False, "error": "Ficha sem account_id/location_id no BD."}), 400

    loc_id = str(gl.location_id).split("/")[-1].strip()

    # ✅ puxa reviews do Google (fonte da verdade)
    google_reviews = _list_reviews(creds, gl.account_id, loc_id) or []
    google_by_id = {}
    for r in google_reviews:
        rid = (r.get("reviewId") or "").strip()
        if rid:
            google_by_id[rid] = r
    google_ids = set(google_by_id.keys())

    # ✅ pega reviews locais dessa ficha
    q_local = Review.query.filter_by(user_id=user_id, source="google")
    if hasattr(Review, "google_location_id"):
        q_local = q_local.filter(Review.google_location_id == gl.id)
    else:
        # fallback antigo
        q_local = q_local.filter(Review.location_name == f"locations/{loc_id}")

    local_reviews = q_local.all()
    local_before = len(local_reviews)

    inserted = 0
    updated = 0
    deleted = 0

    # ✅ UPSERT/UPDATE com dados atuais do Google (sem mexer reply)
    for rid, r in google_by_id.items():
        existing = Review.query.filter_by(user_id=user_id, external_id=rid).first()

        google_reply = (r.get("reviewReply") or {}).get("comment") or ""

        _upsert_review(
            user_id=user_id,
            r=r,
            reply_text=google_reply,  # agora passa a resposta do Google (se tiver)
            location_name=f"locations/{loc_id}",
        )
        if existing:
            updated += 1
        else:
            inserted += 1

        # garante vínculo com ficha
        if hasattr(Review, "google_location_id"):
            rv2 = Review.query.filter_by(user_id=user_id, external_id=rid).first()
            if rv2 and rv2.google_location_id != gl.id:
                rv2.google_location_id = gl.id

    db.session.commit()

    # ✅ DELETE: tudo que tá no BD mas não existe mais no Google
    to_delete = []
    for rv in local_reviews:
        rid = (rv.external_id or "").strip()
        if rid and rid not in google_ids:
            to_delete.append(rv)

    if to_delete and hard_delete:
        for rv in to_delete:
            db.session.delete(rv)
        db.session.commit()
        deleted = len(to_delete)

    # ✅ marca última execução
    if hasattr(gl, "last_reconcile_at"):
        gl.last_reconcile_at = now_utc
        db.session.commit()

    return jsonify({
        "ok": True,
        "google_count": len(google_reviews),
        "local_before": local_before,
        "inserted": inserted,
        "updated": updated,
        "deleted": deleted,
        "google_location_id": gl.id,
        "location_id": loc_id,
        "account_id": gl.account_id,
        "ran_at": now_utc.isoformat(),
        "hard_delete": hard_delete,
    }), 200
def _get_active_location(user_id: str) -> GoogleLocation | None:
    return GoogleLocation.query.filter_by(user_id=user_id, is_active=True).first()

@google_auto_bp.route("/google/reconcile_active", methods=["POST"])
def google_reconcile_active():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"ok": False, "error": "Usuário não autenticado"}), 401

    settings = UserSettings.query.filter_by(user_id=user_id).first()
    plano = ((settings.plano if settings else "free") or "free").lower().strip()
    if not plano.startswith("business"):
        return jsonify({"ok": False, "error": "Recurso disponível apenas no plano Business."}), 403


    gl = _get_active_location(user_id)
    if not gl:
        return jsonify({"ok": False, "error": "Selecione uma ficha ativa antes de reconciliar."}), 400

    hard_delete = True
    if request.is_json:
        hard_delete = bool(request.json.get("hard_delete", True))

    # reaproveita sua função já pronta
    res = reconcile_google_location(user_id=user_id, google_location_id=gl.id, hard_delete=hard_delete)
    status = 200 if res.get("ok") else 400
    return jsonify(res), status


