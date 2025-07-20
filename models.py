from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import pytz
from sqlalchemy import DateTime

db = SQLAlchemy()

def default_brt_now():
    # Retorna o datetime atual já no timezone de São Paulo
    return datetime.now(pytz.timezone('America/Sao_Paulo'))

class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(255), nullable=False)
    reviewer_name = db.Column(db.String(255))
    rating = db.Column(db.Integer)
    text = db.Column(db.Text)
    date = db.Column(db.String(255))
    reply = db.Column(db.Text)
    replied = db.Column(db.Boolean, default=False)
    terms_accepted = db.Column(db.Boolean, default=False)

class UserSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(255), nullable=False, unique=True)
    business_name = db.Column(db.String(255))
    default_greeting = db.Column(db.String(255))
    default_closing = db.Column(db.String(255))
    contact_info = db.Column(db.String(255))
    terms_accepted = db.Column(db.Boolean, default=False)
    logo = db.Column(db.LargeBinary)
    manager_name = db.Column(db.String(255))

class RelatorioHistorico(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(255), nullable=False)
    data_criacao = db.Column(db.DateTime(timezone=True), default=default_brt_now)
    filtro_periodo = db.Column(db.String(50))
    filtro_nota = db.Column(db.String(50))
    filtro_respondida = db.Column(db.String(50))
    nome_arquivo = db.Column(db.String(255))
    caminho_arquivo = db.Column(db.String(500))
    arquivo_pdf = db.Column(db.LargeBinary)

class LegalDocument(db.Model):
    __tablename__ = "legal_documents"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)  # Ex: 'terms', 'privacy'
    content = db.Column(db.Text, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=default_brt_now, onupdate=default_brt_now)