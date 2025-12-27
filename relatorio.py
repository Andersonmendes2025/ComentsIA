import io
import os
import re
import tempfile
from datetime import datetime

import matplotlib
import pandas as pd
import pytz
from fpdf import FPDF
from openai import OpenAI
from PIL import Image

matplotlib.use("Agg")
from matplotlib import pyplot as plt


# ============================================================
# LIMPA FORMATAÇÕES DA IA
# ============================================================

def limpa_markdown(texto: str) -> str:
    if not isinstance(texto, str):
        return ""

    texto = re.sub(r"^\s*#+\s*", "", texto, flags=re.MULTILINE)
    texto = re.sub(r"\*\*([^*]+)\*\*", r"\1", texto)
    texto = re.sub(r"^[\-\*]\s+", "", texto, flags=re.MULTILINE)
    texto = re.sub(r"^\d+\.\s+", "", texto, flags=re.MULTILINE)
    texto = re.sub(r"^---+", "", texto, flags=re.MULTILINE)
    texto = re.sub(r"\n{3,}", "\n\n", texto)

    texto = texto.replace("“", '"').replace("”", '"')
    texto = texto.replace("‘", "'").replace("’", "'")
    texto = texto.replace("–", "-").replace("—", "-")

    return texto.strip()


# ============================================================
# CLASSE PRINCIPAL DO RELATÓRIO
# ============================================================

class RelatorioAvaliacoes:
    print("### RELATORIO.PY CARREGADO:", __file__)

    def __init__(self, avaliacoes, media_atual=None, analises=None,
                 settings=None, nome_ficha=None):

        safe = []
        for a in avaliacoes or []:
            safe.append(
                {
                    "data": a.get("data"),
                    "nota": a.get("nota"),
                    "texto": a.get("texto") or a.get("text") or "",
                    "respondida": a.get("respondida", 0),
                    "tags": a.get("tags", "")
                }
            )

        self.df = pd.DataFrame(safe)
        self.media_atual = media_atual
        self.analises = analises
        self.settings = settings or {}
        self.nome_ficha = nome_ficha or "Todas as Lojas"

    # ============================================================
    # GRÁFICO HISTÓRICO
    # ============================================================

    def gerar_grafico_media_historica(self, output_dir: str) -> str:
        self.df["data"] = pd.to_datetime(self.df.get("data"), errors="coerce", utc=True)

        data_local = self.df["data"].dt.tz_convert("America/Sao_Paulo")
        self.df["data_local_naive"] = data_local.dt.tz_localize(None)

        if "nota" not in self.df.columns:
            self.df["nota"] = None

        df_temp = self.df.dropna(subset=["data_local_naive"])
        if len(df_temp) == 0:
            notas_por_mes = []
        else:
            notas_por_mes = (
                df_temp.groupby(df_temp["data_local_naive"].dt.to_period("M"))["nota"].mean()
            )

        plt.figure(figsize=(9, 4))
        if isinstance(notas_por_mes, list) or len(notas_por_mes) == 0:
            plt.plot([], [])
        else:
            notas_por_mes.plot(kind="line", marker="o", color="#28a745")

        plt.title("Evolução da Nota Média por Mês")
        plt.xlabel("Mês")
        plt.ylabel("Nota Média")
        plt.tight_layout()

        grafico_path = os.path.join(output_dir, "evolucao_medio.png")
        plt.savefig(grafico_path, dpi=140)
        plt.close()

        return grafico_path

    # ============================================================
    # GERAÇÃO DO PDF
    # ============================================================

    def gerar_pdf(self, output):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf = FPDF()
            pdf.add_page()
            y_logo_offset = 10

            # ==========================================
            # LOGO
            # ==========================================
            logo_bytes = self.settings.get("logo")
            if logo_bytes:
                try:
                    img = Image.open(io.BytesIO(logo_bytes))
                    logo_path = os.path.join(tmpdir, "logo_temp.png")
                    img.save(logo_path, "PNG")

                    max_width_mm = 60
                    max_height_mm = 25
                    dpi = 96
                    px_to_mm = 25.4 / dpi
                    img_width_mm = img.width * px_to_mm
                    img_height_mm = img.height * px_to_mm
                    ratio = min(max_width_mm / img_width_mm, max_height_mm / img_height_mm, 1)

                    w = img_width_mm * ratio
                    h = img_height_mm * ratio
                    x_pos = (pdf.w - w) / 2

                    pdf.image(logo_path, x=x_pos, y=y_logo_offset, w=w, h=h)
                    y_logo_offset += h + 7
                except Exception:
                    y_logo_offset = 20
            else:
                y_logo_offset = 20

            # ==========================================
            # CABEÇALHO
            # ==========================================
            br_tz = pytz.timezone("America/Sao_Paulo")
            data_br = datetime.now(br_tz).strftime("%d/%m/%Y %H:%M")

            pdf.set_y(y_logo_offset)
            pdf.set_font("Arial", "B", 16)
            pdf.cell(0, 10, "Relatorio de Avaliacoes", ln=True, align="C")

            pdf.ln(5)
            pdf.set_font("Arial", "", 10)
            pdf.cell(0, 10, f"Data de geracao: {data_br}", ln=True)
            pdf.set_font("Arial", "", 11)
            pdf.ln(2)
            pdf.cell(0, 8, f"Loja / Ficha: {self.nome_ficha}", ln=True)
            pdf.ln(3)


            # ==========================================
            # MÉDIAS
            # ==========================================
            total_avaliacoes = len(self.df)
            media_nota = float(self.df["nota"].mean()) if total_avaliacoes > 0 else 0.0

            pdf.set_font("Arial", "", 12)
            pdf.ln(1)
            pdf.cell(0, 10, f"Media de nota: {media_nota:.2f}", ln=True)

            if self.media_atual is not None:
                try:
                    pdf.cell(0, 10, f"Media Atual: {float(self.media_atual):.2f}", ln=True)
                except Exception:
                    pdf.cell(0, 10, "Media Atual: --", ln=True)

            pdf.ln(5)

            manager_name = self.settings.get("manager_name") or ""
            manager_str = f'O gerente responsavel e "{manager_name}".' if manager_name else ""

            # ==========================================
            # ANÁLISE COM IA
            # ==========================================
            if "texto" not in self.df.columns:
                self.df["texto"] = ""

            if "nota" not in self.df.columns:
                self.df["nota"] = None

            try:
                dados_prompt = self.df[["nota", "texto"]].to_dict(orient="records")
            except Exception:
                dados_prompt = []

            contexto_personalizado = (self.settings.get("contexto_personalizado") or "").strip()

            # Prompt LIMPO e sem duplicações
            prompt = (
                "INSTRUÇÃO PRIORITÁRIA: Use o contexto da empresa como referência principal.\n\n"
            )

            if contexto_personalizado:
                prompt += f"Contexto da empresa: {contexto_personalizado}\n\n"

            prompt += f"""
Você é um analista profissional de satisfação do cliente. Gere um relatório completo para a diretoria da empresa "{self.settings.get('business_name', 'EMPRESA')}".  
Não cite comentários literais. Não repita palavras.  
{manager_str}

Estrutura obrigatória:

RESUMO EXECUTIVO
ANALISE QUANTITATIVA
ANALISE POR ESTRELA
PONTOS CRITICOS
DESTAQUES POSITIVOS
CONCLUSAO E RECOMENDACOES
METODOLOGIA

Regras:
- Texto formal, claro e bem estruturado.
- Não usar negrito, itálico, emojis ou caracteres especiais.
- Não repetir palavras ou ideias.
- Não usar travessões longos.
- Não citar comentários literais.
- Entre 2 e 5 páginas de conteúdo.
- Passe todo o texto por uma corrreção ortografica antes de enviar e nao use acaracteres como travesao.

DADOS:
{dados_prompt}
"""

            # Chamada da IA
            try:
                client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

                completion = client.chat.completions.create(
                    model="gpt-4.1",
                    messages=[
                        {"role": "system", "content": "Você analisa avaliações com precisão."},
                        {"role": "user", "content": prompt},
                    ],
                    timeout=60,
                )

                analise = (completion.choices[0].message.content or "").strip()
                analise_limpa = limpa_markdown(analise)

                pdf.set_font("Arial", "B", 12)
                pdf.cell(0, 10, "Analise da IA sobre as Avaliacoes", ln=True)

                pdf.set_font("Arial", "", 11)

                # Normaliza texto para facilitar a detecção da seção
                texto_n = (
                    analise_limpa.upper()
                    .replace("Á", "A")
                    .replace("Ã", "A")
                    .replace("Â", "A")
                )

                gatilhos = [
                    "ANALISE QUANTITATIVA",
                    "SECAO QUANTITATIVA",
                    "ANALISE  QUANTITATIVA",  # com espaço duplo
                ]

                if any(g in texto_n for g in gatilhos):

                    # identifica qual gatilho ocorreu
                    gatilho_usado = next(g for g in gatilhos if g in texto_n)

                    # tenta dividir texto corretamente
                    try:
                        bloco1, bloco2 = texto_n.split(gatilho_usado, 1)

                        # Mas usamos a versão original formatada para exibir no PDF
                        bloco1_original, bloco2_original = analise_limpa.split(
                            gatilho_usado.replace("  ", " "), 1
                        )
                    except Exception:
                        bloco1_original = analise_limpa
                        bloco2_original = ""

                    # --- Parte antes da análise quantitativa ---
                    pdf.multi_cell(0, 7, bloco1_original.strip())
                    pdf.ln(5)

                    # --- INSERE O GRÁFICO ---
                    grafico_path = self.gerar_grafico_media_historica(tmpdir)
                    largura = pdf.w - 2 * pdf.l_margin
                    pdf.image(grafico_path, w=largura)
                    pdf.ln(8)

                    # --- Parte depois da análise quantitativa ---
                    if bloco2_original:
                        pdf.multi_cell(0, 7, "ANALISE QUANTITATIVA\n" + bloco2_original.strip())

                else:
                    # fallback: IA não encontrou seção -> mas ainda assim adiciona gráfico
                    pdf.multi_cell(0, 7, analise_limpa)
                    pdf.ln(5)
                    grafico_path = self.gerar_grafico_media_historica(tmpdir)
                    largura = pdf.w - 2 * pdf.l_margin
                    pdf.image(grafico_path, w=largura)
                    pdf.ln(8)


            except Exception as e:
                pdf.multi_cell(0, 7, f"Erro ao gerar analise com IA: {str(e)}")

            # Rodapé com gerente
            if manager_name:
                pdf.ln(8)
                pdf.set_font("Arial", "B", 12)
                pdf.cell(0, 10, self.settings.get("business_name", ""), ln=True)
                pdf.cell(0, 10, manager_name, ln=True)

            # ==========================================
            # SAÍDA
            # ==========================================
            if isinstance(output, (str, os.PathLike)):
                pdf.output(output)
            else:
                raw = pdf.output(dest="S")
                if isinstance(raw, str):
                    raw = raw.encode("latin-1")
                output.write(raw)
                output.seek(0)
