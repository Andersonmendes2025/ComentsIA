from __future__ import annotations
import os
import logging
from datetime import datetime
from typing import Dict, List, Optional

from flask import (
    Blueprint, request, jsonify, session, redirect, url_for, flash, render_template, current_app
)
from flask_wtf.csrf import generate_csrf
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from models import db, Review, UserSettings
import requests

# --- Configuração do Blueprint ---
google_auto_bp = Blueprint("google_auto", __name__, url_prefix="/auto")
GBP_SCOPE = "https://www.googleapis.com/auth/business.manage"


# --- Funções utilitárias ---
def _now_brt() -> datetime:
    import pytz
    return datetime.now(pytz.timezone("America/Sao_Paulo"))


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


def _get_persisted_credentials(user_id: str) -> Optional[Credentials]:
    try:
        settings = UserSettings.query.filter_by(user_id=user_id).first()
        refresh_token = getattr(settings, "google_refresh_token", None)
        if not refresh_token:
            return None
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.getenv("GOOGLE_CLIENT_ID"),
            client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
            scopes=[GBP_SCOPE],
        )
        creds.refresh(Request())
        return creds
    except Exception:
        logging.exception("[gbp] Falha ao reconstruir credenciais persistidas")
        return None


def _make_auth_headers(creds: Credentials) -> dict:
    if creds and creds.valid and creds.token:
        return {"Authorization": f"Bearer {creds.token}"}
    return {}


# --- Funções principais da API GBP ---
def _first_account_name(creds: Credentials) -> Optional[str]:
    """Obtém a conta principal (LOCATION_GROUP ou PERSONAL)."""
    try:
        headers = _make_auth_headers(creds)
        url = "https://mybusinessaccountmanagement.googleapis.com/v1/accounts"
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            logging.warning(f"[gbp] Erro ao buscar contas: {resp.text}")
            return None

        data = resp.json()
        accounts = data.get("accounts", [])
        if not accounts:
            logging.warning("[gbp] Nenhuma conta encontrada no perfil Google Business.")
            return None

        # Prioriza LOCATION_GROUP
        location_groups = [a for a in accounts if a.get("type") == "LOCATION_GROUP"]
        selected = location_groups[0] if location_groups else accounts[0]
        logging.warning(f"[gbp] Conta detectada: {selected.get('name')} tipo={selected.get('type')} nome={selected.get('accountName')}")
        return selected.get("name")

    except Exception:
        logging.exception("[gbp] Erro ao obter contas")
        return None


def _first_location_name(creds: Credentials, account_name: str) -> Optional[str]:
    """
    Obtém a primeira ficha válida (location_name) para LOCATION_GROUP ou conta pessoal.
    Corrigido com o endpoint real ativo em 2025: mybusinessbusinessinformation.googleapis.com.
    """
    try:
        headers = _make_auth_headers(creds)
        account_id = account_name.split("/")[-1]

        # ✅ 1️⃣ Novo endpoint ativo (LOCATION_GROUP)
        url_group = f"https://mybusinessbusinessinformation.googleapis.com/v1/accounts/{account_id}/locations"
        params = {"readMask": "name,title,storeCode,metadata"}
        resp_group = requests.get(url_group, headers=headers, params=params, timeout=10)

        if resp_group.status_code == 200:
            data = resp_group.json()
            locations = data.get("locations", [])
            if locations:
                for loc in locations:
                    title = loc.get("title") or loc.get("storeCode") or "(sem título)"
                    logging.warning(f"[gbp] Ficha detectada (v1 group): {loc.get('name')} - {title}")
                return locations[0]["name"]
        else:
            logging.warning(f"[gbp] v1.locations (group) retornou {resp_group.status_code}: {resp_group.text}")

        # ✅ 2️⃣ Fallback para contas pessoais verificadas
        search_url = "https://mybusinessbusinessinformation.googleapis.com/v1/locations:search"
        search_body = {"query": "ComentsIA", "pageSize": 3}
        resp_search = requests.post(search_url, headers=headers, json=search_body, timeout=10)

        if resp_search.status_code == 200:
            data = resp_search.json()
            locations = data.get("locations", [])
            if locations:
                for loc in locations:
                    title = loc.get("title") or "(sem título)"
                    logging.warning(f"[gbp] Ficha detectada (search global): {loc.get('name')} - {title}")
                return locations[0]["name"]
        else:
            logging.warning(f"[gbp] search global retornou {resp_search.status_code}: {resp_search.text}")

        # ✅ 3️⃣ Fallback final: API v4 (somente para reviews)
        url_v4 = f"https://mybusiness.googleapis.com/v4/{account_name}/locations"
        resp_v4 = requests.get(url_v4, headers=headers, timeout=10)
        if resp_v4.status_code == 200:
            data = resp_v4.json()
            locations = data.get("locations", [])
            if locations:
                for loc in locations:
                    logging.warning(f"[gbp] Ficha detectada (v4 fallback): {loc.get('name')} - {loc.get('locationName')}")
                return locations[0]["name"]

        logging.warning(f"[gbp] Nenhuma ficha retornada. group={resp_group.status_code}, search={resp_search.status_code}, v4={resp_v4.status_code}")
        return None

    except Exception:
        logging.exception("[gbp] failed to fetch locations (finalized)")
        return None

# google_auto.py

# google_auto.py (Função _list_reviews atualizada para fallback)

def _list_reviews(creds: Credentials, location_name: str) -> List[Dict]:
    """
    Lista as avaliações da ficha (location_name).
    Tenta primeiro a API v4 e, se falhar (ex: 404/403), tenta o endpoint v1 (Performance API).
    """
    try:
        headers = _make_auth_headers(creds)
        all_reviews = []
        page_token = None
        
        # 1. Tenta API V4 (Google My Business API - Ideal para Leitura e Resposta)
        base_url_v4 = f"https://mybusiness.googleapis.com/v4/{location_name}/reviews"
        logging.info(f"[gbp] Tentando API V4: {base_url_v4}")
        
        # Loop para V4
        while True:
            params = {"pageSize": 50}
            if page_token:
                params["pageToken"] = page_token

            resp = requests.get(base_url_v4, headers=headers, params=params, timeout=15)

            if resp.status_code == 200:
                # Sucesso: Retorna as avaliações
                data = resp.json()
                reviews = data.get("reviews", [])
                all_reviews.extend(reviews)
                page_token = data.get("nextPageToken")
                if not page_token:
                    logging.info(f"[gbp] ✅ V4 OK. {len(all_reviews)} avaliações carregadas.")
                    return all_reviews 
            
            # Falha V4 (404/403/Outro): Tentamos o fallback e quebramos o loop
            elif resp.status_code in [404, 403]:
                logging.warning(f"[gbp] API V4 falhou com {resp.status_code}. Tentando fallback V1...")
                break
            else:
                logging.warning(f"[gbp] Erro inesperado V4 ({resp.status_code}): {resp.text}. Tentando fallback V1...")
                break
            
        # 2. Fallback para API V1 (Business Profile Performance API - APENAS Leitura)
        location_id = location_name.split("/")[-1]
        base_url_v1 = f"https://businessprofileperformance.googleapis.com/v1/locations/{location_id}/reviews"
        logging.info(f"[gbp] Tentando Fallback V1: {base_url_v1}")

        page_token = None 
        while True:
            params = {"pageSize": 50}
            if page_token:
                params["pageToken"] = page_token
            
            resp = requests.get(base_url_v1, headers=headers, params=params, timeout=15)
            
            if resp.status_code == 200:
                data = resp.json()
                reviews = data.get("reviews", [])
                all_reviews.extend(reviews)
                page_token = data.get("nextPageToken")
                if not page_token:
                    logging.info(f"[gbp] ✅ Fallback V1 OK. {len(all_reviews)} avaliações carregadas.")
                    return all_reviews 
            else:
                logging.warning(f"[gbp] Fallback V1 falhou com {resp.status_code}: {resp.text}")
                break

        return all_reviews 

    except Exception:
        logging.exception("[gbp] Falha catastrófica ao buscar reviews")
        return []


def _already_saved(user_id: str, review_id: str) -> bool:
    return db.session.query(Review.id).filter_by(user_id=user_id, external_id=review_id).first() is not None


def _upsert_review(user_id: str, r: Dict, reply_text: str) -> None:
    rid = r.get("reviewId")
    stars = int(r.get("starRating") or 0)
    text = r.get("comment") or ""
    name = (r.get("reviewer") or {}).get("displayName") or "Cliente"
    create_time = r.get("createTime")

    dt = _now_brt()
    if create_time:
        try:
            dt = datetime.fromisoformat(create_time.replace("Z", "+00:00"))
        except Exception:
            pass

    review = Review(
        user_id=user_id,
        source="google",
        external_id=rid,
        reviewer_name=name,
        rating=stars,
        text=text,
        reply=reply_text,
        replied=bool(reply_text),
        date=dt,
    )
    db.session.add(review)
    db.session.commit()


def _publish_reply(creds: Credentials, location_name: str, review_id: str, reply_text: str):
    """Publica uma resposta diretamente no GBP."""
    try:
        headers = _make_auth_headers(creds)
        url = f"https://mybusiness.googleapis.com/v4/{location_name}/reviews/{review_id}/reply"
        payload = {"comment": reply_text}
        resp = requests.put(url, headers=headers, json=payload, timeout=10)
        if resp.status_code != 200:
            logging.warning(f"[gbp] Erro ao publicar resposta: {resp.text}")
    except Exception:
        logging.exception("[gbp] Falha ao publicar resposta")


def _generate_reply_for(user_id: str, stars: int, text: str, reviewer_name: str) -> str:
    """Gera uma resposta automática com IA."""
    try:
        from main import get_user_settings, client as openai_client
        settings = get_user_settings(user_id)

        tone = settings.get("gbp_tone")
        tone_instruction = {
            "empatico": "Demonstre empatia e cuidado.",
            "profissional": "Mantenha tom neutro e educado.",
            "informal": "Use linguagem leve e simpática.",
            "cordial": "Seja gentil e respeitoso."
        }.get(tone, "Seja cordial e útil.")

        assinatura = settings.get("business_name", "")
        if settings.get("manager_name"):
            assinatura += f"\n{settings['manager_name']}"

        prompt = f"""
Você é um assistente de atendimento ao cliente.
Avaliação:
- Nome: {reviewer_name}
- Nota: {stars} estrelas
- Texto: "{text}"

Responda começando com: "{settings['default_greeting']} {reviewer_name},"
- {tone_instruction}
- Reescreva com naturalidade
- Feche com "{settings['default_closing']}"
- Contato: {settings['contact_info']}
- Assine:
{assinatura}
"""
        cp = openai_client.with_options(timeout=30.0).chat.completions.create(
            model="gpt-5",
            messages=[
                {"role": "system", "content": "Você é um assistente cordial e empático."},
                {"role": "user", "content": prompt},
            ],
        )
        return (cp.choices[0].message.content or "").strip()
    except Exception:
        logging.exception("[gbp] Falha na geração da resposta com IA")
        return "Obrigado pelo seu feedback! Estamos sempre à disposição."


# --- Sincronização principal ---
def run_sync_for_user(user_id: str) -> int:
    logging.info(f"[gbp] Iniciando sincronização para usuário {user_id}")
    creds = _get_persisted_credentials(user_id) or _get_session_credentials()
    if not creds:
        logging.warning(f"[gbp] Sem credenciais válidas para o usuário {user_id}")
        return 0

    account = _first_account_name(creds)
    location = _first_location_name(creds, account)
    if not location:
        logging.warning(f"[gbp] Nenhuma ficha encontrada para {user_id}")
        return 0

    reviews = _list_reviews(creds, location)
    logging.info(f"[gbp] {len(reviews)} avaliações encontradas para {user_id}")

    count = 0
    for r in reviews:
        rid = r.get("reviewId")
        if not rid or _already_saved(user_id, rid):
            continue
        stars = int(r.get("starRating") or 0)
        text = r.get("comment") or ""
        name = (r.get("reviewer") or {}).get("displayName") or "Cliente"
        reply = _generate_reply_for(user_id, stars, text, name)
        _upsert_review(user_id, r, reply)
        _publish_reply(creds, location, rid, reply)
        count += 1

    logging.info(f"[gbp] ✅ Sincronização concluída ({count} novas avaliações)")
    return count


# --- Cron diário ---
def register_gbp_cron(scheduler):
    import pytz
    @scheduler.scheduled_job("cron", hour=1, minute=0, timezone=pytz.timezone("America/Sao_Paulo"))
    def _gbp_job():
        try:
            enabled = UserSettings.query.filter_by(gbp_auto_enabled=True).all()
            for s in enabled:
                run_sync_for_user(s.user_id)
        except Exception:
            logging.exception("[gbp] Job diário falhou")


# --- Rotas Flask ---
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

    if request.method == "POST":
        settings.gbp_auto_enabled = request.form.get("ativar") is not None
        settings.gbp_tone = request.form.get("tone")
        db.session.commit()
        flash("Configuração atualizada com sucesso!", "success")
        return redirect(url_for("google_auto.configurar_automacao_google"))

    return render_template("configurar_automacao_google.html", settings=settings)


@google_auto_bp.route("/test-cron-google")
def test_cron_google():
    enabled = UserSettings.query.filter_by(gbp_auto_enabled=True).all()
    for s in enabled:
        run_sync_for_user(s.user_id)
    return "Sincronização forçada concluída!"
