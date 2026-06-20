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
    Monta HTML do e-mail de boas-vindas com design premium (Versão Segura em DIV).
    Aceita nome criptografado (vai tentar decrypt) ou texto plano.
    """
    nome_do_usuario = _maybe_decrypt(nome_do_usuario)
    logo_url = "https://comentsia.com.br/static/logo-symbol.png"

    # Retornamos o e-mail começando direto em uma DIV (como no seu código original que funcionava),
    # mas contendo o design moderno. Isso evita que o Gmail bloqueie a renderização.
    return f"""
    <div style="background-color: #f4f7fa; padding: 40px 20px; font-family: Arial, sans-serif;">
        <table border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.05);">
            <tr>
                <td align="center" style="background: linear-gradient(135deg, #0d6efd 0%, #4f46e5 100%); padding: 40px 20px;">
                    <img src="{logo_url}" alt="ComentsIA Logo" width="60" style="display: block; margin-bottom: 15px; filter: brightness(0) invert(1);">
                    <h1 style="color: #ffffff; margin: 0; font-size: 24px;">Bem-vindo(a) à ComentsIA! 🚀</h1>
                </td>
            </tr>
            <tr>
                <td style="padding: 30px; color: #334155; font-size: 16px; line-height: 1.6;">
                    <p style="margin-top: 0;">Olá, <strong>{nome_do_usuario}</strong>,</p>
                    <p>É oficial: sua conta está pronta e você acaba de dar um passo gigante para revolucionar a forma como sua empresa interage com os clientes.</p>

                    <h2 style="color: #1e293b; font-size: 18px; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px; margin-top: 30px;">O que a ComentsIA faz por você?</h2>
                    
                    <ul style="padding-left: 20px; margin-bottom: 25px;">
                        <li style="margin-bottom: 10px;"><strong>Respostas Inteligentes:</strong> Nossa IA avalia a nota e responde no idioma correto.</li>
                        <li style="margin-bottom: 10px;"><strong>Automação no Google:</strong> Sincronizamos com o Google Business Profile para responder enquanto você dorme.</li>
                        <li style="margin-bottom: 10px;"><strong>Gestão Multi-Lojas:</strong> Gerencie matriz e filiais num único painel.</li>
                        <li style="margin-bottom: 10px;"><strong>Análise de Sentimento:</strong> Extraia relatórios em PDF com métricas e um resumo claro.</li>
                    </ul>

                    <div style="background-color: #f8fafc; border-left: 4px solid #0d6efd; padding: 20px; border-radius: 4px; margin-top: 30px;">
                        <h3 style="margin: 0 0 10px 0; font-size: 16px;">Primeiros Passos</h3>
                        <p style="margin: 0 0 5px 0;">1. <strong>Sincronize o Google</strong> na aba "Locais Google".</p>
                        <p style="margin: 0 0 5px 0;">2. <strong>Configure o Cérebro</strong> no menu de configurações.</p>
                        <p style="margin: 0;">3. <strong>Ligue a Automação</strong> e pronto!</p>
                    </div>

                    <div style="text-align: center; margin-top: 40px;">
                        <a href="https://comentsia.com.br/dashboard" style="background-color: #0d6efd; color: #ffffff; text-decoration: none; padding: 14px 30px; border-radius: 50px; font-weight: bold; display: inline-block;">Acessar Meu Dashboard</a>
                    </div>
                </td>
            </tr>
            <tr>
                <td align="center" style="background-color: #f8fafc; padding: 20px; border-top: 1px solid #e2e8f0; color: #64748b; font-size: 13px;">
                    <p style="margin: 0 0 5px 0;">Se precisar de ajuda, responda a este e-mail.</p>
                    <p style="margin: 0;"><strong>Equipe ComentsIA</strong><br>Inteligência que entende o seu cliente.</p>
                </td>
            </tr>
        </table>
    </div>
    """


def montar_email_conta_apagada(nome_do_usuario: str) -> str:
    """
    Monta HTML do e-mail de confirmação de exclusão de conta.
    Aceita nome criptografado (vai tentar decrypt) ou texto plano.
    """
    nome_do_usuario = _maybe_decrypt(nome_do_usuario)
    logo_url = "https://comentsia.com.br/static/logo-symbol.png"

    return f"""
    <div style="background-color: #f4f7fa; padding: 40px 20px; font-family: Arial, sans-serif; text-align: center;">
        <img src="{logo_url}" alt="ComentsIA" style="height: 60px; margin-bottom: 20px;">
        <h2 style="color: #1e293b;">Conta Excluída</h2>
        <p style="color: #334155;">Olá {nome_do_usuario}, confirmamos a exclusão da sua conta e de todos os dados associados à plataforma.</p>
        <p style="color: #334155;">Se quiser compartilhar o motivo, basta responder a este e-mail. Seu feedback é muito importante.</p>
        <p style="margin-top: 30px; color: #64748b; font-weight: bold;">Obrigado por confiar no ComentsIA.<br>Equipe ComentsIA</p>
    </div>
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
    
    # Voltamos EXATAMENTE para o seu código original de anexo,
    # Apenas com o "utf-8" para garantir os Emojis.
    msg.attach(MIMEText(corpo_html, "html", "utf-8"))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.set_debuglevel(0)  # use 1 se quiser ver o log SMTP
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(remetente, senha)
        server.sendmail(remetente, destinatario, msg.as_string())