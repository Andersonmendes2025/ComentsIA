# -*- coding: utf-8 -*-
import io
import pytest
from datetime import datetime
from relatorio import RelatorioAvaliacoes, limpa_markdown


def test_relatorio_metricas_exatas():
    # Cria uma amostra controlada
    avaliacoes = [
        {"data": datetime(2026, 1, 15), "nota": 5, "texto": "Excelente atendimento!", "respondida": 1},
        {"data": datetime(2026, 1, 20), "nota": 5, "texto": "Muito bom", "respondida": 1},
        {"data": datetime(2026, 2, 10), "nota": 4, "texto": "Bom serviço", "respondida": 0},
        {"data": datetime(2026, 2, 15), "nota": 2, "texto": "Demorou um pouco", "respondida": 0},
    ]

    rel = RelatorioAvaliacoes(avaliacoes, nome_ficha="Filial Teste")
    
    assert rel.total_avaliacoes == 4
    # Média: (5+5+4+2)/4 = 16/4 = 4.00
    assert rel.media_oficial == 4.00
    assert rel.star_counts[5] == 2
    assert rel.star_counts[4] == 1
    assert rel.star_counts[2] == 1
    assert rel.star_counts[1] == 0
    assert rel.total_respondidas == 2
    assert rel.total_pendentes == 2
    assert rel.taxa_resposta == 50.0
    # NPS: Promotores(5+4=3/4=75%) - Detratores(2=1/4=25%) = +50
    assert rel.nps_score == 50


def test_limpa_markdown():
    raw = "### Título\n**Texto em negrito** e *itálico* com “aspas” e – travessão.\n- Item 1\n- Item 2"
    limpo = limpa_markdown(raw)
    assert "###" not in limpo
    assert "**" not in limpo
    assert "- Item 1" in limpo
    assert '"aspas"' in limpo


def test_gerar_pdf_sem_erros():
    avaliacoes = [
        {"data": datetime(2026, 1, 15), "nota": 5, "texto": "Ambiente limpo e organizado.", "respondida": 1},
        {"data": datetime(2026, 2, 10), "nota": 4, "texto": "Gostei do atendimento.", "respondida": 1},
    ]

    rel = RelatorioAvaliacoes(
        avaliacoes,
        settings={"business_name": "Empresa Teste", "manager_name": "Gestor Carlos"},
        nome_ficha="Loja Centro"
    )

    buffer = io.BytesIO()
    rel.gerar_pdf(buffer)
    buffer.seek(0)
    pdf_bytes = buffer.getvalue()

    assert len(pdf_bytes) > 1000
    assert pdf_bytes.startswith(b"%PDF")
