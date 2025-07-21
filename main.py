import os
import json
import flask
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from datetime import datetime
import google.oauth2.credentials
import google_auth_oauthlib.flow
import googleapiclient.discovery
from openai import OpenAI
from models import db, Review, UserSettings
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from flask import session
import logging
import pytz
from datetime import datetime
from relatorio import RelatorioAvaliacoes
import io
import pandas as pd
from flask import send_file
current_date = datetime.now().strftime('%d/%m/%Y')
from sqlalchemy import func
import numpy as np
from datetime import timedelta
from relatorio import RelatorioAvaliacoes
from collections import Counter
import numpy as np
logging.basicConfig(level=logging.DEBUG)
from collections import Counter
from flask_migrate import upgrade
from models import db, Review, UserSettings, RelatorioHistorico
from flask_migrate import Migrate
load_dotenv()
from flask import session, redirect, url_for, flash
import base64
from markupsafe import Markup
from functools import wraps
from email_utils import montar_email_boas_vindas, enviar_email
# Configuração do aplicativo Flask
# Inicializar o Flask
app = Flask(__name__)

app.config.update(
    SESSION_COOKIE_SECURE=True,      # necessário se seu site usar HTTPS
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax'    # 'Lax' geralmente funciona bem para OAuth
)

# Caminho do diretório base
basedir = os.path.abspath(os.path.dirname(__file__))
# Configuração do banco de dados (Render ou local)
db_url = os.getenv("DATABASE_URL", "")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Chave secreta vinda do .env
app.secret_key = os.getenv("FLASK_SECRET_KEY")
db.init_app(app)
migrate = Migrate(app, db)

from auto_reply_setup import auto_reply_bp
app.register_blueprint(auto_reply_bp)

# Configuração da API OpenAI
client = OpenAI(
  api_key=os.getenv("OPENAI_API_KEY")
)


# Configuração do OAuth do Google
CLIENT_SECRETS_FILE = '/etc/secrets/client_secrets.json'
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/business.manage"
]
API_SERVICE_NAME = 'mybusiness'
API_VERSION = 'v4'

from collections import Counter
import numpy as np

# Função para identificar palavras-chave nas avaliações

def analisar_pontos_mais_mencionados(comentarios):
    if not comentarios:
        return []

    palavras = " ".join(comentarios).split()  # Junta os comentários em uma única string e separa por espaços
    contagem = Counter(palavras)  # Conta a frequência de cada palavra

    # Remover palavras comuns e irrelevantes (como artigos e preposições)
    palavras_comuns = {"a", "o", "de", "e", "que", "para", "em", "com", "na", "no"}
    contagem = {k: v for k, v in contagem.items() if k.lower() not in palavras_comuns}
    
    # Retorna as 5 palavras mais comuns
    return Counter(contagem).most_common(5)  # Certifique-se de que contagem é um Counter antes de usar most_common


# Função para calcular a média das avaliações
def calcular_media(avaliacoes):
    return round(sum(avaliacoes) / len(avaliacoes), 2) if avaliacoes else 0.0

# Função para confirmar aceitaçao dos termos
def require_terms_accepted(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_info = session.get('user_info')
        if not user_info:
            return redirect(url_for('authorize'))
        user_id = user_info.get('id')
        settings = get_user_settings(user_id)
        # Se faltar algum campo obrigatório, manda para settings
        if not (settings.get('business_name') and settings.get('contact_info') and settings.get('terms_accepted', False)):
            flash("Complete seu cadastro inicial e aceite os Termos e Condições para acessar esta funcionalidade.", "warning")
            return redirect(url_for('settings'))
        return f(*args, **kwargs)
    return decorated_function



# Função para calcular a projeção de nota para os próximos 30 dias
def calcular_projecao(notas, datas):
    if datas and len(datas) > 1:
        primeira_data = min(datas)
        x = np.array([(d - primeira_data).days for d in datas]).reshape(-1, 1)
        y = np.array(notas)
        coef = np.polyfit(x.flatten(), y, 1)
        ultimo_dia = max(x)[0]
        projecao_dia = ultimo_dia + 30
        projecao_30_dias = coef[0] * projecao_dia + coef[1]
        return max(0, min(5, projecao_30_dias))  # Limitando a projeção entre 0 e 5
    return calcular_media(notas)  # fallback se não houver dados suficientes para projeção
 
# Funções auxiliares para trabalhar com o banco de dados
def get_user_reviews(user_id):
    """Obtém todas as avaliações de um usuário do banco de dados, ordenadas da mais recente para a mais antiga."""
    return Review.query.filter_by(user_id=user_id).order_by(Review.date.desc()).all()

def get_user_settings(user_id):
    """Obtém as configurações de um usuário do banco de dados."""
    settings = UserSettings.query.filter_by(user_id=user_id).first()
    if settings:
        return {
            'business_name': settings.business_name or '',
            'default_greeting': settings.default_greeting or 'Olá,',
            'default_closing': settings.default_closing or 'Agradecemos seu feedback!',
            'contact_info': settings.contact_info or 'Entre em contato pelo telefone (00) 0000-0000 ou email@exemplo.com',
            'terms_accepted': settings.terms_accepted if settings else False,
            'logo': settings.logo if settings else None,
            'manager_name': settings.manager_name or ''if settings else None,
        }
    else:
        # Retorna configurações padrão se não existirem
        return {
            'business_name': '',
            'default_greeting': 'Olá,',
            'default_closing': 'Agradecemos seu feedback!',
            'contact_info': 'Entre em contato pelo telefone (00) 0000-0000 ou email@exemplo.com',
            'terms_accepted': False,
            'logo': None,
            'manager_name': ''
        }

def save_user_settings(user_id, settings_data):
    # Converter checkbox/string em booleano de verdade:
    terms_accepted_raw = settings_data.get('terms_accepted')
    terms_accepted = terms_accepted_raw in [True, 'on', 'true', 'True', 1, '1']

    existing = UserSettings.query.filter_by(user_id=user_id).first()
    if existing:
        existing.business_name = settings_data.get('business_name', '')
        existing.default_greeting = settings_data.get('default_greeting', 'Olá,')
        existing.default_closing = settings_data.get('default_closing', 'Agradecemos seu feedback!')
        existing.contact_info = settings_data.get('contact_info', 'Entre em contato...')
        existing.terms_accepted = terms_accepted
        existing.manager_name = settings_data.get('manager_name', '')
        # Só atualiza logo se veio nova
        if settings_data.get('logo'):
            existing.logo = settings_data['logo']
    else:
        new_settings = UserSettings(
            user_id=user_id,
            business_name=settings_data.get('business_name', ''),
            default_greeting=settings_data.get('default_greeting', 'Olá,'),
            default_closing=settings_data.get('default_closing', 'Agradecemos seu feedback!'),
            contact_info=settings_data.get('contact_info', ''),
            terms_accepted=terms_accepted,
            logo=settings_data.get('logo'),
            manager_name=settings_data.get('manager_name', '')
        )
        db.session.add(new_settings)
    db.session.commit()
from flask import url_for

def montar_email_boas_vindas(nome_do_usuario):
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



@app.context_processor
def inject_user():
    logged_in = 'credentials' in session
    user = session.get('user_info') if logged_in else None
    print(f"[inject_user] logged_in={logged_in} user={user}")
    return dict(logged_in=logged_in, user=user)

@app.route('/')
def index():
    """Página inicial do aplicativo com resumo das avaliações."""
    if 'credentials' not in flask.session:
        return render_template('index.html', logged_in=False, now=datetime.now())

    user_info = flask.session.get('user_info', {})
    user_id = user_info.get('id')

    # Buscar configurações do usuário
    user_settings = get_user_settings(user_id)
    
    # Verificar se o usuário preencheu as informações obrigatórias e aceitou os Termos
    if not user_settings['business_name'] or not user_settings['contact_info'] or not session.get('first_login_done'):
        return redirect(url_for('settings'))  # Redireciona para a página de configurações

    user_reviews = get_user_reviews(user_id)
    total_reviews = len(user_reviews)
    responded_reviews = sum(1 for review in user_reviews if review.replied)
    pending_reviews = total_reviews - responded_reviews
    avg_rating = round(sum(review.rating for review in user_reviews) / total_reviews, 1) if total_reviews else 0.0

    return render_template(
        'index.html',
        logged_in=True,
        user=user_info,
        now=datetime.now(),
        reviews=user_reviews
    )
@app.route('/debug_historico')
def debug_historico():
    # Só permita acesso para o seu usuário
    user_info = session.get('user_info')
    if not user_info or user_info.get('email') != 'comentsia.2025@gmail.com':
        return "Acesso negado", 403

    historicos = RelatorioHistorico.query.all()
    html = "<h2>Relatórios no banco:</h2><ul>"
    for h in historicos:
        html += f"<li>ID: {h.id} | User: {h.user_id} | Nome: {h.nome_arquivo} | Data: {h.data_criacao}</li>"
    html += "</ul>"
    return html 
@app.route('/privacy-policy')
def privacy_policy():
    return render_template('privacy-policy.html')
@app.route("/quem-somos")
def quem_somos():
    return render_template("quem-somos.html")

@app.route('/relatorio', methods=['GET', 'POST'])
@require_terms_accepted
def gerar_relatorio():
    if 'credentials' not in flask.session:
        flash("Você precisa estar logado para gerar o relatório.", "warning")
        return redirect(url_for('authorize'))

    user_info = flask.session.get('user_info', {})
    user_id = user_info.get('id')
    print(f"[RELATÓRIO] user_id: {user_id}")

    user_settings = get_user_settings(user_id)
    print(f"[RELATÓRIO] user_settings: {user_settings}")

    if not user_settings['business_name'] or not user_settings['contact_info'] or not session.get('first_login_done'):
        return redirect(url_for('settings'))

    if request.method == 'GET':
        return render_template('relatorio.html')

    periodo = request.form.get('periodo', '90dias')
    nota = request.form.get('nota', 'todas')
    respondida = request.form.get('respondida', 'todas')
    print(f"[RELATÓRIO] Filtros: periodo={periodo}, nota={nota}, respondida={respondida}")

    avaliacoes_query = Review.query.filter_by(user_id=user_id).all()
    print(f"[RELATÓRIO] Avaliações encontradas: {len(avaliacoes_query)}")

    avaliacoes = []
    agora = datetime.now()
    for av in avaliacoes_query:
        try:
            data_av = datetime.strptime(av.date, '%d/%m/%Y')
        except Exception:
            data_av = av.date
            if isinstance(data_av, str):
                data_av = datetime.strptime(data_av, '%Y-%m-%d')

        if nota != 'todas' and str(av.rating) != nota:
            continue
        if respondida == 'sim' and not av.replied:
            continue
        if respondida == 'nao' and av.replied:
            continue
        if periodo == '90dias' and (agora - data_av).days > 90:
            continue
        if periodo == '6meses' and (agora - data_av).days > 180:
            continue
        if periodo == '1ano' and (agora - data_av).days > 365:
            continue
        avaliacoes.append({
            'data': av.date,
            'nota': av.rating,
            'texto': av.text or "",
            'respondida': 1 if av.replied else 0,
            'tags': getattr(av, 'tags', "") or ""
        })

    print(f"[RELATÓRIO] Avaliações após filtro: {len(avaliacoes)}")

    notas = [av['nota'] for av in avaliacoes]
    media_atual = calcular_media(notas)
    rel = RelatorioAvaliacoes(avaliacoes, media_atual=media_atual, settings=user_settings)

    try:
        nome_arquivo = f"relatorio_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
        buffer = io.BytesIO()
        rel.gerar_pdf(buffer)
        buffer.seek(0)
        pdf_bytes = buffer.getvalue()

        br_tz = pytz.timezone('America/Sao_Paulo')
        data_criacao = datetime.now(br_tz)

        historico = RelatorioHistorico(
            user_id=user_id,
            filtro_periodo=periodo,
            filtro_nota=nota,
            filtro_respondida=respondida,
            nome_arquivo=nome_arquivo,
            arquivo_pdf=pdf_bytes,  # <- aqui salva o PDF binário no Postgres!
            data_criacao=data_criacao
        )
        db.session.add(historico)
        db.session.commit()
        print(f"[RELATÓRIO] Histórico salvo com ID: {historico.id}")
        print(">>> PDF sendo enviado para download:", nome_arquivo)
        buffer.seek(0)
        return send_file(
            io.BytesIO(pdf_bytes), 
            as_attachment=True, 
            download_name=nome_arquivo, 
            mimetype='application/pdf'
        )

    except Exception as e:
        print("!!! ERRO AO GERAR/ENVIAR PDF:", str(e))
        flash(f"Erro ao gerar o relatório: {str(e)}", "danger")
        return redirect(url_for('index'))
@app.route('/delete_account', methods=['POST'])
@require_terms_accepted
def delete_account():
    if 'credentials' not in session:
        print("⚠️ Sessão não encontrada. Usuário não está logado.")
        return jsonify({'success': False, 'error': 'Você precisa estar logado.'})

    user_info = session.get('user_info')
    user_id = user_info.get('id')
    nome_do_usuario = user_info.get('name') or user_info.get('email') or 'Usuário'
    email_destino = user_info.get('email')

    print(f"🗑️ Excluindo conta: {nome_do_usuario} <{email_destino}> (ID: {user_id})")

    # Tenta enviar o e-mail ANTES de apagar a sessão
    try:
        if email_destino:
            html = montar_email_conta_apagada(nome_do_usuario)
            print("✉️ Chamando enviar_email...")
            enviar_email(
                destinatario=email_destino,
                assunto='Sua conta no ComentsIA foi excluída',
                corpo_html=html
            )
            print("✅ E-mail de exclusão enviado!")
        else:
            print("❌ Nenhum e-mail de destino encontrado para enviar a mensagem de exclusão.")
    except Exception as e:
        print(f"❌ Erro ao enviar e-mail de exclusão: {e}")

    # Apaga todos os dados do usuário nas tabelas principais
    Review.query.filter_by(user_id=user_id).delete()
    UserSettings.query.filter_by(user_id=user_id).delete()
    RelatorioHistorico.query.filter_by(user_id=user_id).delete()
    db.session.commit()

    # Limpa a sessão e faz logout
    session.clear()
    print("🚮 Sessão e dados do usuário apagados com sucesso!")
    return jsonify({'success': True})


@app.route('/historico_relatorios')
@require_terms_accepted
def historico_relatorios():
    if 'credentials' not in flask.session:
        return redirect(url_for('authorize'))

    user_info = flask.session.get('user_info', {})
    user_id = user_info.get('id')
    print(f"[HISTÓRICO] user_id: {user_id}")

    brt = pytz.timezone('America/Sao_Paulo')
    historicos = RelatorioHistorico.query.filter_by(user_id=user_id).order_by(RelatorioHistorico.id.desc()).all()
    print(f"[HISTÓRICO] Registros encontrados: {len(historicos)}")

    # Adiciona atributos temporários para exibição no template
    for rel in historicos:
        rel.data_criacao_local = rel.data_criacao.astimezone(brt).strftime('%d/%m/%Y')  # só data, sem hora
        rel.numero = rel.id  # para mostrar o número/id do relatório
        print(f"[DEBUG] Relatório {rel.numero} criado em {rel.data_criacao.astimezone(brt)}")  # data completa no log

    return render_template('historico_relatorios.html', historicos=historicos)


@app.route('/download_relatorio/<int:relatorio_id>')
def download_relatorio(relatorio_id):
    relatorio = RelatorioHistorico.query.get_or_404(relatorio_id)
    user_info = session.get('user_info')
    if not user_info or relatorio.user_id != user_info.get('id'):
        flash('Acesso negado.', 'danger')
        return redirect(url_for('historico_relatorios'))

    if relatorio.arquivo_pdf:
        filename = getattr(relatorio, 'nome_arquivo', f'relatorio_{relatorio.id}.pdf')
        return send_file(
            io.BytesIO(relatorio.arquivo_pdf),
            as_attachment=True,
            download_name=filename,
            mimetype='application/pdf'
        )
    else:
        flash('Arquivo não encontrado.', 'danger')
        return redirect(url_for('historico_relatorios'))


@app.route('/deletar_relatorio/<int:relatorio_id>', methods=['POST'])
def deletar_relatorio(relatorio_id):
    relatorio = RelatorioHistorico.query.get_or_404(relatorio_id)
    user_info = session.get('user_info')
    if not user_info or relatorio.user_id != user_info.get('id'):
        flash('Acesso negado.', 'danger')
        return redirect(url_for('historico_relatorios'))

    # Como o arquivo está salvo no banco, não há arquivo físico para apagar.

    # Remove do banco
    db.session.delete(relatorio)
    db.session.commit()

    flash('Relatório excluído com sucesso.', 'success')
    return redirect(url_for('historico_relatorios'))


@app.route('/sitemap.xml')
def sitemap():
    return app.send_static_file('sitemap.xml')

@app.route('/terms', methods=['GET', 'POST'])
def terms():
    if request.method == 'POST':
        user_info = flask.session.get('user_info', {})
        user_id = user_info.get('id')
        terms_accepted = request.form.get('terms_accepted')
        if not terms_accepted:
            flash("Você precisa aceitar os Termos e Condições para continuar.", "warning")
            return redirect(url_for('terms'))
        # Salva no banco
        settings_data = get_user_settings(user_id)
        settings_data['terms_accepted'] = True
        save_user_settings(user_id, settings_data)
        # Atualiza a sessão
        session['terms_accepted'] = True
        return redirect(url_for('settings'))
    ...

    # Dados do usuário
    user_info = flask.session.get('user_info', {})
    user_name = user_info.get('name', 'Usuário')
    user_email = user_info.get('email', 'Email não informado')

    # Dados da empresa (seriam passados do banco de dados ou informações da sessão)
    company_name = user_info.get('business_name', 'Nome da Empresa Não Informado')
    company_email = user_info.get('business_email', 'E-mail Não Informado')

    current_date = datetime.now().strftime('%d/%m/%Y')  # Data de última atualização

    return render_template('terms.html', 
                           user_name=user_name, 
                           user_email=user_email,
                           company_name=company_name,
                           company_email=company_email,
                           current_date=current_date)

@app.route('/authorize')
def authorize():
    redirect_uri = url_for('oauth2callback', _external=True)
    flow = build_flow(redirect_uri=redirect_uri)  # não passe state aqui!

    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true'
    )

    session['state'] = state  # guarde o state aqui, após pegar o authorization_url
    return redirect(authorization_url)


@app.route('/delete_review', methods=['POST'])
def delete_review():
    """Exclui uma avaliação do banco de dados."""
    if 'credentials' not in flask.session:
        return jsonify({'success': False, 'error': 'Usuário não autenticado'})

    user_info = flask.session.get('user_info', {})
    user_id = user_info.get('id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Usuário não identificado'})

    data = request.get_json() or {}
    review_id = data.get('review_id')
    if not review_id:
        return jsonify({'success': False, 'error': 'ID da avaliação não fornecido'})

    # Busca e exclui a avaliação do usuário atual
    review = Review.query.filter_by(id=int(review_id), user_id=user_id).first()
    if not review:
        return jsonify({'success': False, 'error': 'Avaliação não encontrada'})

    db.session.delete(review)
    db.session.commit()

    return jsonify({'success': True})


   # Deleta respostas  
@app.route('/delete_reply', methods=['POST'])
def delete_reply():
    if 'credentials' not in flask.session:
        return jsonify({'success': False, 'error': 'Usuário não autenticado'})
    
    user_info = flask.session.get('user_info', {})
    user_id = user_info.get('id')

    data = request.get_json() or {}
    review_id = data.get('review_id')

    review = Review.query.filter_by(id=int(review_id), user_id=user_id).first()
    if not review:
        return jsonify({'success': False, 'error': 'Avaliação não encontrada'})

    review.reply = ''
    review.replied = False
    db.session.commit()

    return jsonify({'success': True})

@app.route('/suggest_reply', methods=['POST'])
def suggest_reply():
    """Gera uma sugestão de resposta personalizada usando nome, nota e configurações."""
    if 'credentials' not in flask.session:
        return jsonify({'success': False, 'error': 'Usuário não autenticado'})

    user_info = flask.session.get('user_info', {})
    user_id = user_info.get('id')

    data = request.json
    review_text = data.get('review_text', '')
    reviewer_name = data.get('reviewer_name', 'Cliente')
    star_rating = data.get('star_rating', 5)
    tone = data.get('tone', 'profissional')

    if not review_text:
        return jsonify({'success': False, 'error': 'Texto da avaliação não fornecido'})

    # Buscar configurações personalizadas do usuário do banco de dados
    settings = get_user_settings(user_id)
    # Instruções para o tom da resposta
    tone_instructions = {
        'profissional': 'Use linguagem formal e respeitosa.',
        'amigavel': 'Use uma linguagem calorosa,sutilmente informal e amigável.',
        'empatico': 'Demonstre empatia e compreensão genuína.',
        'entusiasmado': 'Use uma linguagem animada e positiva.',
        'formal': 'Use uma linguagem formal e estruturada.'
    }

    tone_instruction = tone_instructions.get(tone, tone_instructions['profissional'])
    manager = settings.get('manager_name', '').strip()
    business = settings.get('business_name', '').strip()
    if manager:
        assinatura = f"{business}\n{manager}"
    else:
        assinatura = business
    # Prompt para a IA
    prompt = f"""
    Você é um assistente especializado em atendimento ao cliente e deve escrever uma resposta personalizada para uma avaliação recebida por "{business}".

    Avaliação recebida:
    - Nome do cliente: {reviewer_name}
    - Nota: {star_rating} estrelas
    - Texto: "{review_text}"

    Instruções:
    - Comece com: "{settings['default_greeting']} {reviewer_name},"
    - Siga este tom: {tone_instruction}
    - Comente os pontos mencionados, usando palavras diferentes
    - Se a nota for de 1 a 3, demonstre empatia, peça desculpas e ofereça uma solução
    - Se a nota for de 4 ou 5, agradeça e convide para retornar
    - Finalize com: "{settings['default_closing']}"
    - Inclua as informações de contato: "{settings['contact_info']}"
    - Assine ao final exatamente assim, cada item em uma linha:
    {assinatura} Não use cargos, não use "Atenciosamente", apenas os nomes.
    - Nao precisa citar todos os pontos que o cliente disse e se citar use palavras diferentes
    - A resposta deve ter entre 3 e 5 frases, ser personalizada e evitar frases genéricas
    """

    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Você é um assistente cordial, objetivo e empático para atendimento ao cliente."},
                {"role": "user", "content": prompt}
            ]
        )
        suggested_reply = completion.choices[0].message.content.strip()
        return jsonify({'success': True, 'suggested_reply': suggested_reply})
    except Exception as e:
        return jsonify({'success': False, 'error': f'Erro na API OpenAI: {str(e)}'})
from googleapiclient.discovery import build

def credentials_to_dict(credentials):
    """Converte o objeto de credenciais para um dicionário serializável."""
    return {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }

@app.template_filter('b64encode')
def b64encode_filter(data):
    if data:
        return Markup(base64.b64encode(data).decode('utf-8'))
    return ''
@app.route('/oauth2callback')
def oauth2callback():
    # Tenta recuperar o estado da sessão com segurança
    state = session.get('state')
    if not state:
        flash('Sessão inválida. Por favor, inicie o login novamente.', 'danger')
        return redirect(url_for('authorize'))

    redirect_uri = url_for('oauth2callback', _external=True)
    flow = build_flow(state=state, redirect_uri=redirect_uri)

    try:
        authorization_response = request.url
        flow.fetch_token(authorization_response=authorization_response)
    except Exception as e:
        flash(f'Erro ao obter token: {e}', 'danger')
        return redirect(url_for('authorize'))

    credentials = flow.credentials
    session['credentials'] = credentials_to_dict(credentials)

    try:
        user_info = get_user_info(credentials)
    except Exception as e:
        flash(f'Erro ao obter informações do usuário: {e}', 'danger')
        return redirect(url_for('logout'))

    if not user_info.get('id'):
        flash('Erro: não foi possível identificar o usuário. Verifique as permissões concedidas.', 'danger')
        return redirect(url_for('logout'))

    session['user_info'] = user_info
    print("ID do usuário autenticado:", user_info['id'])

    # Verifica se o usuário tem configurações; cria padrão se não
    user_id = user_info.get('id')
    if user_id:
        existing_settings = UserSettings.query.filter_by(user_id=user_id).first()
        if not existing_settings:
            default_settings = {
                'business_name': '',
                'default_greeting': 'Olá,',
                'default_closing': 'Agradecemos seu feedback!',
                'contact_info': 'Entre em contato pelo telefone (00) 0000-0000 ou email@exemplo.com'
            }
            save_user_settings(user_id, default_settings)

    return redirect(url_for('reviews'))


def build_flow(state=None, redirect_uri=None):
    client_config = {
        "web": {
            "client_id": os.getenv("GOOGLE_CLIENT_ID"),
            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "redirect_uris": [redirect_uri or "https://comentsia.com.br/oauth2callback"]
        }
    }

    return google_auth_oauthlib.flow.Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        state=state,
        redirect_uri=redirect_uri or "https://comentsia.com.br/oauth2callback"
    )


def credentials_to_dict(credentials):
    """Converte o objeto de credenciais em um dicionário serializável para a sessão."""
    return {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }


def get_user_info(credentials):
    """
    Obtém informações do usuário logado via Google People API.
    Usa o e-mail como ID e retorna nome e foto.
    Lança exceção se falhar.
    """
    try:
        people_service = build('people', 'v1', credentials=credentials)
        profile = people_service.people().get(
            resourceName='people/me',
            personFields='names,emailAddresses,photos'
        ).execute()

        email_addresses = profile.get('emailAddresses')
        if not email_addresses or not email_addresses[0].get('value'):
            raise ValueError("Não foi possível obter o e-mail do usuário.")

        user_email = email_addresses[0]['value']
        user_info = {
            'id': user_email,
            'email': user_email,
            'name': profile.get('names', [{}])[0].get('displayName', ''),
            'photo': profile.get('photos', [{}])[0].get('url', '')
        }
        return user_info

    except Exception as e:
        raise RuntimeError(f"Erro ao obter informações do usuário: {e}")

@app.route('/logout')
def logout():
    """Encerra a sessão do usuário."""
    # Remove as credenciais da sessão
    flask.session.pop('credentials', None)
    flask.session.pop('user_info', None)
    
    return flask.redirect(url_for('index'))

@app.route('/reviews')
@require_terms_accepted
def reviews():
    """Página de visualização e gerenciamento de avaliações."""
    if 'credentials' not in session:
        return redirect(url_for('authorize'))

    user_info = session.get('user_info', {})
    user_id = user_info.get('id')

    # Log de debug
    print(f"DEBUG: User ID atual na sessão: {user_id}")

    # Obtém todas as avaliações do banco e mostra os user_ids existentes
    all_reviews = Review.query.all()
    print(f"DEBUG: User IDs existentes no banco: {[review.user_id for review in all_reviews]}")

    # Obtém as avaliações do usuário atual
    user_reviews = get_user_reviews(user_id)

    # Log de debug
    print(f"DEBUG: Encontradas {len(user_reviews)} avaliações para este usuário")

    return render_template('reviews.html', reviews=user_reviews, user=user_info, now=datetime.now())

@app.route('/add_review', methods=['GET', 'POST'])
@require_terms_accepted
def add_review():
    """Adiciona avaliação manualmente ou via robô, com verificação de duplicatas e resposta automática."""
    if 'credentials' not in session:
        return redirect(url_for('authorize'))
    
    user_info = session.get('user_info', {})
    user_id = user_info.get('id')

    if request.method == 'POST':
        if not user_id:
            flash('Erro ao identificar usuário. Por favor, faça login novamente.', 'danger')
            return redirect(url_for('logout'))

        # Aceita dados de formulário (manual) ou envio automático (via bot)
        reviewer_name = request.form.get('reviewer_name') or request.json.get('reviewer_name', 'Cliente Anônimo')
        rating = int(request.form.get('rating') or request.json.get('rating', 5))
        text = request.form.get('text') or request.json.get('text', '')
        data = datetime.now().strftime('%d/%m/%Y')

        # Verifica duplicata
        existente = Review.query.filter_by(user_id=user_id, reviewer_name=reviewer_name, text=text).first()
        if existente:
            msg = 'Avaliação já existente. Ignorada.'
            print("⚠️", msg)
            if request.is_json:
                return jsonify({'success': True, 'message': msg})
            else:
                flash(msg, 'info')
                return redirect(url_for('reviews'))

        # Gera resposta com IA
        settings = get_user_settings(user_id)
        tone_instruction = "Use linguagem formal e respeitosa."
        manager = settings.get('manager_name', '').strip()
        business = settings.get('business_name', '').strip()
        if manager:
            assinatura = f"{business}\n{manager}"
        else:
            assinatura = business
        prompt = f"""
Você é um assistente especializado em atendimento ao cliente e deve escrever uma resposta personalizada para uma avaliação recebida por "{settings['business_name']}".

Avaliação recebida:
- Nome do cliente: {reviewer_name}
- Nota: {rating} estrelas
- Texto: "{text}"

Instruções:
- Comece com: "{settings['default_greeting']} {reviewer_name},"
- Use palavras mais umanas possiveis, seja natural na escrita e no vocabulario 
- Comente os pontos mencionados, usando palavras diferentes
- Se a nota for de 1 a 3, demonstre empatia, peça desculpas e ofereça uma solução
- Se a nota for de 4 ou 5, agradeça e convide para retornar
- Finalize com: "{settings['default_closing']}"
- Inclua as informações de contato: "{settings['contact_info']}"
- Assine ao final exatamente assim, cada item em uma linha:
    {assinatura} Não use cargos, não use "Atenciosamente", apenas os nomes.
- Não precisa citar todos os pontos que o cliente disse e se citar use palavras diferentes
- A resposta deve ter entre 3 e 5 frases, ser personalizada e evitar frases genéricas
"""

        try:
            from openai import OpenAI
            client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            completion = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Você é um assistente cordial, objetivo e empático para atendimento ao cliente."},
                    {"role": "user", "content": prompt}
                ]
            )
            resposta_gerada = completion.choices[0].message.content.strip()
        except Exception as e:
            print("❌ Erro ao gerar resposta automática:", e)
            resposta_gerada = ''

        # Salva avaliação com resposta
        new_review = Review(
            user_id=user_id,
            reviewer_name=reviewer_name,
            rating=rating,
            text=text,
            date=data,
            reply=resposta_gerada,
            replied=bool(resposta_gerada)
        )

        db.session.add(new_review)
        db.session.commit()

        print("✅ Avaliação salva com resposta automática.")

        if request.is_json:
            return jsonify({'success': True})
        else:
            flash('Avaliação adicionada com sucesso!', 'success')
            return redirect(url_for('reviews'))

    return render_template('add_review.html', user=user_info, now=datetime.now())


@app.route('/save_reply', methods=['POST'])
def save_reply():
    """Salva a resposta para uma avaliação no banco de dados."""
    if 'credentials' not in flask.session:
        return jsonify({'success': False, 'error': 'Usuário não autenticado'})
    
    user_info = flask.session.get('user_info', {})
    user_id = user_info.get('id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Usuário não identificado'})

    data = request.get_json() or {}
    review_id = data.get('review_id')
    reply_text = data.get('reply_text')
    if not review_id or not reply_text:
        return jsonify({'success': False, 'error': 'Parâmetros inválidos'})

    # Busca a avaliação diretamente no banco de dados
    review = Review.query.filter_by(id=int(review_id), user_id=user_id).first()
    if not review:
        return jsonify({'success': False, 'error': 'Avaliação não encontrada'})

    # Atualiza os campos da avaliação
    review.reply = reply_text
    review.replied = True
    db.session.commit()

    return jsonify({'success': True})

@app.route('/dashboard')
@require_terms_accepted
def dashboard():
    """Página de dashboard com análise de avaliações."""
    if 'credentials' not in flask.session:
        return flask.redirect(url_for('authorize'))
    
    user_info = flask.session.get('user_info', {})
    user_id = user_info.get('id')
    
    if not user_id:
        flash('Erro ao identificar usuário. Por favor, faça login novamente.', 'danger')
        return redirect(url_for('logout'))
    
    # Obtém as avaliações do usuário do banco de dados
    user_reviews = get_user_reviews(user_id)
    
    if not user_reviews:
        flash('Adicione algumas avaliações para visualizar o dashboard.', 'info')
        return redirect(url_for('add_review'))
    
    # Análise básica das avaliações
    total_reviews = len(user_reviews)
    avg_rating = sum(review.rating for review in user_reviews) / total_reviews if total_reviews > 0 else 0
    rating_distribution = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    
    for review in user_reviews:
        rating = review.rating
        if rating in rating_distribution:
            rating_distribution[rating] += 1

    # Novo cálculo do percentual de respondidas
    responded_reviews = sum(1 for review in user_reviews if review.replied)
    percent_responded = (responded_reviews / total_reviews) * 100 if total_reviews else 0

    # Aqui está o que faltava: preparar a lista de valores para o gráfico
    rating_distribution_values = [
        rating_distribution[1],
        rating_distribution[2],
        rating_distribution[3],
        rating_distribution[4],
        rating_distribution[5],
    ]
    
    return render_template(
        'dashboard.html',
        total_reviews=total_reviews,
        avg_rating=avg_rating,
        rating_distribution=rating_distribution,
        rating_distribution_values=rating_distribution_values,  # <- envia para o template
        percent_responded=percent_responded,
        reviews=user_reviews,
        user=user_info,
        now=datetime.now()
    )


@app.route('/analyze_reviews', methods=['POST'])
def analyze_reviews():
    if 'credentials' not in flask.session:
        return jsonify({'success': False, 'error': 'Usuário não autenticado'})

    user_info = flask.session.get('user_info', {})
    user_id = user_info.get('id')

    # Obtém as avaliações do usuário do banco de dados
    user_reviews = get_user_reviews(user_id)
    if not user_reviews:
        return jsonify({'success': False, 'error': 'Nenhuma avaliação para analisar.'})

    # Construir resumo textual das avaliações
    resumo = "\n".join([
        f"{review.reviewer_name} ({review.rating} estrelas): {review.text}"
        for review in user_reviews
    ])

    prompt = f"""
Você é um analista de satisfação do cliente. Analise as avaliações abaixo e gere um resumo útil para gestores.

Tarefas:
 Primeiro paragrafo liste os principais elogios em PONTOS POSITIVOS .
 Segundo paragrafo recorrentes ou oportunidades de melhoria em PONTOS NEGATIVOS .
 Escreva um parágrafo claro em ANALISE GERAL, com tom profissional, respeitoso e construtivo.
 Escreva cada topico em uma linha.
Avaliações:
{resumo}

Responda apenas os seguintes campos:
 Nao cite todos os comentarios, apenas os mais importantes e com palavras diferentes ou mais profissionais do que foram usadas no comentario. 
 Sem caracteres especiais, um texto de facil compreenção mas completo.
 Escolhe os tres pontos principais e diga o primeiro segundo e terceiro em grau de importancia na interveçao
"""

    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Você é um analista de avaliações de clientes."},
                {"role": "user", "content": prompt}
            ]
        )
        response_text = completion.choices[0].message.content.strip()

        # Tentar interpretar como JSON estruturado
        try:
            analysis = json.loads(response_text)
            return jsonify({'success': True, 'analysis': analysis})
        except json.JSONDecodeError:
            # Se não for JSON, retorna como texto simples
            return jsonify({'success': True, 'raw_analysis': response_text})
    except Exception as e:
        return jsonify({'success': False, 'error': f'Erro na análise com IA: {str(e)}'})

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    """Configurações do aplicativo."""
    if 'credentials' not in flask.session:
        return flask.redirect(url_for('authorize'))
    
    user_info = flask.session.get('user_info', {})
    user_id = user_info.get('id')
    
    if not user_id:
        flash('Erro ao identificar usuário. Por favor, faça login novamente.', 'danger')
        return redirect(url_for('logout'))
    
    if request.method == 'POST':
        # Coleta os dados do formulário
        settings_data = {
            'business_name': request.form.get('company_name', ''),
            'default_greeting': request.form.get('default_greeting', ''),
            'default_closing': request.form.get('default_closing', ''),
            'contact_info': request.form.get('contact_info', ''),
            'terms_accepted': request.form.get('terms_accepted'),
            'manager_name': request.form.get('manager_name', ''),
        }
        
        # Logo (imagem)
        ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
        MAX_LOGO_SIZE = 500 * 1024  # 500 KB

        def allowed_file(filename):
            return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

        logo_file = request.files.get('logo')
        logo_bytes = None
        if logo_file and logo_file.filename:
            # Valida extensão
            if not allowed_file(logo_file.filename):
                flash('Formato de imagem não suportado. Só PNG e JPG!', 'danger')
                return redirect(url_for('settings'))
            # Valida tamanho
            logo_file.seek(0, 2)
            file_size = logo_file.tell()
            logo_file.seek(0)
            if file_size > MAX_LOGO_SIZE:
                flash('Logo muito grande! Limite: 500KB.', 'danger')
                return redirect(url_for('settings'))
            logo_bytes = logo_file.read()
        settings_data['logo'] = logo_bytes  # Salva no dict, pode ser None se não tiver upload novo
        
        # Verifica se os Termos e Condições foram aceitos
        if not settings_data['terms_accepted']:
            flash("Você precisa aceitar os Termos e Condições para continuar.", "warning")
            return redirect(url_for('settings'))

        # Salvar as configurações do usuário no banco de dados
        save_user_settings(user_id, settings_data)
        nome_do_usuario = (
        settings_data.get('manager_name')
        or settings_data.get('business_name')
        or user_info.get('name')
        or 'Usuário'
        )
        html = montar_email_boas_vindas(nome_do_usuario)
        email_destino = user_info.get('email')  # do Google
        enviar_email(
            destinatario=email_destino,
            assunto='Seja bem-vindo ao ComentsIA! 🚀',
            corpo_html=html
        )
        session['terms_accepted'] = True  # <-- Só aqui!
        session['first_login_done'] = True
        flash('Configurações salvas com sucesso!', 'success')
        return redirect(url_for('index'))
    
    current_settings = get_user_settings(user_id)
    return render_template('settings.html', settings=current_settings, user=user_info, now=datetime.now())
import base64

@app.route('/logo')
def logo():
    user_id = ... # obtenha do login/session
    settings = UserSettings.query.filter_by(user_id=user_id).first()
    if settings and settings.logo:
        ext = 'png'  # ou verifique o tipo
        return f'data:image/{ext};base64,' + base64.b64encode(settings.logo).decode()
    return ""

@app.route('/apply_template', methods=['POST'])
def apply_template():
    """Aplica o template de saudação e contato à resposta."""
    if 'credentials' not in flask.session:
        return jsonify({'success': False, 'error': 'Usuário não autenticado'})
    
    user_info = flask.session.get('user_info', {})
    user_id = user_info.get('id')
    
    if not user_id:
        return jsonify({'success': False, 'error': 'Usuário não identificado'})
    
    data = request.json
    reply_text = data.get('reply_text', '')
    
    # Obter configurações do usuário do banco de dados
    settings = get_user_settings(user_id)
    
    # Aplicar template
    formatted_reply = f"{settings['default_greeting']}\n\n{reply_text}\n\n{settings['default_closing']}\n{settings['contact_info']}"
    
    return jsonify({
        'success': True,
        'formatted_reply': formatted_reply
    })

# Garante que as tabelas sejam criadas no Render também
if __name__ == '__main__':
    with app.app_context():
        from flask_migrate import upgrade
        upgrade()  # <-- Isso aplica as migrações pendentes no banco de dados online

    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    print("🚀 Servidor Flask rodando em http://127.0.0.1:8000")
    app.run(host='127.0.0.1', port=8000, debug=True)


