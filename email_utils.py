# email_utils.py
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from cryptography.fernet import Fernet
from dotenv import load_dotenv
from flask import url_for

from utils.crypto import decrypt

load_dotenv()


def _load_key_bytes():
    key = os.getenv("ENCRYPTION_KEY")  # opcional: chave direta (base64 do Fernet)
    path = os.getenv("ENCRYPTION_KEY_PATH")  # ou caminho p/ arquivo com a chave
    if key:
        return key.encode()
    if path and os.path.exists(path):
        return open(path, "rb").read().strip()
    raise RuntimeError("ENCRYPTION_KEY ou ENCRYPTION_KEY_PATH ausente")


FERNET = Fernet(_load_key_bytes())


def encrypt(s: str) -> str:
    return FERNET.encrypt(s.encode()).decode()


def decrypt(t: str) -> str:
    return FERNET.decrypt(t.encode()).decode()


def _maybe_decrypt(value: str) -> str:
    """Tenta descriptografar; se falhar, retorna o valor original."""
    if not value:
        return ""
    try:
        dec = decrypt(value)
        return dec or value
    except Exception:
        return value


def montar_email_boas_vindas(nome_do_usuario: str) -> str:
    """
    Monta HTML do e-mail de boas-vindas.
    Aceita nome criptografado (vai tentar decrypt) ou texto plano.
    OBS: precisa de app context para url_for funcionar.
    """
    nome_do_usuario = _maybe_decrypt(nome_do_usuario)

    logo_url = url_for("static", filename="logo-symbol.png", _external=True)
    termos_url = url_for("terms", _external=True)
    privacidade_url = url_for("privacy_policy", _external=True)

    return f"""
    <div style='text-align: center; margin-bottom: 24px;'>
        <img src='{logo_url}' alt='ComentsIA' style='height: 60px; margin: 16px auto;'>
    </div>
    <p>Olá {nome_do_usuario},</p>
    <p>É um prazer ter você conosco no <strong>ComentsIA</strong>!</p>
    <p>Parabéns por dar o primeiro passo para revolucionar a gestão das avaliações da sua empresa. Nosso aplicativo foi criado para simplificar sua rotina e valorizar ainda mais a reputação do seu negócio no Google.</p>
    <p><strong>Benefícios exclusivos do ComentsIA:</strong></p>
    <ul>
        <li>Respostas automáticas ou personalizadas com IA em segundos.</li>
        <li>Análises e relatórios inteligentes sobre o que os clientes estão dizendo.</li>
        <li>Centralização de todas as avaliações em um só lugar.</li>
        <li>Facilidade para personalizar saudações, assinaturas e contato.</li>
        <li>Maior engajamento e satisfação dos seus clientes!</li>
    </ul>
    <p>
      Antes de continuar, confira nossos
      <a href='{termos_url}'>Termos de Uso</a> e
      <a href='{privacidade_url}'>Política de Privacidade</a>.
    </p>
    <p>Conte com a gente para potencializar o relacionamento com seus clientes e a reputação da sua empresa.</p>
    <p style='margin-top: 28px; font-weight: bold;'>Seja muito bem-vindo!<br>
    Equipe ComentsIA</p>
    """


def montar_email_conta_apagada(nome_do_usuario: str) -> str:
    """
    Monta HTML do e-mail de confirmação de exclusão de conta.
    Aceita nome criptografado (vai tentar decrypt) ou texto plano.
    """
    nome_do_usuario = _maybe_decrypt(nome_do_usuario)
    logo_url = url_for("static", filename="logo-symbol.png", _external=True)

    return f"""
    <div style='text-align: center; margin-bottom: 24px;'>
        <img src='{logo_url}' alt='ComentsIA' style='height: 60px; margin: 16px auto;'>
    </div>
    <p>Olá {nome_do_usuario},</p>
    <p>Confirmamos a exclusão da sua conta e de todos os dados associados à plataforma <strong>ComentsIA</strong>.</p>
    <p>Se quiser compartilhar o motivo ou alguma sugestão, basta responder a este e-mail. Seu feedback é muito importante para nós.</p>
    <p style='margin-top: 28px; font-weight: bold;'>Obrigado por confiar no ComentsIA.<br>
    Equipe ComentsIA</p>
    """


def enviar_email(destinatario: str, assunto: str, corpo_html: str) -> None:
    """
    Envia o e-mail via SMTP.
    Depende das variáveis de ambiente (EMAIL_SENHA).
    """
    remetente = "suporte@comentsia.com.br"
    senha = os.getenv("EMAIL_SENHA")
    smtp_host = "smtp.suite.uol"
    smtp_port = 587

    msg = MIMEMultipart("alternative")
    msg["From"] = remetente
    msg["To"] = destinatario
    msg["Subject"] = assunto
    msg.attach(MIMEText(corpo_html, "html"))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.set_debuglevel(0)  # use 1 se quiser ver o log SMTP
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(remetente, senha)
        server.sendmail(remetente, destinatario, msg.as_string())
