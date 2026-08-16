# -*- coding: utf-8 -*-
"""
Modelos de Banco de Dados para a Integração com o Mercado Livre (ComentsIA - Analytics ML).
Armazena dados de reputação do vendedor (Termômetro, Medalha, Claims, Atrasos, Cancelamentos),
métricas de perguntas pré-venda, avaliações agregadas da loja, Dossiê de Saúde por IA e Alertas Preventivos.
"""

from __future__ import annotations
import json
from datetime import datetime
from sqlalchemy.orm import relationship
from models import db, default_brt_now

class MercadoLivreAccount(db.Model):
    __tablename__ = "mercadolivre_accounts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(255), db.ForeignKey("users.id"), index=True, nullable=False)

    # Identificadores do Vendedor no Mercado Livre
    seller_id = db.Column(db.String(255), nullable=False, index=True)  # ex: "123456789"
    nickname = db.Column(db.String(255), nullable=False)               # ex: "LOJA_OFICIAL"
    site_id = db.Column(db.String(20), default="MLB")                  # MLB = Brasil
    permalink = db.Column(db.String(512), nullable=True)

    # "Exame de Sangue" da Reputação (Termômetro & Medalha)
    level_id = db.Column(db.String(50), default="5_green")            # 5_green, 4_light_green, 3_yellow, 2_orange, 1_red
    power_seller_status = db.Column(db.String(50), nullable=True)     # platinum, gold, silver, null
    
    # Métricas de Saúde & Risco (taxas percentuais 0.0 a 1.0)
    claims_rate = db.Column(db.Float, default=0.0)                    # Taxa de Reclamações (limite máx verde: 0.03 = 3%)
    delayed_rate = db.Column(db.Float, default=0.0)                   # Taxa de Atraso nos envios (limite máx verde: 0.15 = 15%)
    cancellations_rate = db.Column(db.Float, default=0.0)             # Taxa de Cancelamento (limite máx verde: 0.025 = 2.5%)

    # Transações e Avaliações de Compradores
    completed_transactions = db.Column(db.Integer, default=0)
    canceled_transactions = db.Column(db.Integer, default=0)
    total_transactions = db.Column(db.Integer, default=0)
    positive_rating_pct = db.Column(db.Float, default=1.0)
    negative_rating_pct = db.Column(db.Float, default=0.0)
    neutral_rating_pct = db.Column(db.Float, default=0.0)

    # Perguntas Pré-Venda da Conta (Atendimento & Conversão)
    total_questions = db.Column(db.Integer, default=0)
    unanswered_questions = db.Column(db.Integer, default=0)
    avg_response_time_minutes = db.Column(db.Float, default=0.0)      # Tempo médio em minutos
    questions_response_rate = db.Column(db.Float, default=1.0)        # 0.0 a 1.0 (ex: 0.98 = 98%)
    recent_questions_json = db.Column(db.Text, nullable=True)         # Lista serializada das últimas perguntas

    # Métricas Agregadas da Loja / Produtos da Conta
    total_active_items = db.Column(db.Integer, default=0)
    store_rating_average = db.Column(db.Float, default=0.0)           # Nota média de todos os produtos (0 a 5.0)
    total_store_reviews = db.Column(db.Integer, default=0)            # Total de avaliações na conta
    rating_breakdown_json = db.Column(db.Text, nullable=True)         # Distribuição de estrelas (5 a 1)
    quality_scores_json = db.Column(db.Text, nullable=True)           # Notas por características da loja

    # Faturamento, Receita e Ticket Médio (Billing API & Orders)
    total_revenue = db.Column(db.Float, default=0.0)                  # Faturamento Bruto Acumulado (R$)
    avg_ticket = db.Column(db.Float, default=0.0)                     # Ticket Médio por Venda (R$)
    billing_summary_json = db.Column(db.Text, nullable=True)          # Resumo de faturamento, comissões e encargos

    # Relatório de Saúde & Desempenho (Health & Performance)
    health_score = db.Column(db.Integer, default=100)                 # Score geral 0 a 100
    ai_health_report_json = db.Column(db.Text, nullable=True)         # Parecer Estratégico com IA (GPT-4o)
    ai_report_generated_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # JSON bruto de resposta da API
    raw_reputation_json = db.Column(db.Text, nullable=True)

    # Tokens de autenticação OAuth (opcional para vendedores autenticados)
    access_token = db.Column(db.Text, nullable=True)
    refresh_token = db.Column(db.Text, nullable=True)
    token_expires_at = db.Column(db.DateTime(timezone=True), nullable=True)

    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=default_brt_now)
    updated_at = db.Column(db.DateTime(timezone=True), default=default_brt_now, onupdate=default_brt_now)
    last_sync_at = db.Column(db.DateTime(timezone=True), nullable=True)

    __table_args__ = (
        db.UniqueConstraint("user_id", "seller_id", name="uq_user_ml_seller"),
    )

    items = relationship("MercadoLivreItem", backref="account", lazy="dynamic", cascade="all, delete-orphan")
    alerts = relationship("MercadoLivreAlert", backref="account", lazy="dynamic", cascade="all, delete-orphan")

    def get_reputation_info(self) -> dict:
        """Calcula diagnóstico interpretado do termômetro e margem de segurança."""
        level_map = {
            "5_green": {"nome": "Verde Escuro (Líder)", "cor": "#00a650", "status": "Excelente", "rank": 5},
            "4_light_green": {"nome": "Verde Claro", "cor": "#39b54a", "status": "Bom", "rank": 4},
            "3_yellow": {"nome": "Amarelo (Atenção)", "cor": "#ffb700", "status": "Atenção", "rank": 3},
            "2_orange": {"nome": "Laranja (Risco)", "cor": "#ff7733", "status": "Risco", "rank": 2},
            "1_red": {"nome": "Vermelho (Crítico)", "cor": "#f04449", "status": "Crítico", "rank": 1},
        }
        
        is_new_or_buyer = (self.completed_transactions or 0) == 0 and not self.power_seller_status and (not self.level_id or self.level_id in ["none", "null", "sem_reputacao"])
        
        if is_new_or_buyer:
            level_data = {"nome": "Sem Termômetro Ativo", "cor": "#64748b", "status": "Sem Vendas", "rank": 0}
        else:
            level_data = level_map.get(self.level_id or "5_green", level_map["5_green"])

        medal_map = {
            "platinum": {"nome": "MercadoLíder Platinum", "badge": "Platinum", "cor": "#708090", "icon": "bi-gem"},
            "gold": {"nome": "MercadoLíder Gold", "badge": "Gold", "cor": "#d4af37", "icon": "bi-trophy-fill"},
            "silver": {"nome": "MercadoLíder Silver", "badge": "Silver", "cor": "#a8a8a8", "icon": "bi-award-fill"},
        }
        medal_data = medal_map.get((self.power_seller_status or "").lower(), None)

        claims_pct = (self.claims_rate or 0.0) * 100
        delay_pct = (self.delayed_rate or 0.0) * 100
        cancel_pct = (self.cancellations_rate or 0.0) * 100

        # Margens oficiais do Mercado Livre Brasil (MLB):
        # Reclamações (Claims): Green <= 2.0%, Yellow <= 4.5%, Orange <= 8.0%, Red > 8.0%
        claims_risk = "danger" if claims_pct > 2.0 else ("warning" if claims_pct > 1.0 else "success")
        
        # Atrasos de Envio (Delayed Handling Time): Green <= 10.0%, Yellow <= 18.0%, Orange <= 22.0%, Red > 22.0%
        delay_risk = "danger" if delay_pct > 10.0 else ("warning" if delay_pct > 6.0 else "success")
        
        # Cancelamentos pelo Vendedor (Cancellations): Green <= 1.5%, Yellow <= 3.5%, Orange <= 4.0%, Red > 4.0%
        cancel_risk = "danger" if cancel_pct > 1.5 else ("warning" if cancel_pct > 0.5 else "success")

        return {
            "level": level_data,
            "medal": medal_data,
            "is_new_or_buyer": is_new_or_buyer,
            "claims_pct": round(claims_pct, 2),
            "delay_pct": round(delay_pct, 2),
            "cancel_pct": round(cancel_pct, 2),
            "claims_risk": claims_risk,
            "delay_risk": delay_risk,
            "cancel_risk": cancel_risk,
        }

    def get_recent_questions(self) -> list:
        """Retorna as perguntas recentes serializadas em lista."""
        if not self.recent_questions_json:
            return []
        try:
            return json.loads(self.recent_questions_json)
        except Exception:
            return []

    def get_rating_breakdown(self) -> dict:
        """Retorna a distribuição global de estrelas da conta."""
        if not self.rating_breakdown_json:
            return {"5": 0, "4": 0, "3": 0, "2": 0, "1": 0}
        try:
            return json.loads(self.rating_breakdown_json)
        except Exception:
            return {"5": 0, "4": 0, "3": 0, "2": 0, "1": 0}

    def get_ai_health_report(self) -> dict | None:
        """Retorna o relatório de saúde por IA em dicionário."""
        if not self.ai_health_report_json:
            return None
        try:
            return json.loads(self.ai_health_report_json)
        except Exception:
            return None

    def get_billing_summary(self) -> dict:
        """Retorna o resumo estruturado de faturamento e encargos."""
        if not self.billing_summary_json:
            return {
                "total_revenue": self.total_revenue or 0.0,
                "avg_ticket": self.avg_ticket or 0.0,
                "periods": [],
                "charges": [],
                "bonuses": []
            }
        try:
            return json.loads(self.billing_summary_json)
        except Exception:
            return {
                "total_revenue": self.total_revenue or 0.0,
                "avg_ticket": self.avg_ticket or 0.0,
                "periods": [],
                "charges": [],
                "bonuses": []
            }

    def calculate_account_health(self) -> dict:
        """
        Calcula o diagnóstico consolidado de Saúde e Desempenho da Conta nos 4 Pilares.
        """
        reputation = self.get_reputation_info()
        level_rank = reputation["level"]["rank"]

        # Se for conta sem vendas ativas / perfil novo
        if reputation.get("is_new_or_buyer"):
            return {
                "overall_score": 100,
                "badge": {"label": "Conta Sem Histórico de Vendas", "cor": "secondary", "icon": "bi-person-badge"},
                "reputation": reputation,
                "pillars": {
                    "logistics": {
                        "score": 100,
                        "on_time_pct": 100.0,
                        "delay_pct": 0.0,
                        "ceiling_pct": 15.0,
                        "risk": "success",
                        "status": "Sem Envios"
                    },
                    "quality": {
                        "score": 100,
                        "claims_pct": 0.0,
                        "ceiling_pct": 3.0,
                        "risk": "success",
                        "status": "Sem Reclamações"
                    },
                    "service": {
                        "score": 100,
                        "avg_time_min": 0.0,
                        "response_rate_pct": 100.0,
                        "unanswered_count": 0,
                        "total_count": 0,
                        "status": "0 Perguntas"
                    },
                    "operation": {
                        "score": 100,
                        "cancel_pct": 0.0,
                        "ceiling_pct": 2.5,
                        "risk": "success",
                        "status": "Sem Cancelamentos"
                    }
                },
                "store_ratings": {
                    "average": 0.0,
                    "total_reviews": 0,
                    "breakdown": {"5": 0, "4": 0, "3": 0, "2": 0, "1": 0},
                    "positive_pct": 100.0
                }
            }

        # 1. Pilar Logística (0 a 100) - Teto atraso 15%
        delay_pct = reputation["delay_pct"]
        on_time_pct = max(0.0, min(100.0, 100.0 - delay_pct))
        logistics_score = max(0, int(100 - (delay_pct / 15.0) * 100)) if delay_pct <= 15.0 else 0

        # 2. Pilar Qualidade / Reclamações (0 a 100) - Teto claims 3%
        claims_pct = reputation["claims_pct"]
        quality_score = max(0, int(100 - (claims_pct / 3.0) * 100)) if claims_pct <= 3.0 else 0

        # 3. Pilar Operação / Cancelamentos (0 a 100) - Teto cancelamentos 2.5%
        cancel_pct = reputation["cancel_pct"]
        operation_score = max(0, int(100 - (cancel_pct / 2.5) * 100)) if cancel_pct <= 2.5 else 0

        # 4. Pilar Atendimento / Perguntas (0 a 100)
        resp_time = self.avg_response_time_minutes or 0.0
        if resp_time == 0:
            resp_score = 100
        elif resp_time <= 15:
            resp_score = 100
        elif resp_time <= 60:
            resp_score = 85
        elif resp_time <= 240:
            resp_score = 65
        else:
            resp_score = 45

        resp_rate_pct = (self.questions_response_rate or 1.0) * 100
        service_score = int((resp_score * 0.6) + (resp_rate_pct * 0.4))

        # Score de Termômetro (0 a 100)
        term_score = max(20, level_rank * 20)

        # Score Global Ponderado (0 a 100)
        overall_health = int(
            (term_score * 0.35) +
            (logistics_score * 0.20) +
            (quality_score * 0.20) +
            (operation_score * 0.15) +
            (service_score * 0.10)
        )
        overall_health = max(0, min(100, overall_health))

        # Classificação de Saúde
        if overall_health >= 90:
            health_badge = {"label": "Excelente", "cor": "success", "icon": "bi-shield-check"}
        elif overall_health >= 75:
            health_badge = {"label": "Boa", "cor": "info", "icon": "bi-check-circle"}
        elif overall_health >= 60:
            health_badge = {"label": "Atenção", "cor": "warning", "icon": "bi-exclamation-triangle"}
        else:
            health_badge = {"label": "Crítica / Risco", "cor": "danger", "icon": "bi-x-octagon"}

        return {
            "overall_score": overall_health,
            "badge": health_badge,
            "reputation": reputation,
            "pillars": {
                "logistics": {
                    "score": logistics_score,
                    "on_time_pct": round(on_time_pct, 1),
                    "delay_pct": delay_pct,
                    "ceiling_pct": 15.0,
                    "risk": reputation["delay_risk"],
                    "status": "No Prazo" if delay_pct < 10.0 else ("Atenção" if delay_pct < 13.5 else "Crítico")
                },
                "quality": {
                    "score": quality_score,
                    "claims_pct": claims_pct,
                    "ceiling_pct": 3.0,
                    "risk": reputation["claims_risk"],
                    "status": "Excelente" if claims_pct < 2.0 else ("Atenção" if claims_pct < 2.8 else "Crítico")
                },
                "service": {
                    "score": service_score,
                    "avg_time_min": round(self.avg_response_time_minutes or 0.0, 1),
                    "response_rate_pct": round(resp_rate_pct, 1),
                    "unanswered_count": self.unanswered_questions or 0,
                    "total_count": self.total_questions or 0,
                    "status": "Rápido" if (self.avg_response_time_minutes or 0) <= 20 else "Lento"
                },
                "operation": {
                    "score": operation_score,
                    "cancel_pct": cancel_pct,
                    "ceiling_pct": 2.5,
                    "risk": reputation["cancel_risk"],
                    "status": "Excelente" if cancel_pct < 1.5 else ("Atenção" if cancel_pct < 2.0 else "Crítico")
                }
            },
            "store_ratings": {
                "average": self.store_rating_average or 0.0,
                "total_reviews": self.total_store_reviews or 0,
                "breakdown": self.get_rating_breakdown(),
                "positive_pct": round((self.positive_rating_pct or 1.0) * 100, 1)
            }
        }

        return {
            "overall_score": overall_health,
            "badge": health_badge,
            "reputation": reputation,
            "pillars": {
                "logistics": {
                    "score": logistics_score,
                    "on_time_pct": round(on_time_pct, 1),
                    "delay_pct": delay_pct,
                    "ceiling_pct": 15.0,
                    "risk": reputation["delay_risk"],
                    "status": "No Prazo" if delay_pct < 10.0 else ("Atenção" if delay_pct < 13.5 else "Crítico")
                },
                "quality": {
                    "score": quality_score,
                    "claims_pct": claims_pct,
                    "ceiling_pct": 3.0,
                    "risk": reputation["claims_risk"],
                    "status": "Excelente" if claims_pct < 2.0 else ("Atenção" if claims_pct < 2.8 else "Crítico")
                },
                "operation": {
                    "score": operation_score,
                    "cancel_pct": cancel_pct,
                    "ceiling_pct": 2.5,
                    "risk": reputation["cancel_risk"],
                    "status": "Seguro" if cancel_pct < 1.5 else ("Atenção" if cancel_pct < 2.0 else "Crítico")
                },
                "service": {
                    "score": service_score,
                    "avg_response_minutes": round(resp_time, 0),
                    "response_rate_pct": round(resp_rate_pct, 1),
                    "unanswered": self.unanswered_questions or 0,
                    "total_questions": self.total_questions or 0,
                    "status": "Rápido" if resp_time <= 30 else ("Médio" if resp_time <= 120 else "Lento")
                }
            },
            "store_ratings": {
                "rating_average": round(self.store_rating_average or 0.0, 1),
                "total_reviews": self.total_store_reviews or 0,
                "breakdown": self.get_rating_breakdown(),
                "positive_pct": round((self.positive_rating_pct or 1.0) * 100, 1),
                "neutral_pct": round((self.neutral_rating_pct or 0.0) * 100, 1),
                "negative_pct": round((self.negative_rating_pct or 0.0) * 100, 1)
            }
        }


class MercadoLivreItem(db.Model):
    __tablename__ = "mercadolivre_items"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("mercadolivre_accounts.id"), index=True, nullable=False)

    item_id = db.Column(db.String(100), nullable=False, index=True)   # ex: "MLB1234567890"
    title = db.Column(db.String(500), nullable=False)
    price = db.Column(db.Float, default=0.0)
    currency_id = db.Column(db.String(10), default="BRL")
    thumbnail = db.Column(db.String(512), nullable=True)
    permalink = db.Column(db.String(512), nullable=True)

    # Avaliações do Produto
    rating_average = db.Column(db.Float, default=0.0)
    total_reviews = db.Column(db.Integer, default=0)
    levels_distribution = db.Column(db.Text, nullable=True)  # JSON com contagem de 1, 2, 3, 4, 5 estrelas

    # Dossiê de IA (OpenAI GPT-4o / Gemini)
    ai_summary_json = db.Column(db.Text, nullable=True)
    ai_last_analyzed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), default=default_brt_now)

    def get_ai_dossier(self) -> dict | None:
        """Retorna o Dossiê Estratégico decodificado em JSON."""
        if not self.ai_summary_json:
            return None
        try:
            return json.loads(self.ai_summary_json)
        except Exception:
            return None

    def get_distribution(self) -> dict:
        """Retorna distribuição de estrelas 1 a 5."""
        if not self.levels_distribution:
            return {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}
        try:
            return json.loads(self.levels_distribution)
        except Exception:
            return {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}


class MercadoLivreAlert(db.Model):
    __tablename__ = "mercadolivre_alerts"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("mercadolivre_accounts.id"), index=True, nullable=False)

    tipo = db.Column(db.String(50), nullable=False)  # claims_risk, delay_risk, cancellation_risk, reputation_drop, questions_delay
    titulo = db.Column(db.String(255), nullable=False)
    mensagem = db.Column(db.Text, nullable=False)
    nivel = db.Column(db.String(20), default="warning")  # danger, warning, info, success
    lido = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime(timezone=True), default=default_brt_now)
