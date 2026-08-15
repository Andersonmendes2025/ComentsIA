import json
import pytest
from unittest.mock import patch, MagicMock
import os
from flask import Flask

# Ajusta o PYTHONPATH para que a pasta pai seja reconhecida
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app as flask_app
from models import db, User, UserSettings

@pytest.fixture
def client():
    flask_app.config['TESTING'] = True
    flask_app.config['WTF_CSRF_ENABLED'] = False
    
    with flask_app.test_client() as client:
        with flask_app.app_context():
            yield client

def test_ajuda_page_loads(client):
    """Verifica se a página da Central de Ajuda carrega corretamente e exibe as categorias."""
    response = client.get('/ajuda')
    assert response.status_code == 200
    html = response.data.decode('utf-8')
    assert 'Como podemos ajudar?' in html
    assert 'Primeiro Acesso' in html
    assert 'Google Business' in html
    assert 'Chat Inteligente' in html

@patch('routes_ajuda.genai.GenerativeModel')
@patch('routes_ajuda.os.getenv')
def test_support_chat_gemini_response(mock_getenv, mock_model, client):
    """Testa se o chat responde corretamente via mock do Gemini (sem function call)."""
    # Garante que temos uma API KEY fake
    mock_getenv.return_value = "fake_api_key"
    
    # Prepara o Mock do Gemini
    mock_chat = MagicMock()
    mock_model.return_value.start_chat.return_value = mock_chat
    
    # Prepara a resposta Fake
    mock_response = MagicMock()
    mock_part = MagicMock()
    mock_part.text = "Olá! Como posso ajudar você hoje?"
    mock_part.function_call = None
    mock_candidate = MagicMock()
    mock_candidate.content.parts = [mock_part]
    mock_response.candidates = [mock_candidate]
    mock_chat.send_message.return_value = mock_response

    # Dispara a requisição
    payload = {"messages": [{"role": "user", "content": "Olá IA"}]}
    response = client.post('/api/support-chat', json=payload)
    
    assert response.status_code == 200
    data = response.get_json()
    assert data['reply'] == "Olá! Como posso ajudar você hoje?"
    assert data['function_called'] is False
    assert data['protocolo'] is None

@patch('routes_ajuda.genai.GenerativeModel')
@patch('routes_ajuda.os.getenv')
@patch('services.email_service.enviar_email')
def test_support_chat_opens_ticket(mock_enviar_email, mock_getenv, mock_model, client):
    """Testa se o function calling abre um chamado enviando e-mail."""
    # Garante API key
    mock_getenv.side_effect = lambda k, default=None: "fake_api_key" if k == "GEMINI_API_KEY" else "suporte@comentsia.com.br"
    
    # Prepara o Mock do Gemini
    mock_chat = MagicMock()
    mock_model.return_value.start_chat.return_value = mock_chat
    
    # Prepara o Mock da Function Call
    mock_response = MagicMock()
    mock_part = MagicMock()
    mock_part.text = "Abri o chamado para você."
    mock_fc = MagicMock()
    mock_fc.name = "abrir_chamado_suporte"
    mock_fc.args = {"assunto": "Problema X", "descricao": "Detalhes Y"}
    mock_part.function_call = mock_fc
    
    mock_candidate = MagicMock()
    mock_candidate.content.parts = [mock_part]
    mock_response.candidates = [mock_candidate]
    mock_chat.send_message.return_value = mock_response

    # Dispara a requisição
    payload = {"messages": [{"role": "user", "content": "Quero falar com humano"}]}
    response = client.post('/api/support-chat', json=payload)
    
    assert response.status_code == 200
    data = response.get_json()
    
    # Verifica a resposta HTTP
    assert data['function_called'] is True
    assert data['protocolo'] is not None
    assert data['protocolo'].startswith('CSUP-')
    
    # Verifica se a função interna de enviar e-mail foi chamada
    assert mock_enviar_email.call_count >= 1
    chamadas = [call[0] for call in mock_enviar_email.call_args_list]
    destinatarios = [c[0] for c in chamadas]
    assert any("suporte@comentsia.com.br" in d for d in destinatarios)
    assunto_chamada = chamadas[0][1]
    assert data['protocolo'] in assunto_chamada
