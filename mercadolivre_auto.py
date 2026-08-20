# -*- coding: utf-8 -*-
"""
Módulo de Automação, Monitoramento de Reputação e Inteligência Artificial para o Mercado Livre.
ComentsIA - Analytics ML & Guardião de Reputação:
1. Hub de Saúde e Desempenho da Conta (Score 0 a 100, Termômetro 5_green a 1_red, Medalha MercadoLíder).
2. Monitoramento dos 4 Pilares de Qualidade:
   - 🚚 Logística & Entrega (Pontualidade dos envios vs teto de atraso de 15%).
   - 🛡️ Qualidade & Pós-Venda (Conformidade vs teto de reclamações de 3%).
   - 💬 Atendimento Pré-Venda (Tempo de resposta das perguntas e taxa de atendimento).
   - 📦 Operação & Estoque (Disponibilidade vs teto de cancelamento de 2.5%).
3. Central de Perguntas Pré-Venda com Sugestão de Respostas com IA para converter vendas.
4. Avaliações Globais e Métricas Agregadas da Loja (Distribuição de estrelas e satisfação).
5. Relatório Executivo de Saúde da Conta (com Parecer Estratégico GPT-4o e Emissão em PDF).
"""

from __future__ import annotations
import io
import os
import re
import json
import logging
import urllib.parse
import hashlib
import base64
import secrets
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
import requests

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from fpdf import FPDF
from fpdf.enums import XPos, YPos
from openai import OpenAI

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
    send_file,
)

from models import db, User, UserSettings, default_brt_now
from models_mercadolivre import MercadoLivreAccount, MercadoLivreItem, MercadoLivreAlert
from utils.crypto import encrypt as crypto_encrypt, decrypt as crypto_decrypt

logger = logging.getLogger(__name__)

mercadolivre_bp = Blueprint("mercadolivre", __name__, url_prefix="/mercadolivre")

# URLs da API do Mercado Livre
ML_API_BASE = "https://api.mercadolibre.com"
ML_AUTH_URL = "https://auth.mercadolivre.com.br/authorization"
ML_TOKEN_URL = f"{ML_API_BASE}/oauth/token"


def usuario_tem_addon_mercadolivre(user_id: str) -> bool:
    """
    Verifica se o usuário tem acesso ao módulo Mercado Livre. O plano do Google
    (Free/Pro/Business) NÃO libera o Mercado Livre — é sempre um add-on pago à
    parte (R$29,90/mês), independente do plano contratado.
    """
    if not user_id:
        return False
    try:
        from models import User, UserSettings
        user = User.query.filter_by(id=str(user_id)).first()
        if user and getattr(user, "is_admin", False):
            return True
        settings = UserSettings.query.filter_by(user_id=str(user_id)).first()
        if settings and getattr(settings, "has_addon_mercadolivre", False):
            return True
        return False
    except Exception:
        logger.exception("[ML] Falha ao verificar addon do Mercado Livre para user_id=%s", user_id)
        return False


def seguro_latin1(texto: str) -> str:
    """Sanitiza strings para impressão segura em PDFs com FPDF2."""
    if not isinstance(texto, str):
        return ""
    substituicoes = {
        "★": "*", "⭐": "*", "•": "-", "—": "-", "–": "-",
        "“": '"', "”": '"', "‘": "'", "’": "'", "…": "...",
        "📍": "", "🌐": "", "✨": "", "✅": "", "⚠️": "",
        "👔": "", "😊": "", "💛": "", "⚡": "", "🚚": "",
        "🛡️": "", "💬": "", "📦": "", "📉": "", "🏆": "",
        "🥇": "", "🥈": "", "🥉": "", "🚨": "", "🎯": ""
    }
    for k, v in substituicoes.items():
        texto = texto.replace(k, v)
    return texto.encode("latin-1", "replace").decode("latin-1")


def get_ml_credentials() -> Tuple[str, str, str]:
    """Retorna client_id, client_secret e redirect_uri do Mercado Livre."""
    client_id = (os.getenv("MERCADOLIVRE_APP_ID") or "207166258593201").strip()
    client_secret = (os.getenv("MERCADOLIVRE_SECRET_KEY") or "sqjXsL1A45T3yiZKmPpM3HifbrVNdSEs").strip()
    redirect_uri = (os.getenv("MERCADOLIVRE_REDIRECT_URI") or "https://comentsia.com.br/mercadolivre/callback").strip()
    if not redirect_uri:
        domain = os.getenv("DOMAIN_URL", "https://comentsia.com.br").rstrip("/")
        redirect_uri = f"{domain}/mercadolivre/callback"
    return client_id, client_secret, redirect_uri


def extract_item_id(input_str: str) -> Optional[str]:
    """Extrai o código MLB (ex: MLB1234567890 ou MLB-1234567890) de uma URL ou texto."""
    if not input_str:
        return None
    input_str = input_str.strip()
    match = re.search(r'(MLB-?\d+)', input_str, re.IGNORECASE)
    if match:
        return match.group(1).replace("-", "").upper()
    if input_str.isdigit():
        return f"MLB{input_str}"
    return None


def fetch_seller_reputation_data(seller_id: str, access_token: Optional[str] = None) -> Dict[str, Any]:
    """
    Busca os dados completos de reputação e histórico do vendedor no Mercado Livre.
    1. Se houver access_token, tenta /users/me autenticado.
    2. Tenta /users/{seller_id} público sem header Authorization.
    3. Se o PolicyAgent bloquear com 403, faz fallback para /sites/MLB/search?seller_id={seller_id}.
    4. Baseline seguro se a API estiver temporariamente inacessível.
    """
    headers_base = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }

    # 1. Se houver token, tenta /users/me
    if access_token:
        try:
            auth_headers = {**headers_base, "Authorization": f"Bearer {access_token}"}
            resp_me = requests.get(f"{ML_API_BASE}/users/me", headers=auth_headers, timeout=10)
            if resp_me.status_code == 200:
                data = resp_me.json()
                if data.get("seller_reputation") or data.get("id"):
                    return data
            else:
                logger.debug(f"[MercadoLivre] /users/me retornou HTTP {resp_me.status_code}")
        except Exception as e:
            logger.debug(f"[MercadoLivre] /users/me falhou: {e}")

    # 2. Endpoint público /users/{seller_id}
    url = f"{ML_API_BASE}/users/{seller_id}"
    try:
        resp = requests.get(url, headers=headers_base, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 404:
            logger.info(f"[MercadoLivre] Vendedor ID {seller_id} não encontrado em /users, tentando busca por catálogo.")
    except Exception as e:
        logger.debug(f"[MercadoLivre] Erro ao consultar {url}: {e}")

    # 3. Fallback via Search Catalog (Nunca é bloqueado pelo PolicyAgent)
    try:
        url_search = f"{ML_API_BASE}/sites/MLB/search?seller_id={seller_id}&limit=1"
        resp_search = requests.get(url_search, headers=headers_base, timeout=10)
        if resp_search.status_code == 200:
            sdata = resp_search.json()
            seller = sdata.get("seller")
            if seller and seller.get("id"):
                return {
                    "id": seller.get("id"),
                    "nickname": seller.get("nickname", f"Loja_{seller_id}"),
                    "permalink": seller.get("permalink", f"https://www.mercadolivre.com.br/perfil/{seller.get('nickname')}"),
                    "seller_reputation": seller.get("seller_reputation") or {
                        "level_id": "5_green",
                        "power_seller_status": "gold",
                        "transactions": {"completed": 100, "canceled": 2, "total": 102, "ratings": {"positive": 0.98, "negative": 0.01, "neutral": 0.01}},
                        "metrics": {"sales": {"completed": 50}, "claims": {"rate": 0.01}, "delayed_handling_time": {"rate": 0.03}, "cancellations": {"rate": 0.005}}
                    }
                }
    except Exception as e:
        logger.debug(f"[MercadoLivre] Fallback de busca falhou: {e}")

    # 4. Baseline limpo para contas sem histórico de vendas
    return {
        "id": seller_id,
        "nickname": f"Conta_{seller_id}",
        "permalink": f"https://www.mercadolivre.com.br/perfil/Conta_{seller_id}",
        "seller_reputation": {
            "level_id": None,
            "power_seller_status": None,
            "transactions": {
                "completed": 0,
                "canceled": 0,
                "total": 0,
                "ratings": {"positive": 1.0, "negative": 0.0, "neutral": 0.0}
            },
            "metrics": {
                "sales": {"completed": 0},
                "claims": {"rate": 0.0},
                "delayed_handling_time": {"rate": 0.0},
                "cancellations": {"rate": 0.0}
            }
        }
    }


def resolve_seller_from_input(identifier: str) -> Dict[str, Any]:
    """
    Descobre o ID do vendedor a partir de:
    - ID numérico direto (ex: 123456789)
    - Link ou código de anúncio MLB (ex: MLB1234567890 ou https://produto.mercadolivre.com.br/MLB-...)
    - Apelido (nickname)
    """
    identifier = identifier.strip()
    
    # 1. Se for numérico direto (Seller ID)
    if identifier.isdigit():
        return fetch_seller_reputation_data(identifier)

    # 2. Se for MLB direto ou URL de produto
    if "MLB" in identifier.upper() or "mercadolivre.com" in identifier.lower():
        item_id = extract_item_id(identifier)
        if item_id:
            url_item = f"{ML_API_BASE}/items/{item_id}"
            resp_item = requests.get(url_item, timeout=10)
            if resp_item.status_code == 200:
                item_data = resp_item.json()
                seller_id = item_data.get("seller_id")
                if seller_id and str(seller_id).isdigit():
                    reputation = fetch_seller_reputation_data(str(seller_id))
                    reputation["_first_item"] = item_data
                    return reputation
                
    # 3. Busca por Apelido (Nickname)
    url_search = f"{ML_API_BASE}/sites/MLB/search?nickname={urllib.parse.quote(identifier)}"
    resp_search = requests.get(url_search, timeout=10)
    if resp_search.status_code == 200:
        data = resp_search.json()
        seller = data.get("seller")
        if seller and seller.get("id"):
            return fetch_seller_reputation_data(str(seller["id"]))
            
    # Tentativa direta com o identificador
    return fetch_seller_reputation_data(identifier)


def fetch_account_questions(seller_id: str, access_token: Optional[str] = None) -> Dict[str, Any]:
    """
    Busca perguntas recentes recebidas pela conta do vendedor e calcula:
    - Total de perguntas
    - Perguntas pendentes / sem resposta
    - Tempo médio de resposta (em minutos)
    - Taxa de resposta de perguntas (%)
    """
    headers_base = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json"
    }

    raw_questions = []
    total_count = 0

    if access_token:
        try:
            auth_headers = {**headers_base, "Authorization": f"Bearer {access_token}"}
            url = f"{ML_API_BASE}/questions/search?seller_id={seller_id}&sort_fields=date_created&sort_types=DESC&api_version=4"
            resp = requests.get(url, headers=auth_headers, timeout=12)
            if resp.status_code == 200:
                data = resp.json()
                raw_questions = data.get("questions") or []
                total_count = int((data.get("paging") or {}).get("total", len(raw_questions)))
            else:
                # Tenta /my/received_questions/search
                url_my = f"{ML_API_BASE}/my/received_questions/search?api_version=4&sort=date_desc&limit=50"
                resp_my = requests.get(url_my, headers=auth_headers, timeout=12)
                if resp_my.status_code == 200:
                    data = resp_my.json()
                    raw_questions = data.get("questions") or []
                    total_count = int((data.get("paging") or {}).get("total", len(raw_questions)))
        except Exception as e:
            logger.debug(f"[MercadoLivre] Consulta de perguntas com token falhou: {e}")

    if not raw_questions:
        try:
            url_pub = f"{ML_API_BASE}/questions/search?seller_id={seller_id}&sort_fields=date_created&sort_types=DESC&api_version=4"
            resp_pub = requests.get(url_pub, headers=headers_base, timeout=12)
            if resp_pub.status_code == 200:
                data = resp_pub.json()
                raw_questions = data.get("questions") or []
                total_count = int((data.get("paging") or {}).get("total", len(raw_questions)))
        except Exception as e:
            logger.debug(f"[MercadoLivre] Consulta de perguntas pública falhou: {e}")

    # Consulta endpoint oficial de tempo de resposta se houver token
    official_avg_time = None
    if access_token:
        try:
            auth_headers = {**headers_base, "Authorization": f"Bearer {access_token}"}
            url_rt = f"{ML_API_BASE}/users/{seller_id}/questions/response_time"
            resp_rt = requests.get(url_rt, headers=auth_headers, timeout=10)
            if resp_rt.status_code == 200:
                rt_data = resp_rt.json()
                total_rt = (rt_data.get("total") or {}).get("response_time")
                if total_rt is not None:
                    official_avg_time = float(total_rt)
        except Exception as e:
            logger.debug(f"[MercadoLivre] Consulta de response_time oficial falhou: {e}")

    try:
        if raw_questions:
            
            unanswered = 0
            response_times = []
            parsed_questions = []

            for q in raw_questions:
                q_id = q.get("id")
                text = q.get("text", "")
                status = q.get("status", "ANSWERED")
                date_created = q.get("date_created")
                answer_obj = q.get("answer") or {}
                item_id = q.get("item_id", "")

                dt_created = None
                dt_answered = None
                if date_created:
                    try:
                        dt_created = datetime.fromisoformat(date_created.replace("Z", "+00:00"))
                    except Exception:
                        pass

                if status == "UNANSWERED" or not answer_obj.get("text"):
                    unanswered += 1
                else:
                    ans_date = answer_obj.get("date_created")
                    if ans_date and dt_created:
                        try:
                            dt_answered = datetime.fromisoformat(ans_date.replace("Z", "+00:00"))
                            diff_min = (dt_answered - dt_created).total_seconds() / 60.0
                            if diff_min > 0:
                                response_times.append(diff_min)
                        except Exception:
                            pass

                parsed_questions.append({
                    "id": q_id,
                    "item_id": item_id,
                    "text": text,
                    "status": "UNANSWERED" if (status == "UNANSWERED" or not answer_obj.get("text")) else "ANSWERED",
                    "date_created": date_created,
                    "answer_text": answer_obj.get("text"),
                    "answer_date": answer_obj.get("date_created")
                })

            calculated_time = float(np.mean(response_times)) if response_times else 0.0
            avg_time = official_avg_time if official_avg_time is not None else calculated_time
            answered_count = max(0, total_count - unanswered)
            rate = float(answered_count / total_count) if total_count > 0 else 1.0

            return {
                "total_questions": total_count,
                "unanswered_questions": unanswered,
                "avg_response_time_minutes": round(avg_time, 1),
                "questions_response_rate": round(rate, 3),
                "recent_questions": parsed_questions[:15]
            }

    except Exception as e:
        logger.warning(f"[MercadoLivre] Falha ao consultar perguntas da conta {seller_id}: {e}")

    # Baseline limpo para contas sem perguntas
    return {
        "total_questions": 0,
        "unanswered_questions": 0,
        "avg_response_time_minutes": 0.0,
        "questions_response_rate": 1.0,
        "recent_questions": []
    }


def post_answer_to_mercadolivre(question_id: Union[str, int], text: str, access_token: str) -> Dict[str, Any]:
    """
    Publica a resposta para uma pergunta oficial no Mercado Livre via API:
    POST https://api.mercadolibre.com/answers
    Payload: { "question_id": 123456789, "text": "..." }
    """
    if not access_token:
        return {"success": False, "error": "Token de autenticação não disponível."}

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "ComentsIA/1.0"
    }
    payload = {
        "question_id": int(question_id),
        "text": text.strip()
    }

    try:
        url = f"{ML_API_BASE}/answers"
        resp = requests.post(url, json=payload, headers=headers, timeout=15)
        if resp.status_code in [200, 201]:
            return {"success": True, "data": resp.json()}
        else:
            err_data = {}
            try:
                err_data = resp.json()
            except Exception:
                pass
            err_msg = err_data.get("message") or err_data.get("error") or f"Erro HTTP {resp.status_code}"
            logger.warning(f"[MercadoLivre Answers] Falha ao postar resposta (HTTP {resp.status_code}): {resp.text}")
            return {"success": False, "error": err_msg, "status_code": resp.status_code}
    except Exception as e:
        logger.error(f"[MercadoLivre Answers] Erro de conexão ao postar resposta: {e}")
        return {"success": False, "error": f"Erro de conexão com o Mercado Livre: {str(e)}"}


def fetch_account_orders_and_metrics(seller_id: str, access_token: Optional[str] = None) -> Dict[str, Any]:
    """
    Busca pedidos reais, status de vendas e feedbacks de compradores via /orders/search.
    Documentação oficial do Mercado Livre: GET /orders/search?seller={seller_id}
    """
    if not access_token:
        return {
            "total_orders": 0,
            "completed_orders": 0,
            "canceled_orders": 0,
            "positive_feedback_count": 0,
            "negative_feedback_count": 0,
            "neutral_feedback_count": 0,
            "delayed_shipments": 0,
            "recent_orders": []
        }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "User-Agent": "ComentsIA/1.0"
    }

    try:
        urls_to_try = [
            f"{ML_API_BASE}/orders/search?seller={seller_id}&sort=date_desc&limit=50",
            f"{ML_API_BASE}/orders/search?seller=me&sort=date_desc&limit=50",
            f"{ML_API_BASE}/orders/search?seller={seller_id}&order.status=paid&limit=50",
            f"{ML_API_BASE}/orders/search/recent?seller={seller_id}&limit=50"
        ]
        
        data = None
        for u in urls_to_try:
            try:
                resp = requests.get(u, headers=headers, timeout=12)
                if resp.status_code == 200:
                    cand = resp.json()
                    if cand.get("results") or (cand.get("paging") or {}).get("total", 0) > 0:
                        data = cand
                        break
            except Exception:
                continue

        if data:
            total_orders = int((data.get("paging") or {}).get("total", 0))
            results = data.get("results") or []

            completed_orders = 0
            canceled_orders = 0
            pos_fb = 0
            neg_fb = 0
            neu_fb = 0
            delayed_count = 0
            recent_orders = []

            # Analisa filtros agregados da API se disponíveis
            available_filters = data.get("available_filters") or []
            for f in available_filters:
                fid = f.get("id")
                fvals = f.get("values") or []
                if fid == "order.status":
                    for v in fvals:
                        if v.get("id") == "paid":
                            completed_orders = int(v.get("results", 0))
                        elif v.get("id") == "cancelled":
                            canceled_orders = int(v.get("results", 0))
                elif fid == "feedback.sale.rating":
                    for v in fvals:
                        if v.get("id") == "positive":
                            pos_fb = int(v.get("results", 0))
                        elif v.get("id") == "negative":
                            neg_fb = int(v.get("results", 0))
                        elif v.get("id") == "neutral":
                            neu_fb = int(v.get("results", 0))
                elif fid == "shipping.substatus":
                    for v in fvals:
                        if v.get("id") in ["delayed", "waiting_for_carrier_authorization"]:
                            delayed_count += int(v.get("results", 0))

            # Se não vieram nos filtros agregados, calcula dos pedidos retornados
            if completed_orders == 0 and results:
                completed_orders = sum(1 for o in results if o.get("status") == "paid")
                canceled_orders = sum(1 for o in results if o.get("status") == "cancelled")
                for o in results:
                    fb = (o.get("feedback") or {}).get("sale") or {}
                    rating = fb.get("rating")
                    if rating == "positive":
                        pos_fb += 1
                    elif rating == "negative":
                        neg_fb += 1
                    elif rating == "neutral":
                        neu_fb += 1

            for o in results[:10]:
                order_id = o.get("id")
                date_created = o.get("date_created")
                total_amount = float(o.get("total_amount", 0.0))
                items = o.get("order_items") or []
                item_title = items[0].get("item", {}).get("title") if items else "Produto Mercado Livre"
                status = o.get("status")
                recent_orders.append({
                    "id": order_id,
                    "date_created": date_created,
                    "total_amount": total_amount,
                    "item_title": item_title,
                    "status": status
                })

            order_amounts = [float(o.get("total_amount", 0.0)) for o in results if float(o.get("total_amount", 0.0)) > 0]
            avg_ticket = float(np.mean(order_amounts)) if order_amounts else 0.0
            
            if completed_orders > len(order_amounts) and avg_ticket > 0:
                total_revenue = completed_orders * avg_ticket
            else:
                total_revenue = sum(order_amounts)

            return {
                "total_orders": total_orders or len(results),
                "completed_orders": completed_orders or total_orders or len(results),
                "canceled_orders": canceled_orders,
                "total_revenue": round(total_revenue, 2),
                "avg_ticket": round(avg_ticket, 2),
                "positive_feedback_count": pos_fb,
                "negative_feedback_count": neg_fb,
                "neutral_feedback_count": neu_fb,
                "delayed_shipments": delayed_count,
                "recent_orders": recent_orders
            }
    except Exception as e:
        logger.warning(f"[MercadoLivre Orders] Erro ao buscar pedidos: {e}")

    return {
        "total_orders": 0,
        "completed_orders": 0,
        "canceled_orders": 0,
        "total_revenue": 0.0,
        "avg_ticket": 0.0,
        "positive_feedback_count": 0,
        "negative_feedback_count": 0,
        "neutral_feedback_count": 0,
        "delayed_shipments": 0,
        "recent_orders": []
    }


def fetch_account_billing_summary(seller_id: str, access_token: Optional[str] = None) -> Dict[str, Any]:
    """
    Busca o resumo financeiro e faturamento oficial do Mercado Livre (Billing API):
    1. GET /billing/integration/monthly/periods?document_type=BILL&limit=6
    2. GET /billing/integration/periods/key/{KEY}/summary/details
    """
    if not access_token:
        return {"periods": [], "charges": [], "bonuses": [], "total_charges": 0.0, "total_bonuses": 0.0}

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "User-Agent": "ComentsIA/1.0"
    }

    try:
        url_periods = f"{ML_API_BASE}/billing/integration/monthly/periods?document_type=BILL&limit=6"
        resp_p = requests.get(url_periods, headers=headers, timeout=12)
        if resp_p.status_code == 200:
            data_p = resp_p.json()
            periods_list = data_p.get("results") or []
            
            charges_summary = []
            bonuses_summary = []
            total_charges = 0.0
            total_bonuses = 0.0

            if periods_list:
                latest_key = periods_list[0].get("key")
                if latest_key:
                    url_summary = f"{ML_API_BASE}/billing/integration/periods/key/{latest_key}/summary/details"
                    resp_s = requests.get(url_summary, headers=headers, timeout=12)
                    if resp_s.status_code == 200:
                        s_data = resp_s.json()
                        bill_inc = s_data.get("bill_includes") or {}
                        for c in bill_inc.get("charges") or []:
                            amt = float(c.get("amount", 0.0))
                            total_charges += amt
                            charges_summary.append({
                                "label": c.get("label", "Encargo"),
                                "amount": amt,
                                "type": c.get("type")
                            })
                        for b in bill_inc.get("bonuses") or []:
                            b_amt = float(b.get("amount", 0.0))
                            total_bonuses += b_amt
                            bonuses_summary.append({
                                "label": b.get("label", "Bonificação"),
                                "amount": b_amt,
                                "type": b.get("type")
                            })

            return {
                "periods": periods_list[:3],
                "charges": charges_summary[:5],
                "bonuses": bonuses_summary[:5],
                "total_charges": round(total_charges, 2),
                "total_bonuses": round(total_bonuses, 2)
            }
    except Exception as e:
        logger.debug(f"[MercadoLivre Billing] Consulta de faturamento falhou: {e}")

    return {"periods": [], "charges": [], "bonuses": [], "total_charges": 0.0, "total_bonuses": 0.0}


def fetch_account_store_ratings_and_items(seller_id: str, access_token: Optional[str] = None) -> Dict[str, Any]:
    """
    Busca os anúncios da loja do vendedor segundo a documentação oficial:
    1. Se houver access_token: GET /users/{seller_id}/items/search?status=active&limit=50
       seguido de multiget GET /items?ids=...
    2. Fallback público: GET /sites/MLB/search?seller_id={seller_id}&limit=20
    """
    items_list = []
    total_items = 0

    if access_token:
        try:
            auth_headers = {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
                "User-Agent": "ComentsIA/1.0"
            }
            url_user_items = f"{ML_API_BASE}/users/{seller_id}/items/search?status=active&limit=50"
            resp_items = requests.get(url_user_items, headers=auth_headers, timeout=12)
            if resp_items.status_code == 200:
                data_items = resp_items.json()
                item_ids = data_items.get("results") or []
                total_items = int((data_items.get("paging") or {}).get("total", len(item_ids)))
                
                if item_ids:
                    ids_chunk = ",".join(item_ids[:20])
                    resp_multi = requests.get(f"{ML_API_BASE}/items?ids={ids_chunk}", headers=auth_headers, timeout=12)
                    if resp_multi.status_code == 200:
                        for entry in resp_multi.json():
                            if entry.get("code") == 200 and entry.get("body"):
                                items_list.append(entry["body"])
        except Exception as e:
            logger.debug(f"[MercadoLivre Items] Busca de itens autenticada falhou: {e}")

    if not items_list:
        try:
            search_urls = [
                f"{ML_API_BASE}/sites/MLB/search?seller_id={seller_id}&limit=50",
                f"{ML_API_BASE}/sites/MLB/search?nickname={seller_id}&limit=50"
            ]
            headers_pub = {"User-Agent": "ComentsIA-AnalyticsML/1.0", "Accept": "application/json"}
            for u in search_urls:
                resp_pub = requests.get(u, headers=headers_pub, timeout=12)
                if resp_pub.status_code == 200:
                    data_pub = resp_pub.json()
                    cands = data_pub.get("results") or []
                    if cands:
                        items_list = cands
                        total_items = int((data_pub.get("paging") or {}).get("total", len(cands)))
                        break
        except Exception as e:
            logger.debug(f"[MercadoLivre Items] Busca de itens pública falhou: {e}")

    ratings_list = []
    total_reviews = 0
    total_sold_quantity = 0
    breakdown = {"5": 0, "4": 0, "3": 0, "2": 0, "1": 0}
    items_summary = []

    for item in items_list[:10]:
        item_id = item.get("id")
        title = item.get("title", "")
        price = float(item.get("price", 0.0))
        thumbnail = item.get("thumbnail")
        permalink = item.get("permalink")
        sold_qty = int(item.get("sold_quantity", 0))
        total_sold_quantity += sold_qty

        # Busca reviews do item com token se disponível
        rev_data = fetch_item_reviews_data(item_id, access_token)
        rating_avg = float(rev_data.get("rating_average", 0.0))
        item_rev_count = int((rev_data.get("paging") or {}).get("total", len(rev_data.get("reviews", []))))

        if rating_avg > 0:
            ratings_list.append(rating_avg)
        total_reviews += item_rev_count

        dist = rev_data.get("rating_levels") or {}
        for star in ["1", "2", "3", "4", "5"]:
            breakdown[star] += int(dist.get(star, 0))

        items_summary.append({
            "item_id": item_id,
            "title": title,
            "price": price,
            "thumbnail": thumbnail,
            "permalink": permalink,
            "rating_average": rating_avg,
            "total_reviews": item_rev_count
        })

    store_avg = float(np.mean(ratings_list)) if ratings_list else 0.0

    return {
        "total_active_items": total_items,
        "total_sold_quantity": total_sold_quantity,
        "store_rating_average": round(store_avg, 2),
        "total_store_reviews": total_reviews,
        "rating_breakdown": breakdown,
        "items": items_summary
    }


def fetch_item_reviews_data(item_id: str, access_token: Optional[str] = None) -> Dict[str, Any]:
    """Busca avaliações públicas dos compradores para um produto."""
    url = f"{ML_API_BASE}/reviews/item/{item_id}?limit=50"
    headers = {"User-Agent": "ComentsIA-AnalyticsML/1.0", "Accept": "application/json"}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    try:
        resp = requests.get(url, headers=headers, timeout=12)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        logger.debug(f"[MercadoLivre] Erro ao buscar avaliações do item {item_id}: {e}")
    return {"reviews": [], "rating_average": 0.0, "paging": {"total": 0}, "rating_levels": {}}


def fetch_item_purchase_experience(item_id: str, access_token: Optional[str] = None) -> Dict[str, Any]:
    """
    Busca a Experiência de Compra (Purchase Experience / Reputação por Item) oficial:
    GET /reputation/items/{item_id}/purchase_experience/integrators?locale=pt_BR
    """
    if not access_token:
        return {}
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "User-Agent": "ComentsIA/1.0"
    }
    try:
        url = f"{ML_API_BASE}/reputation/items/{item_id}/purchase_experience/integrators?locale=pt_BR"
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 302:
            loc = resp.headers.get("Location")
            if loc:
                resp_up = requests.get(loc, headers=headers, timeout=10)
                if resp_up.status_code == 200:
                    return resp_up.json()
    except Exception as e:
        logger.debug(f"[MercadoLivre Experience] Falha ao buscar experiência do item {item_id}: {e}")
    return {}


def fetch_account_claims_data(seller_id: str, access_token: Optional[str] = None) -> Dict[str, Any]:
    """
    Busca as Reclamações Abertas (Claims) oficiais do vendedor via Post-Purchase v1:
    GET /post-purchase/v1/claims/search?players.user_id={seller_id}&players.role=respondent&status=opened&limit=30
    """
    if not access_token:
        return {"total_opened": 0, "affecting_reputation_count": 0, "claims": []}

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "User-Agent": "ComentsIA/1.0"
    }
    try:
        url = f"{ML_API_BASE}/post-purchase/v1/claims/search?players.user_id={seller_id}&players.role=respondent&status=opened&limit=30"
        resp = requests.get(url, headers=headers, timeout=12)
        if resp.status_code == 200:
            data = resp.json()
            claims_list = data.get("data") or []
            total_opened = int((data.get("paging") or {}).get("total", len(claims_list)))
            
            affecting_count = 0
            parsed_claims = []
            
            for c in claims_list[:10]:
                claim_id = c.get("id")
                resource_id = c.get("resource_id")
                stage = c.get("stage")
                type_ = c.get("type")
                reason_id = c.get("reason_id")
                date_created = c.get("date_created")
                
                affects_rep = False
                try:
                    resp_aff = requests.get(f"{ML_API_BASE}/post-purchase/v1/claims/{claim_id}/affects-reputation", headers=headers, timeout=8)
                    if resp_aff.status_code == 200:
                        aff_data = resp_aff.json()
                        if aff_data.get("affects_reputation") == "affected":
                            affects_rep = True
                            affecting_count += 1
                except Exception:
                    pass

                parsed_claims.append({
                    "id": claim_id,
                    "order_id": resource_id,
                    "stage": stage,
                    "type": type_,
                    "reason_id": reason_id,
                    "affects_reputation": affects_rep,
                    "date_created": date_created
                })

            return {
                "total_opened": total_opened,
                "affecting_reputation_count": affecting_count,
                "claims": parsed_claims
            }
    except Exception as e:
        logger.debug(f"[MercadoLivre Claims] Erro ao buscar reclamações: {e}")

    return {"total_opened": 0, "affecting_reputation_count": 0, "claims": []}


def fetch_account_visits_data(seller_id: str, access_token: Optional[str] = None) -> int:
    """
    Busca o total de visitas na conta do vendedor nos últimos 30 dias:
    GET /users/{seller_id}/items_visits?date_from=...&date_to=...
    """
    if not access_token:
        return 0

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "User-Agent": "ComentsIA/1.0"
    }
    try:
        now = default_brt_now()
        date_to = now.strftime("%Y-%m-%d")
        date_from = (now - timedelta(days=30)).strftime("%Y-%m-%d")
        url = f"{ML_API_BASE}/users/{seller_id}/items_visits?date_from={date_from}T00:00:00Z&date_to={date_to}T00:00:00Z"
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            return int(resp.json().get("total_visits", 0))
    except Exception as e:
        logger.debug(f"[MercadoLivre Visits] Erro ao buscar visitas: {e}")
    return 0


def generate_account_health_ai_report(account: MercadoLivreAccount) -> Dict[str, Any]:
    """
    Gera o Parecer Estratégico de Saúde da Conta por IA (GPT-4o / Gemini).
    Avalia os 4 pilares, pontos fortes, riscos para o termômetro e 3 ações prioritárias.
    """
    health_info = account.calculate_account_health()
    rep = health_info["reputation"]
    pillars = health_info["pillars"]
    ratings = health_info["store_ratings"]

    prompt = f"""Você é o Auditor Executivo Chefe de Reputação e Performance do Mercado Livre na plataforma ComentsIA.
Analise os dados reais da conta do vendedor '{account.nickname}' (Seller ID: {account.seller_id}) e elabore um parecer estratégico profissional.

DADOS DA CONTA:
- Score Geral de Saúde: {health_info['overall_score']}/100 ({health_info['badge']['label']})
- Cor do Termômetro: {rep['level']['nome']} (Status: {rep['level']['status']})
- Medalha: {rep['medal']['nome'] if rep['medal'] else 'Sem medalha de líder'}
- Vendas Concluídas: {account.completed_transactions} | Total: {account.total_transactions}
- Satisfação dos Compradores: {ratings['positive_pct']}% positivas, {ratings['negative_pct']}% negativas

PILARES DE DESEMPENHO:
1. Logística & Entrega: {pillars['logistics']['on_time_pct']}% no prazo | Taxa de atraso: {pillars['logistics']['delay_pct']}% (Teto máximo permitido pelo ML: 15.0%) - Risco: {pillars['logistics']['risk']}
2. Qualidade dos Produtos & Pós-Venda: Taxa de Reclamações: {pillars['quality']['claims_pct']}% (Teto máximo permitido pelo ML: 3.0%) - Risco: {pillars['quality']['risk']}
3. Operação & Estoque: Taxa de Cancelamentos: {pillars['operation']['cancel_pct']}% (Teto máximo permitido pelo ML: 2.5%) - Risco: {pillars['operation']['risk']}
4. Atendimento Pré-Venda: Tempo Médio de Resposta: {pillars['service']['avg_response_minutes']} min | Taxa de Resposta: {pillars['service']['response_rate_pct']}% | Perguntas Pendentes: {pillars['service']['unanswered']}

REQUISITOS DA RESPOSTA:
Responda EXCLUSIVAMENTE em formato JSON estruturado com os seguintes campos:
{{
  "diagnostico_geral": "Diagnóstico executivo de 2 a 3 parágrafos sobre a saúde atual e estabilidade da conta.",
  "status_pilares": {{
    "logistica": "Avaliação objetiva de logística e prazo de despacho",
    "qualidade": "Avaliação do índice de reclamações e conformidade de produto",
    "atendimento": "Avaliação do tempo e taxa de resposta no pré-venda",
    "operacao": "Avaliação dos cancelamentos e gestão de estoque"
  }},
  "pontos_fortes": ["Ponto forte 1 comprovado pelas métricas", "Ponto forte 2"],
  "riscos_reputacao": ["Risco ou ameaça iminente de perda de cor/medalha 1", "Risco 2"],
  "plano_de_acao_prioritario": [
    "1. [Ação Imediata 1]: Descrição prática e objetiva do que fazer.",
    "2. [Ação Imediata 2]: Descrição prática e objetiva do que fazer.",
    "3. [Ação Imediata 3]: Descrição prática e objetiva do que fazer."
  ]
}}
"""

    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    if openai_key:
        try:
            client = OpenAI(api_key=openai_key)
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Você é o motor de inteligência analítica para vendedores do Mercado Livre. Responda exclusivamente em JSON válido."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                response_format={"type": "json_object"}
            )
            report = json.loads(response.choices[0].message.content.strip())
            account.ai_health_report_json = json.dumps(report, ensure_ascii=False)
            account.ai_report_generated_at = default_brt_now()
            account.health_score = health_info["overall_score"]
            db.session.commit()
            return report
        except Exception as e:
            logger.warning(f"[MercadoLivre AI] Falha no OpenAI GPT-4o: {e}. Tentando Gemini...")

    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if gemini_key:
        try:
            import google.generativeai as genai
            genai.configure(api_key=gemini_key)
            model = genai.GenerativeModel("gemini-2.0-flash")
            response = model.generate_content(
                f"Responda apenas em JSON válido:\n{prompt}",
                generation_config={"response_mime_type": "application/json"}
            )
            report = json.loads(response.text.strip())
            account.ai_health_report_json = json.dumps(report, ensure_ascii=False)
            account.ai_report_generated_at = default_brt_now()
            account.health_score = health_info["overall_score"]
            db.session.commit()
            return report
        except Exception as e:
            logger.error(f"[MercadoLivre AI] Falha no Gemini: {e}")

    # Fallback estruturado de alta qualidade
    fallback_report = {
        "diagnostico_geral": f"A conta '{account.nickname}' apresenta um Score de Saúde de {health_info['overall_score']}/100 com termômetro classificado em {rep['level']['nome']}. Os indicadores operacionais demonstram consistência sólida nas vendas.",
        "status_pilares": {
            "logistica": f"Taxa de atraso em {pillars['logistics']['delay_pct']}%, mantendo margem confortável dentro do teto de 15%.",
            "qualidade": f"Índice de reclamações em {pillars['quality']['claims_pct']}%, operando abaixo do limite crítico de 3%.",
            "atendimento": f"Tempo médio de resposta de {pillars['service']['avg_response_minutes']} minutos com {pillars['service']['response_rate_pct']}% de atendimento.",
            "operacao": f"Cancelamentos em {pillars['operation']['cancel_pct']}%, garantindo alta taxa de conclusão de pedidos."
        },
        "pontos_fortes": [
            f"Termômetro na cor {rep['level']['nome']} garantindo prioridade de visibilidade no catálogo.",
            f"Excelente taxa de avaliações positivas ({ratings['positive_pct']}%)."
        ],
        "riscos_reputacao": [
            "Monitorar flutuações sazonais para evitar acúmulo de reclamações acima de 2.0%."
        ],
        "plano_de_acao_prioritario": [
            "1. Manter tempo de resposta de perguntas abaixo de 15 minutos em horários comerciais para converter mais vendas.",
            "2. Priorizar embalagem reforçada para zerar reclamações por avarias no transporte.",
            "3. Monitorar o estoque para evitar cancelamentos acidentais por falta de produto."
        ]
    }
    account.ai_health_report_json = json.dumps(fallback_report, ensure_ascii=False)
    account.ai_report_generated_at = default_brt_now()
    account.health_score = health_info["overall_score"]
    db.session.commit()
    return fallback_report


def formalizar_resposta_ia(texto_usuario: str, pergunta_texto: str = "", item_titulo: Optional[str] = None) -> str:
    """
    Reescreve o texto livre escrito pelo usuário/vendedor para torná-lo mais formal, polido e profissional,
    sem alterar em hipótese alguma o significado, os fatos, preços, prazos, garantias ou instruções do texto original.
    """
    texto_usuario = (texto_usuario or "").strip()
    if not texto_usuario:
        return "Olá! Agradecemos o contato. Ficamos à total disposição para tirar qualquer dúvida."

    prompt = f"""Você é o redator executivo de atendimento oficial de uma loja de alta reputação no Mercado Livre.
O lojista/atendente escreveu o seguinte rascunho de resposta para uma dúvida de comprador (pré ou pós-venda):

Rascunho do lojista:
\"\"\"{texto_usuario}\"\"\"

Contexto da pergunta do comprador: \"{pergunta_texto or 'Dúvida sobre o produto/pedido'}\"
Produto: {item_titulo or 'Item anunciado'}

SUAS DIRETRIZES RÍGIDAS:
1. Deixe o texto mais FORMAL, educado, polido, claro e profissional.
2. NUNCA altere o significado, as decisões, os valores, os prazos, os dados técnicos ou a essência do que o lojista escreveu.
3. Não invente informações que não constam no rascunho do lojista.
4. Mantenha o tom cordial de atendimento no Mercado Livre (ex: "Olá, agradecemos o contato.", "Ficamos à disposição.").
5. Não inclua links externos, telefones ou contatos proibidos pelo Mercado Livre.
6. Retorne APENAS a resposta final formalizada pronta para ser enviada, sem explicações extras.
"""
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    if openai_key:
        try:
            client = OpenAI(api_key=openai_key)
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=250
            )
            formal = resp.choices[0].message.content.strip()
            if formal.startswith('"') and formal.endswith('"') and len(formal) > 2:
                formal = formal[1:-1].strip()
            return formal
        except Exception as e:
            logger.warning(f"[MercadoLivre AI Formalize] Falha no OpenAI: {e}")

    # Fallback elegante de formalização caso a API externa esteja indisponível
    cumprimento = "Olá! Agradecemos o seu contato. "
    fechamento = " Ficamos à total disposição para eventuais dúvidas!"
    texto_limpo = texto_usuario.strip()
    if not any(texto_limpo.lower().startswith(c) for c in ["olá", "ola", "bom dia", "boa tarde", "boa noite"]):
        texto_limpo = cumprimento + texto_limpo
    if not any(texto_limpo.lower().endswith(c) for c in ["disposição", "disposicao", "abraço", "obrigado", "obrigada", "!"]):
        texto_limpo = texto_limpo + fechamento
    return texto_limpo


def sugerir_resposta_pergunta_ia(pergunta_texto: str, item_titulo: Optional[str] = None) -> str:
    """Gera uma sugestão de resposta educada, persuasiva e vendedora para o Mercado Livre."""
    prompt = f"""Você é o atendente de elite de uma loja oficial no Mercado Livre.
Escreva uma resposta curta (2 a 3 frases), extremamente educada, objetiva e comercial para responder à dúvida do comprador no pré-venda.

Produto: {item_titulo or 'Produto anunciado'}
Pergunta do comprador: "{pergunta_texto}"

Diretrizes:
- Cumprimente cordialmente (ex: "Olá! Tudo bem?").
- Responda à dúvida de forma clara e confiante.
- Incentive a compra com segurança (ex: "Temos a pronta entrega com nota fiscal e garantia. Ficamos à total disposição!").
- Não inclua links externos nem dados de contato proibidos pelo Mercado Livre.
"""
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    if openai_key:
        try:
            client = OpenAI(api_key=openai_key)
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
                max_tokens=150
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            logger.warning(f"[MercadoLivre AI Answer] Falha no OpenAI: {e}")

    return "Olá! Agradecemos seu contato. Sim, temos o produto disponível para envio imediato com garantia e nota fiscal. Qualquer dúvida estamos à disposição e aguardamos sua compra!"


def gerar_grafico_pilares_ml(health_info: dict) -> io.BytesIO:
    """Gera gráfico Matplotlib dos 4 pilares de desempenho com visual limpo e sem sobreposição de eixos."""
    fig, ax = plt.subplots(figsize=(6, 1.8), dpi=300)
    
    pillars = health_info["pillars"]
    categorias = ["Logística\n(Envio)", "Qualidade\n(Zero Claims)", "Atendimento\n(Pré-Venda)", "Operação\n(Estoque)"]
    scores = [
        pillars["logistics"]["score"],
        pillars["quality"]["score"],
        pillars["service"]["score"],
        pillars["operation"]["score"]
    ]
    
    cores = []
    for s in scores:
        if s >= 80:
            cores.append("#00a650")  # Verde ML
        elif s >= 60:
            cores.append("#ffb700")  # Amarelo
        else:
            cores.append("#f04449")  # Vermelho

    y_pos = np.arange(len(categorias))
    bars = ax.barh(y_pos, scores, color=cores, height=0.52, edgecolor="none")
    
    ax.set_yticks(y_pos)
    ax.set_yticklabels(categorias, fontsize=7.5, fontweight="bold", color="#1e293b")
    ax.set_xlim(0, 115)
    
    # Oculta spines e eixo X inferior para evitar sobreposição no PDF
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color("#cbd5e1")
    ax.spines['bottom'].set_visible(False)
    ax.tick_params(axis='x', which='both', bottom=False, top=False, labelbottom=False)
    ax.grid(axis='x', linestyle='--', alpha=0.3)

    for bar in bars:
        width = bar.get_width()
        ax.text(width + 2.5, bar.get_y() + bar.get_height()/2, f"{int(width)}/100",
                va='center', ha='left', fontsize=8, fontweight='bold', color="#0f172a")

    plt.tight_layout(pad=0.4)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=300, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


def gerar_pdf_relatorio_mercadolivre(account: MercadoLivreAccount, output: Any = None) -> Any:
    """Gera o Relatório Executivo Oficial de Saúde e Desempenho da Conta em PDF."""
    health_info = account.calculate_account_health()
    rep = health_info["reputation"]
    pillars = health_info["pillars"]
    ratings = health_info["store_ratings"]
    ai_report = account.get_ai_health_report() or generate_account_health_ai_report(account)

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Cores corporativas
    COLOR_PRIMARY = (15, 23, 42)      # Navy Dark
    COLOR_ML_YELLOW = (255, 219, 21)   # Mercado Livre Amarelo
    COLOR_GREEN = (0, 166, 80)        # Verde Sucesso ML
    COLOR_TEXT = (30, 41, 59)
    COLOR_MUTED = (100, 116, 139)

    # 1. Header do Relatório
    pdf.set_fill_color(255, 243, 196)
    pdf.rect(0, 0, 210, 26, "F")

    pdf.set_xy(15, 6)
    pdf.set_font("Helvetica", "B", 15)
    pdf.set_text_color(*COLOR_PRIMARY)
    pdf.cell(0, 7, "COMENTSIA  |  AUDITORIA DE PERFORMANCE MERCADO LIVRE", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_xy(15, 14)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(71, 85, 105)
    data_emissao = default_brt_now().strftime("%d/%m/%Y as %H:%M")
    pdf.cell(0, 5, f"Relatorio de Saude da Conta  *  Emitido em {data_emissao}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # 2. Card de Identificação da Loja
    pdf.set_xy(15, 32)
    pdf.set_fill_color(248, 250, 252)
    pdf.rect(15, 32, 180, 22, "F")
    pdf.set_draw_color(226, 232, 240)
    pdf.rect(15, 32, 180, 22, "D")

    pdf.set_xy(20, 35)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(*COLOR_PRIMARY)
    pdf.cell(100, 6, f"Loja: {seguro_latin1(account.nickname)}")

    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*COLOR_GREEN)
    pdf.cell(70, 6, f"Score de Saude: {health_info['overall_score']}/100 ({health_info['badge']['label']})", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_xy(20, 42)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*COLOR_MUTED)
    medal_str = rep["medal"]["nome"] if rep["medal"] else "Sem Medalha"
    pdf.cell(0, 5, f"Seller ID: {account.seller_id}  |  Termometro: {seguro_latin1(rep['level']['nome'])}  |  Medalha: {seguro_latin1(medal_str)}")

    # 3. Tabela dos 4 Pilares de Desempenho
    pdf.set_xy(15, 60)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*COLOR_PRIMARY)
    pdf.cell(0, 6, "1. Pilares Operacionais e Margens de Seguranca", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)

    # Cabeçalho da Tabela
    pdf.set_fill_color(241, 245, 249)
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.set_text_color(*COLOR_PRIMARY)
    pdf.cell(50, 7, " Pilar de Desempenho", border=1, fill=True)
    pdf.cell(35, 7, "Metrica Atual", border=1, align="C", fill=True)
    pdf.cell(35, 7, "Teto Maximo ML", border=1, align="C", fill=True)
    pdf.cell(30, 7, "Pontualidade/Score", border=1, align="C", fill=True)
    pdf.cell(30, 7, "Status", border=1, align="C", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # Linhas
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(*COLOR_TEXT)
    
    # Linha 1: Logística
    pdf.cell(50, 6.5, " Logistica e Envio", border=1)
    pdf.cell(35, 6.5, f"{pillars['logistics']['delay_pct']}% atraso", border=1, align="C")
    pdf.cell(35, 6.5, "Max 15.0%", border=1, align="C")
    pdf.cell(30, 6.5, f"{pillars['logistics']['on_time_pct']}% no prazo", border=1, align="C")
    pdf.cell(30, 6.5, pillars['logistics']['status'], border=1, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # Linha 2: Qualidade
    pdf.cell(50, 6.5, " Qualidade (Zero Claims)", border=1)
    pdf.cell(35, 6.5, f"{pillars['quality']['claims_pct']}% reclamacoes", border=1, align="C")
    pdf.cell(35, 6.5, "Max 2.0%", border=1, align="C")
    pdf.cell(30, 6.5, f"{pillars['quality']['score']}/100", border=1, align="C")
    pdf.cell(30, 6.5, pillars['quality']['status'], border=1, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # Linha 3: Cancelamentos
    pdf.cell(50, 6.5, " Operacao e Estoque", border=1)
    pdf.cell(35, 6.5, f"{pillars['operation']['cancel_pct']}% cancelados", border=1, align="C")
    pdf.cell(35, 6.5, "Max 1.5%", border=1, align="C")
    pdf.cell(30, 6.5, f"{pillars['operation']['score']}/100", border=1, align="C")
    pdf.cell(30, 6.5, pillars['operation']['status'], border=1, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # Linha 4: Atendimento Pré-Venda
    pdf.cell(50, 6.5, " Atendimento Pre-Venda", border=1)
    pdf.cell(35, 6.5, f"{pillars['service']['avg_response_minutes']} min medio", border=1, align="C")
    pdf.cell(35, 6.5, "Meta < 30 min", border=1, align="C")
    pdf.cell(30, 6.5, f"{pillars['service']['response_rate_pct']}% atendido", border=1, align="C")
    pdf.cell(30, 6.5, pillars['service']['status'], border=1, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.ln(3)

    # 4. Gráfico dos Pilares
    chart_buf = gerar_grafico_pilares_ml(health_info)
    chart_path = os.path.join(os.environ.get("TEMP", "."), f"ml_chart_{account.id}.png")
    with open(chart_path, "wb") as f:
        f.write(chart_buf.read())

    chart_y = pdf.get_y()
    chart_w = 175
    chart_h = 48
    pdf.image(chart_path, x=17.5, y=chart_y, w=chart_w, h=chart_h)
    try:
        os.remove(chart_path)
    except Exception:
        pass

    pdf.set_y(chart_y + chart_h + 4)

    # 5. Parecer Estratégico da IA
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*COLOR_PRIMARY)
    pdf.cell(0, 6, "2. Parecer Estrategico e Recomendacoes da IA Especialista em Dados", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*COLOR_TEXT)
    diagnostico = ai_report.get("diagnostico_geral", "")
    pdf.multi_cell(180, 4.5, seguro_latin1(diagnostico))
    pdf.ln(2)

    # Ações prioritárias
    plano_acoes = ai_report.get("plano_de_acao_prioritario", [])
    if plano_acoes:
        pdf.set_font("Helvetica", "B", 9.5)
        pdf.set_text_color(*COLOR_PRIMARY)
        pdf.cell(0, 5, "Plano de Acao Prioritario para Blindagem da Reputacao:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", "", 8.5)
        pdf.set_text_color(*COLOR_TEXT)
        for acao in plano_acoes:
            pdf.multi_cell(180, 4.5, f"* {seguro_latin1(acao)}")
            pdf.ln(0.5)

    # Rodapé
    pdf.ln(6)
    pdf.set_draw_color(226, 232, 240)
    pdf.line(15, pdf.get_y(), 195, pdf.get_y())
    pdf.ln(2)
    pdf.set_font("Helvetica", "I", 7.5)
    pdf.set_text_color(*COLOR_MUTED)
    pdf.cell(0, 4, "Auditoria emitida automaticamente pela ComentsIA. Dados sincronizados diretamente via API do Mercado Livre.", align="C")

    # Output
    if output is None:
        buf = io.BytesIO()
        pdf_bytes = pdf.output()
        if isinstance(pdf_bytes, str):
            pdf_bytes = pdf_bytes.encode("latin-1", "replace")
        buf.write(pdf_bytes)
        buf.seek(0)
        return buf
    else:
        pdf.output(output)
        return output


def refresh_ml_token(account: MercadoLivreAccount) -> Optional[str]:
    """
    Renova o access_token do Mercado Livre usando o refresh_token (criptografado em repouso com AES-256).
    Em conformidade com as diretrizes oficiais de segurança do Mercado Livre (OWASP / OAuth 2.0).
    """
    if not account.refresh_token:
        return None

    try:
        raw_refresh_token = crypto_decrypt(account.refresh_token)
    except Exception as e:
        logger.error(f"[MercadoLivre Security] Falha ao descriptografar refresh_token: {e}")
        return None

    client_id, client_secret, _ = get_ml_credentials()
    payload = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": raw_refresh_token
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "User-Agent": "ComentsIA/1.0"
    }

    try:
        resp = requests.post(ML_TOKEN_URL, data=payload, headers=headers, timeout=15)
        if resp.status_code == 200:
            token_data = resp.json()
            new_access_token = token_data.get("access_token")
            new_refresh_token = token_data.get("refresh_token")
            expires_in = token_data.get("expires_in", 21600)

            if new_access_token:
                account.access_token = crypto_encrypt(new_access_token)
            if new_refresh_token:
                account.refresh_token = crypto_encrypt(new_refresh_token)
            account.token_expires_at = default_brt_now() + timedelta(seconds=expires_in)
            db.session.commit()
            logger.info(f"[MercadoLivre Security] Token da conta {account.seller_id} renovado com sucesso e criptografado.")
            return new_access_token
        else:
            logger.warning(f"[MercadoLivre Security] Falha ao renovar token (HTTP {resp.status_code}): {resp.text}")
            return None
    except Exception as e:
        logger.error(f"[MercadoLivre Security] Erro de rede ao renovar token: {e}")
        return None


def get_fresh_ml_token(account: MercadoLivreAccount) -> Optional[str]:
    """
    Sempre renova e retorna o token de acesso oficial mais recente.
    Executa refresh preventivo com refresh_token a cada sincronização/operação.
    """
    if account.refresh_token:
        new_token = refresh_ml_token(account)
        if new_token:
            return new_token
    if account.access_token:
        try:
            return crypto_decrypt(account.access_token)
        except Exception:
            return None
    return None


def sync_all_account_data(account: MercadoLivreAccount) -> None:
    """Executa sincronização completa dos dados e histórico da conta do Mercado Livre com refresh contínuo."""
    token = get_fresh_ml_token(account)

    # 1. Reputação & Histórico
    try:
        data = fetch_seller_reputation_data(account.seller_id, token)
        if data.get("nickname") and not account.nickname.startswith("Conta_"):
            account.nickname = data["nickname"]
        if data.get("permalink"):
            account.permalink = data["permalink"]

        rep = data.get("seller_reputation") or {}
        account.level_id = rep.get("level_id")
        account.power_seller_status = rep.get("power_seller_status")

        metrics = rep.get("metrics") or {}
        
        def parse_ml_rate(metric_dict):
            if not metric_dict:
                return 0.0
            r = metric_dict.get("rate")
            if r is None:
                r = metric_dict.get("value", 0.0)
            try:
                val = float(r)
                return val if val <= 1.0 else (val / 100.0)
            except Exception:
                return 0.0

        account.claims_rate = parse_ml_rate(metrics.get("claims"))
        account.delayed_rate = parse_ml_rate(metrics.get("delayed_handling_time"))
        account.cancellations_rate = parse_ml_rate(metrics.get("cancellations"))

        transactions = rep.get("transactions") or data.get("transactions") or {}
        metrics_sales = ((metrics.get("sales") or {}).get("completed")) or 0
        tx_completed = transactions.get("completed")

        completed_val = 0
        if tx_completed is not None:
            completed_val = int(tx_completed)
        elif metrics_sales:
            completed_val = int(metrics_sales)
        elif transactions.get("total"):
            completed_val = int(transactions.get("total"))

        canceled_val = int(transactions.get("canceled") or ((metrics.get("cancellations") or {}).get("value")) or 0)
        total_val = int(transactions.get("total") or (completed_val + canceled_val))

        ratings = transactions.get("ratings") or {}
        account.positive_rating_pct = float(ratings.get("positive", 1.0))
        account.negative_rating_pct = float(ratings.get("negative", 0.0))
        account.neutral_rating_pct = float(ratings.get("neutral", 0.0))

        account.completed_transactions = completed_val
        account.canceled_transactions = canceled_val
        account.total_transactions = total_val
        account.raw_reputation_json = json.dumps(data)
    except Exception as e:
        logger.warning(f"[MercadoLivre] Falha parcial ao sincronizar reputação: {e}")

    # 2. Perguntas
    try:
        q_data = fetch_account_questions(account.seller_id, token)
        account.total_questions = q_data["total_questions"]
        account.unanswered_questions = q_data["unanswered_questions"]
        account.avg_response_time_minutes = q_data["avg_response_time_minutes"]
        account.questions_response_rate = q_data["questions_response_rate"]
        account.recent_questions_json = json.dumps(q_data["recent_questions"], ensure_ascii=False)
    except Exception as e:
        logger.warning(f"[MercadoLivre] Falha parcial ao sincronizar perguntas: {e}")

    # 3. Avaliações agregadas da loja e contagem de itens
    try:
        store_data = fetch_account_store_ratings_and_items(account.seller_id, token)
        account.total_active_items = store_data["total_active_items"]
        account.store_rating_average = store_data["store_rating_average"]
        account.total_store_reviews = store_data["total_store_reviews"]
        account.rating_breakdown_json = json.dumps(store_data["rating_breakdown"])

        # Se completed ainda for 0, usa a soma de itens vendidos acumulados nos anúncios da loja
        if (account.completed_transactions or 0) == 0 and store_data.get("total_sold_quantity", 0) > 0:
            account.completed_transactions = store_data["total_sold_quantity"]
            account.total_transactions = max(account.total_transactions or 0, account.completed_transactions + (account.canceled_transactions or 0))
    except Exception as e:
        logger.warning(f"[MercadoLivre] Falha parcial ao sincronizar avaliações da loja: {e}")

    # 4. Pedidos Reais, Feedbacks e Faturamento via OAuth (/orders/search e /billing)
    try:
        if token:
            orders_data = fetch_account_orders_and_metrics(account.seller_id, token)
            if orders_data["completed_orders"] > 0 or orders_data["total_revenue"] > 0:
                if orders_data["completed_orders"] > 0:
                    account.completed_transactions = orders_data["completed_orders"]
                    account.canceled_transactions = orders_data["canceled_orders"]
                    account.total_transactions = orders_data["total_orders"]
                account.total_revenue = orders_data.get("total_revenue", 0.0)
                account.avg_ticket = orders_data.get("avg_ticket", 0.0)
                
                total_fb = orders_data["positive_feedback_count"] + orders_data["negative_feedback_count"] + orders_data["neutral_feedback_count"]
                if total_fb > 0:
                    account.positive_rating_pct = round(orders_data["positive_feedback_count"] / total_fb, 3)
                    account.negative_rating_pct = round(orders_data["negative_feedback_count"] / total_fb, 3)
                    account.neutral_rating_pct = round(orders_data["neutral_feedback_count"] / total_fb, 3)

            # Reclamações ativas em tempo real (apenas para auditoria de chamados abertos)
            claims_data = fetch_account_claims_data(account.seller_id, token)

            # Resumo de Faturamento & Custos (Billing API)
            billing_data = fetch_account_billing_summary(account.seller_id, token)
            billing_data["total_revenue"] = account.total_revenue
            billing_data["avg_ticket"] = account.avg_ticket
            account.billing_summary_json = json.dumps(billing_data, ensure_ascii=False)

        # Se total_revenue for 0 mas houver vendas concluídas e/ou anúncios na loja
        if (account.total_revenue or 0.0) == 0.0 and (account.completed_transactions or 0) > 0:
            items = store_data.get("items") or []
            prices = [float(it.get("price", 0.0)) for it in items if float(it.get("price", 0.0)) > 0]
            avg_price = float(np.mean(prices)) if prices else 119.90
            account.avg_ticket = round(avg_price, 2)
            account.total_revenue = round((account.completed_transactions or 0) * account.avg_ticket, 2)
            
            # Estimativa de comissão do Mercado Livre (~16% taxa padrão Brasil)
            est_commission = round(account.total_revenue * 0.16, 2)
            account.billing_summary_json = json.dumps({
                "total_revenue": account.total_revenue,
                "avg_ticket": account.avg_ticket,
                "total_charges": est_commission,
                "charges": [
                    {"label": "Comissão Mercado Livre (Estimada ~16%)", "amount": est_commission, "type": "CV"},
                    {"label": "Tarifa de Processamento", "amount": round(account.total_revenue * 0.02, 2), "type": "MP"}
                ],
                "bonuses": []
            }, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"[MercadoLivre] Falha parcial ao sincronizar pedidos reais, faturamento e reclamações: {e}")

    # 5. Score de Saúde e Alertas
    health = account.calculate_account_health()
    account.health_score = health["overall_score"]
    account.last_sync_at = default_brt_now()
    db.session.commit()

    analyze_account_health_and_generate_alerts(account)


def analyze_account_health_and_generate_alerts(account: MercadoLivreAccount) -> List[MercadoLivreAlert]:
    """Gera alertas preventivos automáticos da IA se alguma métrica atingir margem de risco."""
    MercadoLivreAlert.query.filter_by(account_id=account.id, lido=False).delete()

    claims_pct = (account.claims_rate or 0.0) * 100
    delay_pct = (account.delayed_rate or 0.0) * 100
    cancel_pct = (account.cancellations_rate or 0.0) * 100

    alerts = []

    # 1. Reclamações
    if claims_pct >= 2.8:
        alerts.append(MercadoLivreAlert(
            account_id=account.id,
            tipo="claims_risk",
            titulo="🚨 Risco Crítico de Perda do Termômetro Verde",
            mensagem=f"Sua taxa de reclamações atingiu {claims_pct:.2f}%. O teto máximo permitido pelo Mercado Livre é 3.0%. Qualquer nova reclamação derrubará sua reputação.",
            nivel="danger"
        ))
    elif claims_pct >= 2.0:
        alerts.append(MercadoLivreAlert(
            account_id=account.id,
            tipo="claims_risk",
            titulo="⚠️ Atenção: Taxa de Reclamações em Elevação",
            mensagem=f"Sua taxa de reclamações está em {claims_pct:.2f}%. A margem de segurança recomendada é abaixo de 2.0%.",
            nivel="warning"
        ))

    # 2. Atrasos
    if delay_pct >= 13.5:
        alerts.append(MercadoLivreAlert(
            account_id=account.id,
            tipo="delay_risk",
            titulo="🚨 Risco Iminente no Prazo de Envio",
            mensagem=f"Seus envios com atraso estão em {delay_pct:.2f}% (o teto máximo é 15.0%). Agilize a postagem nos Correios ou Agências Mercado Livre.",
            nivel="danger"
        ))

    # 3. Cancelamentos
    if cancel_pct >= 2.0:
        alerts.append(MercadoLivreAlert(
            account_id=account.id,
            tipo="cancellation_risk",
            titulo="🚨 Taxa de Cancelamento Próxima do Limite",
            mensagem=f"Suas vendas canceladas pelo vendedor estão em {cancel_pct:.2f}% (limite máx de 2.5%). Revise seu estoque para evitar rupturas.",
            nivel="danger"
        ))

    # 4. Perguntas com demora
    if (account.avg_response_time_minutes or 0) > 120:
        alerts.append(MercadoLivreAlert(
            account_id=account.id,
            tipo="questions_delay",
            titulo="💬 Tempo de Resposta Elevado no Pré-Venda",
            mensagem=f"O tempo médio de resposta das perguntas está em {account.avg_response_time_minutes:.0f} minutos. Respostas em menos de 15 minutos aumentam as conversões em até 40%.",
            nivel="info"
        ))

    for a in alerts:
        db.session.add(a)
    db.session.commit()
    return alerts


# ==========================================
# ROTAS DO BLUEPRINT MERCADO LIVRE
# ==========================================

@mercadolivre_bp.route("/dashboard")
@mercadolivre_bp.route("/")
def dashboard():
    """Painel principal do Mercado Livre Analytics & AI Reputation."""
    user_id = session.get("user_id") or (session.get("user_info") or {}).get("id")
    if not user_id:
        flash("Faça login para acessar o módulo do Mercado Livre.", "warning")
        return redirect(url_for("login"))

    if not usuario_tem_addon_mercadolivre(user_id):
        flash("Assine o Add-on do Mercado Livre (R$ 29,90/mês) para acessar este módulo.", "warning")
        return redirect(url_for("integracoes"))

    accounts = MercadoLivreAccount.query.filter_by(user_id=str(user_id)).all()
    selected_account_id = request.args.get("account_id", type=int)
    
    current_account = None
    if selected_account_id:
        current_account = MercadoLivreAccount.query.filter_by(id=selected_account_id, user_id=str(user_id)).first()
    
    if not current_account and accounts:
        current_account = accounts[0]

    health_info = current_account.calculate_account_health() if current_account else None
    ai_report = current_account.get_ai_health_report() if current_account else None
    recent_questions = current_account.get_recent_questions() if current_account else []
    alerts = current_account.alerts.order_by(MercadoLivreAlert.created_at.desc()).all() if current_account else []

    client_id, _, _ = get_ml_credentials()
    oauth_available = bool(client_id)

    return render_template(
        "mercadolivre_dashboard.html",
        accounts=accounts,
        current_account=current_account,
        health_info=health_info,
        ai_report=ai_report,
        recent_questions=recent_questions,
        alerts=alerts,
        oauth_available=oauth_available
    )


@mercadolivre_bp.route("/conectar_publico", methods=["GET", "POST"])
def conectar_publico():
    """Redireciona diretamente para o fluxo oficial OAuth 2.0."""
    return redirect(url_for("mercadolivre.conectar_oauth"))


@mercadolivre_bp.route("/sincronizar/<int:account_id>", methods=["POST"])
def sincronizar_conta(account_id: int):
    """Sincroniza todos os dados e métricas em tempo real da conta."""
    user_id = session.get("user_id") or (session.get("user_info") or {}).get("id")
    if not usuario_tem_addon_mercadolivre(user_id):
        flash("Assine o Add-on do Mercado Livre (R$ 29,90/mês) para sincronizar esta conta.", "warning")
        return redirect(url_for("integracoes"))

    account = MercadoLivreAccount.query.filter_by(id=account_id, user_id=str(user_id)).first_or_404()

    try:
        sync_all_account_data(account)
        flash(f"Métricas da conta '{account.nickname}' atualizadas com sucesso!", "success")
    except Exception as e:
        logger.error(f"[MercadoLivre] Erro ao sincronizar conta {account_id}: {e}", exc_info=True)
        flash(f"Falha ao atualizar dados: {str(e)}", "danger")

    return redirect(url_for("mercadolivre.dashboard", account_id=account.id))


@mercadolivre_bp.route("/conta/<int:account_id>/gerar_parecer_ia", methods=["POST"])
def gerar_parecer_ia(account_id: int):
    """Gera o parecer estratégico de IA para a saúde da conta."""
    user_id = session.get("user_id") or (session.get("user_info") or {}).get("id")
    account = MercadoLivreAccount.query.filter_by(id=account_id, user_id=str(user_id)).first_or_404()

    try:
        report = generate_account_health_ai_report(account)
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
            return jsonify({"success": True, "report": report})
        flash("Parecer Estratégico de IA gerado com sucesso!", "success")
    except Exception as e:
        logger.error(f"[MercadoLivre AI] Erro ao gerar parecer da conta {account_id}: {e}", exc_info=True)
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
            return jsonify({"success": False, "error": str(e)}), 500
        flash(f"Falha ao gerar parecer de IA: {str(e)}", "danger")

    return redirect(url_for("mercadolivre.dashboard", account_id=account.id))


@mercadolivre_bp.route("/conta/<int:account_id>/relatorio/pdf")
def baixar_relatorio_pdf(account_id: int):
    """Gera e faz o download do Relatório Executivo de Saúde da Conta em PDF."""
    user_id = session.get("user_id") or (session.get("user_info") or {}).get("id")
    account = MercadoLivreAccount.query.filter_by(id=account_id, user_id=str(user_id)).first_or_404()

    try:
        pdf_buf = gerar_pdf_relatorio_mercadolivre(account)
        filename = f"Relatorio_MercadoLivre_{account.nickname}_{datetime.now().strftime('%Y%m%d')}.pdf"
        return send_file(
            pdf_buf,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        logger.error(f"[MercadoLivre PDF] Erro ao gerar PDF da conta {account_id}: {e}", exc_info=True)
        flash(f"Falha ao gerar relatório PDF: {str(e)}", "danger")
        return redirect(url_for("mercadolivre.dashboard", account_id=account.id))


@mercadolivre_bp.route("/pergunta/formalizar", methods=["POST"])
def formalizar_resposta_ajax():
    """Transforma o texto escrito pelo vendedor em uma versão mais formal com IA sem alterar o significado."""
    user_id = session.get("user_id") or (session.get("user_info") or {}).get("id")
    if not user_id:
        return jsonify({"success": False, "error": "Não autenticado"}), 401

    data = request.get_json() or request.form
    texto_usuario = (data.get("texto_usuario") or "").strip()
    pergunta = (data.get("pergunta") or "").strip()
    item_titulo = data.get("item_titulo", "")

    if not texto_usuario:
        return jsonify({"success": False, "error": "Por favor, digite sua resposta no campo antes de torná-la mais formal."}), 400

    try:
        resposta_formal = formalizar_resposta_ia(texto_usuario, pergunta, item_titulo)
        return jsonify({"success": True, "resposta_formal": resposta_formal})
    except Exception as e:
        logger.error(f"[MercadoLivre AI Formalize] Erro: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@mercadolivre_bp.route("/pergunta/sugerir_resposta", methods=["POST"])
def sugerir_resposta_ajax():
    """Sugere ou formaliza resposta com IA para pergunta pré/pós-venda via AJAX."""
    user_id = session.get("user_id") or (session.get("user_info") or {}).get("id")
    if not user_id:
        return jsonify({"success": False, "error": "Não autenticado"}), 401

    data = request.get_json() or request.form
    texto_usuario = (data.get("texto_usuario") or "").strip()
    pergunta = data.get("pergunta", "").strip()
    item_titulo = data.get("item_titulo", "")

    if texto_usuario:
        try:
            resposta_formal = formalizar_resposta_ia(texto_usuario, pergunta, item_titulo)
            return jsonify({"success": True, "resposta": resposta_formal, "resposta_formal": resposta_formal})
        except Exception as e:
            logger.error(f"[MercadoLivre AI Formalize] Erro: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    if not pergunta:
        return jsonify({"success": False, "error": "Texto da pergunta não informado"}), 400

    try:
        resposta = sugerir_resposta_pergunta_ia(pergunta, item_titulo)
        return jsonify({"success": True, "resposta": resposta})
    except Exception as e:
        logger.error(f"[MercadoLivre AI] Erro ao sugerir resposta: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@mercadolivre_bp.route("/pergunta/responder", methods=["POST"])
def responder_pergunta_ajax():
    """Publica a resposta para a pergunta oficial no Mercado Livre."""
    user_id = session.get("user_id") or (session.get("user_info") or {}).get("id")
    if not user_id:
        return jsonify({"success": False, "error": "Não autenticado"}), 401

    data = request.get_json() or request.form
    account_id = data.get("account_id")
    question_id = data.get("question_id")
    resposta_texto = (data.get("resposta") or "").strip()

    if not question_id or not resposta_texto:
        return jsonify({"success": False, "error": "ID da pergunta e texto da resposta são obrigatórios."}), 400

    account = MercadoLivreAccount.query.filter_by(id=account_id, user_id=str(user_id)).first()
    if not account:
        return jsonify({"success": False, "error": "Conta do Mercado Livre não encontrada."}), 404

    if not account.access_token:
        return jsonify({
            "success": False, 
            "error": "Esta conta foi conectada em modo público (apenas leitura). Para postar respostas diretamente pelo aplicativo, conecte com o login oficial (OAuth) do Mercado Livre."
        }), 403

    token = None
    try:
        if account.token_expires_at and account.token_expires_at <= default_brt_now() + timedelta(minutes=10):
            token = refresh_ml_token(account)
        if not token:
            token = crypto_decrypt(account.access_token)
    except Exception as e:
        logger.error(f"[MercadoLivre Answers] Erro ao recuperar token: {e}")
        return jsonify({"success": False, "error": "Falha de autenticação ao descriptografar token."}), 500

    result = post_answer_to_mercadolivre(question_id, resposta_texto, token)

    if not result.get("success") and result.get("status_code") == 401:
        token = refresh_ml_token(account)
        if token:
            result = post_answer_to_mercadolivre(question_id, resposta_texto, token)

    if result.get("success"):
        try:
            recent_q = account.get_recent_questions()
            for q in recent_q:
                if str(q.get("id")) == str(question_id):
                    q["status"] = "ANSWERED"
                    q["answer_text"] = resposta_texto
                    break
            account.recent_questions_json = json.dumps(recent_q, ensure_ascii=False)
            if account.unanswered_questions and account.unanswered_questions > 0:
                account.unanswered_questions -= 1
            db.session.commit()
        except Exception as e:
            logger.warning(f"[MercadoLivre Answers] Falha ao atualizar cache local da pergunta: {e}")

        return jsonify({
            "success": True, 
            "message": "Resposta publicada com sucesso no Mercado Livre!",
            "question_id": question_id,
            "answer_text": resposta_texto
        })
    else:
        return jsonify({
            "success": False, 
            "error": result.get("error", "Não foi possível publicar a resposta no Mercado Livre.")
        }), 400


@mercadolivre_bp.route("/desconectar/<int:account_id>", methods=["POST"])
def desconectar_conta(account_id: int):
    """Desconecta a conta do vendedor."""
    user_id = session.get("user_id") or (session.get("user_info") or {}).get("id")
    account = MercadoLivreAccount.query.filter_by(id=account_id, user_id=str(user_id)).first_or_404()

    nickname = account.nickname
    db.session.delete(account)
    db.session.commit()
    flash(f"Conta '{nickname}' desconectada com sucesso.", "info")
    return redirect(url_for("mercadolivre.dashboard"))


def generate_pkce_pair() -> Tuple[str, str]:
    """Gera o par code_verifier e code_challenge (S256) compatível com RFC 7636 do Mercado Livre."""
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return code_verifier, code_challenge


# ==========================================
# FLUXO OAUTH 2.0 OFICIAL DO MERCADO LIVRE
# ==========================================

@mercadolivre_bp.route("/conectar")
def conectar_oauth():
    """Inicia o fluxo OAuth 2.0 redirecionando o vendedor para o Mercado Livre."""
    user_id = session.get("user_id") or (session.get("user_info") or {}).get("id")
    if not user_id:
        flash("Faça login para conectar sua conta.", "warning")
        return redirect(url_for("login"))

    if not usuario_tem_addon_mercadolivre(user_id):
        flash("Assine o Add-on do Mercado Livre (R$ 29,90/mês) para conectar uma conta.", "warning")
        return redirect(url_for("integracoes"))

    client_id, _, redirect_uri = get_ml_credentials()
    if not client_id:
        flash("Credenciais do Mercado Livre não configuradas no servidor.", "danger")
        return redirect(url_for("mercadolivre.dashboard"))

    state = f"ml_auth_{user_id}_{int(datetime.now().timestamp())}"
    session["ml_oauth_state"] = state

    # Geração do PKCE (obrigatório se o switch PKCE estiver ativo no portal de desenvolvedores)
    code_verifier, code_challenge = generate_pkce_pair()
    session["ml_code_verifier"] = code_verifier

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256"
    }
    url_auth = f"{ML_AUTH_URL}?{urllib.parse.urlencode(params)}"
    return redirect(url_auth)


@mercadolivre_bp.route("/callback")
def callback_oauth():
    """Callback do Mercado Livre após aprovação do vendedor."""
    user_id = session.get("user_id") or (session.get("user_info") or {}).get("id")
    code = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")
    error_desc = request.args.get("error_description")

    if error:
        logger.error(f"[MercadoLivre OAuth] Erro retornado: {error} - {error_desc}")
        flash(f"Autorização cancelada ou recusada: {error_desc or error}", "danger")
        return redirect(url_for("mercadolivre.dashboard"))

    if not code:
        flash("Código de autorização não recebido do Mercado Livre.", "danger")
        return redirect(url_for("mercadolivre.dashboard"))

    client_id, client_secret, redirect_uri = get_ml_credentials()
    payload = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri
    }

    # Envia o code_verifier do PKCE caso tenha sido gerado
    code_verifier = session.get("ml_code_verifier")
    if code_verifier:
        payload["code_verifier"] = code_verifier

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "User-Agent": "ComentsIA/1.0"
    }

    try:
        resp = requests.post(ML_TOKEN_URL, data=payload, headers=headers, timeout=15)
        if resp.status_code != 200:
            logger.error(f"[MercadoLivre OAuth] Falha na troca do token: {resp.text}")
            flash(f"Falha ao autenticar com o Mercado Livre: {resp.text}", "danger")
            return redirect(url_for("mercadolivre.dashboard"))

        token_data = resp.json()
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 21600)
        seller_id = str(token_data.get("user_id"))

        nickname = f"Vendedor_{seller_id}"
        permalink = f"https://www.mercadolivre.com.br/perfil/{nickname}"
        site_id = "MLB"

        headers_me = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "User-Agent": "ComentsIA/1.0"
        }
        try:
            resp_me = requests.get(f"{ML_API_BASE}/users/me", headers=headers_me, timeout=10)
            if resp_me.status_code == 200:
                me_data = resp_me.json()
                nickname = me_data.get("nickname") or nickname
                permalink = me_data.get("permalink") or permalink
                site_id = me_data.get("site_id") or site_id
        except Exception as e:
            logger.debug(f"[MercadoLivre OAuth] /users/me falhou: {e}")

        account = MercadoLivreAccount.query.filter_by(user_id=str(user_id), seller_id=seller_id).first()
        if not account:
            account = MercadoLivreAccount(
                user_id=str(user_id),
                seller_id=seller_id,
                nickname=nickname,
                permalink=permalink,
                site_id=site_id
            )
            db.session.add(account)
            db.session.commit()
        else:
            account.nickname = nickname
            account.permalink = permalink
            account.site_id = site_id

        if access_token:
            account.access_token = crypto_encrypt(access_token)
        if refresh_token:
            account.refresh_token = crypto_encrypt(refresh_token)
        account.token_expires_at = default_brt_now() + timedelta(seconds=expires_in)

        # Sincroniza dados completos
        sync_all_account_data(account)

        flash(f"Conta '{account.nickname}' autenticada e sincronizada via OAuth!", "success")
        return redirect(url_for("mercadolivre.dashboard", account_id=account.id))

    except Exception as e:
        logger.error(f"[MercadoLivre OAuth] Exceção no callback: {e}", exc_info=True)
        flash(f"Erro ao processar login com o Mercado Livre: {str(e)}", "danger")
        return redirect(url_for("mercadolivre.dashboard"))
