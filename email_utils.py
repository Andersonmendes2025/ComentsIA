# email_utils.py

from flask import url_for, current_app
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from flask import url_for
def montar_email_boas_vindas(nome_do_usuario):
    # Precisa de app context para url_for funcionar!
    logo_url = url_for('static', filename='logo-symbol.png', _external=True)
    termos_url = url_for('terms', _external=True)
    privacidade_url = url_for('privacy_policy', _external=True)
    return f"""
    <div style='text-align: center; margin-bottom: 24px;'>
        <img src='{logo_url}' alt='ComentsIA' style='height: 60px; margin: 16px auto;'>
    </div>
    <p>Olá {nome_do_usuario},</p>
    <p>É um prazer ter você conosco no <strong>ComentsIA</strong>!</p>
    <p>Parabéns por dar o primeiro passo para revolucionar a gestão das avaliações da sua empresa. Nosso aplicativo foi criado para simplificar sua rotina e valorizar ainda mais a reputação do seu negócio no Google.</p>
    <p>O ComentsIA utiliza Inteligência Artificial para automatizar, sugerir e agilizar as respostas às avaliações recebidas no seu perfil do Google Business. Assim, você responde clientes de forma profissional, cordial e personalizada — ganhando tempo e fortalecendo a imagem da sua marca.</p>
    <p><strong>Benefícios exclusivos do ComentsIA:</strong></p>
    <ul>
        <li>Respostas automáticas ou personalizadas com IA em segundos.</li>
        <li>Análises e relatórios inteligentes sobre o que os clientes estão dizendo.</li>
        <li>Centralização de todas as avaliações em um só lugar.</li>
        <li>Facilidade para personalizar saudações, assinaturas e contato.</li>
        <li>Maior engajamento e satisfação dos seus clientes!</li>
    </ul>
    <p>
    Antes de continuar, lembre-se de conferir nossos
    <a href='{termos_url}'>Termos de Uso</a> e
    <a href='{privacidade_url}'>Política de Privacidade</a>,
    que explicam de forma clara como protegemos seus dados e como funciona o uso do app:
    </p>
    <ul>
        <li><a href='{termos_url}'>Termos de Uso</a></li>
        <li><a href='{privacidade_url}'>Política de Privacidade</a></li>
    </ul>
    <p>Conte com a gente para potencializar ainda mais seu relacionamento com clientes e a reputação da sua empresa.</p>
    <p>Se tiver qualquer dúvida, basta responder este e-mail ou acessar o painel de ajuda do ComentsIA.</p>
    <p style='margin-top: 28px; font-weight: bold;'>Seja muito bem-vindo!<br>
    Equipe ComentsIA</p>
 """
#Envia o Email
def enviar_email(destinatario, assunto, corpo_html):
    remetente = "comentsia.2025@gmail.com"
    senha = os.getenv("EMAIL_SENHA")  # Use senha de app do Gmail
    msg = MIMEMultipart('alternative')
    msg['From'] = remetente
    msg['To'] = destinatario
    msg['Subject'] = assunto

    # Anexa o corpo em HTML
    msg.attach(MIMEText(corpo_html, 'html'))

    with smtplib.SMTP('smtp.gmail.com', 587) as server:
        server.starttls()
        server.login(remetente, senha)
        server.sendmail(remetente, destinatario, msg.as_string())

def montar_email_conta_apagada(nome_do_usuario):
    logo_url = url_for('static', filename='logo-symbol.png', _external=True)
    return f"""
    <div style='text-align: center; margin-bottom: 24px;'>
        <img src='{logo_url}' alt='ComentsIA' style='height: 60px; margin: 16px auto;'>
    </div>
    <p>Olá {nome_do_usuario},</p>
    <p>Confirmamos a exclusão da sua conta e de todos os dados associados à plataforma <strong>ComentsIA</strong>. Respeitamos sua decisão e garantimos que nenhuma informação pessoal ou empresarial permanece armazenada em nossos servidores.</p>
    <p>Gostaríamos de entender melhor o que motivou sua saída. Seu feedback é essencial para melhorarmos continuamente nossos serviços. Caso queira compartilhar o motivo ou alguma sugestão, basta responder a este e-mail.</p>
    <p>Se, em algum momento, decidir retornar, estaremos prontos para recebê-lo(a) de volta. Nosso compromisso é tornar a gestão de avaliações do seu negócio mais fácil e eficiente, com a qualidade e o cuidado que você merece.</p>
    <p>Em caso de dúvida ou se precisar de qualquer suporte, nossa equipe está à disposição.</p>
    <p style='margin-top: 28px; font-weight: bold;'>Obrigado por confiar no ComentsIA.<br>
    Equipe ComentsIA</p>
    """