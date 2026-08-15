import pytest
from unittest.mock import patch, MagicMock
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app as flask_app
from models import db, User, UserSettings, Company, Ticket, PlanPrice, AppNotification
from admin import get_plan_prices

@pytest.fixture
def client():
    flask_app.config['TESTING'] = True
    flask_app.config['WTF_CSRF_ENABLED'] = False
    
    with flask_app.test_client() as client:
        with flask_app.app_context():
            # Cria empresa e usuário admin para os testes
            admin_email = "anderson.mendesdossantos011@gmail.com"
            user = db.session.get(User, admin_email)
            if not user:
                user = User(id=admin_email, email=admin_email, nome="Admin Anderson")
                db.session.add(user)

            company = Company.query.filter_by(owner_user_id=admin_email).first()
            if not company:
                company = Company(owner_user_id=admin_email, name="ComentsIA Admin Co")
                db.session.add(company)

            user_settings = UserSettings.query.filter_by(user_id=admin_email).first()
            if not user_settings:
                user_settings = UserSettings(user_id=admin_email, plano="business")
                db.session.add(user_settings)

            # Limpa tickets e notificações de testes anteriores
            Ticket.query.filter(Ticket.assunto.like("%Teste Automatizado%")).delete()
            AppNotification.query.filter_by(user_id=admin_email).delete()

            db.session.commit()

            # Simula sessão logada como Admin
            with client.session_transaction() as sess:
                sess['user_info'] = {'id': admin_email, 'email': admin_email, 'name': 'Admin Anderson'}

            yield client

def test_admin_pricing_get_and_post(client):
    """Testa leitura e atualização de preços de planos no Admin."""
    # 1. GET Pricing
    res = client.get('/admin/pricing')
    assert res.status_code == 200
    assert "Catálogo & Precificação" in res.data.decode('utf-8')

    # 2. POST Pricing alterando Pro para 59.90 e Business para 89.90
    post_data = {
        'free_cents': '0',
        'pro_reais': '59,90',
        'pro_anual_reais': '599,00',
        'business_reais': '89,90',
        'business_anual_reais': '899,00',
    }
    res_post = client.post('/admin/pricing', data=post_data, follow_redirects=True)
    assert res_post.status_code == 200
    assert "Tabela oficial de preços atualizada com sucesso!" in res_post.data.decode('utf-8')

    # Verifica no banco / cache
    prices = get_plan_prices()
    assert prices['pro']['price_cents'] == 5990
    assert prices['business']['price_cents'] == 8990

    # Restaura para valores padrão
    client.post('/admin/pricing', data={
        'free_cents': '0',
        'pro_cents': '4999',
        'pro_anual_cents': '49900',
        'business_cents': '7999',
        'business_anual_cents': '79900',
    })

def test_admin_tickets_crud_and_move(client):
    """Testa criação e movimentação de status no Kanban de tickets."""
    # 1. GET Tickets board
    res = client.get('/admin/tickets')
    assert res.status_code == 200
    assert "Central de Chamados" in res.data.decode('utf-8')

    # 2. Criar novo ticket
    company = Company.query.first()
    res_create = client.post('/admin/tickets', data={
        'company_id': str(company.id),
        'assunto': 'Teste Automatizado de Chamado 123',
        'prioridade': 'alta',
        'status': 'aberto'
    }, follow_redirects=True)
    assert res_create.status_code == 200

    ticket = Ticket.query.filter_by(assunto='Teste Automatizado de Chamado 123').order_by(Ticket.id.desc()).first()
    assert ticket is not None
    assert ticket.status == 'aberto'

    # 3. Mover para pendente
    res_move1 = client.post(f'/admin/tickets/{ticket.id}/move', data={'status': 'pendente'}, follow_redirects=True)
    assert res_move1.status_code == 200
    db.session.refresh(ticket)
    assert ticket.status == 'pendente'

    # 4. Mover para resolvido
    res_move2 = client.post(f'/admin/tickets/{ticket.id}/move', data={'status': 'resolvido'}, follow_redirects=True)
    assert res_move2.status_code == 200
    db.session.refresh(ticket)
    assert ticket.status == 'resolvido'

@patch('admin.enviar_email')
def test_admin_broadcast_email_and_inapp(mock_enviar_email, client):
    """Testa envio de comunicação em massa (broadcast) tanto via e-mail quanto via notificação in-app."""
    # 1. GET Broadcast page
    res = client.get('/admin/broadcast')
    assert res.status_code == 200
    assert "Comunicação em Massa" in res.data.decode('utf-8')

    # 2. POST Broadcast via Email
    payload_email = {
        'subject': 'Aviso de Manutenção Programada',
        'html': '<p>Olá {{nome_usuario}}, informamos que o sistema passará por manutenção.</p>',
        'segment': 'all',
        'channel': 'email'
    }
    res_post_email = client.post('/admin/broadcast', data=payload_email, follow_redirects=True)
    assert res_post_email.status_code == 200
    assert "E-mail enviado com sucesso" in res_post_email.data.decode('utf-8')
    assert mock_enviar_email.call_count >= 1

    # 3. POST Broadcast via Notificação In-App
    mock_enviar_email.reset_mock()
    payload_inapp = {
        'subject': 'Nova Funcionalidade no Painel',
        'html': '<p>Confira agora a nova Central de Chamados e Notificações.</p>',
        'segment': 'all',
        'channel': 'inapp'
    }
    res_post_inapp = client.post('/admin/broadcast', data=payload_inapp, follow_redirects=True)
    assert res_post_inapp.status_code == 200
    assert "Notificação in-app enviada com sucesso" in res_post_inapp.data.decode('utf-8')
    # Garante que NÃO disparou e-mail quando o canal foi apenas inapp
    assert mock_enviar_email.call_count == 0

    # Verifica se a notificação foi gravada no banco
    admin_email = "anderson.mendesdossantos011@gmail.com"
    notif = AppNotification.query.filter_by(user_id=admin_email, titulo='Nova Funcionalidade no Painel').first()
    assert notif is not None
    assert notif.is_read is False

    # 4. Testa marcar notificações como lidas
    res_marcar = client.post('/api/notificacoes/marcar-lidas')
    assert res_marcar.status_code == 200
    assert res_marcar.get_json()['success'] is True
    db.session.refresh(notif)
    assert notif.is_read is True
