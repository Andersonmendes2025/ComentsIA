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
    """Obtém a conta principal do Google Business, priorizando LOCATION_GROUP (contas de grupo)."""
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
            logging.warning("[gbp] Nenhuma conta encontrada.")
            return None

        # Prioriza contas de grupo (LOCATION_GROUP), onde geralmente ficam as fichas reais
        location_groups = [a for a in accounts if a.get("type") == "LOCATION_GROUP"]
        personal_accounts = [a for a in accounts if a.get("type") == "USER_ACCOUNT"]

        if location_groups:
            selected = location_groups[0]
            logging.info(
                f"[gbp] Conta de grupo detectada: {selected.get('name')} ({selected.get('accountName')})"
            )
            return selected.get("name")

        if personal_accounts:
            selected = personal_accounts[0]
            logging.info(
                f"[gbp] Conta pessoal detectada: {selected.get('name')} ({selected.get('accountName')})"
            )
            return selected.get("name")

        logging.warning("[gbp] Nenhuma conta válida encontrada.")
        return None

    except Exception:
        logging.exception("[gbp] Falha ao obter conta principal")
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


def _upsert_review(user_id: str, r: Dict, reply_text: str) -> None:
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


def run_sync_for_user(user_id: str) -> int:
    """Executa sincronização completa, pegando apenas as avaliações do dia atual (BRT)."""

    try:
        from main import (
            registrar_uso_resposta_especial,
            usuario_pode_usar_resposta_especial,
        )
    except ImportError:
        logging.error(
            "As funções de limite (hiper_compreensiva) não foram encontradas em main.py."
        )

        def usuario_pode_usar_resposta_especial(uid):
            return False

        def registrar_uso_resposta_especial(uid):
            pass

    print(f"\n--- [GBP SYNC START] Iniciando sync para user={user_id} ---\n")

    creds = _get_persisted_credentials(user_id) or _get_session_credentials()
    if not creds:
        print(f"WARN [gbp] Sem credenciais válidas para {user_id}")
        return 0

    account_name = _first_account_name(creds)
    location_name = _first_location_name(creds, account_name) if account_name else None

    if not location_name:
        print(f"FAIL [gbp] Nenhuma ficha encontrada para {user_id}")
        return 0

    reviews = _list_reviews(creds, account_name, location_name)
    if not reviews:
        print(f"[gbp] Nenhuma avaliação nova.")
        return 0

    # 🕓 Define o início do dia atual em BRT para filtro
    tz_brt = pytz.timezone("America/Sao_Paulo")
    agora = datetime.now(tz_brt)
    inicio_dia = agora.replace(hour=0, minute=0, second=0, microsecond=0)

    print(
        f"[gbp] ⏱️ Filtro: apenas avaliações publicadas a partir de {inicio_dia.strftime('%Y-%m-%d %H:%M:%S %Z')}"
    )

    count = 0
    for r in reviews:
        rid = r.get("reviewId")
        if not rid:
            continue

        # 1. OTIMIZAÇÃO: Verifica no BD primeiro. Se já foi salva, ignora a data e o resto.
        if _already_saved(user_id, rid):
            continue

        # 2. FILTRO DE TEMPO (Apenas para reviews que AINDA NÃO FORAM SALVAS)
        create_time_str = r.get("createTime")
        if create_time_str:
            try:
                # Converte o timestamp UTC do Google para o objeto datetime BRT
                dt_utc = datetime.fromisoformat(create_time_str.replace("Z", "+00:00"))
                dt_brt = dt_utc.astimezone(tz_brt)

                # Compara com o início do dia BRT
                if dt_brt < inicio_dia:
                    print(
                        f"[gbp] ⏩ Ignorando {rid} ({dt_brt.strftime('%d/%m %H:%M')}) — anterior a hoje."
                    )
                    continue
            except Exception:
                # Se falhar ao processar a data, processa a review para evitar perda
                logging.exception(
                    f"[gbp] Erro ao processar data da avaliação {rid}. Processando sem filtro de tempo."
                )

        # 3. PROCESSAMENTO (Apenas reviews NOVAS e DE HOJE)
        stars = converter_nota_gbp_para_int(r.get("starRating"))
        text = r.get("comment") or ""
        name = (r.get("reviewer") or {}).get("displayName") or "Cliente"

        is_hiper = stars in (1, 2) and usuario_pode_usar_resposta_especial(user_id)
        reply = _generate_reply_for(user_id, stars, text, name, is_hiper)

        _upsert_review(user_id, r, reply)
        ok = _publish_reply(creds, account_name, location_name, rid, reply)
        if ok:
            _update_local_reply_status(user_id, rid, reply, True)
        if is_hiper and ok:
            registrar_uso_resposta_especial(user_id)

        count += 1

    print(
        f"\n--- [GBP SYNC END] ✅ {count} avaliações novas processadas (somente de hoje). ---\n"
    )
    return count


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
def register_gbp_cron(scheduler):

    @scheduler.scheduled_job(
        "cron", hour=1, minute=0, timezone=pytz.timezone("America/Sao_Paulo")
    )
    def _gbp_job():
        try:
            enabled = UserSettings.query.filter_by(gbp_auto_enabled=True).all()
            for s in enabled:
                run_sync_for_user(s.user_id)
        except Exception:
            logging.exception("[gbp] Job diário falhou")


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

    data = _get_location_and_account(user_id)
    if not data:
        return (
            jsonify({"success": False, "message": "Falha ao obter dados da conta."}),
            400,
        )

    creds, account_name, location_name = data

    # 1. Tenta publicar/editar no Google (Assumindo que _publish_reply retorna True em sucesso)
    publicado = _publish_reply(
        creds, account_name, location_name, external_id, reply_text
    )

    if not publicado:
        # Se a publicação falhar no Google (400, 403, etc.)
        return (
            jsonify(
                {
                    "success": False,
                    "message": "Falha na publicação do Google. Resposta não salva.",
                }
            ),
            500,
        )

    # 2. Atualiza localmente APENAS se a publicação foi bem-sucedida
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


def _get_location_and_account(user_id: str) -> Optional[tuple[Credentials, str, str]]:
    """Obtém credenciais, conta e localização para operações diretas (editar/excluir resposta)."""
    try:
        creds = _get_persisted_credentials(user_id) or _get_session_credentials()
        if not creds:
            logging.warning("[gbp] Nenhuma credencial encontrada para o usuário.")
            return None

        account_name = _first_account_name(creds)
        if not account_name:
            logging.warning("[gbp] Conta principal não encontrada.")
            return None

        location_name = _first_location_name(creds, account_name)
        if not location_name:
            logging.warning("[gbp] Localização não encontrada.")
            return None

        return creds, account_name, location_name
    except Exception:
        logging.exception("[gbp] Erro ao obter location/account.")
        return None


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
    """Tenta excluir a resposta no Google. Retorna True em caso de sucesso."""
    try:
        # 1️⃣ Obtém credenciais, conta e localização
        data = _get_location_and_account(user_id)
        if not data:
            logging.warning(
                f"[gbp] ⚠️ Nenhuma credencial ou conta válida encontrada para user_id={user_id}"
            )
            return False

        creds, account_name, location_name = data

        # 2️⃣ Chama a função core para exclusão
        ok = _delete_reply(creds, account_name, location_name, external_review_id)

        if ok:
            logging.info(
                f"[gbp] 🗑️ Resposta do review {external_review_id} excluída com sucesso no Google."
            )
        else:
            logging.error(
                f"[gbp] ❌ Falha ao excluir resposta para review {external_review_id} no Google."
            )

        return ok

    except Exception:
        logging.exception("[gbp] Falha na função gbp_excluir_resposta.")
        return False
