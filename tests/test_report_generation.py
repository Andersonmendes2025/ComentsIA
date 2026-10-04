import io
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image
from pypdf import PdfReader

import relatorio


def sample():
    return [{"data": "2026-09-01", "nota": n, "texto": "Atendimento observado no teste.",
             "respondida": n > 2} for n in [1, 2, 3, 4, 5]]


@pytest.mark.parametrize("data", [[], sample(), sample() * 1000])
def test_chart_has_bounded_print_resolution(tmp_path, data):
    report = relatorio.RelatorioAvaliacoes(data)
    path = report.gerar_painel_graficos_executivos(str(tmp_path))
    with Image.open(path) as image:
        assert image.format == "JPEG"
        assert image.mode == "RGB"
        assert 2125 <= image.width <= 2126
        assert 826 <= image.height <= 827
        assert image.info["dpi"] == (300, 300)


@pytest.mark.parametrize("failure", [False, True, "empty"])
def test_complete_pdf_and_ai_fallback(monkeypatch, failure):
    client = Mock()
    create = client.chat.completions.create
    if failure is True:
        create.side_effect = TimeoutError("synthetic timeout")
    else:
        text = "" if failure == "empty" else "RESUMO EXECUTIVO\nAnalise de teste.\nSegundo paragrafo de teste."
        create.return_value = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])
    factory = Mock(return_value=client)
    monkeypatch.setattr(relatorio, "OpenAI", factory)
    report = relatorio.RelatorioAvaliacoes(sample())
    buffer = io.BytesIO()
    report.gerar_pdf(buffer)
    assert buffer.read(5) == b"%PDF-"
    buffer.seek(0)
    text = " ".join(" ".join(page.extract_text() for page in PdfReader(buffer).pages).split())
    assert "3.00 / 5.0" in text
    assert "60.0%" in text
    if failure:
        assert "temporariamente indisponivel" in text
        assert "nenhuma conclusao qualitativa foi inferida" in text
    else:
        assert "Segundo paragrafo" in text
    assert factory.call_args.kwargs["max_retries"] == 0
    assert create.call_args.kwargs["timeout"] == 40
    assert create.call_count == 1
    client.close.assert_called_once()


def test_figure_released_on_save_error(monkeypatch, tmp_path):
    figure = relatorio.Figure(figsize=(180 / 25.4, 70 / 25.4))
    monkeypatch.setattr(relatorio, "Figure", lambda **kwargs: figure)
    monkeypatch.setattr(figure, "savefig", Mock(side_effect=OSError("disk failure")))
    with pytest.raises(OSError):
        relatorio.RelatorioAvaliacoes(sample()).gerar_painel_graficos_executivos(str(tmp_path))
    assert not figure.axes

