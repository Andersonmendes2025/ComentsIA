"""
services/email_service.py
Serviço dedicado para envio de e-mails de chamado de suporte ao cliente e integração com o painel admin.
Usa a infraestrutura SMTP já configurada em email_utils.py.
"""
from __future__ import annotations

import logging
import os
import random
import string
from datetime import datetime
from typing import List, Optional

import pytz

from email_utils import enviar_email


def _gerar_protocolo() -> str:
    """Gera número de protocolo único no formato CSUP-AAAAMMDD-XXXX."""
    brt = pytz.timezone("America/Sao_Paulo")
    hoje = datetime.now(brt).strftime("%Y%m%d")
    sufixo = "".join(random.choices(string.digits, k=4))
    return f"CSUP-{hoje}-{sufixo}"


def _formatar_historico(historico: List[dict]) -> str:
    """Formata o histórico de conversa para exibição no e-mail."""
    if not historico:
        return "<em>(sem histórico disponível)</em>"
    linhas = []
    for msg in historico[-10:]:  # últimas 10 mensagens
        role = msg.get("role", "")
        content = msg.get("content", "")
        label = "👤 Usuário" if role == "user" else "🤖 Assistente"
        linhas.append(f"<p><strong>{label}:</strong><br>{content}</p>")
    return "\n".join(linhas)


def _montar_html_chamado_equipe(
    protocolo: str,
    nome_usuario: str,
    email_usuario: str,
    plano: str,
    assunto: str,
    descricao: str,
    historico: List[dict],
) -> str:
    """Monta o HTML do e-mail de chamado enviado para a equipe de suporte."""
    historico_html = _formatar_historico(historico)
    brt = pytz.timezone("America/Sao_Paulo")
    agora = datetime.now(brt).strftime("%d/%m/%Y às %H:%M (BRT)")

    return f"""
    <div style="background:#f4f7fa;padding:40px 20px;font-family:Arial,sans-serif;">
      <table border="0" cellpadding="0" cellspacing="0" width="100%"
             style="max-width:680px;margin:0 auto;background:#fff;border-radius:12px;
                    overflow:hidden;box-shadow:0 4px 15px rgba(0,0,0,.07);">
        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#0d6efd 0%,#4f46e5 100%);
                     padding:30px 24px;color:#fff;">
            <h1 style="margin:0;font-size:20px;">🎫 Novo Chamado de Suporte</h1>
            <p style="margin:8px 0 0;opacity:.85;font-size:14px;">
              Protocolo: <strong>{protocolo}</strong> &mdash; {agora}
            </p>
          </td>
        </tr>
        <!-- Dados do usuário -->
        <tr>
          <td style="padding:24px;border-bottom:1px solid #e2e8f0;">
            <h2 style="font-size:16px;color:#1e293b;margin:0 0 12px;">Dados do Cliente</h2>
            <table style="width:100%;font-size:14px;color:#334155;">
              <tr><td style="padding:4px 0;width:120px;"><strong>Nome:</strong></td>
                  <td>{nome_usuario}</td></tr>
              <tr><td style="padding:4px 0;"><strong>E-mail:</strong></td>
                  <td>{email_usuario}</td></tr>
              <tr><td style="padding:4px 0;"><strong>Plano:</strong></td>
                  <td>{plano.upper()}</td></tr>
            </table>
          </td>
        </tr>
        <!-- Chamado -->
        <tr>
          <td style="padding:24px;border-bottom:1px solid #e2e8f0;">
            <h2 style="font-size:16px;color:#1e293b;margin:0 0 12px;">Detalhes da Solicitação</h2>
            <p style="font-size:14px;color:#334155;margin:0 0 8px;">
              <strong>Assunto:</strong> {assunto}
            </p>
            <p style="font-size:14px;color:#334155;margin:0;">
              <strong>Descrição:</strong><br>{descricao}
            </p>
          </td>
        </tr>
        <!-- Histórico -->
        <tr>
          <td style="padding:24px;">
            <h2 style="font-size:16px;color:#1e293b;margin:0 0 12px;">
              Histórico Recente da Conversa
            </h2>
            <div style="background:#f8fafc;border-radius:8px;padding:16px;
                        font-size:13px;color:#334155;max-height:400px;overflow:auto;">
              {historico_html}
            </div>
          </td>
        </tr>
        <!-- Footer -->
        <tr>
          <td style="background:#f8fafc;padding:16px 24px;
                     border-top:1px solid #e2e8f0;text-align:center;
                     font-size:12px;color:#64748b;">
            ComentsIA — Sistema de Suporte Automatizado<br>
            Prazo de resposta acordado com o cliente: <strong>até 2 dias úteis</strong>.
          </td>
        </tr>
      </table>
    </div>
    """


def _montar_html_confirmacao_cliente(
    protocolo: str,
    nome_usuario: str,
    assunto: str,
    descricao: str,
) -> str:
    """Monta o HTML do e-mail de confirmação enviado para o próprio cliente."""
    brt = pytz.timezone("America/Sao_Paulo")
    agora = datetime.now(brt).strftime("%d/%m/%Y às %H:%M (BRT)")

    return f"""
    <div style="background:#f4f7fa;padding:40px 20px;font-family:Arial,sans-serif;">
      <table border="0" cellpadding="0" cellspacing="0" width="100%"
             style="max-width:600px;margin:0 auto;background:#fff;border-radius:12px;
                    overflow:hidden;box-shadow:0 4px 15px rgba(0,0,0,.07);">
        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#0d6efd 0%,#4f46e5 100%);
                     padding:30px 24px;color:#fff;text-align:center;">
            <h1 style="margin:0;font-size:22px;">✅ Chamado Aberto com Sucesso</h1>
            <p style="margin:8px 0 0;opacity:.9;font-size:14px;">
              Protocolo: <strong>{protocolo}</strong>
            </p>
          </td>
        </tr>
        <!-- Conteúdo -->
        <tr>
          <td style="padding:28px 24px;color:#334155;line-height:1.6;">
            <p style="font-size:15px;margin-top:0;">
              Olá, <strong>{nome_usuario}</strong>!
            </p>
            <p style="font-size:14px;">
              Confirmamos a abertura do seu chamado de suporte em nossa plataforma. Nossa equipe técnica já recebeu todos os detalhes e está analisando a sua solicitação.
            </p>
            
            <div style="background:#f8fafc;border-left:4px solid #0d6efd;padding:16px;border-radius:0 8px 8px 0;margin:20px 0;">
              <p style="margin:0 0 6px;font-size:14px;"><strong>Assunto:</strong> {assunto}</p>
              <p style="margin:0;font-size:14px;"><strong>Descrição:</strong> {descricao}</p>
              <p style="margin:8px 0 0;font-size:12px;color:#64748b;">Aberto em: {agora}</p>
            </div>

            <p style="font-size:14px;color:#1e293b;font-weight:600;">
              ⏰ Prazo de Resposta:
            </p>
            <p style="font-size:14px;margin-top:4px;">
              Nossa equipe responderá diretamente a este e-mail em <strong>até 2 dias úteis</strong>.
            </p>
            
            <p style="font-size:13px;color:#64748b;margin-top:24px;">
              Se tiver informações adicionais para complementar, basta responder a este e-mail mantendo o assunto original.
            </p>
          </td>
        </tr>
        <!-- Footer -->
        <tr>
          <td style="background:#f8fafc;padding:16px 24px;
                     border-top:1px solid #e2e8f0;text-align:center;
                     font-size:12px;color:#64748b;">
            Equipe de Sucesso do Cliente &mdash; <strong>ComentsIA</strong><br>
            <a href="https://comentsia.com.br" style="color:#0d6efd;text-decoration:none;">comentsia.com.br</a>
          </td>
        </tr>
      </table>
    </div>
    """


def _salvar_ticket_no_banco(protocolo: str, assunto: str, descricao: str, email_usuario: str):
    """Registra o chamado na tabela Ticket para visualização no painel Admin."""
    try:
        from flask import has_app_context
        from models import db, Ticket, Company

        def _do_save():
            company = None
            if email_usuario:
                company = Company.query.filter_by(owner_user_id=email_usuario).first()
            if not company:
                company = Company.query.first()

            if company:
                ticket = Ticket(
                    company_id=company.id,
                    assunto=f"[{protocolo}] {assunto} - {descricao[:100]}",
                    status="aberto",
                    prioridade="normal",
                    owner_id=email_usuario or "Suporte IA",
                )
                db.session.add(ticket)
                db.session.commit()
                logging.info("[suporte] Ticket registrado no banco de dados com ID %s", ticket.id)

        if has_app_context():
            _do_save()
        else:
            from main import app as flask_app
            with flask_app.app_context():
                _do_save()
    except Exception as ex_db:
        logging.warning("[suporte] Não foi possível salvar ticket no banco: %s", ex_db)


def abrir_chamado_suporte(
    assunto: str,
    descricao: str,
    nome_usuario: str,
    email_usuario: str,
    plano: str,
    historico: Optional[List[dict]] = None,
) -> str:
    """
    Abre um chamado de suporte:
    1. Gera número de protocolo único (CSUP-AAAAMMDD-XXXX).
    2. Salva o ticket no banco de dados (tabela tickets do Admin).
    3. Envia e-mail para a equipe de suporte (suporte@comentsia.com.br).
    4. Envia e-mail de confirmação para o cliente com prazo de até 2 dias úteis.

    Returns:
        Número do protocolo gerado.
    """
    if historico is None:
        historico = []

    protocolo = _gerar_protocolo()

    # 1. Salva no banco de dados do Admin
    _salvar_ticket_no_banco(protocolo, assunto, descricao, email_usuario)

    # 2. Envia e-mail para a equipe de suporte
    destinatario_equipe = os.getenv("SUPPORT_EMAIL", "suporte@comentsia.com.br")
    assunto_equipe = f"[{protocolo}] Chamado: {assunto[:60]}"
    corpo_equipe = _montar_html_chamado_equipe(
        protocolo=protocolo,
        nome_usuario=nome_usuario or "Não informado",
        email_usuario=email_usuario or "Não informado",
        plano=plano or "free",
        assunto=assunto,
        descricao=descricao,
        historico=historico,
    )

    try:
        enviar_email(destinatario_equipe, assunto_equipe, corpo_equipe)
        logging.info("[suporte] Chamado %s enviado para a equipe de suporte (%s)", protocolo, destinatario_equipe)
    except Exception:
        logging.exception("[suporte] Falha ao enviar e-mail do chamado para a equipe")

    # 3. Envia e-mail de confirmação para o cliente
    if email_usuario and "@" in email_usuario:
        assunto_cliente = f"[{protocolo}] Chamado de Suporte Aberto - ComentsIA"
        corpo_cliente = _montar_html_confirmacao_cliente(
            protocolo=protocolo,
            nome_usuario=nome_usuario or "Cliente",
            assunto=assunto,
            descricao=descricao,
        )
        try:
            enviar_email(email_usuario, assunto_cliente, corpo_cliente)
            logging.info("[suporte] Confirmação de chamado %s enviada para o cliente (%s)", protocolo, email_usuario)
        except Exception:
            logging.exception("[suporte] Falha ao enviar e-mail de confirmação para o cliente")

    return protocolo
