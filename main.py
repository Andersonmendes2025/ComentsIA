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
from sqlalchemy import Date
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
from email_utils import montar_email_conta_apagada
from email_utils import montar_email_boas_vindas, enviar_email
from models import RespostaEspecialUso
from flask import request, flash
from models import ConsideracoesUso
from utils.crypto import encrypt, decrypt

# Configuração do aplicativo Flask
# Inicializar o Flask

app = Flask(__name__)


# No início do arquivo, após as imports
PLANOS = {
    'free': {
        'nome': 'Gratuito',
        'preco': 0,
        'avaliacoes_mes': 20,
        'hiper_dia': 0,
        'consideracoes_dia': 0,      # <-- Adicionado!
        'relatorio_pdf_mes': 0,
        'api': False,
        'dashboard': 'simples',
        'suporte': 'básico',
        'marca_dagua': True,
    },
    'pro': {
        'nome': 'Pro',
        'preco': 19.99,
        'avaliacoes_mes': 200,
        'hiper_dia': 2,
        'consideracoes_dia': 2,      # <-- Adicionado!
        'relatorio_pdf_mes': 1,
        'api': False,
        'dashboard': 'completo',
        'suporte': 'prioritário',
        'marca_dagua': False,
    },
    'pro_anual': {
        'nome': 'Pro Anual',
        'preco': 199.00,  # Exemplo: 2 meses grátis (~16,58/mês)
        'avaliacoes_mes': 200,
        'hiper_dia': 2,
        'consideracoes_dia': 2,      # <-- Adicionado!
        'relatorio_pdf_mes': 1,
        'api': False,
        'dashboard': 'completo',
        'suporte': 'prioritário',
        'marca_dagua': False,
        'anual': True,
    },
    'business': {
        'nome': 'Business',
        'preco': 34.99,
        'avaliacoes_mes': None,
        'hiper_dia': None,
        'consideracoes_dia': None,   # <-- Adicionado!
        'relatorio_pdf_mes': None,
        'api': True,
        'dashboard': 'avançado',
        'suporte': 'vip',
        'marca_dagua': False,
    },
    'business_anual': {
        'nome': 'Business Anual',
        'preco': 349.00,  # Exemplo: 2 meses grátis (~29,08/mês)
        'avaliacoes_mes': None,
        'hiper_dia': None,
        'consideracoes_dia': None,   # <-- Adicionado!
        'relatorio_pdf_mes': None,
        'api': True,
        'dashboard': 'avançado',
        'suporte': 'vip',
        'marca_dagua': False,
        'anual': True,
    }
}


  
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
def agora_brt():
    return datetime.now(pytz.timezone("America/Sao_Paulo"))

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

ADMIN_EMAILS = [
    "anderson.mendesdossantos011@gmail.com",
    "comentsia.2025@gmail.com"
]
PLANO_EQUIVALENTES = {
    'pro': ['pro', 'pro_anual'],
    'business': ['business', 'business_anual']
}
def is_pro(user_id):
    return get_user_plan(user_id) in PLANO_EQUIVALENTES['pro']

def is_business(user_id):
    return get_user_plan(user_id) in PLANO_EQUIVALENTES['business']

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
def contar_avaliacoes_mes(user_id):
    inicio_mes = agora_brt().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    count = Review.query.filter(
        Review.user_id == user_id,
        Review.date >= inicio_mes
    ).count()
    return count

def contar_relatorios_mes(user_id):
    inicio_mes = agora_brt().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    count = RelatorioHistorico.query.filter(
        RelatorioHistorico.user_id == user_id,
        RelatorioHistorico.data_criacao >= inicio_mes
    ).count()
    return count
def get_data_hoje_brt():
    """Retorna a data atual no fuso de São Paulo (sem hora)."""
    return datetime.now(pytz.timezone("America/Sao_Paulo")).date()

def usuario_pode_usar_resposta_especial(user_id):
    hoje = get_data_hoje_brt()
    plano = get_user_plan(user_id)
    hiper_limite = PLANOS[plano]['hiper_dia']
    if hiper_limite is None:
        return True  # Ilimitado no Business
    uso = RespostaEspecialUso.query.filter_by(user_id=user_id, data_uso=hoje).first()
    return not uso or uso.quantidade_usos < hiper_limite


def atingiu_limite_avaliacoes_mes(user_id):
    plano = get_user_plan(user_id)
    limite = PLANOS[plano]['avaliacoes_mes']
    if not limite:  # None = ilimitado
        return False
    inicio_mes = agora_brt().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    avals_mes = Review.query.filter(
        Review.user_id == user_id,
        Review.date >= inicio_mes
    ).count()
    return avals_mes >= limite

def registrar_uso_resposta_especial(user_id):
    hoje = get_data_hoje_brt()
    uso = RespostaEspecialUso.query.filter_by(user_id=user_id, data_uso=hoje).first()

    if not uso:
        uso = RespostaEspecialUso(user_id=user_id, data_uso=hoje, quantidade_usos=1)
        db.session.add(uso)
    else:
        uso.quantidade_usos += 1

    db.session.commit()
def get_user_plan(user_id):
    settings = UserSettings.query.filter_by(user_id=user_id).first()
    if settings and settings.plano in PLANOS:
        return settings.plano
    return 'free'


def get_plan_limits(user_id):
    plano = get_user_plan(user_id)
    return PLANOS[plano]
def plano_ativo(user_id):
    """
    Retorna True se o usuário possui um plano ativo (não expirado), False caso contrário.
    O plano free é sempre considerado ativo.
    """
    settings = UserSettings.query.filter_by(user_id=user_id).first()
    if not settings:
        return False
    if settings.plano and settings.plano != 'free':
        if settings.plano_ate is not None:
            now = agora_brt()
            plano_ate = settings.plano_ate
            # Corrige se o plano_ate veio sem timezone
            if plano_ate.tzinfo is None:
                # Força o mesmo timezone de agora_brt()
                plano_ate = plano_ate.replace(tzinfo=now.tzinfo)
            return plano_ate >= now
        else:
            return False
    return settings.plano == 'free'


def require_plano_ativo(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_info = session.get('user_info', {})
        user_id = user_info.get('id')
        if not plano_ativo(user_id):
            flash("Seu plano venceu! Renove para continuar usando.", "warning")
            return redirect(url_for('planos'))
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
    from utils.crypto import decrypt

    settings = UserSettings.query.filter_by(user_id=user_id).first()
    if settings:
        try:
            return {
                'business_name': decrypt(settings.business_name) if settings.business_name else '',
                'default_greeting': settings.default_greeting or 'Olá,',
                'default_closing': settings.default_closing or 'Agradecemos seu feedback!',
                'contact_info': decrypt(settings.contact_info) if settings.contact_info else 'Entre em contato pelo telefone (00) 0000-0000 ou email@exemplo.com',
                'terms_accepted': settings.terms_accepted,
                'logo': settings.logo,
                'manager_name': decrypt(settings.manager_name) if settings.manager_name else ''
            }
        except Exception as e:
            print(f"[⚠️ ERRO de descriptografia]: {e}")
            return {
                'business_name': '',
                'default_greeting': 'Olá,',
                'default_closing': 'Agradecemos seu feedback!',
                'contact_info': '',
                'terms_accepted': False,
                'logo': None,
                'manager_name': ''
            }
    else:
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
    from utils.crypto import encrypt  # garante que está visível mesmo se estiver fora do escopo

    # Converter checkbox/string em booleano de verdade:
    terms_accepted_raw = settings_data.get('terms_accepted')
    terms_accepted = terms_accepted_raw in [True, 'on', 'true', 'True', 1, '1']

    # Criptografar campos sensíveis
    encrypted_name = encrypt(settings_data.get('business_name', ''))
    encrypted_contact = encrypt(settings_data.get('contact_info', ''))
    encrypted_manager = encrypt(settings_data.get('manager_name', ''))

    existing = UserSettings.query.filter_by(user_id=user_id).first()
    if existing:
        existing.business_name = encrypted_name
        existing.default_greeting = settings_data.get('default_greeting', 'Olá,')
        existing.default_closing = settings_data.get('default_closing', 'Agradecemos seu feedback!')
        existing.contact_info = encrypted_contact
        existing.terms_accepted = terms_accepted
        existing.manager_name = encrypted_manager
        # Só atualiza logo se veio nova
        if settings_data.get('logo'):
            existing.logo = settings_data['logo']
    else:
        new_settings = UserSettings(
            user_id=user_id,
            business_name=encrypted_name,
            default_greeting=settings_data.get('default_greeting', 'Olá,'),
            default_closing=settings_data.get('default_closing', 'Agradecemos seu feedback!'),
            contact_info=encrypted_contact,
            terms_accepted=terms_accepted,
            logo=settings_data.get('logo'),
            manager_name=encrypted_manager
        )
        db.session.add(new_settings)
    db.session.commit()

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
def inject_logged_user():
    user_info = flask.session.get('user_info')
    logged_in = 'credentials' in flask.session and user_info is not None
    return dict(
        logged_in=logged_in,
        user=user_info if logged_in else None
    )

@app.context_processor
def inject_plan_helpers():
    def is_pro_plan(user_plano):
        return user_plano in ['pro', 'pro_anual']
    def is_business_plan(user_plano):
        return user_plano in ['business', 'business_anual']
    return dict(is_pro_plan=is_pro_plan, is_business_plan=is_business_plan)


@app.route('/planos', methods=['GET', 'POST'])
def planos():
    user_info = session.get('user_info', {})
    user_id = user_info.get('id') if user_info else None

    if request.method == 'POST':
        if not user_id:
            flash("Você precisa estar logado para alterar o plano.", "warning")
            return redirect(url_for('authorize'))
        
        novo_plano = request.form.get('plano')
        if novo_plano not in PLANOS:
            flash("Plano inválido.", "danger")
            return redirect(url_for('planos'))

        settings = UserSettings.query.filter_by(user_id=user_id).first()
        if not settings:
            flash("Configurações do usuário não encontradas.", "danger")
            return redirect(url_for('planos'))

        if settings.plano == novo_plano:
            flash(f"Você já está no plano {PLANOS[novo_plano]['nome']}.", "info")
            return redirect(url_for('planos'))

        settings.plano = novo_plano

        # Sempre definir validade para planos pagos
        if novo_plano != 'free':
            dias_validade = 365 if novo_plano.endswith('_anual') else 30
            settings.plano_ate = agora_brt() + timedelta(days=dias_validade)
        else:
            settings.plano_ate = None

        db.session.commit()


        flash(f"Plano alterado para {PLANOS[novo_plano]['nome']} com sucesso!", "success")
        # Redireciona para página inicial após troca de plano
        return redirect(url_for('index'))

    # GET
    user_plano = get_user_plan(user_id) if user_id else 'free'
    return render_template('planos.html', planos=PLANOS, user_plano=user_plano)

@app.route('/alterar_plano', methods=['POST'])
def alterar_plano():
    if 'credentials' not in session:
        flash("Você precisa estar logado para alterar o plano.", "warning")
        return redirect(url_for('authorize'))

    user_info = session.get('user_info', {})
    user_id = user_info.get('id')
    if not user_id:
        flash("Usuário não identificado.", "danger")
        return redirect(url_for('logout'))

    novo_plano = request.form.get('plano')
    if novo_plano not in PLANOS:
        flash("Plano inválido.", "danger")
        return redirect(url_for('planos'))

    settings = UserSettings.query.filter_by(user_id=user_id).first()
    if not settings:
        # Se não existir configurações, cria uma nova com valores padrão
        settings = UserSettings(user_id=user_id)
        db.session.add(settings)

    if settings.plano == novo_plano:
        flash(f"Você já está no plano {PLANOS[novo_plano]['nome']}.", "info")
        return redirect(url_for('planos'))

    # Atualiza plano e validade
    settings.plano = novo_plano

    # Define validade conforme plano mensal ou anual
    dias_validade = 365 if novo_plano.endswith('_anual') else 30
    settings.plano_ate = agora_brt() + timedelta(days=dias_validade)

    db.session.commit()

    flash(f"Plano alterado para {PLANOS[novo_plano]['nome']} com sucesso!", "success")
    return redirect(url_for('planos'))
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
    if not user_settings['business_name'] or not user_settings['contact_info'] or not user_settings['terms_accepted']:
        return redirect(url_for('settings'))

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
@app.route('/get_avaliacoes_count')
def get_avaliacoes_count():
    user_info = session.get('user_info')
    if not user_info:
        return jsonify(success=False, error="Usuário não autenticado")
    user_id = user_info.get('id')
    count = contar_avaliacoes_mes(user_id)
    limite = PLANOS[get_user_plan(user_id)]['avaliacoes_mes']
    restantes = (limite - count) if limite is not None else None
    return jsonify(success=True, usados=count, restantes=restantes)

@app.route('/get_relatorios_count')
def get_relatorios_count():
    user_info = session.get('user_info')
    if not user_info:
        return jsonify(success=False, error="Usuário não autenticado")
    user_id = user_info.get('id')
    count = contar_relatorios_mes(user_id)
    limite = PLANOS[get_user_plan(user_id)]['relatorio_pdf_mes']
    restantes = (limite - count) if limite is not None else None
    return jsonify(success=True, usados=count, restantes=restantes)

@app.context_processor
def inject_admin_flag():
    user_info = session.get('user_info')
    is_admin = user_info and user_info.get('email') in ADMIN_EMAILS
    return dict(is_admin=is_admin)

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
@app.route('/admin')
def admin_dashboard():
    user_info = session.get('user_info')
    if not user_info or user_info.get('email') not in ADMIN_EMAILS:
        flash("Acesso restrito ao administrador.", "danger")
        return redirect(url_for('index'))

    total_usuarios = UserSettings.query.count()
    total_avaliacoes = Review.query.count()
    total_respostas = Review.query.filter(Review.reply != '').count()
    total_relatorios = RelatorioHistorico.query.count()

    # Consulta corrigida: só pega usuários com created_at preenchido
    usuarios_query = (
        db.session.query(
            db.func.date_trunc('month', UserSettings.created_at).label('mes'),
            db.func.count(UserSettings.id)
        )
        .filter(UserSettings.created_at != None)  # <-- ESSA LINHA É A NOVIDADE
        .group_by('mes')
        .order_by('mes')
        .all()
    )
    meses = [mes.strftime('%m/%Y') for mes, _ in usuarios_query]
    qtds = [qtd for _, qtd in usuarios_query]
    usuarios_por_mes = {"meses": meses, "qtds": qtds}

    top_empresas = db.session.query(
        UserSettings.business_name,
        db.func.count(Review.id)
    ).join(Review, UserSettings.user_id == Review.user_id) \
     .group_by(UserSettings.business_name) \
     .order_by(db.func.count(Review.id).desc()) \
     .limit(5).all()

    return render_template(
        'admin_dashboard.html',
        total_usuarios=total_usuarios,
        total_avaliacoes=total_avaliacoes,
        total_respostas=total_respostas,
        total_relatorios=total_relatorios,
        top_empresas=top_empresas,
        usuarios_por_mes=usuarios_por_mes,
        now=datetime.now()
    )

@app.route("/quem-somos")
def quem_somos():
    return render_template("quem-somos.html")

@app.route('/relatorio', methods=['GET', 'POST'])
@require_terms_accepted
@require_plano_ativo
def gerar_relatorio():
    if 'credentials' not in flask.session:
        flash("Você precisa estar logado para gerar o relatório.", "warning")
        return redirect(url_for('authorize'))

    user_info = flask.session.get('user_info', {})
    user_id = user_info.get('id')
    print(f"[RELATÓRIO] user_id: {user_id}")

    user_settings = get_user_settings(user_id)
    print(f"[RELATÓRIO] user_settings: {user_settings}")

    if not user_settings['business_name'] or not user_settings['contact_info'] or not user_settings['terms_accepted']:
        return redirect(url_for('settings'))

    plano = get_user_plan(user_id)
    relatorio_limite = PLANOS[plano]['relatorio_pdf_mes']

    # GET: Sempre mostra a página (deixe para bloquear no template)
    if request.method == 'GET':
        return render_template(
            'relatorio.html',
            PLANOS=PLANOS,
            user_plano=plano,
            user_settings=user_settings
        )

    # POST: Só permite gerar se o plano permitir
    if relatorio_limite == 0:
        flash("Baixar relatórios em PDF está disponível apenas no plano PRO ou superior.", "warning")
        return redirect(url_for('relatorio'))

    # Conta quantos relatórios o usuário já gerou neste mês
    if relatorio_limite is not None:  # Se não for ilimitado
        inicio_mes = agora_brt().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        rels_mes = RelatorioHistorico.query.filter(
            RelatorioHistorico.user_id == user_id,
            RelatorioHistorico.data_criacao >= inicio_mes
        ).count()
        if rels_mes >= relatorio_limite:
            flash(f"Você já atingiu o limite mensal de download de relatórios em PDF do seu plano ({relatorio_limite} por mês).", "warning")
            return redirect(url_for('relatorio'))

    # Coleta filtros do formulário
    periodo = request.form.get('periodo', '90dias')
    nota = request.form.get('nota', 'todas')
    respondida = request.form.get('respondida', 'todas')
    print(f"[RELATÓRIO] Filtros: periodo={periodo}, nota={nota}, respondida={respondida}")

    avaliacoes_query = Review.query.filter_by(user_id=user_id).all()
    print(f"[RELATÓRIO] Avaliações encontradas: {len(avaliacoes_query)}")

    avaliacoes = []
    agora = agora_brt()
    for av in avaliacoes_query:
        data_av = av.date

        # Consistência de timezone: tudo para America/Sao_Paulo
        if data_av.tzinfo is None:
            # Assume que é BRT se não tiver tzinfo
            data_av = data_av.replace(tzinfo=agora.tzinfo)
        else:
            # Se já tem tzinfo, converte para BRT
            data_av = data_av.astimezone(agora.tzinfo)

        # Debug: diferença de dias para checar filtro correto
        diff_days = (agora - data_av).days
        print(f"[RELATÓRIO] DEBUG data_av={data_av}, agora={agora}, diff_days={diff_days}")

        # Aplicando filtros
        if nota != 'todas' and str(av.rating) != nota:
            continue
        if respondida == 'sim' and not av.replied:
            continue
        if respondida == 'nao' and av.replied:
            continue
        if periodo == '90dias' and diff_days > 90:
            continue
        if periodo == '6meses' and diff_days > 180:
            continue
        if periodo == '1ano' and diff_days > 365:
            continue
        avaliacoes.append({
            'data': data_av,  # <- AGORA SEMPRE TIMEZONE-AWARE!
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
@app.template_filter('formatar_data_brt')
def formatar_data_brt(data):
    if data:
        fuso = pytz.timezone('America/Sao_Paulo')
        return data.astimezone(fuso).strftime('%d/%m/%Y às %H:%M')
    return ''

@app.route('/get_hiper_count')
def get_hiper_count():
    if 'credentials' not in session:
        return jsonify({'success': False, 'error': 'Não autenticado.'})
    user_info = session.get('user_info', {})
    user_id = user_info.get('id')
    usos_hoje = RespostaEspecialUso.query.filter_by(user_id=user_id, data_uso=get_data_hoje_brt()).first()
    plano = get_user_plan(user_id)
    hiper_limite = PLANOS[plano]['hiper_dia'] or 0
    usos_restantes_hiper = (hiper_limite - (usos_hoje.quantidade_usos if usos_hoje else 0)) if hiper_limite else 0

    if usos_restantes_hiper < 0:
        usos_restantes_hiper = 0
    return jsonify({'success': True, 'usos_restantes_hiper': usos_restantes_hiper})
@app.template_filter('b64encode')
def b64encode_filter(data):
    if data:
        return Markup(base64.b64encode(data).decode('utf-8'))
    return ''
def usuario_pode_usar_consideracoes(user_id):
    hoje = get_data_hoje_brt()
    plano = get_user_plan(user_id)
    cons_limite = PLANOS[plano]['consideracoes_dia']
    if cons_limite is None:
        return True  # Ilimitado no Business
    uso = ConsideracoesUso.query.filter_by(user_id=user_id, data_uso=hoje).first()
    return not uso or uso.quantidade_usos < cons_limite


def registrar_uso_consideracoes(user_id):
    hoje = get_data_hoje_brt()
    uso = ConsideracoesUso.query.filter_by(user_id=user_id, data_uso=hoje).first()
    if not uso:
        uso = ConsideracoesUso(user_id=user_id, data_uso=hoje, quantidade_usos=1)
        db.session.add(uso)
    else:
        uso.quantidade_usos += 1
    db.session.commit()
@app.route('/get_consideracoes_count')
def get_consideracoes_count():
    if 'credentials' not in session:
        return jsonify({'success': False, 'error': 'Não autenticado.'})
    user_info = session.get('user_info', {})
    user_id = user_info.get('id')
    plano = get_user_plan(user_id)
    cons_limite = PLANOS[plano]['consideracoes_dia'] or 0
    usos_hoje = ConsideracoesUso.query.filter_by(user_id=user_id, data_uso=get_data_hoje_brt()).first()
    usos_restantes_consideracoes = (cons_limite - (usos_hoje.quantidade_usos if usos_hoje else 0)) if cons_limite else 0
    if usos_restantes_consideracoes < 0:
        usos_restantes_consideracoes = 0
    return jsonify({'success': True, 'usos_restantes_consideracoes': usos_restantes_consideracoes})

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

def ativar_ou_alterar_plano(user_id, novo_plano):
    settings = UserSettings.query.filter_by(user_id=user_id).first()
    if not settings:
        settings = UserSettings(user_id=user_id)
        db.session.add(settings)  # adiciona para a sessão

    settings.plano = novo_plano
    # Define validade conforme plano mensal ou anual
    dias_validade = 365 if novo_plano.endswith('_anual') else 30
    settings.plano_ate = agora_brt() + timedelta(days=365)

    db.session.commit()

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
@require_plano_ativo
def add_review():
    """Adiciona avaliação manualmente ou via robô, com verificação de duplicatas e resposta automática considerando limites do plano."""
    if 'credentials' not in session:
        return redirect(url_for('authorize'))

    user_info = session.get('user_info', {})
    user_id = user_info.get('id')

    # Função auxiliar para limite mensal de avaliações
    def atingiu_limite_avaliacoes_mes(user_id):
        plano = get_user_plan(user_id)
        limite = PLANOS[plano]['avaliacoes_mes']
        if not limite:  # None = ilimitado
            return False
        inicio_mes = agora_brt().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        avals_mes = Review.query.filter(
            Review.user_id == user_id,
            Review.date >= inicio_mes
        ).count()
        return avals_mes >= limite

    # Função auxiliar para hiper compreensiva
    def usuario_pode_usar_resposta_especial_plano(user_id):
        hoje = get_data_hoje_brt()
        plano = get_user_plan(user_id)
        hiper_limite = PLANOS[plano]['hiper_dia']
        if hiper_limite is None:
            return True  # Ilimitado no Business
        if hiper_limite == 0:
            return False  # Free não pode
        uso = RespostaEspecialUso.query.filter_by(user_id=user_id, data_uso=hoje).first()
        return not uso or uso.quantidade_usos < hiper_limite

    if request.method == 'POST':
        if not user_id:
            flash('Erro ao identificar usuário. Por favor, faça login novamente.', 'danger')
            return redirect(url_for('logout'))

        hiper_compreensiva = request.form.get('hiper_compreensiva') == 'on'
        consideracoes = request.form.get('consideracoes', '').strip()

        # BLOQUEIO POR PLANO - Limite de avaliações
        if atingiu_limite_avaliacoes_mes(user_id):
            flash("Você atingiu o limite de avaliações do seu plano este mês.", "warning")
            return redirect(url_for('reviews'))

        # BLOQUEIO POR PLANO - Resposta hiper compreensiva
        if hiper_compreensiva and not usuario_pode_usar_resposta_especial_plano(user_id):
            flash('Você atingiu o limite diário de respostas hiper compreensivas do seu plano.', 'warning')
            return redirect(url_for('add_review'))

        reviewer_name = request.form.get('reviewer_name') or request.json.get('reviewer_name', 'Cliente Anônimo')
        rating = int(request.form.get('rating') or request.json.get('rating', 5))
        text = request.form.get('text') or request.json.get('text', '')
        data = datetime.now(pytz.timezone("America/Sao_Paulo"))

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

        settings = get_user_settings(user_id)
        manager = settings.get('manager_name', '').strip()
        business = settings.get('business_name', '').strip()
        assinatura = f"{business}\n{manager}" if manager else business

        # Prompt base
        prompt = f"""
Você é um assistente especializado em atendimento ao cliente e deve escrever uma resposta personalizada para uma avaliação recebida por "{settings['business_name']}".
Avaliação recebida:
- Nome do cliente: {reviewer_name}
- Nota: {rating} estrelas
- Texto: "{text}"
"""

        # Se houver considerações, inclua no prompt
        if consideracoes:
            prompt += f'\nIMPORTANTE: O usuário forneceu as seguintes considerações para personalizar a resposta. Use essas informações com prioridade:\n"{consideracoes}"\n'
            registrar_uso_consideracoes(user_id)

        prompt += f"""
Instruções:
- Comece com: "{settings['default_greeting']} {reviewer_name},"
- Use palavras mais humanas possíveis, seja natural na escrita e no vocabulário.
- Comente os pontos mencionados, usando palavras diferentes.
- Se a nota for de 1 a 3, demonstre empatia, peça desculpas e ofereça uma solução.
- Se a nota for de 4 ou 5, agradeça e convide para retornar.
- Finalize com: "{settings['default_closing']}"
- Inclua as informações de contato: "{settings['contact_info']}"
- Assine ao final exatamente assim, cada item em uma linha:
{assinatura}
- Não use cargos, não use "Atenciosamente", apenas os nomes.
- A resposta deve ter entre 3 e 5 frases, ser personalizada e evitar frases genéricas.
"""

        if hiper_compreensiva:
            registrar_uso_resposta_especial(user_id)
            prompt += "\n\nGere uma resposta mais longa, empática e detalhada. Use de 10 a 15 frases. Mostre escuta ativa, reconhecimento das críticas e profissionalismo elevado. Responda cuidadosamente aos principais pontos levantados pelo cliente, mesmo que indiretamente." 
        try:
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

    return render_template(
    'add_review.html',
    user=user_info,
    now=datetime.now(),
    user_plano=get_user_plan(user_info.get('id') if user_info else None),
    PLANOS=PLANOS
    )




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
@require_plano_ativo
def dashboard():
    """Página de dashboard com análise de avaliações, adaptada ao plano."""
    if 'credentials' not in flask.session:
        return flask.redirect(url_for('authorize'))
    
    user_info = flask.session.get('user_info', {})
    user_id = user_info.get('id')
    
    if not user_id:
        flash('Erro ao identificar usuário. Por favor, faça login novamente.', 'danger')
        return redirect(url_for('logout'))
    
    # Obtém o plano do usuário
    plano = get_user_plan(user_id)

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

    responded_reviews = sum(1 for review in user_reviews if review.replied)
    percent_responded = (responded_reviews / total_reviews) * 100 if total_reviews else 0

    rating_distribution_values = [
        rating_distribution[1],
        rating_distribution[2],
        rating_distribution[3],
        rating_distribution[4],
        rating_distribution[5],
    ]
    
    # Passe também o dicionário PLANOS
    return render_template(
        'dashboard.html',
        total_reviews=total_reviews,
        avg_rating=avg_rating,
        rating_distribution=rating_distribution,
        rating_distribution_values=rating_distribution_values,
        percent_responded=percent_responded,
        reviews=user_reviews,
        user=user_info,
        user_plano=plano,
        PLANOS=PLANOS,  # <- AQUI!
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
            if not allowed_file(logo_file.filename):
                flash('Formato de imagem não suportado. Só PNG e JPG!', 'danger')
                return redirect(url_for('settings'))
            logo_file.seek(0, 2)
            file_size = logo_file.tell()
            logo_file.seek(0)
            if file_size > MAX_LOGO_SIZE:
                flash('Logo muito grande! Limite: 500KB.', 'danger')
                return redirect(url_for('settings'))
            logo_bytes = logo_file.read()
        settings_data['logo'] = logo_bytes
        
        if not settings_data['terms_accepted']:
            flash("Você precisa aceitar os Termos e Condições para continuar.", "warning")
            return redirect(url_for('settings'))

        # Salva as configurações
        save_user_settings(user_id, settings_data)

        # Envia o e-mail de boas-vindas apenas se ainda não foi enviado
        existing_settings = UserSettings.query.filter_by(user_id=user_id).first()
        if existing_settings and not existing_settings.email_boas_vindas_enviado:
            nome_do_usuario = (
                existing_settings.manager_name
                or existing_settings.business_name
                or user_info.get('name')
                or 'Usuário'
            )
            html = montar_email_boas_vindas(nome_do_usuario)
            email_destino = user_info.get('email')
            try:
                enviar_email(
                    destinatario=email_destino,
                    assunto='Seja bem-vindo ao ComentsIA! 🚀',
                    corpo_html=html
                )
                existing_settings.email_boas_vindas_enviado = True
                db.session.commit()
            except Exception as e:
                print(f"Erro ao enviar e-mail de boas-vindas: {e}")

        session['terms_accepted'] = True  
        flash('Configurações salvas com sucesso!', 'success')
        return redirect(url_for('index'))
    
    current_settings = get_user_settings(user_id)
    return render_template('settings.html', settings=current_settings, user=user_info, now=datetime.now())


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


