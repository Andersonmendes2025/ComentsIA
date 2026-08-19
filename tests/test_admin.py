import pytest
from unittest.mock import patch, MagicMock
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app as flask_app
from models import db, User, UserSettings, Company, Ticket, PlanPrice, AppNotification, EmailTemplate, Coupon
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


def test_admin_email_templates_crud(client):
    """Testa a pagina de Templates de E-mail (criar, editar, excluir)."""
    EmailTemplate.query.filter_by(key='teste_automatizado_tpl').delete()
    db.session.commit()

    # 1. GET lista (garante que o template admin_templates.html existe e renderiza)
    res = client.get('/admin/templates')
    assert res.status_code == 200
    assert "Templates de E-mail" in res.data.decode('utf-8')

    # 2. Criar
    res_create = client.post('/admin/templates', data={
        'action': 'create',
        'key': 'teste_automatizado_tpl',
        'subject': 'Assunto de Teste',
        'html': '<p>Ola {{nome_usuario}}</p>',
    }, follow_redirects=True)
    assert res_create.status_code == 200
    tpl = EmailTemplate.query.filter_by(key='teste_automatizado_tpl').first()
    assert tpl is not None
    assert tpl.subject == 'Assunto de Teste'

    # a listagem deve mostrar o conteudo literal (nao processado pelo Jinja)
    assert '{{nome_usuario}}' in res_create.data.decode('utf-8')

    # 3. Editar
    res_edit = client.post('/admin/templates', data={
        'action': 'edit',
        'template_id': tpl.id,
        'subject': 'Assunto Editado',
        'html': '<p>Editado {{nome_empresa}}</p>',
    }, follow_redirects=True)
    assert res_edit.status_code == 200
    db.session.refresh(tpl)
    assert tpl.subject == 'Assunto Editado'

    # 4. Excluir
    res_delete = client.post('/admin/templates', data={
        'action': 'delete',
        'template_id': tpl.id,
    }, follow_redirects=True)
    assert res_delete.status_code == 200
    assert EmailTemplate.query.filter_by(key='teste_automatizado_tpl').first() is None


def test_admin_coupon_edit_page_renders(client):
    """Garante que a pagina de edicao de cupom existe e processa o POST (regressao: faltava o template)."""
    Coupon.query.filter_by(code='TESTEAUTOMATIZADO').delete()
    db.session.commit()

    coupon = Coupon(code='TESTEAUTOMATIZADO', discount_type='percent', discount_value=10, active=True)
    db.session.add(coupon)
    db.session.commit()

    # GET precisa renderizar o formulario de edicao sem erro
    res_get = client.get(f'/admin/coupons/{coupon.id}/edit')
    assert res_get.status_code == 200
    assert 'TESTEAUTOMATIZADO' in res_get.data.decode('utf-8')

    # POST atualiza o cupom
    res_post = client.post(f'/admin/coupons/{coupon.id}/edit', data={
        'description': 'Cupom de teste automatizado',
        'discount_type': 'percent',
        'discount_value': '20',
        'max_uses': '0',
        'active': 'on',
    }, follow_redirects=True)
    assert res_post.status_code == 200
    db.session.refresh(coupon)
    assert coupon.discount_value == 20
    assert coupon.description == 'Cupom de teste automatizado'

    Coupon.query.filter_by(code='TESTEAUTOMATIZADO').delete()
    db.session.commit()


def test_admin_historical_pricing_requires_permission_and_redirects(client):
    """Regressao: essa rota nao tinha NENHUMA protecao de permissao antes."""
    res = client.get('/admin/pricing/historical', follow_redirects=False)
    # Com o admin logado (fixture), deve redirecionar pra /admin/pricing (nao mais 500)
    assert res.status_code == 302
    assert '/admin/pricing' in res.headers['Location']


def test_admin_payment_failed_webhook_removed():
    """Regressao de seguranca: essa rota publica sem autenticacao (nem verificacao de
    assinatura) permitia que qualquer pessoa disparasse e-mails reais de 'pagamento
    falhou' para qualquer user_id. Ela era redundante com o webhook assinado do
    Stripe em stripe_pay.py, entao foi removida."""
    with flask_app.test_client() as anon_client:
        res = anon_client.post('/admin/webhooks/payment_failed', json={'user_id': 'vitima@example.com'})
        assert res.status_code == 404
