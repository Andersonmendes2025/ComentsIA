import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()

def enviar_email_teste():
    remetente = "suporte@comentsia.com.br"
    senha = os.getenv("EMAIL_SENHA")  # Certifique-se que a variável ambiente está definida
    destinatario = "andersonmendes575@gmail.com"  # Coloque seu email para teste
    smtp_host = "smtp.suite.uol"  # Use o hostname que seu DNS resolve
    smtp_port = 587

    corpo_html = "<p>Teste de envio de email pelo SMTP UOL Host</p>"

    msg = MIMEMultipart('alternative')
    msg['From'] = remetente
    msg['To'] = destinatario
    msg['Subject'] = "Teste SMTP ComentsIA"
    msg.attach(MIMEText(corpo_html, 'html'))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.set_debuglevel(1)  # Ativa debug detalhado no console
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(remetente, senha)
            server.sendmail(remetente, destinatario, msg.as_string())
        print("E-mail enviado com sucesso!")
    except Exception as e:
        print("Erro ao enviar e-mail:", e)

if __name__ == "__main__":
    enviar_email_teste()
