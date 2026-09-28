import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from services.ai_service import build_relevant_context


def completion(text):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


def selector(response):
    client = MagicMock()
    client.with_options.return_value.chat.completions.create.return_value = completion(response)
    return client


def test_keeps_selected_local_and_global_facts_only():
    client = selector('{"indices": [0, 2]}')
    result = build_relevant_context(
        client, "Gostei do estacionamento e da acessibilidade.",
        "Estacionamento gratuito. Música ao vivo às sextas.",
        global_context="Todas as unidades têm rampa de acesso.",
    )
    assert "Estacionamento gratuito" in result
    assert "rampa de acesso" in result
    assert "Música ao vivo" not in result
    payload = json.loads(client.with_options.return_value.chat.completions.create.call_args.kwargs['messages'][1]['content'])
    assert payload['trechos'][0]['origem'] == 'ficha'
    assert payload['trechos'][2]['origem'] == 'conta'


@pytest.mark.parametrize('response', ['{"indices": []}', '{"indices": [99]}',
                                     '{"indices": [-1]}', '{"indices": [true]}',
                                     '{"indices": "0"}', 'texto inválido',
                                     '{"indices": [0, 0, 0]}'])
def test_omits_context_on_empty_or_invalid_selection(response):
    assert build_relevant_context(selector(response), 'Muito bom!', 'Temos piscina.') == ''


def test_empty_review_does_not_call_selector():
    client = selector('{}')
    assert build_relevant_context(client, '', 'Temos piscina.') == ''
    client.with_options.assert_not_called()


def test_failure_does_not_block_reply_or_leak_context():
    client = selector('{}')
    client.with_options.side_effect = TimeoutError()
    assert build_relevant_context(client, 'Equipe educada.', 'Temos piscina.') == ''


def test_global_context_is_available_without_local_context():
    client = selector('{"indices": [0]}')
    result = build_relevant_context(client, 'Gostei da piscina.', '', global_context='Piscina aquecida.')
    assert 'Piscina aquecida' in result
    assert 'conta' in result


def test_ifood_passes_local_and_account_context_to_selection(monkeypatch):
    import main
    from ifood_auto import generate_ifood_ai_reply

    client = MagicMock()
    calls = client.with_options.return_value.chat.completions.create
    calls.side_effect = [completion('{"indices": [1]}'), completion('Obrigado pelo elogio à embalagem!')]
    monkeypatch.setattr(main, 'client', client)
    monkeypatch.setattr(main, 'get_user_settings', lambda _: {'contexto_personalizado': 'Embalagens recicláveis.'})
    merchant = SimpleNamespace(user_id='test', name='Loja', default_greeting='', default_closing='',
                               contexto_personalizado='Música ao vivo.', tone='profissional', idioma_resposta='pt')
    result = generate_ifood_ai_reply(merchant, 5, 'A embalagem é ótima.', 'Ana')
    assert 'embalagem' in result
    assert 'Embalagens recicláveis' in calls.call_args.kwargs['messages'][1]['content']
    assert 'Música ao vivo' not in calls.call_args.kwargs['messages'][1]['content']


@pytest.mark.parametrize('stars', [4, 5])
def test_google_positive_review_uses_old_prompt_without_context(monkeypatch, stars):
    import main
    from google_auto import _generate_reply_for

    client = MagicMock()
    calls = client.with_options.return_value.chat.completions.create
    calls.return_value = completion('Obrigado por elogiar o acesso!')
    monkeypatch.setattr(main, 'client', client)
    monkeypatch.setattr(main, 'get_user_settings', lambda _: {'contexto_personalizado': 'Música ao vivo às sextas.'})
    location = SimpleNamespace(contexto_personalizado='Entrada com rampa de acesso.')
    result = _generate_reply_for('test', stars, 'Acesso fácil.', 'Ana', False, location)
    assert result == 'Obrigado por elogiar o acesso!'
    assert calls.call_count == 1
    prompt = calls.call_args.kwargs['messages'][1]['content']
    assert 'Música ao vivo' not in prompt
    assert 'rampa de acesso' not in prompt
    assert 'TAMANHO: Escreva de 3 a 5 frases focadas e humanizadas' in prompt


def test_google_negative_review_uses_old_prompt_with_local_context(monkeypatch):
    import main
    from google_auto import _generate_reply_for

    client = MagicMock()
    calls = client.with_options.return_value.chat.completions.create
    calls.return_value = completion('Sentimos muito pelo problema de acesso.')
    monkeypatch.setattr(main, 'client', client)
    monkeypatch.setattr(main, 'get_user_settings', lambda _: {'contexto_personalizado': 'Música ao vivo às sextas.'})
    location = SimpleNamespace(contexto_personalizado='Entrada com rampa de acesso.')
    result = _generate_reply_for('test', 2, 'A entrada estava bloqueada.', 'Ana', False, location)
    assert result == 'Sentimos muito pelo problema de acesso.'
    prompt = calls.call_args.kwargs['messages'][1]['content']
    assert 'Entrada com rampa de acesso' in prompt
    assert 'Música ao vivo' not in prompt
    assert 'somente se couber naturalmente' in prompt
    assert 'TAMANHO: Escreva de 3 a 5 frases focadas e humanizadas' in prompt
    assert calls.call_count == 1


def test_google_negative_review_uses_account_context_without_local_context(monkeypatch):
    import main
    from google_auto import _generate_reply_for

    client = MagicMock()
    calls = client.with_options.return_value.chat.completions.create
    calls.return_value = completion('Sentimos muito pelo problema.')
    monkeypatch.setattr(main, 'client', client)
    monkeypatch.setattr(main, 'get_user_settings', lambda _: {'contexto_personalizado': 'A entrada possui rampa.'})
    _generate_reply_for('test', 1, 'A entrada estava bloqueada.', 'Ana', False)
    assert 'A entrada possui rampa.' in calls.call_args.kwargs['messages'][1]['content']
