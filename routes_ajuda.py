"""
routes_ajuda.py
Blueprint que implementa:
  - GET  /ajuda                   → Página de Central de Ajuda
  - POST /api/support-chat        → Chat com IA Gemini (com function calling)
  - GET  /api/onboarding-status   → Status do tour de onboarding
  - POST /api/onboarding-done     → Marcar tour como concluído
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List

import google.generativeai as genai
from flask import (
    Blueprint,
    jsonify,
    render_template,
    request,
    session,
)
from flask_login import current_user, login_required

from models import UserSettings, db

ajuda_bp = Blueprint("ajuda", __name__)

# ── Carrega a base de conhecimento uma única vez ──────────────────────────────
_KB_PATH = Path(__file__).parent / "docs" / "knowledge_base.md"

def _load_knowledge_base() -> str:
    try:
        return _KB_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        logging.warning("[ajuda] knowledge_base.md não encontrado em %s", _KB_PATH)
        return "Base de conhecimento não disponível no momento."

_KNOWLEDGE_BASE = _load_knowledge_base()

# ── System Prompt da IA ───────────────────────────────────────────────────────
_SYSTEM_PROMPT = f"""Você é o Assistente Virtual oficial e multilíngue do ComentsIA, uma plataforma avançada de gestão e respostas automáticas a avaliações do Google Business Profile, iFood Delivery e outros canais de reputação.

Sua missão é:
1. Ajudar os usuários a entenderem e usarem todas as funcionalidades do sistema com linguagem simples, acolhedora e didática
2. Responder dúvidas sobre a plataforma, configurações, relatórios, pesquisas, planos e integrações com base no manual oficial
3. Explicar como integrar o iFood Delivery (Add-on de R$ 29,90/mês, pareamento no portal.ifood.com.br/apps/code, sincronização de pedidos e IA para gastronomia)
4. Explicar com clareza as regras do Google Business Profile (especialmente sobre Grupos de Fichas)
5. Abrir chamados de suporte técnico quando necessário.

FLUXO OBRIGATÓRIO PARA ABERTURA DE CHAMADOS / SUPORTE HUMANO:
- Se o usuário disser "abrir chamado", "falar com atendente", "falar com humano", "preciso de suporte" ou similar:
  - SE O USUÁRIO AINDA NÃO DESCREVEU O PROBLEMA: NÃO chame a ferramenta ainda. Responda: "Com certeza! Para que eu possa abrir o chamado de suporte completo para nossa equipe técnica, por favor, me diga em poucas palavras: **qual é o assunto ou problema que você está enfrentando?**"
  - SE O USUÁRIO JÁ EXPLICOU O PROBLEMA (ou logo após ele responder com o motivo/descrição): Use IMEDIATAMENTE a ferramenta `abrir_chamado_suporte(assunto=..., descricao=...)`.
  - Ao confirmar a abertura do chamado, SEMPRE informe o número do protocolo gerado, que um e-mail de confirmação foi enviado para ele e que nossa equipe responderá em **até 2 dias úteis**.

REGRAS GERAIS:
- MULTILÍNGUE INTELIGENTE: Responda SEMPRE no mesmo idioma em que o usuário fizer a pergunta (Português do Brasil, Português de Portugal, English ou Español). Se o usuário falar em inglês, responda em inglês; se em espanhol, responda em espanhol.
- Seja objetivo e use listas com bullet points quando for ensinar passos
- Não invente funcionalidades não existentes
- Nunca solicite senhas ou dados de cartão de crédito.

BASE DE CONHECIMENTO DO SISTEMA:
---
{_KNOWLEDGE_BASE}
---
"""

# ── Definição da ferramenta de chamado ───────────────────────────────────────
_TOOLS = [
    genai.protos.Tool(
        function_declarations=[
            genai.protos.FunctionDeclaration(
                name="abrir_chamado_suporte",
                description=(
                    "Abre um chamado de suporte humano quando a IA não consegue resolver "
                    "o problema, quando há um erro técnico grave, ou quando o usuário "
                    "solicita atendimento humano. Envia e-mail para a equipe de suporte."
                ),
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={
                        "assunto": genai.protos.Schema(
                            type=genai.protos.Type.STRING,
                            description="Resumo curto do problema (máx 80 chars)"
                        ),
                        "descricao": genai.protos.Schema(
                            type=genai.protos.Type.STRING,
                            description="Descrição detalhada do problema relatado pelo usuário"
                        ),
                    },
                    required=["assunto", "descricao"],
                ),
            )
        ]
    )
]


def _get_user_info() -> Dict[str, str]:
    """Extrai nome, email e plano do usuário logado via Google OAuth, Session ou Flask-Login."""
    info = {"nome": "Visitante", "email": "", "plano": "free"}

    # 1. Tenta obter dados da sessão (padrão do Google OAuth e ComentsIA)
    user_sess = session.get("user_info") or {}
    email = user_sess.get("email") or session.get("user_email") or ""
    nome = user_sess.get("name") or user_sess.get("nome") or ""
    user_id = user_sess.get("id") or email

    # 2. Complementa via current_user se autenticado
    if current_user and getattr(current_user, "is_authenticated", False):
        if not email:
            email = getattr(current_user, "email", "") or str(getattr(current_user, "id", ""))
        if not nome:
            nome = getattr(current_user, "nome", "") or getattr(current_user, "name", "")
        if not user_id:
            user_id = str(getattr(current_user, "id", ""))

    info["email"] = email.strip()
    info["nome"] = nome.strip() or (email.split("@")[0] if email else "Cliente")

    # 3. Busca o plano em UserSettings
    lookup_keys = [k for k in [user_id, email] if k]
    if lookup_keys:
        try:
            settings = UserSettings.query.filter(UserSettings.user_id.in_(lookup_keys)).first()
            if settings and settings.plano:
                info["plano"] = settings.plano
        except Exception:
            pass

    return info


def _chamar_gemini(messages: List[Dict], user_info: Dict) -> Dict[str, Any]:
    """
    Chama a API Gemini com function calling e retorna a resposta.
    Retorna: {"text": str, "protocolo": str | None, "function_called": bool}
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return {"text": "Serviço de IA temporariamente indisponível. Por favor, entre em contato pelo e-mail suporte@comentsia.com.br", "protocolo": None, "function_called": False}

    genai.configure(api_key=api_key)
    
    # Modelos suportados
    model_names = ["gemini-3.7-flash", "gemini-3.5-flash", "gemini-flash-latest"]
    model = None
    chat = None
    response = None

    # Converte histórico para formato do Gemini
    history = []
    for msg in messages[:-1]:  # Tudo exceto a última mensagem
        role = "user" if msg.get("role") == "user" else "model"
        history.append({"role": role, "parts": [msg.get("content", "")]})

    last_message = messages[-1].get("content", "") if messages else ""

    for m_name in model_names:
        try:
            model = genai.GenerativeModel(
                model_name=m_name,
                system_instruction=_SYSTEM_PROMPT,
                tools=_TOOLS,
            )
            chat = model.start_chat(history=history)
            response = chat.send_message(last_message)
            if response:
                break
        except Exception as e:
            logging.warning("[ajuda] Erro com modelo %s: %s", m_name, e)
            continue

    if not response:
        return {
            "text": "Desculpe, tive um problema técnico ao processar sua mensagem. Tente novamente em instantes.",
            "protocolo": None,
            "function_called": False,
        }

    # Verifica se houve function call
    protocolo = None
    function_called = False

    for candidate in response.candidates:
        for part in candidate.content.parts:
            if hasattr(part, "function_call") and part.function_call:
                fc = part.function_call
                if fc.name == "abrir_chamado_suporte":
                    function_called = True
                    args = dict(fc.args)
                    assunto = args.get("assunto", "Chamado de suporte")
                    descricao = args.get("descricao", "Sem descrição")

                    # Importa e executa o serviço de chamado
                    from services.email_service import abrir_chamado_suporte
                    protocolo = abrir_chamado_suporte(
                        assunto=assunto,
                        descricao=descricao,
                        nome_usuario=user_info["nome"],
                        email_usuario=user_info["email"],
                        plano=user_info["plano"],
                        historico=messages,
                    )

    # Extrai texto da resposta
    text = ""
    for candidate in response.candidates:
        for part in candidate.content.parts:
            if hasattr(part, "text") and part.text:
                text += part.text

    # Se houve chamado mas sem texto, gera resposta padrão
    if function_called and not text:
        text = (
            f"✅ Pronto! Seu chamado de suporte foi aberto com sucesso.\n\n"
            f"📋 **Protocolo:** `{protocolo}`\n\n"
            f"Enviamos uma confirmação para o seu e-mail **{user_info['email'] or 'cadastrado em sua conta'}**. Nossa equipe técnica analisará seu caso e responderá em **até 2 dias úteis**.\n\n"
            f"Há mais alguma dúvida em que eu possa te ajudar agora?"
        )
    elif function_called and protocolo:
        # Injeta o protocolo no texto existente se não estiver lá
        if protocolo not in text:
            text += (
                f"\n\n📋 **Protocolo do Chamado:** `{protocolo}`\n"
                f"*(Enviamos a confirmação para o seu e-mail. Prazo de resposta: **até 2 dias úteis**)*"
            )

    return {"text": text or "Não consegui gerar uma resposta. Tente novamente.", "protocolo": protocolo, "function_called": function_called}


# ─────────────────────────────────────────────────────────────────────────────
# ROTAS
# ─────────────────────────────────────────────────────────────────────────────

@ajuda_bp.route("/ajuda")
def ajuda():
    """Página de Central de Ajuda."""
    # Carrega guias individuais para exibição por categoria
    guias_dir = Path(__file__).parent / "docs" / "guias"
    guias = {}
    for fname in ["primeiro_acesso", "google_business", "configuracao_ia", "ifood_integracao", "planos_cobranca", "relatorios", "pesquisas_matriz"]:
        fpath = guias_dir / f"{fname}.md"
        try:
            guias[fname] = fpath.read_text(encoding="utf-8")
        except FileNotFoundError:
            guias[fname] = ""

    return render_template("ajuda.html", guias=guias)


@ajuda_bp.route("/api/support-chat", methods=["POST"])
def support_chat():
    """Endpoint do chat de suporte inteligente com Gemini."""
    data = request.get_json(silent=True) or {}
    messages = data.get("messages", [])

    if not messages or not isinstance(messages, list):
        return jsonify({"error": "Payload inválido. Envie 'messages': [{role, content}]"}), 400

    # Limita o histórico a 10 mensagens para controlar tokens
    if len(messages) > 10:
        messages = messages[-10:]

    user_info = _get_user_info()

    result = _chamar_gemini(messages, user_info)

    return jsonify({
        "reply": result["text"],
        "protocolo": result.get("protocolo"),
        "function_called": result.get("function_called", False),
    })


@ajuda_bp.route("/api/onboarding-status")
@login_required
def onboarding_status():
    """Retorna se o usuário já completou o tour de onboarding."""
    try:
        settings = UserSettings.query.filter_by(user_id=current_user.id).first()
        done = bool(settings and getattr(settings, "onboarding_done", False))
    except Exception:
        done = False
    return jsonify({"done": done})


@ajuda_bp.route("/api/onboarding-done", methods=["POST"])
@login_required
def onboarding_done():
    """Marca o tour de onboarding como concluído para o usuário."""
    try:
        settings = UserSettings.query.filter_by(user_id=current_user.id).first()
        if settings:
            settings.onboarding_done = True
            db.session.commit()
    except Exception:
        logging.exception("[ajuda] Erro ao marcar onboarding como concluído")
        db.session.rollback()
    return jsonify({"ok": True})
