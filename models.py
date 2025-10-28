from datetime import datetime

import pytz
from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import DateTime
from sqlalchemy.orm import relationship

db = SQLAlchemy()


def default_brt_now():
    # Retorna o datetime atual já no timezone de São Paulo
    return datetime.now(pytz.timezone("America/Sao_Paulo"))


# models.py (classe Review)
class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(255), nullable=False)
    reviewer_name = db.Column(db.String(255))
    rating = db.Column(db.Integer)
    location_name = db.Column(db.String(255), nullable=True)
    text = db.Column(db.Text)
    date = db.Column(DateTime(timezone=True), default=default_brt_now)
    reply = db.Column(db.Text)
    replied = db.Column(db.Boolean, default=False)
    terms_accepted = db.Column(db.Boolean, default=False)
    source = db.Column(db.String(50))
    is_auto = db.Column(db.Boolean, default=False, nullable=False)
    auto_origin = db.Column(db.String(50))  # Ex: 'gbp' para Google Business Profile
    external_id = db.Column(db.String(255), index=True)
    fingerprint = db.Column(db.String(128), index=True)
    upload_log_id = db.Column(
        db.Integer,
        db.ForeignKey("upload_log.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )


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
    plano = db.Column(db.String(32), default="free")
    plano_ate = db.Column(db.DateTime, nullable=True)
    gbp_tone = db.Column(db.String(32))
    gbp_auto_enabled = db.Column(db.Boolean, default=False)
    google_refresh_token = db.Column(db.String(512))


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
    name = db.Column(
        db.String(50), unique=True, nullable=False
    )  # Ex: 'terms', 'privacy'
    content = db.Column(db.Text, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True), default=default_brt_now, onupdate=default_brt_now
    )


class RespostaEspecialUso(db.Model):
    __tablename__ = "resposta_especial_uso"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(255), nullable=False)
    data_uso = db.Column(db.Date, nullable=False)
    quantidade_usos = db.Column(db.Integer, default=1)


class ConsideracoesUso(db.Model):
    __tablename__ = "consideracoes_uso"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(255), nullable=False)
    data_uso = db.Column(db.Date, nullable=False)
    quantidade_usos = db.Column(db.Integer, default=1)


class FilialVinculo(db.Model):
    __tablename__ = "filial_vinculo"
    id = db.Column(db.Integer, primary_key=True)
    parent_user_id = db.Column(
        db.String, db.ForeignKey("users.id"), index=True, nullable=False
    )
    child_user_id = db.Column(
        db.String, db.ForeignKey("users.id"), index=True, nullable=False
    )
    status = db.Column(db.String(20), default="pendente", nullable=False)
    data_convite = db.Column(DateTime(timezone=True), default=default_brt_now)
    data_aceite = db.Column(db.DateTime(timezone=True), nullable=True)

    parent_user = relationship(
        "User", foreign_keys=[parent_user_id], backref="convites_enviados"
    )
    child_user = relationship(
        "User", foreign_keys=[child_user_id], backref="convites_recebidos"
    )

    __table_args__ = (
        db.UniqueConstraint("parent_user_id", "child_user_id", name="uq_parent_child"),
    )


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.String(255), primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    nome = db.Column(db.String(255))
    foto_url = db.Column(db.String(512))
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
    external_id = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=default_brt_now)

    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "source",
            "external_id",
            name="uq_reservation_index_user_source_extid",
        ),
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
    reviews = relationship(
        "Review",
        backref="upload_log",
        lazy="dynamic",
        passive_deletes=True,
    )

    inserted = db.Column(db.Integer, default=0)
    duplicates = db.Column(db.Integer, default=0)
    skipped = db.Column(db.Integer, default=0)

    status = db.Column(db.String(24), default="running")  # running|success|error
    errors_json = db.Column(db.Text)  # lista curta de erros/avisos


class Role(db.Model):
    __tablename__ = "roles"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(
        db.String(32), unique=True, nullable=False
    )  # admin, financeiro, diretoria, marketing_email, suporte
    name = db.Column(db.String(64), nullable=False)


class RolePermission(db.Model):
    __tablename__ = "role_permissions"
    id = db.Column(db.Integer, primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False)
    perm = db.Column(db.String(64), nullable=False)  # ex: finance.view, finance.edit
    level = db.Column(db.String(8), nullable=False, default="read")  # none|read|write


class UserRole(db.Model):
    __tablename__ = "user_roles"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.String(255), db.ForeignKey("users.id"), unique=True, nullable=False
    )
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False)


class UserPermissionOverride(db.Model):
    __tablename__ = "user_perm_overrides"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.String(255), db.ForeignKey("users.id"), nullable=False, index=True
    )
    perm = db.Column(db.String(64), nullable=False)  # ex: finance.edit
    level = db.Column(db.String(8), nullable=False, default="read")  # none|read|write


class PlanPrice(db.Model):
    __tablename__ = "plan_prices"
    id = db.Column(db.Integer, primary_key=True)
    plan_key = db.Column(
        db.String(32), unique=True, nullable=False
    )  # free, pro, pro_anual, business, business_anual
    price_cents = db.Column(db.Integer, nullable=False, default=0)
    currency = db.Column(db.String(8), default="BRL")


class PaymentTransaction(db.Model):
    __tablename__ = "payment_transactions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(255), db.ForeignKey("users.id"), index=True)
    plan_key = db.Column(db.String(32), index=True)
    amount_cents = db.Column(
        db.Integer, nullable=False, default=0
    )  # valor realmente pago
    fees_cents = db.Column(db.Integer, default=0)  # opcional: custo por transação
    status = db.Column(db.String(16), default="paid")  # paid|failed|refunded
    paid_at = db.Column(db.DateTime(timezone=True), default=default_brt_now)
    external_id = db.Column(db.String(255), index=True)


class FinanceItem(db.Model):
    __tablename__ = "finance_items"
    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(16), nullable=False)  # "tax" | "cost"
    name = db.Column(db.String(120), nullable=False)
    method = db.Column(db.String(16), nullable=False)  # "percent" | "fixed"
    percent = db.Column(db.Float)  # se method = percent
    amount_cents = db.Column(db.Integer)  # se method = fixed
    recurrence = db.Column(db.String(16), default="monthly")  # monthly | once
    start_month = db.Column(db.Date)  # AAAA-MM-01
    end_month = db.Column(db.Date)  # opcional
    active = db.Column(db.Boolean, default=True)
    allocation_method = db.Column(
        db.String(24), default="per_user_equal"
    )  # per_user_equal | per_revenue_share | per_transaction
    cost_center = db.Column(db.String(64))  # opcional


class Coupon(db.Model):
    __tablename__ = "coupons"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.String(200))
    discount_type = db.Column(db.String(16), nullable=False)  # percent | fixed
    discount_value = db.Column(
        db.Integer, nullable=False
    )  # se percent: 10 => 10%; se fixed: centavos
    max_uses = db.Column(db.Integer)
    uses_count = db.Column(db.Integer, default=0)
    valid_from = db.Column(db.DateTime(timezone=True))
    valid_until = db.Column(db.DateTime(timezone=True))
    recurring = db.Column(db.Boolean, default=False)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=default_brt_now)

    def is_valid(self) -> bool:
        now = default_brt_now()
        if not self.active:
            return False
        if self.valid_from and now < self.valid_from:
            return False
        if self.valid_until and now > self.valid_until:
            return False
        if self.max_uses and (self.uses_count or 0) >= self.max_uses:
            return False
        return True


class EmailTemplate(db.Model):
    __tablename__ = "email_templates"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), unique=True, nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    html = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=default_brt_now)


class BillingEvent(db.Model):
    __tablename__ = "billing_events"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(255), index=True)
    event = db.Column(db.String(32), nullable=False)  # payment_failed
    external_id = db.Column(db.String(255), index=True)
    occurred_at = db.Column(db.DateTime(timezone=True), default=default_brt_now)
    handled_immediate = db.Column(db.Boolean, default=False)
    sent_day1 = db.Column(db.Boolean, default=False)
    sent_day2 = db.Column(db.Boolean, default=False)


class MessageLog(db.Model):
    __tablename__ = "message_log"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(255), index=True)
    channel = db.Column(db.String(16), default="email")  # email|whats|inapp
    template_key = db.Column(db.String(64))
    event_ref_id = db.Column(db.Integer)  # referencia BillingEvent.id
    created_at = db.Column(db.DateTime(timezone=True), default=default_brt_now)


# ==== LOG/AUDITORIA (usando default_brt_now) ====


class AdminActionLog(db.Model):
    __tablename__ = "admin_action_log"
    id = db.Column(db.Integer, primary_key=True)
    admin_user_id = db.Column(db.String(255), nullable=False)  # quem fez
    target_user_id = db.Column(db.String(255))  # em quem aplicou (opcional)
    action = db.Column(
        db.String(64), nullable=False
    )  # change_role | change_perm | export | pricing_update | broadcast | etc
    meta = db.Column(db.JSON)  # detalhes
    ip = db.Column(db.String(64))
    user_agent = db.Column(db.String(256))
    created_at = db.Column(db.DateTime(timezone=True), default=default_brt_now)


# ==== CRM-lite (opcional) ====


class Contact(db.Model):
    __tablename__ = "contacts"
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), index=True)
    nome = db.Column(db.String(120))
    email = db.Column(db.String(255))
    phone = db.Column(db.String(64))
    cargo = db.Column(db.String(120))


class Ticket(db.Model):
    __tablename__ = "tickets"
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), index=True)
    assunto = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(16), default="aberto")  # aberto|pendente|resolvido
    prioridade = db.Column(db.String(16), default="normal")  # baixa|normal|alta
    owner_id = db.Column(db.String(255))  # responsável interno
    created_at = db.Column(db.DateTime(timezone=True), default=default_brt_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), default=default_brt_now, onupdate=default_brt_now
    )


class Activity(db.Model):
    __tablename__ = "activities"
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), index=True)
    tipo = db.Column(db.String(16), nullable=False)
    texto = db.Column(db.Text)
    due_at = db.Column(db.DateTime(timezone=True))
    done_at = db.Column(db.DateTime(timezone=True))
    owner_id = db.Column(db.String(255))
    created_at = db.Column(db.DateTime(timezone=True), default=default_brt_now)


class Company(db.Model):
    __tablename__ = "companies"
    id = db.Column(db.Integer, primary_key=True)
    owner_user_id = db.Column(db.String(255), db.ForeignKey("users.id"))
    name = db.Column(db.String(255), nullable=False)
    segmento = db.Column(db.String(64))
    cidade = db.Column(db.String(64))
    email = db.Column(db.String(255))
    phone = db.Column(db.String(50))
    created_at = db.Column(db.DateTime(timezone=True), default=default_brt_now)
