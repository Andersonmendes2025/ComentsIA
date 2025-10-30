from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pytz
import requests
from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_wtf.csrf import generate_csrf
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from models import Review, UserSettings, db

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


def _first_account_name(creds: Credentials) -> Optional[str]:
    """
    Obtém a conta principal do Google Business, priorizando LOCATION_GROUP (contas de grupo).
    Mantém compatibilidade com o fluxo atual, mas com logs e tratamento aprimorados.
    """
    try:
        headers = _make_auth_headers(creds)
        url = "https://mybusinessaccountmanagement.googleapis.com/v1/accounts"
        resp = requests.get(url, headers=headers, timeout=10)

        if resp.status_code != 200:
            logging.warning(
                f"[gbp] Erro ao buscar contas ({resp.status_code}): {resp.text}"
            )
            return None

        data = resp.json()
        accounts = data.get("accounts", [])
        if not accounts:
            logging.warning("[gbp] Nenhuma conta retornada pela API Google Business.")
            return None

        # Separa as contas por tipo
        location_groups = [a for a in accounts if a.get("type") == "LOCATION_GROUP"]
        personal_accounts = [a for a in accounts if a.get("type") == "USER_ACCOUNT"]

        # Loga todas as contas encontradas para depuração
        todas = ", ".join(
            f"{a.get('accountName', 'Sem nome')} ({a.get('type', '?')})"
            for a in accounts
        )
        logging.info(f"[gbp] Contas detectadas: {todas}")

        # Prioriza conta de grupo (LOCATION_GROUP)
        if location_groups:
            selected = location_groups[0]
            logging.info(
                f"[gbp] ✅ Conta de grupo selecionada: {selected.get('accountName')} "
                f"→ {selected.get('name')}"
            )
            return selected.get("name")

        # Caso não tenha grupo, usa a conta pessoal
        if personal_accounts:
            selected = personal_accounts[0]
            logging.info(
                f"[gbp] ⚙️ Conta pessoal selecionada: {selected.get('accountName')} "
                f"→ {selected.get('name')}"
            )
            return selected.get("name")

        # Nenhuma válida
        logging.warning("[gbp] Nenhuma conta válida encontrada.")
        return None

    except requests.RequestException as e:
        logging.warning(f"[gbp] Erro de conexão com API Google: {e}")
        return None
    except Exception:
        logging.exception("[gbp] Falha inesperada ao obter conta principal")
        return None


# --- Funções principais da API GBP ---


def _first_location_name(creds: Credentials, account_name: str) -> Optional[str]:
    """
    Obtém a primeira ficha (location) da conta Google Business.
    Compatível com contas pessoais (USER_ACCOUNT) e contas de grupo (LOCATION_GROUP).
    """
    try:
        if not account_name:
            logging.warning("[gbp] Conta vazia ao tentar obter locations.")
            return None

        headers = _make_auth_headers(creds)
        account_id = account_name.split("/")[-1]

        # Parâmetro obrigatório para V1 (Business Information API)
        params = {"readMask": "name,title"}

        # 1️⃣ Nova API Business Information (contas de grupo / organização)
        url_v1 = f"https://mybusinessbusinessinformation.googleapis.com/v1/accounts/{account_id}/locations"
        resp = requests.get(
            url_v1, headers=headers, params=params, timeout=10
        )  # Usa params

        if resp.status_code == 200:
            data = resp.json()
            locs = data.get("locations", [])
            if locs:
                loc = locs[0]
                logging.info(
                    f"[gbp] Ficha encontrada (v1): {loc.get('name')} - {loc.get('title')}"
                )
                return loc.get("name")
            logging.warning(f"[gbp] Nenhuma ficha retornada via v1 para {account_name}")
        else:
            logging.warning(
                f"[gbp] Falha ao listar fichas (v1) ({resp.status_code}): {resp.text}"
            )

        # 2️⃣ Fallback para a API V4
        # NOTE: A API V4 não exige o readMask para /locations no V4 de Management.
        url_v4 = f"https://mybusiness.googleapis.com/v4/accounts/{account_id}/locations"
        resp2 = requests.get(url_v4, headers=headers, timeout=10)

        if resp2.status_code == 200:
            data = resp2.json()
            locs = data.get("locations", [])
            if locs:
                loc = locs[0]
                logging.info(
                    f"[gbp] Ficha encontrada (v4 fallback): {loc.get('name')} - {loc.get('locationName')}"
                )
                return loc.get("name")
            else:
                logging.warning(
                    f"[gbp] Nenhuma ficha retornada via v4 para {account_name}"
                )
        else:
            logging.warning(
                f"[gbp] Falha ao listar fichas (v4) ({resp2.status_code}): {resp2.text}"
            )

        logging.warning(
            f"[gbp] Nenhuma ficha encontrada para {account_name} após todas as tentativas."
        )
        return None

    except Exception:
        logging.exception("[gbp] Erro ao obter locationId")
        return None

def _list_all_accounts(creds: Credentials) -> List[str]:
    """
    Retorna uma lista com TODAS as contas do Google Business disponíveis
    (LOCATION_GROUP e USER_ACCOUNT), priorizando as de grupo,
    com fallback para V4 userAccounts e, por fim, /v4/accounts (perfil pessoal).
    """
    headers = _make_auth_headers(creds)
    url_v1 = "https://mybusinessaccountmanagement.googleapis.com/v1/accounts"

    try:
        # 1️⃣ API principal (AccountManagement)
        resp = requests.get(url_v1, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            accounts = data.get("accounts", [])
            if accounts:
                location_groups = [a for a in accounts if a.get("type") == "LOCATION_GROUP"]
                personal_accounts = [a for a in accounts if a.get("type") == "USER_ACCOUNT"]
                ordered_accounts = location_groups + personal_accounts

                todas = ", ".join(
                    f"{a.get('accountName', 'Sem nome')} ({a.get('type', '?')})"
                    for a in ordered_accounts
                )
                logging.info(f"[gbp] Contas detectadas via V1: {todas}")
                return [a.get("name") for a in ordered_accounts if a.get("name")]

            # --- Fallback V4 (userAccounts) ------------------------------------
            logging.warning("[gbp] Nenhuma conta retornada pela API AccountManagement. Tentando fallback V4 (userAccounts)...")
            url_fallback = "https://mybusiness.googleapis.com/v4/userAccounts"
            resp2 = requests.get(url_fallback, headers=headers, timeout=10)
            if resp2.status_code == 200:
                data2 = resp2.json()
                accs2 = data2.get("accounts", [])
                if accs2:
                    user_account_names = [a.get("name") for a in accs2 if a.get("name")]
                    user_account_names = [
                        n if n.startswith("userAccounts/") else f"userAccounts/{n.split('/')[-1]}"
                        for n in user_account_names
                    ]
                    logging.info(f"[gbp] ✅ Contas pessoais detectadas via fallback V4: {len(user_account_names)}")
                    return user_account_names
                else:
                    logging.warning("[gbp] Nenhuma conta retornada no fallback userAccounts.")
            else:
                logging.warning(f"[gbp] Fallback userAccounts falhou ({resp2.status_code}): {resp2.text[:200]}")

        else:
            logging.warning(f"[gbp] Erro ao buscar contas V1 ({resp.status_code}): {resp.text[:200]}")

    except requests.RequestException as e:
        logging.warning(f"[gbp] Erro de conexão com API Google: {e}")
    except Exception:
        logging.exception("[gbp] Falha inesperada ao obter contas")

    # 3️⃣ Último fallback — tenta buscar fichas diretamente do usuário autenticado
    try:
        logging.warning("[gbp] Nenhuma conta encontrada — tentando fallback direto no endpoint /v4/accounts (perfil pessoal)...")
        url_direct = "https://mybusiness.googleapis.com/v4/accounts"
        resp3 = requests.get(url_direct, headers=headers, timeout=10)
        if resp3.status_code == 200:
            data3 = resp3.json()
            accs3 = data3.get("accounts", [])
            if accs3:
                direct_accounts = [a.get("name") for a in accs3 if a.get("name")]
                direct_accounts = [
                    n if n.startswith("userAccounts/") else f"userAccounts/{n.split('/')[-1]}"
                    for n in direct_accounts
                ]
                logging.info(f"[gbp] ✅ Contas pessoais detectadas via fallback direto: {len(direct_accounts)}")
                return direct_accounts
        else:
            logging.warning(f"[gbp] Fallback direto falhou ({resp3.status_code}): {resp3.text[:200]}")
    except Exception as e:
        logging.warning(f"[gbp] Erro no fallback direto: {e}")

    # Nenhum método retornou resultados
    return []

@google_auto_bp.route("/debug-accounts")
def debug_accounts():
    """Testa todos os fallbacks de listagem de contas GBP."""
    user_info = session.get("user_info") or {}
    user_id = user_info.get("id")
    if not user_id:
        return "Usuário não autenticado", 401

    creds = _get_persisted_credentials(user_id) or _get_session_credentials()
    if not creds:
        return "Sem credenciais válidas", 401

    headers = _make_auth_headers(creds)
    results = {}

    for label, url in [
        ("v1", "https://mybusinessaccountmanagement.googleapis.com/v1/accounts"),
        ("v4_userAccounts", "https://mybusiness.googleapis.com/v4/userAccounts"),
        ("v4_accounts", "https://mybusiness.googleapis.com/v4/accounts"),
    ]:
        try:
            r = requests.get(url, headers=headers, timeout=10)
            results[label] = {
                "status": r.status_code,
                "text": r.text[:300],
            }
        except Exception as e:
            results[label] = {"error": str(e)}

    return jsonify(results)

def _list_reviews(
    creds: Credentials, account_name: str, location_name: Optional[str]
) -> List[Dict]:
    if not location_name:
        logging.warning(
            "[gbp] Não é possível listar avaliações: location_name não fornecido."
        )
        return []

    try:
        headers = _make_auth_headers(creds)
        account_id = account_name.split("/")[-1]
        location_id = location_name.split("/")[-1]

        url = f"https://mybusiness.googleapis.com/v4/accounts/{account_id}/locations/{location_id}/reviews"
        resp = requests.get(url, headers=headers, timeout=10)  # 👈 FALTAVA ESSA LINHA

        if resp.status_code == 200:
            data = resp.json()
            reviews = data.get("reviews", [])
            print(f"[gbp] Total de {len(reviews)} avaliações encontradas pela API.")
            return reviews
        else:
            print(
                f"FAIL [gbp] Falha ao buscar avaliações ({resp.status_code}): {resp.text}"
            )
            return []
    except Exception as e:
        print(f"ERROR [gbp] Erro ao listar avaliações: {e}")
        return []


def _already_saved(user_id: str, review_id: str) -> bool:
    return (
        db.session.query(Review.id)
        .filter_by(user_id=user_id, external_id=review_id)
        .first()
        is not None
    )


# google_auto.py (Função _upsert_review)
# Substitua a sua função _upsert_review por esta:


def _upsert_review(user_id: str, r: Dict, reply_text: str, location_name: Optional[str] = None) -> None: # ⬅️ ADICIONADO location_name
    """Salva ou atualiza uma avaliação automática do Google no banco,
    já marcando com etiqueta de automação (source='google', is_auto=True)."""

    rid = r.get("reviewId")
    if not rid:
        logging.warning("[gbp] Review recebida sem reviewId — ignorando.")
        return

    # Extrai dados básicos
    star_str = r.get("starRating")
    stars = converter_nota_gbp_para_int(star_str)
    text = r.get("comment") or ""
    name = (r.get("reviewer") or {}).get("displayName") or "Cliente"
    create_time = r.get("createTime")

    # Data de criação (com fallback)
    dt = _now_brt()
    if create_time:
        try:
            dt = datetime.fromisoformat(create_time.replace("Z", "+00:00"))
        except Exception:
            pass

    try:
        existing = Review.query.filter_by(user_id=user_id, external_id=rid).first()

        if existing:
            # Atualiza review existente (mantém automação)
            existing.rating = stars
            existing.text = text
            existing.reply = reply_text
            existing.replied = bool(reply_text)
            existing.source = "google"
            
            if location_name:
                existing.location_name = location_name # ⬅️ SALVANDO LOCATION ID
            
            if hasattr(existing, "is_auto"):
                existing.is_auto = True
            if hasattr(existing, "auto_origin"):
                existing.auto_origin = "gbp"
            db.session.commit()
            logging.info(
                f"[gbp] 🔄 Review {rid} atualizada no BD com etiqueta de automação."
            )

        else:
            # Insere nova review automática
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
                "location_name": location_name, # ⬅️ SALVANDO LOCATION ID
            }

            # Campos opcionais se existirem no modelo
            if hasattr(Review, "is_auto"):
                review_data["is_auto"] = True
            if hasattr(Review, "auto_origin"):
                review_data["auto_origin"] = "gbp"

            review = Review(**review_data)
            db.session.add(review)
            db.session.commit()
            logging.info(
                f"[gbp] 🆕 Review {rid} inserida no BD com etiqueta de automação."
            )

    except Exception as e:
        db.session.rollback()
        logging.exception(f"[gbp] ❌ Erro ao salvar review automática {rid}: {e}")

# NOTA: A função run_sync_for_user deve ser ajustada para passar 4 argumentos para esta função.
def _publish_reply(
    creds: Credentials,
    account_name: str,
    location_name: str,
    review_id: str,
    reply_text: str,
) -> bool:
    """Publica ou atualiza uma resposta no Google Business Profile.
    Retorna True em caso de sucesso (HTTP 200), False em falha.
    """
    try:
        headers = _make_auth_headers(creds)
        account_id = account_name.split("/")[-1]
        location_id = location_name.split("/")[-1]

        url = f"https://mybusiness.googleapis.com/v4/accounts/{account_id}/locations/{location_id}/reviews/{review_id}/reply"
        payload = {"comment": reply_text}

        resp = requests.put(url, headers=headers, json=payload, timeout=10)

        # Sucesso
        if resp.status_code == 200:
            logging.info(
                f"[gbp] ✅ Resposta publicada no Google (Review ID: {review_id})."
            )
            return True

        # Alguns erros comuns e como reagir
        elif resp.status_code == 400:
            logging.warning(
                f"[gbp] ⚠️ Requisição inválida (400) — Verifique o corpo do payload. {resp.text}"
            )
        elif resp.status_code == 401:
            logging.warning("[gbp] ❌ Token expirado ou inválido (401).")
        elif resp.status_code == 403:
            logging.warning(
                "[gbp] 🚫 Permissão negada (403). Verifique escopos e acesso da conta."
            )
        elif resp.status_code == 404:
            logging.warning(
                f"[gbp] ❓ Avaliação não encontrada (404) — ID: {review_id}."
            )
        elif resp.status_code == 429:
            logging.warning(
                "[gbp] ⏳ Limite de requisições atingido (429). Tente novamente mais tarde."
            )
        elif 500 <= resp.status_code < 600:
            logging.error(f"[gbp] 💥 Erro no servidor do Google ({resp.status_code}).")

        # Falhou, loga resposta completa
        logging.error(
            f"[gbp] ❌ Falha ao publicar resposta ({resp.status_code}): {resp.text}"
        )
        return False

    except requests.exceptions.RequestException as e:
        logging.exception(f"[gbp] ❌ Erro de rede ao publicar resposta: {e}")
        return False
    except Exception as e:
        logging.exception(f"[gbp] ❌ Erro inesperado ao publicar resposta: {e}")
        return False


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


# google_auto.py (Função _generate_reply_for atualizada)


def _generate_reply_for(
    user_id: str, stars: int, text: str, reviewer_name: str, is_hiper_enabled: bool
) -> str:
    """Gera uma resposta automática com IA."""
    try:
        from main import client as openai_client
        from main import get_user_settings

        settings = get_user_settings(user_id)

        tone = settings.get("gbp_tone")
        tone_instruction = {
            "empatico": "Demonstre empatia e cuidado.",
            "profissional": "Mantenha tom neutro e educado.",
            "informal": "Use linguagem leve e simpática.",
            "cordial": "Seja gentil e respeitoso.",
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
        # 🎯 NOVO: Lógica da instrução Hiper Compreensiva
        if is_hiper_enabled:
            prompt += (
                "\n\n**Gere uma resposta mais longa, empática e detalhada.** Use de 10 a 15 frases. "
                "Mostre escuta ativa, reconhecimento das críticas e profissionalismo elevado. "
                "Responda cuidadosamente aos principais pontos levantados pelo cliente."
            )
        # Fim da lógica Hiper Compreensiva

        cp = openai_client.with_options(timeout=30.0).chat.completions.create(
            model="gpt-5",
            messages=[
                {
                    "role": "system",
                    "content": "Você é um assistente cordial e empático.",
                },
                {"role": "user", "content": prompt},
            ],
        )
        return (cp.choices[0].message.content or "").strip()
    except Exception:
        logging.exception("[gbp] Falha na geração da resposta com IA")
        return "Obrigado pelo seu feedback! Estamos sempre à disposição."


# google_auto.py (Função run_sync_for_user - CORRIGIDA)


# google_auto.py (Função run_sync_for_user - OTIMIZADA PARA MULTI-LOCATION)

def run_sync_for_user(user_id: str) -> int:
    """Executa sincronização completa, pegando apenas as avaliações do dia atual (BRT)."""

    try:
        from main import (
            registrar_uso_resposta_especial,
            usuario_pode_usar_resposta_especial,
        )
    except ImportError:
        logging.error("Funções de limite (hiper_compreensiva) não encontradas em main.py.")
        def usuario_pode_usar_resposta_especial(uid): return False
        def registrar_uso_resposta_especial(uid): pass

    print(f"\n--- [GBP SYNC START] Iniciando sync para user={user_id} ---\n")

    creds = _get_persisted_credentials(user_id) or _get_session_credentials()
    if not creds:
        print(f"WARN [gbp] Sem credenciais válidas para {user_id}")
        return 0

    # 1. Busca TODAS as contas (Grupos e Pessoais)
    accounts = _list_all_accounts(creds)
    if not accounts:
        print(f"[gbp] Nenhuma conta retornada para {user_id}")
        return 0
        
    # 2. Busca TODAS as fichas (locations) em TODAS as contas
    all_locations_data = _list_all_locations(creds, accounts)
    
    if not all_locations_data:
        print(f"FAIL [gbp] Nenhuma ficha (location) encontrada para {user_id} em nenhuma conta.")
        return 0

    tz_brt = pytz.timezone("America/Sao_Paulo")
    agora = datetime.now(tz_brt)
    inicio_dia = agora.replace(hour=0, minute=0, second=0, microsecond=0)

    print(f"[gbp] ⏱️ Filtro: apenas avaliações publicadas após {inicio_dia.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    total_processadas = 0

    # 3. Itera por TODAS as fichas encontradas
    for location_data in all_locations_data:
        account_name = location_data['account_name']
        location_name = location_data['location_name']
        location_title = location_data['location_title']

        print(f"\n[gbp] ➡️ Sincronizando ficha: {location_title} ({location_name})")

        # 4. Lista reviews para ESTA ficha e ESTA conta
        reviews = _list_reviews(creds, account_name, location_name)
        if not reviews:
            print(f"[gbp] Nenhuma avaliação encontrada na ficha {location_title}.")
            continue

        for r in reviews:
            rid = r.get("reviewId")
            if not rid or _already_saved(user_id, rid):
                continue
            
            # FILTRO DE TEMPO 
            create_time_str = r.get("createTime")
            if create_time_str:
                try:
                    dt_utc = datetime.fromisoformat(create_time_str.replace("Z", "+00:00"))
                    dt_brt = dt_utc.astimezone(tz_brt)
                    
                    if dt_brt < inicio_dia:
                        print(f"[gbp] ⏩ Ignorando {rid} ({dt_brt.strftime('%d/%m %H:%M')}) — anterior a hoje.")
                        continue
                except Exception:
                    logging.exception(f"[gbp] Erro ao processar data da avaliação {rid}. Processando sem filtro de tempo.")
                    
            # PROCESSAMENTO
            stars = converter_nota_gbp_para_int(r.get("starRating"))
            text = r.get("comment") or ""
            name = (r.get("reviewer") or {}).get("displayName") or "Cliente"

            is_hiper = stars in (1, 2) and usuario_pode_usar_resposta_especial(user_id)
            reply = _generate_reply_for(user_id, stars, text, name, is_hiper)

            # Salva no BD local - PASSANDO location_name!
            _upsert_review(user_id, r, reply, location_name=location_name) # ⬅️ CORRIGIDO
            
            # Publica no Google
            ok = _publish_reply(creds, account_name, location_name, rid, reply)
            
            if ok:
                # Atualiza status local para refletir publicação e registra uso Hiper
                _update_local_reply_status(user_id, rid, reply, True)
                if is_hiper:
                    registrar_uso_resposta_especial(user_id) 

            total_processadas += 1

    print(f"\n--- [GBP SYNC END] ✅ Total: {total_processadas} avaliações processadas ---\n")
    return total_processadas

def _update_local_reply_status(
    user_id: str, external_id: str, reply_text: Optional[str], is_auto: bool = True
) -> bool:
    """Atualiza o status e texto da resposta no banco de dados local (model Review)."""
    try:
        review = Review.query.filter_by(
            user_id=user_id, external_id=external_id
        ).first()
        if not review:
            logging.warning(
                f"[gbp] Review {external_id} não encontrada no BD local para atualização."
            )
            return False

        review.reply = reply_text
        review.replied = bool(reply_text)

        if hasattr(review, "is_auto"):
            review.is_auto = is_auto

        if hasattr(review, "auto_origin"):
            review.auto_origin = "gbp"

        db.session.commit()
        logging.info(
            f"[gbp] ✅ BD local atualizado para review {external_id}. (is_auto={is_auto})"
        )
        return True

    except Exception:
        db.session.rollback()
        logging.exception(
            f"[gbp] ❌ Falha ao atualizar BD local (Review ID: {external_id})."
        )
        return False


# --- Cron diário ---
def register_gbp_cron(scheduler, app):
    """Registra o job diário do Google Business Profile (roda às 01:00 BRT)."""
    import pytz

    def _gbp_job():
        with app.app_context():
            try:
                enabled = UserSettings.query.filter_by(gbp_auto_enabled=True).all()
                logging.info(f"[gbp] 🕐 Job diário iniciado — {len(enabled)} contas habilitadas.")
                for s in enabled:
                    logging.info(f"[gbp] ▶️ Rodando sync para user_id={s.user_id}")
                    run_sync_for_user(s.user_id)
                logging.info("[gbp] ✅ Job diário concluído com sucesso.")
            except Exception:
                logging.exception("[gbp] 💥 Job diário falhou.")

    # 👉 Usa add_job() em vez do decorador
    scheduler.add_job(
        id="gbp_daily_sync",
        func=_gbp_job,
        trigger="cron",
        hour=10,
        minute=15,
        timezone=pytz.timezone("America/Sao_Paulo"),
        replace_existing=True,
    )

    logging.info("[gbp] ⏰ Job diário GBP registrado com sucesso.")



# --- Rotas Flask ---
@google_auto_bp.route("/excluir_reply/<external_id>", methods=["DELETE"])
def excluir_reply_auto(external_id):
    """Exclui resposta automática tanto no Google quanto no banco."""
    user_info = session.get("user_info") or {}
    user_id = user_info.get("id")
    if not user_id:
        return (
            jsonify({"success": False, "message": "Usuário não autenticado"}),
            401,
        )  # Retorna False

    # Assumindo que a função gbp_excluir_resposta existe e retorna True/False
    ok = gbp_excluir_resposta(user_id, external_id)

    if ok:
        # Se o Google confirmou a exclusão (200, 204 ou 404), atualizamos localmente
        if not _update_local_reply_status(user_id, external_id, None, False):
            logging.warning(
                f"[gbp] Falha ao atualizar BD local após exclusão {external_id}."
            )
            return jsonify(
                {
                    "success": True,
                    "message": "Resposta excluída no Google, mas falhou ao atualizar o painel local.",
                }
            )
        return jsonify({"success": True, "message": "Resposta excluída com sucesso!"})
    else:
        # Erro de permissão, rede, ou API
        return (
            jsonify(
                {
                    "success": False,
                    "message": "Erro ao excluir resposta no Google. Permissão negada ou erro de rede.",
                }
            ),
            500,
        )


@google_auto_bp.route("/test-cron-google")
def test_cron_google():
    from flask import session

    # Obtém o user_id da sessão (o usuário logado)
    user_info = session.get("user_info") or {}
    user_id = user_info.get("id")

    if not user_id:
        return "Nenhum usuário logado na sessão.", 401

    # Força a execução APENAS para o usuário logado
    run_sync_for_user(user_id)

    # Se o log do Python for gerado, o teste funcionou.
    return "Sincronização forçada concluída para o usuário da sessão!"


@google_auto_bp.route("/test-token")
def test_token():
    from google.oauth2.credentials import Credentials

    creds_dict = session.get("credentials")
    if not creds_dict:
        return "❌ Nenhum token encontrado na sessão. Faça login novamente.", 401

    creds = Credentials(**creds_dict)
    scopes = creds.scopes or []
    return f"<h3>🔍 Escopos ativos:</h3><pre>{'<br>'.join(scopes)}</pre>"


# google_auto.py


@google_auto_bp.route("/editar_reply/<external_id>", methods=["POST"])
def editar_reply_auto(external_id):
    """Edita uma resposta automática tanto no Google quanto no banco."""
    user_info = session.get("user_info") or {}
    user_id = user_info.get("id")
    if not user_id:
        return jsonify({"success": False, "message": "Usuário não autenticado"}), 401

    reply_text = request.json.get("reply_text")
    if not reply_text:
        return jsonify({"success": False, "message": "Texto de resposta ausente"}), 400

    # 1. Obtém credenciais, conta e localização CORRETA (salva no BD)
    # CHAMA A NOVA FUNÇÃO AQUI:
    creds, account_name, location_name = _get_review_data_for_action(user_id, external_id)
    
    # Se credenciais, conta ou Location ID não foram encontrados no BD
    if not creds: 
        return (
            jsonify({"success": False, "message": "Falha ao obter dados da ficha correta. A avaliação pode ter sido removida do BD ou as credenciais inválidas."}),
            400,
        )

    # 2. Tenta publicar/editar no Google (usando a location_name correta)
    publicado = _publish_reply(
        creds, account_name, location_name, external_id, reply_text
    )

    if not publicado:
        # Se a publicação falhar (404, 403, etc.)
        return (
            jsonify(
                {
                    "success": False,
                    # Mensagem genérica para falha de API/permissão
                    "message": "Falha na publicação do Google. A avaliação pode ter sido removida ou as credenciais estão inválidas.",
                }
            ),
            500,
        )

    # 3. Atualiza localmente APENAS se a publicação foi bem-sucedida
    # Nota: _update_local_reply_status deve ser ajustada para não buscar a location_name
    # pois a edição manual não recebe a location_name no payload.
    if not _update_local_reply_status(user_id, external_id, reply_text, True):
        logging.warning(
            f"[gbp] Falha ao atualizar BD local após editar reply {external_id}."
        )
        return jsonify(
            {
                "success": True,
                "message": "Resposta publicada no Google, mas falhou ao atualizar o painel local.",
            }
        )

    return jsonify({"success": True, "message": "Resposta atualizada com sucesso!"})

def _get_review_data_for_action(user_id: str, external_id: str) -> Optional[tuple[Credentials, str, str]]:
    """
    Obtém Credenciais, Account Name e o Location Name CORRETO (salvo no BD)
    para operações de PUT/DELETE na API do Google, consultando a Review pelo external_id.
    
    Esta função substitui _get_location_and_account.
    """
    try:
        # 1. Busca a Review no BD local para obter o Location ID salvo (location_name)
        review = Review.query.filter_by(
            user_id=user_id, external_id=external_id
        ).first()

        # Verifica se a review e o ID da Localização foram encontrados
        if not review or not review.location_name:
            logging.warning(
                f"[gbp] Review (external_id={external_id}) ou Location ID ausente no BD local. Falha ao identificar a ficha correta."
            )
            return None, None, None

        # 2. Obtém Credenciais e a Conta (Credenciais são necessárias para todas as fichas)
        creds = _get_persisted_credentials(user_id) or _get_session_credentials()
        if not creds:
            logging.warning("[gbp] Nenhuma credencial válida para o usuário.")
            return None, None, None

        # 3. Obtém o Account Name (Necessário para montar a URL da API V4/PUT/DELETE)
        # Reusamos _first_account_name, pois o Account ID geralmente é o mesmo para todas as fichas do usuário.
        account_name = _first_account_name(creds)
        if not account_name:
            logging.warning("[gbp] Conta principal (Account Name) não encontrada.")
            return None, None, None

        # O location_name correto é o que salvamos no BD (o campo 'location_name' no objeto review)
        correct_location_name = review.location_name 
        
        logging.info(
            f"[gbp] ✅ Location ID para ação encontrado no BD: {correct_location_name}"
        )
            
        # Retorna credenciais, o ID da conta e o ID da ficha CORRETO
        return creds, account_name, correct_location_name
    
    except Exception:
        logging.exception("[gbp] Erro ao obter dados para ação (BD/Credenciais).")
        return None, None, None

def _delete_reply(
    creds: Credentials, account_name: str, location_name: str, review_id: str
) -> bool:
    """Função core para enviar DELETE para a API do Google Review Reply (v4)."""
    try:
        # 1️⃣ Extrai IDs
        account_id = account_name.split("/")[-1]
        location_id = location_name.split("/")[-1]

        # 2️⃣ Garante que o token esteja válido
        if creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request

            creds.refresh(Request())

        # 3️⃣ Monta URL do endpoint V4
        url = f"https://mybusiness.googleapis.com/v4/accounts/{account_id}/locations/{location_id}/reviews/{review_id}/reply"

        headers = {
            "Authorization": f"Bearer {creds.token}",
            "Content-Type": "application/json",
        }

        logging.info(f"[gbp] Tentando excluir resposta (V4): {url}")
        response = requests.delete(url, headers=headers)

        # 4️⃣ Trata códigos de resposta
        if response.status_code in (200, 204):
            logging.info(
                f"[gbp] ✅ Resposta excluída com sucesso! (Status {response.status_code})"
            )
            return True
        elif response.status_code == 404:
            logging.warning(
                f"[gbp] ⚠️ Resposta não encontrada (404) — já estava excluída."
            )
            return True
        else:
            logging.error(
                f"[gbp] ❌ Falha ao excluir resposta (Status {response.status_code}): {response.text}"
            )
            return False

    except requests.exceptions.RequestException:
        logging.exception("[gbp] 💥 Erro de rede/conexão ao tentar excluir resposta.")
        return False
    except Exception:
        logging.exception("[gbp] 💥 Erro inesperado ao tentar excluir resposta.")
        return False


def gbp_excluir_resposta(user_id: str, external_review_id: str) -> bool:
    """Tenta excluir a resposta no Google, utilizando o Location ID salvo no BD.
    Retorna True em caso de sucesso ou se a resposta já foi excluída (404).
    """
    try:
        # 1️⃣ Obtém credenciais, conta e localização CORRETA do BD
        # CHAMA A NOVA FUNÇÃO AQUI:
        data = _get_review_data_for_action(user_id, external_review_id)
        
        # O data[0] é o objeto credenciais. Se não houver creds, Location ID, ou Account ID, falha.
        if not data or not data[0]:
            logging.warning(
                f"[gbp] ⚠️ Nenhuma credencial ou dados de ficha válidos (BD) encontrados para user_id={user_id}. Exclusão abortada."
            )
            return False

        creds, account_name, location_name = data

        # 2️⃣ Chama a função core para exclusão
        # Esta função core agora usa o location_name CORRETO.
        ok = _delete_reply(creds, account_name, location_name, external_review_id)

        if ok:
            logging.info(
                f"[gbp] 🗑️ Resposta do review {external_review_id} excluída com sucesso no Google."
            )
        else:
            logging.error(
                f"[gbp] ❌ Falha ao excluir resposta para review {external_review_id} no Google (API error)."
            )

        return ok

    except Exception:
        logging.exception("[gbp] Falha na função gbp_excluir_resposta (erro inesperado).")
        return False
    
@google_auto_bp.route("/debug-reviews")
def debug_reviews():
    """Rota temporária para testar listagem direta de reviews da conta atual."""
    user_info = session.get("user_info") or {}
    user_id = user_info.get("id")
    if not user_id:
        return "Sem usuário logado", 401

    creds = _get_persisted_credentials(user_id) or _get_session_credentials()
    if not creds:
        return "Sem credenciais válidas.", 401

    account_name = _first_account_name(creds)
    if not account_name:
        return "Nenhuma conta detectada.", 404

    location_name = _first_location_name(creds, account_name)
    if not location_name:
        return "Nenhuma ficha encontrada.", 404

    headers = _make_auth_headers(creds)
    account_id = account_name.split("/")[-1]
    location_id = location_name.split("/")[-1]

    url = f"https://mybusiness.googleapis.com/v4/accounts/{account_id}/locations/{location_id}/reviews"
    resp = requests.get(url, headers=headers, timeout=10)
    return f"<h3>Status {resp.status_code}</h3><pre>{resp.text}</pre>"

# google_auto.py (Rota Flask)

@google_auto_bp.route("/test-cron-all")
def test_cron_all():
    """Força a execução do job GBP para todos os usuários, sincronizando as últimas 48 horas."""
    from flask import current_app, session

    # Requer login para evitar acesso anônimo à rota de testes
    user_info = session.get("user_info") or {}
    if not user_info.get("id"):
        return "Acesso não autorizado.", 401

    with current_app.app_context():
        try:
            enabled = UserSettings.query.filter_by(gbp_auto_enabled=True).all()
            if not enabled:
                return "Nenhum usuário com automação ativa.", 200

            print(f"\n[gbp] ⚡ Rodando TESTE GLOBAL (ÚLTIMAS 48h)\n")
            total_geral = 0
            for s in enabled:
                print(f"\n--- [TESTE] Rodando para {s.user_id} ---")
                
                # 🎯 CHAMA A NOVA FUNÇÃO DE TESTE DE 48H
                total = run_sync_last_48h(s.user_id) 
                
                print(f"[gbp] ✅ {s.user_id}: {total} avaliações processadas.\n")
                total_geral += total

            return f"Teste de 48h concluído! Total de avaliações processadas: {total_geral}", 200

        except Exception as e:
            import traceback
            traceback.print_exc()
            return f"Erro ao rodar teste global: {e}", 500
# google_auto.py

# ... (restante das funções auxiliares de API, como _list_reviews, etc.) ...
def _list_all_locations(creds: Credentials, accounts: List[str]) -> List[Dict]:
    """
    Busca todas as fichas (locations) sob todas as contas fornecidas, 
    usando o endpoint correto para LOCATION_GROUP (V1/V4) e USER_ACCOUNT (V4 userAccounts).
    """
    all_locations = []
    headers = _make_auth_headers(creds)

    for account_name in accounts:
        account_id = account_name.split("/")[-1]

        # 🔍 Detecta tipo da conta: Se o nome do recurso começar com "userAccounts/", é pessoal.
        is_user_account = account_name.startswith("userAccounts/") 

        # =======================================================
        # 1️⃣ Tenta Nova API Business Information (V1) → Grupos (Melhor performance)
        # =======================================================
        if not is_user_account:
            url_v1 = f"https://mybusinessbusinessinformation.googleapis.com/v1/{account_name}/locations"
            params = {"readMask": "name,title"}

            try:
                resp = requests.get(url_v1, headers=headers, params=params, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    locs = data.get("locations", [])
                    if locs:
                        logging.info(f"[gbp] Encontradas {len(locs)} fichas via V1 em {account_name} (Grupo).")
                        for loc in locs:
                            all_locations.append({
                                'account_name': account_name,
                                'location_name': loc.get("name"),
                                'location_title': loc.get("title")
                            })
                        continue  # Já encontrou com sucesso, pula para próxima conta
                    else:
                        logging.warning(f"[gbp] Falha V1 {resp.status_code}: {resp.text[:200]}")
                else:
                    logging.warning(f"[gbp] Falha V1 {resp.status_code}: {resp.text[:200]}")
            except Exception as e:
                logging.warning(f"[gbp] Erro V1 para {account_name}: {e}")

        # =======================================================
        # 2️⃣ Tenta API V4 genérica (Cobre USER_ACCOUNT e fallback de LOCATION_GROUP)
        # =======================================================
        try:
            # O Google aceita o nome do recurso completo aqui (accounts/... ou userAccounts/...)
            url_v4 = f"https://mybusiness.googleapis.com/v4/{account_name}/locations"
            resp2 = requests.get(url_v4, headers=headers, timeout=10)
            if resp2.status_code == 200:
                data2 = resp2.json()
                locs2 = data2.get("locations", [])
                if locs2:
                    logging.info(f"[gbp] Encontradas {len(locs2)} fichas via V4 em {account_name}.")
                    for loc in locs2:
                        all_locations.append({
                            'account_name': account_name,
                            'location_name': loc.get("name"),
                            'location_title': loc.get("title") or loc.get("locationName")
                        })
            else:
                # Falha V4 (que pode ser a conta pessoal sem fichas ou erro de permissão)
                logging.warning(f"[gbp] Falha V4 {resp2.status_code}: {resp2.text[:200]}")
        except Exception as e:
            logging.error(f"[gbp] Erro ao listar fichas via V4 em {account_name}: {e}")

    # 🧹 Remove duplicatas por location_name
    unique_locations = {loc['location_name']: loc for loc in all_locations}.values()
    return list(unique_locations)

def run_sync_last_48h(user_id: str) -> int:
    """Executa sincronização completa do Google Business, pegando avaliações das ÚLTIMAS 48 horas."""
    
    try:
        from main import (
            registrar_uso_resposta_especial,
            usuario_pode_usar_resposta_especial,
        )
    except ImportError:
        logging.error("Funções de limite (hiper_compreensiva) não encontradas em main.py.")
        def usuario_pode_usar_resposta_especial(uid): return False
        def registrar_uso_resposta_especial(uid): pass

    print(f"\n--- [GBP SYNC START] Iniciando sync (ÚLTIMAS 48H) para user={user_id} ---\n")

    creds = _get_persisted_credentials(user_id) or _get_session_credentials()
    if not creds:
        print(f"WARN [gbp] Sem credenciais válidas para {user_id}")
        return 0

    # 1. Busca TODAS as contas
    accounts = _list_all_accounts(creds)
    if not accounts:
        print(f"[gbp] Nenhuma conta retornada para {user_id}")
        return 0
        
    # 2. Busca TODAS as fichas
    all_locations_data = _list_all_locations(creds, accounts)
    
    if not all_locations_data:
        print(f"FAIL [gbp] Nenhuma ficha (location) encontrada para {user_id} em nenhuma conta.")
        return 0

    tz_brt = pytz.timezone("America/Sao_Paulo")
    agora = datetime.now(tz_brt)
    
    # 🎯 FILTRO: 48 horas atrás
    limite_tempo = agora - timedelta(hours=48) 

    print(f"[gbp] ⏱️ Filtro: apenas avaliações publicadas após {limite_tempo.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    total_processadas = 0

    # 3. Itera por TODAS as fichas encontradas
    for location_data in all_locations_data:
        account_name = location_data['account_name']
        location_name = location_data['location_name']
        location_title = location_data['location_title']

        print(f"\n[gbp] ➡️ Sincronizando ficha: {location_title} ({location_name})")

        reviews = _list_reviews(creds, account_name, location_name)
        if not reviews:
            print(f"[gbp] Nenhuma avaliação encontrada na ficha {location_title}.")
            continue

        for r in reviews:
            rid = r.get("reviewId")
            if not rid or _already_saved(user_id, rid):
                continue
            
            # FILTRO DE TEMPO (usando o limite de 48h)
            create_time_str = r.get("createTime")
            if create_time_str:
                try:
                    dt_utc = datetime.fromisoformat(create_time_str.replace("Z", "+00:00"))
                    dt_brt = dt_utc.astimezone(tz_brt)
                    
                    if dt_brt < limite_tempo: # Compara com o limite flutuante de 48h
                        print(f"[gbp] ⏩ Ignorando {rid} ({dt_brt.strftime('%d/%m %H:%M')}) — anterior a 48h.")
                        continue
                except Exception:
                    logging.exception(f"[gbp] Erro ao processar data da avaliação {rid}. Processando sem filtro de tempo.")
                    
            # PROCESSAMENTO
            stars = converter_nota_gbp_para_int(r.get("starRating"))
            text = r.get("comment") or ""
            name = (r.get("reviewer") or {}).get("displayName") or "Cliente"

            is_hiper = stars in (1, 2) and usuario_pode_usar_resposta_especial(user_id)
            reply = _generate_reply_for(user_id, stars, text, name, is_hiper)

            # Salva no BD local - PASSANDO location_name!
            _upsert_review(user_id, r, reply, location_name=location_name) # ⬅️ CORREÇÃO
            
            # Publica no Google
            ok = _publish_reply(creds, account_name, location_name, rid, reply)
            
            if ok:
                _update_local_reply_status(user_id, rid, reply, True)
                if is_hiper:
                    registrar_uso_resposta_especial(user_id) 

            total_processadas += 1

    print(f"\n--- [GBP SYNC END] ✅ Total: {total_processadas} avaliações processadas (Últimas 48h) ---\n")
    return total_processadas


def run_sync_historical(user_id: str, period: str) -> int:
    """
    Busca e responde avaliações retroativas (30, 60, 90, 180 dias ou todas).
    """
    try:
        # Importa funções de limite (hiper_compreensiva)
        from main import (
            registrar_uso_resposta_especial,
            usuario_pode_usar_resposta_especial,
        )
    except ImportError:
        logging.error("Funções hiper_compreensiva não encontradas, usando fallback.")
        def usuario_pode_usar_resposta_especial(uid): return False
        def registrar_uso_resposta_especial(uid): pass

    print(f"\n--- [GBP HISTÓRICO] Iniciando sync retroativa ({period}) para user={user_id} ---\n")

    # Obtém Credenciais
    creds = _get_persisted_credentials(user_id) or _get_session_credentials()
    if not creds:
        print(f"[gbp] ⚠️ Sem credenciais válidas para {user_id}")
        return 0

    # Busca Contas e Localizações (usa as funções robustas de Multi-Location)
    accounts = _list_all_accounts(creds)
    if not accounts:
        print(f"[gbp] Nenhuma conta retornada para {user_id}")
        return 0

    all_locations_data = _list_all_locations(creds, accounts)
    if not all_locations_data:
        print(f"[gbp] ❌ Nenhuma ficha encontrada para {user_id}.")
        return 0

    tz_brt = pytz.timezone("America/Sao_Paulo")
    agora = datetime.now(tz_brt)

    # Calcula limite de tempo
    dias = None if period == "all" else int(period)
    limite_tempo = agora - timedelta(days=dias) if dias else None

    if limite_tempo:
        print(f"[gbp] ⏱️ Buscando avaliações após {limite_tempo.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    else:
        print(f"[gbp] 🕰️ Buscando TODAS as avaliações disponíveis...")

    total_processadas = 0

    for loc in all_locations_data:
        account_name = loc["account_name"]
        location_name = loc["location_name"]
        location_title = loc["location_title"]

        print(f"\n[gbp] ➡️ Sincronizando ficha: {location_title}")

        reviews = _list_reviews(creds, account_name, location_name)
        if not reviews:
            print(f"[gbp] Nenhuma avaliação na ficha {location_title}.")
            continue

        for r in reviews:
            rid = r.get("reviewId")
            if not rid or _already_saved(user_id, rid):
                continue

            # Filtro de tempo (aplica apenas se não for ALL)
            create_time_str = r.get("createTime")
            if create_time_str and limite_tempo:
                try:
                    dt_utc = datetime.fromisoformat(create_time_str.replace("Z", "+00:00"))
                    dt_brt = dt_utc.astimezone(tz_brt)
                    if dt_brt < limite_tempo:
                        continue
                except Exception:
                    pass

            # Geração e publicação
            stars = converter_nota_gbp_para_int(r.get("starRating"))
            text = r.get("comment") or ""
            name = (r.get("reviewer") or {}).get("displayName") or "Cliente"

            is_hiper = stars in (1, 2) and usuario_pode_usar_resposta_especial(user_id)
            reply = _generate_reply_for(user_id, stars, text, name, is_hiper)

            # Salva no BD local - PASSANDO location_name!
            _upsert_review(user_id, r, reply, location_name=location_name)
            ok = _publish_reply(creds, account_name, location_name, rid, reply)

            if ok:
                _update_local_reply_status(user_id, rid, reply, True)
                if is_hiper:
                    registrar_uso_resposta_especial(user_id)

            total_processadas += 1

    print(f"\n--- [GBP HISTÓRICO] ✅ Total de avaliações processadas: {total_processadas} ---\n")
    return total_processadas
# --- SINCRONIZAÇÃO HISTÓRICA: ROTA PARA EXECUÇÃO MANUAL ---
@google_auto_bp.route("/sync_historical/<period>", methods=["POST"])
def sync_historical(period):
    """
    Executa sincronização retroativa de avaliações (30, 60, 90, 180 dias ou todas)
    apenas para o usuário logado.
    """
    # --- Autenticação de sessão ---
    user_info = session.get("user_info") or {}
    user_id = user_info.get("id")
    if not user_id:
        return jsonify({"success": False, "message": "Usuário não autenticado."}), 401

    # --- Validação do parâmetro ---
    valid_periods = ["30", "60", "90", "180", "all"]
    if period not in valid_periods:
        return jsonify({"success": False, "message": "Período inválido."}), 400

    # --- Modo teste: libera geral (sem Stripe ainda) ---
    logging.info(f"[TESTE] Liberando execução manual da sync_historical para {user_id}, período {period}")

    try:
        total = run_sync_historical(user_id, period)
        return jsonify({
            "success": True,
            "message": f"Sincronização de {period} dias concluída com sucesso!",
            "total_processadas": total
        })
    except Exception as e:
        logging.exception(f"[gbp] Erro ao executar sync_historical para {user_id}: {e}")
        return jsonify({
            "success": False,
            "message": "Erro interno durante a sincronização."
        }), 500
