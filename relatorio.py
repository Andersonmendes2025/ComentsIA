# -*- coding: utf-8 -*-
"""
Módulo de Geração de Relatórios Executivos de Avaliações - ComentsIA.
Combina auditoria estatística exata (zero contradições numéricas),
gráficos executivos de alta fidelidade visual (300 DPI) e inteligência estratégica com GPT-4o.
"""

import io
import os
import re
import tempfile
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytz
from fpdf import FPDF
from fpdf.enums import XPos, YPos
from openai import OpenAI
from PIL import Image


# ============================================================
# LIMPEZA E FORMATAÇÃO DE TEXTO PARA PDF
# ============================================================

def seguro_latin1(texto: str) -> str:
    if not isinstance(texto, str):
        return ""
    substituicoes = {
        "★": "*",
        "⭐": "*",
        "•": "-",
        "—": "-",
        "–": "-",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "…": "...",
        "📍": "",
        "🌐": "",
        "✨": "",
        "✅": "",
        "⚠️": "",
        "👔": "",
        "😊": "",
        "💛": "",
        "⚡": "",
    }
    for k, v in substituicoes.items():
        texto = texto.replace(k, v)
    return texto.encode("latin-1", "replace").decode("latin-1")


def limpa_markdown(texto: str) -> str:
    if not isinstance(texto, str):
        return ""

    # Remove formatações markdown indesejadas
    texto = re.sub(r"^\s*#+\s*", "", texto, flags=re.MULTILINE)
    texto = re.sub(r"\*\*([^*]+)\*\*", r"\1", texto)
    texto = re.sub(r"\*([^*]+)\*", r"\1", texto)
    texto = re.sub(r"^[\-\*]\s+", "- ", texto, flags=re.MULTILINE)
    texto = re.sub(r"^---+", "", texto, flags=re.MULTILINE)
    texto = re.sub(r"\n{3,}", "\n\n", texto)

    return seguro_latin1(texto.strip())


# ============================================================
# CLASSE PRINCIPAL DO RELATÓRIO EXECUTIVO
# ============================================================

class RelatorioAvaliacoes:
    def __init__(self, avaliacoes: List[Dict[str, Any]], media_atual: Optional[float] = None,
                 settings: Optional[Dict[str, Any]] = None, nome_ficha: Optional[str] = None):

        safe_data = []
        for a in avaliacoes or []:
            nota_val = a.get("nota")
            try:
                nota_float = float(nota_val) if nota_val is not None else None
            except (ValueError, TypeError):
                nota_float = None

            safe_data.append({
                "data": a.get("data"),
                "nota": nota_float,
                "texto": a.get("texto") or a.get("text") or "",
                "respondida": 1 if a.get("respondida") in [1, True, "1", "true"] else 0,
                "tags": a.get("tags", "")
            })

        self.df = pd.DataFrame(safe_data)
        
        if not self.df.empty and "data" in self.df.columns:
            self.df["data"] = pd.to_datetime(self.df["data"], errors="coerce", utc=True)
            self.df = self.df.dropna(subset=["data"])

        self.settings = settings or {}
        self.nome_ficha = seguro_latin1(nome_ficha or "Todas as Lojas / Unidades")

        # ========================================================
        # CÁLCULOS ESTATÍSTICOS OFICIAIS (FONTE ÚNICA DA VERDADE)
        # ========================================================
        self.total_avaliacoes = len(self.df)
        valid_ratings = self.df["nota"].dropna().tolist() if not self.df.empty and "nota" in self.df.columns else []
        
        if valid_ratings:
            self.media_oficial = round(float(np.mean(valid_ratings)), 2)
        elif media_atual is not None and media_atual > 0:
            self.media_oficial = round(float(media_atual), 2)
        else:
            self.media_oficial = 0.0

        # Contagem por estrelas
        self.star_counts = {5: 0, 4: 0, 3: 0, 2: 0, 1: 0}
        for r in valid_ratings:
            star_int = int(round(r))
            if star_int in self.star_counts:
                self.star_counts[star_int] += 1

        total_valid = len(valid_ratings) if valid_ratings else 1
        self.star_pcts = {s: round((c / total_valid) * 100, 1) for s, c in self.star_counts.items()}

        # Métricas de Resposta
        self.total_respondidas = int(self.df["respondida"].sum()) if not self.df.empty and "respondida" in self.df.columns else 0
        self.total_pendentes = max(0, self.total_avaliacoes - self.total_respondidas)
        self.taxa_resposta = round((self.total_respondidas / self.total_avaliacoes * 100), 1) if self.total_avaliacoes > 0 else 0.0

        # Índice NPS Estimado
        promotores = self.star_counts[5] + self.star_counts[4]
        detratores = self.star_counts[1] + self.star_counts[2]
        self.nps_score = round(((promotores - detratores) / total_valid) * 100) if valid_ratings else 0

    # ============================================================
    # GRÁFICOS EXECUTIVOS DE ALTA FIDELIDADE (MATPLOTLIB 300 DPI)
    # ============================================================

    def gerar_painel_graficos_executivos(self, output_dir: str) -> str:
        """
        Gera um painel gráfico duplo elegante, padrão Google Executive / McKinsey Dashboard:
        - Painel Esquerdo: Evolução da Nota Média por Mês (Linha com preenchimento suave)
        - Painel Direito: Distribuição de Avaliações por Estrelas (Barras horizontais com % e contagem)
        """
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.2), dpi=300)
        fig.patch.set_facecolor("#ffffff")

        # ----------------------------------------------------
        # 1. GRÁFICO DE EVOLUÇÃO TEMPORAL
        # ----------------------------------------------------
        ax1.set_facecolor("#f8fafc")
        ax1.grid(True, linestyle="--", alpha=0.5, color="#cbd5e1", zorder=1)

        tem_dados_tempo = False
        if not self.df.empty and "data" in self.df.columns and not self.df["nota"].dropna().empty:
            data_local = self.df["data"].dt.tz_convert("America/Sao_Paulo")
            df_temp = self.df.copy()
            df_temp["mes_ano"] = data_local.dt.to_period("M")
            serie_mensal = df_temp.groupby("mes_ano")["nota"].mean().dropna()

            if len(serie_mensal) > 0:
                tem_dados_tempo = True
                labels_mes = [p.strftime("%b/%y").capitalize() for p in serie_mensal.index]
                valores_mes = serie_mensal.values

                x_indices = np.arange(len(labels_mes))
                ax1.plot(x_indices, valores_mes, color="#1a73e8", linewidth=2.8, marker="o", markersize=6,
                         markerfacecolor="#ffffff", markeredgecolor="#1a73e8", markeredgewidth=2.2, zorder=3)
                ax1.fill_between(x_indices, valores_mes, self.media_oficial * 0.7, color="#1a73e8", alpha=0.08, zorder=2)

                ax1.axhline(self.media_oficial, color="#10b981", linestyle=":", linewidth=1.5, alpha=0.8,
                            label=f"Media Geral ({self.media_oficial:.2f})", zorder=2)

                for xi, yi in zip(x_indices, valores_mes):
                    ax1.annotate(f"{yi:.2f}", (xi, yi), textcoords="offset points", xytext=(0, 9),
                                 ha="center", fontsize=9, fontweight="bold", color="#1e293b")

                ax1.set_xticks(x_indices)
                ax1.set_xticklabels(labels_mes, fontsize=9, color="#475569")
                min_y = max(1.0, float(min(valores_mes)) - 0.4)
                max_y = min(5.3, float(max(valores_mes)) + 0.4)
                ax1.set_ylim(min_y, max_y)
                ax1.legend(loc="lower right", fontsize=8.5, framealpha=0.9)

        if not tem_dados_tempo:
            ax1.text(0.5, 0.5, "Dados temporais insuficientes", ha="center", va="center", color="#94a3b8", fontsize=11)
            ax1.set_ylim(1, 5)

        ax1.set_title("Evolucao da Nota Media por Mes", fontsize=12, fontweight="bold", color="#1e293b", pad=12)
        ax1.set_ylabel("Nota Media (1 a 5)", fontsize=9.5, color="#64748b")
        for spine in ["top", "right", "left", "bottom"]:
            ax1.spines[spine].set_color("#e2e8f0")

        # ----------------------------------------------------
        # 2. GRÁFICO DE DISTRIBUIÇÃO POR ESTRELAS
        # ----------------------------------------------------
        ax2.set_facecolor("#f8fafc")
        ax2.grid(True, linestyle="--", alpha=0.5, color="#cbd5e1", axis="x", zorder=1)

        estrelas_labels = ["5 Estrelas", "4 Estrelas", "3 Estrelas", "2 Estrelas", "1 Estrela"]
        cores_estrelas = ["#10b981", "#06b6d4", "#f59e0b", "#f97316", "#ef4444"]
        contagens = [self.star_counts[5], self.star_counts[4], self.star_counts[3], self.star_counts[2], self.star_counts[1]]
        percentuais = [self.star_pcts[5], self.star_pcts[4], self.star_pcts[3], self.star_pcts[2], self.star_pcts[1]]

        y_pos = np.arange(len(estrelas_labels))
        bars = ax2.barh(y_pos, contagens, color=cores_estrelas, height=0.55, edgecolor="none", zorder=2)
        ax2.set_yticks(y_pos)
        ax2.set_yticklabels(estrelas_labels, fontsize=9.5, fontweight="600", color="#334155")
        ax2.invert_yaxis()

        max_c = max(contagens) if contagens and max(contagens) > 0 else 1
        for bar, count, pct in zip(bars, contagens, percentuais):
            width = bar.get_width()
            ax2.text(width + (max_c * 0.03), bar.get_y() + bar.get_height() / 2,
                     f"{count} ({pct:.1f}%)", ha="left", va="center", fontsize=9, fontweight="bold", color="#1e293b")

        ax2.set_xlim(0, max_c * 1.32)
        ax2.set_title("Distribuicao de Avaliacoes por Estrelas", fontsize=12, fontweight="bold", color="#1e293b", pad=12)
        ax2.set_xlabel("Quantidade de Avaliacoes", fontsize=9.5, color="#64748b")
        for spine in ["top", "right", "left", "bottom"]:
            ax2.spines[spine].set_color("#e2e8f0")

        plt.tight_layout(pad=2.5)
        grafico_path = os.path.join(output_dir, "painel_executivo_kpi.png")
        plt.savefig(grafico_path, dpi=300, bbox_inches="tight")
        plt.close()

        return grafico_path

    # ============================================================
    # GERAÇÃO DO PDF CORPORATIVO COM FPDF
    # ============================================================

    def gerar_pdf(self, output):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf = FPDF(orientation="P", unit="mm", format="A4")
            pdf.set_auto_page_break(auto=True, margin=15)
            pdf.add_page()

            # Cores corporativas
            COLOR_PRIMARY = (26, 115, 232)      # #1a73e8
            COLOR_DARK = (30, 41, 59)          # #1e293b
            COLOR_MUTED = (100, 116, 139)      # #64748b
            COLOR_BG_CARD = (248, 250, 252)    # #f8fafc
            COLOR_SUCCESS = (16, 185, 129)     # #10b981

            br_tz = pytz.timezone("America/Sao_Paulo")
            data_geracao = datetime.now(br_tz).strftime("%d/%m/%Y as %H:%M")

            if not self.df.empty and "data" in self.df.columns:
                menor_data = self.df["data"].min().astimezone(br_tz).strftime("%d/%m/%Y")
                maior_data = self.df["data"].max().astimezone(br_tz).strftime("%d/%m/%Y")
                periodo_analisado = f"{menor_data} a {maior_data}"
            else:
                periodo_analisado = "Todo o historico disponivel"

            # ==========================================
            # CABEÇALHO & IDENTIDADE VISUAL
            # ==========================================
            y_start = 12
            logo_bytes = self.settings.get("logo")
            if logo_bytes:
                try:
                    img = Image.open(io.BytesIO(logo_bytes))
                    logo_path = os.path.join(tmpdir, "logo_empresa.png")
                    img.save(logo_path, "PNG")
                    pdf.image(logo_path, x=15, y=y_start, h=16)
                    pdf.set_xy(75, y_start)
                except Exception:
                    pdf.set_xy(15, y_start)
            else:
                pdf.set_xy(15, y_start)

            empresa_nome = seguro_latin1(self.settings.get("business_name") or "ComentsIA Analytics")
            pdf.set_font("Helvetica", "B", 15)
            pdf.set_text_color(*COLOR_DARK)
            pdf.cell(0, 7, "RELATORIO ESTRATEGICO DE AUDITORIA", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            
            pdf.set_font("Helvetica", "B", 11)
            pdf.set_text_color(*COLOR_PRIMARY)
            pdf.cell(0, 6, empresa_nome.upper(), align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

            pdf.set_font("Helvetica", "", 8.5)
            pdf.set_text_color(*COLOR_MUTED)
            pdf.cell(0, 5, f"Unidade: {self.nome_ficha}  |  Periodo: {periodo_analisado}  |  Gerado em: {data_geracao}", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

            pdf.ln(4)
            pdf.set_draw_color(226, 232, 240)
            pdf.set_line_width(0.4)
            pdf.line(15, pdf.get_y(), 195, pdf.get_y())
            pdf.ln(5)

            # ==========================================
            # CARDS DE KPIS ESTATÍSTICOS (OFICIAIS)
            # ==========================================
            card_y = pdf.get_y()
            card_w = 42
            card_h = 22
            espacamento = 3

            kpis = [
                {"label": "NOTA MEDIA", "val": f"{self.media_oficial:.2f} / 5.0", "sub": "Escala de 1 a 5", "cor": COLOR_PRIMARY},
                {"label": "TOTAL DE AVALIACOES", "val": str(self.total_avaliacoes), "sub": "Feedbacks analisados", "cor": COLOR_DARK},
                {"label": "TAXA DE RESPOSTA", "val": f"{self.taxa_resposta:.1f}%", "sub": f"{self.total_respondidas} respondidas", "cor": COLOR_SUCCESS},
                {"label": "INDICE NPS", "val": f"+{self.nps_score}", "sub": f"{self.star_pcts[5] + self.star_pcts[4]:.0f}% Promotores", "cor": (147, 51, 234)}
            ]

            for i, k in enumerate(kpis):
                cx = 15 + i * (card_w + espacamento)
                pdf.set_fill_color(*COLOR_BG_CARD)
                pdf.set_draw_color(226, 232, 240)
                pdf.rect(cx, card_y, card_w, card_h, style="FD")

                pdf.set_xy(cx + 2, card_y + 2.5)
                pdf.set_font("Helvetica", "B", 7)
                pdf.set_text_color(*COLOR_MUTED)
                pdf.cell(card_w - 4, 4, seguro_latin1(k["label"]), align="C")

                pdf.set_xy(cx + 2, card_y + 7)
                pdf.set_font("Helvetica", "B", 12)
                pdf.set_text_color(*k["cor"])
                pdf.cell(card_w - 4, 7, seguro_latin1(k["val"]), align="C")

                pdf.set_xy(cx + 2, card_y + 14.5)
                pdf.set_font("Helvetica", "", 6.5)
                pdf.set_text_color(*COLOR_MUTED)
                pdf.cell(card_w - 4, 4, seguro_latin1(k["sub"]), align="C")

            pdf.set_y(card_y + card_h + 5)

            # ==========================================
            # PAINEL GRÁFICO EXECUTIVO (300 DPI)
            # ==========================================
            grafico_path = self.gerar_painel_graficos_executivos(tmpdir)
            largura_grafico = 180
            pdf.image(grafico_path, x=15, y=pdf.get_y(), w=largura_grafico)
            pdf.ln(70)

            # ==========================================
            # ANÁLISE DE ALTA INTELIGÊNCIA COM GPT-4O
            # ==========================================
            manager_name = seguro_latin1(self.settings.get("manager_name") or "")
            manager_str = f'O gerente/responsavel operacional e "{manager_name}".' if manager_name else ""

            amostra_comentarios = []
            if not self.df.empty and "texto" in self.df.columns:
                reviews_com_texto = self.df[self.df["texto"].str.len() > 5]
                for _, row in reviews_com_texto.head(40).iterrows():
                    amostra_comentarios.append({
                        "nota": row["nota"],
                        "comentario": seguro_latin1(str(row["texto"])[:300])
                    })

            prompt_ai = f"""
Voce e um Diretor de Inteligencia de Mercado e Auditor Senior de Experiencia do Cliente.
Gere um relatorio executivo estrategico de alto padrao destinado a diretoria da empresa "{empresa_nome}".

DADOS ESTATISTICOS OFICIAIS CALCULADOS PELO SISTEMA (Use rigorosamente estes numeros para evitar qualquer divergencia):
- Unidade / Ficha: {self.nome_ficha}
- Periodo Analisado: {periodo_analisado}
- Total de Avaliacoes: {self.total_avaliacoes}
- Nota Media Oficial: {self.media_oficial:.2f} de 5.00 estrelas
- Distribuicao de Estrelas: 5 estrelas ({self.star_counts[5]} | {self.star_pcts[5]}%), 4 estrelas ({self.star_counts[4]} | {self.star_pcts[4]}%), 3 estrelas ({self.star_counts[3]} | {self.star_pcts[3]}%), 2 estrelas ({self.star_counts[2]} | {self.star_pcts[2]}%), 1 estrela ({self.star_counts[1]} | {self.star_pcts[1]}%)
- Taxa de Resposta: {self.taxa_resposta:.1f}% ({self.total_respondidas} respondidas de {self.total_avaliacoes})
- Net Promoter Score (NPS Estimado): +{self.nps_score}
{manager_str}

REGRAS ESTRITAS DE COERENCIA MATEMATICA E ESCRITA:
1. CONSISTENCIA DE DADOS: Cite sempre a Nota Media Oficial de {self.media_oficial:.2f} estrelas e as contagens exatas fornecidas. NUNCA calcule nem afirme uma media diferente de {self.media_oficial:.2f}.
2. POSTURA CONSULTIVA DE ELITE: Texto formal, analitico, direto, corporativo e com profundo rigor de governanca.
3. SEM TERMOS DE IA: E expressamente PROIBIDO mencionar 'prompt', 'inteligencia artificial', 'modelo de linguagem' ou 'parametros'.
4. ESTRUTURA OBRIGATORIA (Use exatamente estas secoes em letras maiusculas):
   RESUMO EXECUTIVO & DIAGNOSTICO
   AUDITORIA QUANTITATIVA & DISTRIBUICAO
   ANALISE QUALITATIVA DE ASPECTOS E SENTIMENTOS
   PONTOS CRITICOS & GARGALOS OPERACIONAIS
   DESTAQUES POSITIVOS & ALAVANCAS DE SUCESSO
   PLANO DE ACAO E RECOMENDACOES ESTRATEGICAS
   METODOLOGIA TECNICA APLICADA

AMOSTRA DE COMENTARIOS DO PERIODO:
{amostra_comentarios if amostra_comentarios else "Sem comentarios adicionais em texto."}
"""

            try:
                client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
                completion = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Voce e um auditor senior de inteligencia corporativa. "
                                "Gere relatorios analiticos impecaveis, mantendo 100% de consistencia com os numeros oficiais fornecidos."
                            )
                        },
                        {"role": "user", "content": prompt_ai}
                    ],
                    temperature=0.3,
                    timeout=90,
                )
                conteudo_analise = (completion.choices[0].message.content or "").strip()
            except Exception as ex_ai:
                logging.exception("Falha na chamada do GPT-4o para relatório: %s", ex_ai)
                conteudo_analise = (
                    f"RESUMO EXECUTIVO & DIAGNOSTICO\n"
                    f"A unidade {self.nome_ficha} registrou um volume de {self.total_avaliacoes} avaliacoes no periodo analisado ({periodo_analisado}), "
                    f"atingindo uma Nota Media Oficial de {self.media_oficial:.2f} de 5.00 estrelas com taxa de engajamento de {self.taxa_resposta:.1f}%.\n\n"
                    f"AUDITORIA QUANTITATIVA & DISTRIBUICAO\n"
                    f"A base demonstra {self.star_counts[5]} avaliacoes de 5 estrelas ({self.star_pcts[5]}%), {self.star_counts[4]} de 4 estrelas ({self.star_pcts[4]}%), "
                    f"{self.star_counts[3]} de 3 estrelas ({self.star_pcts[3]}%), {self.star_counts[2]} de 2 estrelas ({self.star_pcts[2]}%) e {self.star_counts[1]} de 1 estrela ({self.star_pcts[1]}%).\n\n"
                    f"PLANO DE ACAO E RECOMENDACOES ESTRATEGICAS\n"
                    f"Manter o monitoramento continuo das avaliacoes e responder ativamente a todos os feedbacks dos clientes."
                )

            texto_limpo = limpa_markdown(conteudo_analise)
            linhas = texto_limpo.split("\n")

            secoes_principais = [
                "RESUMO EXECUTIVO",
                "AUDITORIA QUANTITATIVA",
                "ANALISE QUALITATIVA",
                "PONTOS CRITICOS",
                "DESTAQUES POSITIVOS",
                "PLANO DE ACAO",
                "METODOLOGIA TECNICA",
                "CONCLUSAO",
                "RECOMENDACOES"
            ]

            pdf.set_text_color(*COLOR_DARK)

            for linha in linhas:
                linha_str = linha.strip()
                if not linha_str:
                    pdf.ln(3)
                    continue

                linha_upper = linha_str.upper()
                is_titulo = any(sec in linha_upper for sec in secoes_principais) and len(linha_str) < 65

                if is_titulo:
                    pdf.ln(4)
                    if pdf.get_y() > 250:
                        pdf.add_page()
                    
                    pdf.set_fill_color(241, 245, 249)
                    pdf.set_text_color(*COLOR_PRIMARY)
                    pdf.set_font("Helvetica", "B", 10.5)
                    pdf.cell(0, 7, f"  {linha_str}", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                    pdf.ln(2)
                    pdf.set_text_color(*COLOR_DARK)
                    pdf.set_font("Helvetica", "", 9.5)
                else:
                    pdf.set_font("Helvetica", "", 9.5)
                    pdf.set_text_color(*COLOR_DARK)
                    safe_text = seguro_latin1(linha_str)
                    pdf.multi_cell(0, 5, safe_text)
                    pdf.ln(1)

            # ==========================================
            # RODAPÉ DE ASSINATURA CORPORATIVA
            # ==========================================
            pdf.ln(6)
            if pdf.get_y() > 255:
                pdf.add_page()

            pdf.set_draw_color(226, 232, 240)
            pdf.line(15, pdf.get_y(), 195, pdf.get_y())
            pdf.ln(3)

            pdf.set_font("Helvetica", "B", 9)
            pdf.set_text_color(*COLOR_DARK)
            pdf.cell(0, 5, empresa_nome, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

            if manager_name:
                pdf.set_font("Helvetica", "", 8.5)
                pdf.set_text_color(*COLOR_MUTED)
                pdf.cell(0, 4.5, f"Responsavel Tecnico: {manager_name}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

            # ==========================================
            # OUTPUT DO PDF
            # ==========================================
            if isinstance(output, (str, os.PathLike)):
                pdf.output(output)
            else:
                pdf_bytes = pdf.output()
                if isinstance(pdf_bytes, str):
                    pdf_bytes = pdf_bytes.encode("latin-1", "replace")
                output.write(pdf_bytes)
                output.seek(0)