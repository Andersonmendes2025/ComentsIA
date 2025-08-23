from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import pytz
from sqlalchemy import DateTime
from sqlalchemy.orm import relationship

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
    date = db.Column(DateTime(timezone=True), default=default_brt_now)
    reply = db.Column(db.Text)
    replied = db.Column(db.Boolean, default=False)
    terms_accepted = db.Column(db.Boolean, default=False)
    source = db.Column(db.String(50))
    external_id = db.Column(db.String(64), index=True)      # número da reserva / review id
    fingerprint = db.Column(db.String(128), index=True)     # opcional: hash único

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
    created_at = db.Column(db.DateTime(timezone=True), default=default_brt_now)
    email_boas_vindas_enviado = db.Column(db.Boolean, default=False)
    stripe_customer_id = db.Column(db.String)
    stripe_subscription_id = db.Column(db.String)  
    plano = db.Column(db.String(32), default='free')
    plano_ate = db.Column(db.DateTime, nullable=True)

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

class RespostaEspecialUso(db.Model):
    __tablename__ = 'resposta_especial_uso'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(255), nullable=False)
    data_uso = db.Column(db.Date, nullable=False)
    quantidade_usos = db.Column(db.Integer, default=1)

class ConsideracoesUso(db.Model):
    __tablename__ = 'consideracoes_uso'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(255), nullable=False)
    data_uso = db.Column(db.Date, nullable=False)
    quantidade_usos = db.Column(db.Integer, default=1)

class FilialVinculo(db.Model):
    __tablename__ = "filial_vinculo"
    id = db.Column(db.Integer, primary_key=True)
    parent_user_id = db.Column(db.String, db.ForeignKey('users.id'), index=True, nullable=False)
    child_user_id  = db.Column(db.String, db.ForeignKey('users.id'), index=True, nullable=False)
    status = db.Column(db.String(20), default="pendente", nullable=False)
    data_convite = db.Column(DateTime(timezone=True), default=default_brt_now)
    data_aceite = db.Column(db.DateTime(timezone=True), nullable=True)

    parent_user = relationship("User", foreign_keys=[parent_user_id], backref="convites_enviados")
    child_user  = relationship("User", foreign_keys=[child_user_id], backref="convites_recebidos")

    __table_args__ = (db.UniqueConstraint("parent_user_id", "child_user_id", name="uq_parent_child"),)

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.String(255), primary_key=True)  # ID do Google (email)
    email = db.Column(db.String(255), unique=True, nullable=False)
    nome = db.Column(db.String(255))
    foto_url = db.Column(db.String(512))  # opcional: para exibir avatar
    criado_em = db.Column(db.DateTime(timezone=True), default=default_brt_now)

    def __repr__(self):
        return f"<users {self.email}>"

# ========== NOVAS TABELAS Booking ==========
class ReservationIndex(db.Model):
    """
    Índice de números de reserva (ou review id) já importados por usuário/fonte.
    """
    __tablename__ = "reservation_index"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(255), nullable=False, index=True)
    source = db.Column(db.String(32), nullable=False, index=True, default="booking")
    external_id = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=default_brt_now)

    __table_args__ = (
        db.UniqueConstraint("user_id", "source", "external_id", name="uq_reservation_index_user_source_extid"),
    )

class UploadLog(db.Model):
    """
    Histórico de uploads efetuados pelo usuário (Booking CSV).
    """
    __tablename__ = "upload_log"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(255), index=True, nullable=False)
    source = db.Column(db.String(32), index=True, nullable=False, default="booking")
    filename = db.Column(db.String(255))
    filesize = db.Column(db.Integer)
    started_at = db.Column(db.DateTime(timezone=True), default=default_brt_now)
    finished_at = db.Column(db.DateTime(timezone=True))

    inserted = db.Column(db.Integer, default=0)
    duplicates = db.Column(db.Integer, default=0)
    skipped = db.Column(db.Integer, default=0)

    status = db.Column(db.String(24), default="running")  # running|success|error
    errors_json = db.Column(db.Text)  # lista curta de erros/avisos
