# -*- coding: utf-8 -*-
from unittest.mock import patch, MagicMock
from services.ai_service import generate_claude_response


def test_generate_claude_response_no_key():
    """Testa se a função lida adequadamente quando a chave não está configurada."""
    with patch.dict("os.environ", {}, clear=True):
        res = generate_claude_response("Olá", api_key=None)
        assert res is None


@patch("anthropic.Anthropic")
def test_generate_claude_response_success(mock_anthropic_class):
    """Testa geração de resposta com sucesso mockando a API da Anthropic."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_block = MagicMock()
    mock_block.text = "Esta é uma resposta de teste gerada pelo Claude."
    mock_response.content = [mock_block]
    mock_client.messages.create.return_value = mock_response
    mock_anthropic_class.return_value = mock_client

    res = generate_claude_response(
        prompt="Analise este comentário",
        system_prompt="Você é um assistente",
        api_key="fake-anthropic-key"
    )

    assert res == "Esta é uma resposta de teste gerada pelo Claude."
    mock_anthropic_class.assert_called_once_with(api_key="fake-anthropic-key")
    mock_client.messages.create.assert_called_once()
