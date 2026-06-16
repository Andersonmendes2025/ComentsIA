from datetime import datetime
import json
from models import db, default_brt_now

class PesquisaConfig(db.Model):
    """
    Representa o formulário de pesquisa criado (Pode ter vários por empresa).
    """
    __tablename__ = "pesquisa_configs"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), index=True)
    titulo = db.Column(db.String(255), default="Sua opinião é muito importante para nós!")
    subtitulo = db.Column(db.Text, default="Leve menos de 1 minuto para responder.")
    slug = db.Column(db.String(100), unique=True, index=True)
    
    # Redirecionamento Estratégico do SaaS (Opcional, baseado em uma pergunta de nota geral)
    link_google_feedback = db.Column(db.String(512), nullable=True)
    redirecionar_positivo_auto = db.Column(db.Boolean, default=False)
    
    # 🚀 NOVA COLUNA ADICIONADA: Guarda qual é a pergunta que vai servir de gatilho para o Google
    pergunta_gatilho_id = db.Column(db.Integer, nullable=True)
    
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=default_brt_now)

    # Relacionamentos
    perguntas = db.relationship("PesquisaPergunta", backref="pesquisa", lazy="joined", cascade="all, delete-orphan", order_by="PesquisaPergunta.ordem")
    envios = db.relationship("PesquisaEnvio", backref="pesquisa", lazy="dynamic", cascade="all, delete-orphan")


class PesquisaPergunta(db.Model):
    """
    Perguntas dinâmicas adicionadas no estilo Google Forms.
    """
    __tablename__ = "pesquisa_perguntas"

    id = db.Column(db.Integer, primary_key=True)
    pesquisa_config_id = db.Column(db.Integer, db.ForeignKey("pesquisa_configs.id"), index=True)
    
    texto_pergunta = db.Column(db.String(255), nullable=False)
    tipo_resposta = db.Column(db.String(32), nullable=False) # 'texto' | 'multipla_escolha' | 'estrelas'
    is_obrigatoria = db.Column(db.Boolean, default=False)
    ordem = db.Column(db.Integer, default=0)
    
    # Opções guardadas em JSON text caso seja múltipla escolha (ex: '["Ótimo", "Regular", "Ruim"]')
    opcoes_json = db.Column(db.Text, nullable=True)

    @property
    def opcoes(self):
        return json.loads(self.opcoes_json) if self.opcoes_json else []


class PesquisaEnvio(db.Model):
    """
    Guarda os dados do cabeçalho do respondente e cria o vínculo para as respostas.
    """
    __tablename__ = "pesquisa_envios"

    id = db.Column(db.Integer, primary_key=True)
    pesquisa_config_id = db.Column(db.Integer, db.ForeignKey("pesquisa_configs.id"), index=True)
    
    cliente_nome = db.Column(db.String(255), nullable=True)
    cliente_email = db.Column(db.String(255), nullable=True)
    cliente_whatsapp = db.Column(db.String(32), nullable=True)
    
    created_at = db.Column(db.DateTime(timezone=True), default=default_brt_now)
    respostas = db.relationship("PesquisaRespostaItem", backref="envio", lazy="selectin", cascade="all, delete-orphan")


class PesquisaRespostaItem(db.Model):
    """
    Guarda o valor de cada campo individual respondido pelo cliente.
    """
    __tablename__ = "pesquisa_respostas_itens"

    id = db.Column(db.Integer, primary_key=True)
    pesquisa_envio_id = db.Column(db.Integer, db.ForeignKey("pesquisa_envios.id"), index=True)
    pesquisa_pergunta_id = db.Column(db.Integer, db.ForeignKey("pesquisa_perguntas.id"), nullable=False)
    
    valor_resposta = db.Column(db.Text, nullable=False) # Guarda o texto digitado, a opção escolhida ou o número de estrelas
    pergunta = db.relationship("PesquisaPergunta", backref="respostas_itens", lazy="joined")