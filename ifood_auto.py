# -*- coding: utf-8 -*-
"""
Módulo de Automação, OAuth e Respostas por Inteligência Artificial para o iFood.
Permite conexão de lojas via OAuth Distribuído (userCode), sincronização de avaliações
e publicação de respostas automatizadas com calibragem de tom de voz via GPT-4o / Gemini.
"""

from __future__ import annotations
import os
import json
import base64
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
import pytz
import requests
from flask import (
    Blueprint,
    request,
    jsonify,
    session,
    redirect,
    url_for,
    flash,
    render_template,
    current_app,
)

from models import db, Review, UserSettings, IFoodMerchant, default_brt_now
from utils.crypto import encrypt as crypto_encrypt, decrypt as crypto_decrypt

logger = logging.getLogger(__name__)

ifood_bp = Blueprint("ifood", __name__, url_prefix="/ifood")

# Configurações de API do iFood
IFOOD_BASE_URL = "https://merchant-api.ifood.com.br"
IFOOD_AUTH_URL = f"{IFOOD_BASE_URL}/authentication/v1.0/oauth"
IFOOD_REVIEW_URL = f"{IFOOD_BASE_URL}/review/v2.0"
IFOOD_MERCHANT_URL = f"{IFOOD_BASE_URL}/merchant/v1.0"

def get_ifood_credentials() -> Tuple[str, str]:
    client_id = os.getenv("IFOOD_CLIENT_ID", "36d9a47e-cd93-4bde-954e-37457696540d").strip()
    client_secret = os.getenv("IFOOD_CLIENT_SECRET", "10i05cnkkr05r64u61eftrql7p7z0sds2kmha3pejshyy02or2l2dlk0m77nluzz2v0h7fhw47jzhknw9tpz4k4q9m1lt03zfg1m").strip()
    return client_id, client_secret


def usuario_tem_addon_ifood(user_id: str) -> bool:
    """Verifica se o usuário tem o Add-on do iFood ativo ou é administrador."""
    if not user_id:
        return False
    try:
        from admin import is_admin
        # Se for admin, tem acesso liberado para testes
        if is_admin(user_id):
            return True
    except Exception:
        pass

    try:
        settings = UserSettings.query.filter_by(user_id=str(user_id)).first()
        if not settings:
            return False
        
        # Add-on explicitamente ativo
        if getattr(settings, "has_addon_ifood", False):
            # Se tem data de expiração, valida
            until = getattr(settings, "addon_ifood_until", None)
            if until and until < datetime.now():
                return False
            return True
        return False
    except Exception as e:
        logger.exception("Erro ao checar addon iFood: %s", e)
        return False


# -----------------------------------------------------------------------------
# 🔐 OAuth 2.0 Distribuído (Fluxo userCode)
# -----------------------------------------------------------------------------

def request_ifood_user_code() -> Dict[str, Any]:
    """
    Solicita um userCode ao iFood para o lojista autorizar o ComentsIA no Portal do Parceiro.
    Retorna o dicionário com userCode, verificationUrl, verificationUrlComplete, authorizationCodeVerifier.
    """
    client_id, _ = get_ifood_credentials()
    url = f"{IFOOD_AUTH_URL}/userCode"
    data = {"clientId": client_id}
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    resp = requests.post(url, data=data, headers=headers, timeout=15)
    if resp.status_code != 200:
        logger.error("Erro ao solicitar userCode iFood: %d - %s", resp.status_code, resp.text)
        raise Exception(f"Falha na comunicação com o iFood ({resp.status_code}): {resp.text}")

    return resp.json()


def exchange_ifood_code(authorization_code: str, code_verifier: str) -> Dict[str, Any]:
    """
    Troca o authorizationCode retornado após autorização pelo accessToken e refreshToken.
    """
    client_id, client_secret = get_ifood_credentials()
    url = f"{IFOOD_AUTH_URL}/token"
    data = {
        "grantType": "authorization_code",
        "clientId": client_id,
        "clientSecret": client_secret,
        "authorizationCode": authorization_code.strip(),
        "authorizationCodeVerifier": code_verifier.strip()
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    resp = requests.post(url, data=data, headers=headers, timeout=15)
    if resp.status_code != 200:
        logger.error("Erro ao trocar authorizationCode iFood: %d - %s", resp.status_code, resp.text)
        raise Exception(f"Falha ao validar código no iFood: {resp.text}")

    return resp.json()


def refresh_ifood_merchant_token(merchant: IFoodMerchant) -> str:
    """
    Atualiza o token de acesso do comerciante caso esteja prestes a expirar.
    """
    client_id, client_secret = get_ifood_credentials()
    
    # Decodifica o refresh_token atual
    raw_refresh = crypto_decrypt(merchant.refresh_token) if merchant.refresh_token else None
    if not raw_refresh:
        raw_refresh = merchant.refresh_token

    if not raw_refresh:
        # Se não houver refresh_token (caso client_credentials), usa o client_credentials
        url = f"{IFOOD_AUTH_URL}/token"
        data = {
            "grantType": "client_credentials",
            "clientId": client_id,
            "clientSecret": client_secret
        }
    else:
        url = f"{IFOOD_AUTH_URL}/token"
        data = {
            "grantType": "refresh_token",
            "clientId": client_id,
            "clientSecret": client_secret,
            "refreshToken": raw_refresh
        }

    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    resp = requests.post(url, data=data, headers=headers, timeout=15)
    if resp.status_code != 200:
        logger.error("Erro ao atualizar token do iFood para merchant %s: %s", merchant.merchant_id, resp.text)
        raise Exception("Token expirado e não foi possível renovar.")

    res_data = resp.json()
    new_access = res_data.get("accessToken")
    new_refresh = res_data.get("refreshToken")
    expires_in = res_data.get("expiresIn", 21600)

    merchant.access_token = crypto_encrypt(new_access)
    if new_refresh:
        merchant.refresh_token = crypto_encrypt(new_refresh)
    merchant.token_expires_at = datetime.now(pytz.timezone("America/Sao_Paulo")) + timedelta(seconds=expires_in - 300)
    db.session.commit()

    return new_access


def get_valid_merchant_token(merchant: IFoodMerchant) -> str:
    """Retorna o access_token descriptografado e renovado se necessário."""
    now = datetime.now(pytz.timezone("America/Sao_Paulo"))
    if merchant.token_expires_at and merchant.token_expires_at < now:
        return refresh_ifood_merchant_token(merchant)

    raw_token = crypto_decrypt(merchant.access_token) if merchant.access_token else None
    if not raw_token:
        raw_token = merchant.access_token
    return raw_token or ""


def parse_jwt_merchant_ids(access_token: str) -> List[str]:
    """Extrai os merchant UUIDs contidos no escopo do token JWT."""
    merchant_ids = []
    try:
        parts = access_token.split(".")
        if len(parts) >= 2:
            payload_b64 = parts[1]
            # Padding correto para base64
            payload_b64 += "=" * ((4 - len(payload_b64) % 4) % 4)
            payload_json = base64.b64decode(payload_b64).decode("utf-8")
            payload = json.loads(payload_json)
            scopes = payload.get("merchant_scope", [])
            for s in scopes:
                if ":" in s:
                    m_id = s.split(":")[0]
                    if m_id and m_id not in merchant_ids:
                        merchant_ids.append(m_id)
    except Exception as e:
        logger.warning("Não foi possível extrair merchant_ids do JWT: %s", e)
    return merchant_ids


def fetch_merchant_details(token: str, merchant_id: str) -> Dict[str, Any]:
    """Obtém os detalhes da loja no iFood (nome, endereço, status)."""
    url = f"{IFOOD_MERCHANT_URL}/merchants/{merchant_id}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    resp = requests.get(url, headers=headers, timeout=15)
    if resp.status_code == 200:
        return resp.json()
    return {}


# -----------------------------------------------------------------------------
# 🤖 Motor de Avaliações e Respostas com IA
# -----------------------------------------------------------------------------

def generate_ifood_ai_reply(merchant: IFoodMerchant, stars: int, review_text: str, reviewer_name: str) -> str:
    """
    Gera uma resposta altamente calibrada e empática para avaliações do iFood,
    levando em consideração o tom da loja, sabor, embalagem, entrega e cordialidade.
    """
    try:
        from main import client as openai_client
        from services.ai_service import limpar_texto_review, get_tone_instructions, get_language_instructions

        clean_text = limpar_texto_review(review_text)
        store_name = merchant.name or "Nosso Restaurante"
        greeting = merchant.default_greeting or "Olá"
        closing = merchant.default_closing or "Equipe"
        contexto = merchant.contexto_personalizado or ""
        tone = merchant.tone or "amigavel"
        idioma = merchant.idioma_resposta or "Português (Brasil)"

        system_inst, prompt_lang_rule = get_language_instructions(idioma)
        tone_inst = get_tone_instructions(tone)

        prompt = f"""Você é o responsável pelo atendimento e relacionamento com clientes do restaurante "{store_name}" no iFood.
Avaliação recebida no iFood:
- Cliente: {reviewer_name or 'Cliente iFood'}
- Nota: {stars} de 5 estrelas
- Comentário do Cliente: "{clean_text}"

DIRETRIZES DE RESPOSTA NO IFOOD:
{prompt_lang_rule}

2. {tone_inst}

3. ESPECIFICIDADES DO IFOOD / DELIVERY:
- Se a avaliação for POSITIVA (4 ou 5 estrelas): Agradeça calorosamente pela preferência, celebre o carinho com a comida/preparo e convide para pedir novamente em breve!
- Se a avaliação for CRÍTICA ou NEGATIVA (1 a 3 estrelas): Acolha o feedback com extrema educação e humildade, lamente profundamente que a experiência com o pedido não tenha sido perfeita e reforce o compromisso da cozinha/equipe em aprimorar.
- Nunca dê desculpas genéricas ou culpe o entregador.
- Comece com "{greeting} {reviewer_name}," (se houver nome) ou "{greeting},"
- Encerre com uma despedida calorosa e a assinatura "{closing} {store_name}".
- Tamanho: 2 a 4 frases bem escritas, naturais e humanizadas.
"""
        if contexto:
            prompt += f"\n🚨 CONTEXTO E INSTRUÇÕES ESPECÍFICAS DA LOJA: {contexto}\n"

        cp = openai_client.with_options(timeout=30.0).chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_inst},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=350,
        )
        return cp.choices[0].message.content.strip()
    except Exception as e:
        logger.exception("Erro ao gerar resposta com IA para iFood: %s", e)
        # Fallback elegante caso a API de IA tenha instabilidade
        if stars >= 4:
            return f"Olá {reviewer_name or 'Cliente'}! Muito obrigado pelo carinho e pela excelente avaliação. Preparamos cada pedido com muita dedicação. Esperamos te atender novamente em breve! Um abraço de toda a equipe {merchant.name}."
        else:
            return f"Olá {reviewer_name or 'Cliente'}, sentimos muito que sua experiência não tenha sido impecável como você merece. Agradecemos o feedback e já estamos trabalhando com nossa equipe para aprimorar nossos pedidos. Um abraço, equipe {merchant.name}."


def send_ifood_reply_to_api(merchant: IFoodMerchant, review_id: str, reply_text: str) -> bool:
    """Envia a resposta de uma avaliação para a API do iFood."""
    token = get_valid_merchant_token(merchant)
    url = f"{IFOOD_REVIEW_URL}/merchants/{merchant.merchant_id}/reviews/{review_id}/answers"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    payload = {"text": reply_text}

    resp = requests.post(url, json=payload, headers=headers, timeout=15)
    if resp.status_code in [200, 201, 202, 204]:
        logger.info("✅ Resposta enviada com sucesso ao iFood para review %s", review_id)
        return True
    else:
        logger.error("❌ Falha ao responder review %s no iFood: %d - %s", review_id, resp.status_code, resp.text)
        return False


def sync_merchant_reviews(merchant_db_id: int, auto_reply: bool = True) -> Dict[str, Any]:
    """
    Sincroniza as avaliações de uma loja iFood com o ComentsIA e executa
    o disparo de respostas automáticas por IA caso esteja ativado.
    """
    merchant = IFoodMerchant.query.get(merchant_db_id)
    if not merchant or not merchant.is_active:
        return {"success": False, "error": "Loja iFood inativa ou não encontrada."}

    token = get_valid_merchant_token(merchant)
    url = f"{IFOOD_REVIEW_URL}/merchants/{merchant.merchant_id}/reviews"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    params = {"page": 1, "size": 50}

    resp = requests.get(url, headers=headers, params=params, timeout=20)
    if resp.status_code != 200:
        logger.error("Erro ao buscar avaliações no iFood: %d - %s", resp.status_code, resp.text)
        return {"success": False, "error": f"Erro iFood ({resp.status_code}): {resp.text}"}

    data = resp.json()
    reviews_list = data.get("reviews", []) if isinstance(data, dict) else []
    
    novas_count = 0
    respondidas_count = 0

    for item in reviews_list:
        rev_id = str(item.get("id") or "")
        if not rev_id:
            continue

        # Verifica se já existe no banco
        existing = Review.query.filter_by(
            user_id=merchant.user_id,
            external_id=rev_id,
            source="ifood"
        ).first()

        score = int(item.get("score") or item.get("rating") or 5)
        comment = item.get("comment") or item.get("text") or ""
        cust_info = item.get("customer") or {}
        cust_name = cust_info.get("name") if isinstance(cust_info, dict) else (item.get("customerName") or "Cliente iFood")
        
        # Tratamento de datas
        created_str = item.get("createdAt") or item.get("date")
        rev_date = default_brt_now()
        if created_str:
            try:
                # Trata ISO 8601
                rev_date = datetime.fromisoformat(created_str.replace("Z", "+00:00")).astimezone(pytz.timezone("America/Sao_Paulo"))
            except Exception:
                pass

        # Checa se já possui resposta no iFood
        answers = item.get("answers") or item.get("replies") or []
        has_existing_reply = False
        existing_reply_text = None
        if isinstance(answers, list) and len(answers) > 0:
            has_existing_reply = True
            existing_reply_text = answers[0].get("text") or answers[0].get("comment")
        elif isinstance(answers, dict) and answers.get("text"):
            has_existing_reply = True
            existing_reply_text = answers.get("text")

        if not existing:
            rev_obj = Review(
                user_id=merchant.user_id,
                ifood_merchant_id=merchant.id,
                reviewer_name=cust_name,
                rating=score,
                location_name=merchant.name or "Loja iFood",
                text=comment,
                date=rev_date,
                reply=existing_reply_text,
                replied=has_existing_reply,
                source="ifood",
                is_auto=True,
                auto_origin="ifood",
                external_id=rev_id
            )
            db.session.add(rev_obj)
            db.session.flush()
            novas_count += 1
            review_to_process = rev_obj
        else:
            review_to_process = existing
            if has_existing_reply and not existing.replied:
                existing.replied = True
                existing.reply = existing_reply_text

        # Executa resposta automática se configurado e ainda não respondida
        if auto_reply and merchant.auto_reply_enabled and not review_to_process.replied:
            ai_reply = generate_ifood_ai_reply(merchant, score, comment, cust_name)
            # Envia para a API do iFood
            api_ok = send_ifood_reply_to_api(merchant, rev_id, ai_reply)
            if api_ok:
                review_to_process.replied = True
                review_to_process.reply = ai_reply
                respondidas_count += 1

    merchant.last_sync_at = default_brt_now()
    db.session.commit()

    return {
        "success": True,
        "novas_avaliacoes": novas_count,
        "respostas_enviadas": respondidas_count,
        "total_recebidas": len(reviews_list)
    }


# -----------------------------------------------------------------------------
# 🌐 Rotas e Endpoints do Blueprint /ifood
# -----------------------------------------------------------------------------

@ifood_bp.route("/conectar", methods=["POST", "GET"])
def conectar_ifood():
    """Gera um userCode e URL de verificação para o lojista autorizar no Portal do iFood."""
    user_info = session.get("user_info") or {}
    user_id = user_info.get("id") or user_info.get("email")
    if not user_id:
        return jsonify({"success": False, "error": "Usuário não autenticado"}), 401

    if not usuario_tem_addon_ifood(user_id):
        return jsonify({
            "success": False,
            "error": "addon_required",
            "message": "Você precisa assinar o Add-on do iFood (R$ 30,00/mês) para conectar lojas."
        }), 403

    try:
        code_data = request_ifood_user_code()
        # Salva o verifier na sessão do usuário
        session["ifood_code_verifier"] = code_data.get("authorizationCodeVerifier")
        session["ifood_user_code"] = code_data.get("userCode")
        
        return jsonify({
            "success": True,
            "userCode": code_data.get("userCode"),
            "verificationUrl": code_data.get("verificationUrl"),
            "verificationUrlComplete": code_data.get("verificationUrlComplete"),
            "expiresIn": code_data.get("expiresIn")
        })
    except Exception as e:
        logger.exception("Erro ao iniciar conexão iFood: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@ifood_bp.route("/confirmar-codigo", methods=["POST"])
def confirmar_codigo_ifood():
    """
    Recebe o authorizationCode gerado após a autorização do lojista no portal,
    conclui a troca de tokens e cadastra as lojas no banco de dados.
    """
    user_info = session.get("user_info") or {}
    user_id = user_info.get("id") or user_info.get("email")
    if not user_id:
        return jsonify({"success": False, "error": "Não autenticado"}), 401

    payload = request.get_json(silent=True) or {}
    auth_code = payload.get("authorizationCode") or request.form.get("authorizationCode")
    if not auth_code:
        return jsonify({"success": False, "error": "Informe o código de autorização fornecido pelo iFood."}), 400

    verifier = session.get("ifood_code_verifier")
    if not verifier:
        # Tenta pegar do payload se enviado
        verifier = payload.get("authorizationCodeVerifier")

    if not verifier:
        return jsonify({"success": False, "error": "Sessão de autorização expirada. Por favor, inicie a conexão novamente."}), 400

    try:
        token_data = exchange_ifood_code(auth_code, verifier)
        access_token = token_data.get("accessToken")
        refresh_token = token_data.get("refreshToken")
        expires_in = token_data.get("expiresIn", 21600)

        # Identifica as lojas autorizadas pelo JWT
        merchant_ids = parse_jwt_merchant_ids(access_token)
        if not merchant_ids:
            # Fallback caso não venha no JWT: tenta merchantId informado
            custom_mid = payload.get("merchantId")
            if custom_mid:
                merchant_ids = [custom_mid]

        if not merchant_ids:
            return jsonify({
                "success": False,
                "error": "Não foi possível identificar nenhuma loja vinculada ao seu aplicativo iFood."
            }), 400

        lojas_conectadas = []
        for m_id in merchant_ids:
            # Busca dados cadastrais da loja
            details = fetch_merchant_details(access_token, m_id)
            m_name = details.get("name") or details.get("corporateName") or f"Loja iFood {m_id[:8]}"
            corp_name = details.get("corporateName") or m_name
            addr = details.get("address") or {}
            city = addr.get("city")
            state = addr.get("state")

            expires_at = datetime.now(pytz.timezone("America/Sao_Paulo")) + timedelta(seconds=expires_in - 300)

            # Salva ou atualiza no banco
            m_obj = IFoodMerchant.query.filter_by(user_id=str(user_id), merchant_id=m_id).first()
            if not m_obj:
                m_obj = IFoodMerchant(
                    user_id=str(user_id),
                    merchant_id=m_id,
                    name=m_name,
                    corporate_name=corp_name,
                    city=city,
                    state=state,
                    access_token=crypto_encrypt(access_token),
                    refresh_token=crypto_encrypt(refresh_token) if refresh_token else None,
                    token_expires_at=expires_at,
                    is_active=True,
                    auto_reply_enabled=True,
                    tone="amigavel"
                )
                db.session.add(m_obj)
            else:
                m_obj.name = m_name
                m_obj.corporate_name = corp_name
                m_obj.city = city
                m_obj.state = state
                m_obj.access_token = crypto_encrypt(access_token)
                if refresh_token:
                    m_obj.refresh_token = crypto_encrypt(refresh_token)
                m_obj.token_expires_at = expires_at
                m_obj.is_active = True

            db.session.commit()
            lojas_conectadas.append({"id": m_obj.id, "name": m_name, "merchant_id": m_id})

            # Sincronização inicial em segundo plano
            try:
                sync_merchant_reviews(m_obj.id, auto_reply=True)
            except Exception as e_sync:
                logger.warning("Erro na sincronização inicial da loja %s: %s", m_id, e_sync)

        return jsonify({
            "success": True,
            "message": f"Conexão realizada com sucesso! {len(lojas_conectadas)} loja(s) conectada(s).",
            "lojas": lojas_conectadas
        })

    except Exception as e:
        logger.exception("Erro ao concluir confirmação de código iFood: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@ifood_bp.route("/configurar/<int:merchant_db_id>", methods=["POST"])
def configurar_loja_ifood(merchant_db_id: int):
    """Atualiza as configurações de automação, tom e regras de uma loja iFood específica."""
    user_info = session.get("user_info") or {}
    user_id = user_info.get("id") or user_info.get("email")
    if not user_id:
        return jsonify({"success": False, "error": "Não autenticado"}), 401

    merchant = IFoodMerchant.query.filter_by(id=merchant_db_id, user_id=str(user_id)).first()
    if not merchant:
        return jsonify({"success": False, "error": "Loja não encontrada."}), 404

    payload = request.get_json(silent=True) or request.form.to_dict()

    if "auto_reply_enabled" in payload:
        val = payload.get("auto_reply_enabled")
        merchant.auto_reply_enabled = True if str(val).lower() in ["true", "1", "on"] else False

    if "tone" in payload:
        merchant.tone = (payload.get("tone") or "amigavel").strip()

    if "idioma_resposta" in payload:
        merchant.idioma_resposta = (payload.get("idioma_resposta") or "Português (Brasil)").strip()

    if "default_greeting" in payload:
        merchant.default_greeting = payload.get("default_greeting", "").strip()

    if "default_closing" in payload:
        merchant.default_closing = payload.get("default_closing", "").strip()

    if "contexto_personalizado" in payload:
        merchant.contexto_personalizado = payload.get("contexto_personalizado", "").strip()

    if "delay_minutes" in payload:
        try:
            merchant.delay_minutes = max(1, int(payload.get("delay_minutes", 5)))
        except ValueError:
            pass

    db.session.commit()
    return jsonify({"success": True, "message": "Configurações da loja iFood atualizadas com sucesso!"})


@ifood_bp.route("/sincronizar/<int:merchant_db_id>", methods=["POST"])
def sincronizar_loja_ifood(merchant_db_id: int):
    """Dispara a sincronização manual e resposta de avaliações do iFood."""
    user_info = session.get("user_info") or {}
    user_id = user_info.get("id") or user_info.get("email")
    if not user_id:
        return jsonify({"success": False, "error": "Não autenticado"}), 401

    merchant = IFoodMerchant.query.filter_by(id=merchant_db_id, user_id=str(user_id)).first()
    if not merchant:
        return jsonify({"success": False, "error": "Loja não encontrada."}), 404

    result = sync_merchant_reviews(merchant.id, auto_reply=True)
    return jsonify(result)


@ifood_bp.route("/desconectar/<int:merchant_db_id>", methods=["POST"])
def desconectar_loja_ifood(merchant_db_id: int):
    """Desconecta a loja do iFood."""
    user_info = session.get("user_info") or {}
    user_id = user_info.get("id") or user_info.get("email")
    if not user_id:
        return jsonify({"success": False, "error": "Não autenticado"}), 401

    merchant = IFoodMerchant.query.filter_by(id=merchant_db_id, user_id=str(user_id)).first()
    if not merchant:
        return jsonify({"success": False, "error": "Loja não encontrada."}), 404

    merchant.is_active = False
    merchant.auto_reply_enabled = False
    db.session.delete(merchant)
    db.session.commit()

    return jsonify({"success": True, "message": "Loja iFood desconectada com sucesso."})
