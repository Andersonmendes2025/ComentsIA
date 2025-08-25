# relatorio.py — otimizado p/ GPT-4.1 (leve, seguro e sempre gera saída)
import os
import io
import re
import unicodedata
import tempfile
from datetime import datetime

import pandas as pd
import pytz
from fpdf import FPDF
from openai import OpenAI
from PIL import Image

# --- Matplotlib sem GUI (evita Tkinter) ---
import matplotlib
matplotlib.use("Agg")
from matplotlib import pyplot as plt


def limpa_markdown(texto: str) -> str:
    if not isinstance(texto, str):
        return ""
    texto = re.sub(r'^\s*#+\s*', '', texto, flags=re.MULTILINE)
    texto = re.sub(r'\*\*([^*]+)\*\*', r'\1', texto)
    texto = re.sub(r'^[\-\*]\s+', '', texto, flags=re.MULTILINE)
    texto = re.sub(r'^\d+\.\s+', '', texto, flags=re.MULTILINE)
    texto = re.sub(r'^---+', '', texto, flags=re.MULTILINE)
    texto = re.sub(r'\n{3,}', '\n\n', texto)
    texto = texto.replace('“', '"').replace('”', '"').replace('‘', "'").replace('’', "'")
    texto = texto.replace('–', '-').replace('—', '-')
    texto = unicodedata.normalize('NFKD', texto).encode('ASCII', 'ignore').decode('ASCII')
    return texto.strip()


class RelatorioAvaliacoes:
    MAX_RECORDS_PROMPT = 400  # limite p/ não pesar memória/token

    def __init__(self, avaliacoes, media_atual=None, analises=None, settings=None):
        safe = []
        for a in (avaliacoes or []):
            safe.append({
                "data": a.get("data"),
                "nota": a.get("nota"),
                "texto": a.get("texto") or a.get("text") or "",
                "respondida": a.get("respondida", 0),
                "tags": a.get("tags", ""),
            })
        self.df = pd.DataFrame(safe)
        self.media_atual = media_atual
        self.analises = analises
        self.settings = settings or {}

    def gerar_grafico_media_historica(self, output_dir: str) -> str:
        self.df["data"] = pd.to_datetime(self.df.get("data"), errors="coerce", utc=True)
        data_local = self.df["data"].dt.tz_convert("America/Sao_Paulo")
        self.df["data_local_naive"] = data_local.dt.tz_localize(None)

        if "nota" not in self.df.columns:
            self.df["nota"] = None
        notas_por_mes = (
            self.df.dropna(subset=["data_local_naive"])
                   .groupby(self.df["data_local_naive"].dt.to_period("M"))["nota"]
                   .mean()
        )

        plt.figure(figsize=(9, 4))
        if len(notas_por_mes) > 0:
            notas_por_mes.plot(kind="line", marker="o", color="#007bff")
        else:
            plt.plot([], [])
        plt.title("Evolução da Nota Média por Mês")
        plt.xlabel("Mês")
        plt.ylabel("Nota Média")
        plt.tight_layout()

        grafico_path = os.path.join(output_dir, "evolucao_media.png")
        plt.savefig(grafico_path, dpi=140)
        plt.close()
        return grafico_path

    def _analise_local(self) -> str:
        """Fallback se GPT não responder"""
        total = len(self.df)
        if total == 0:
            return "Nao ha avaliacoes suficientes para gerar analise."
        media = float(self.df["nota"].mean()) if "nota" in self.df.columns else 0.0
        return (f"RESUMO EXECUTIVO\nTotal de avaliacoes: {total}. "
                f"Media geral: {media:.2f}.\n\n"
                "ANALISE QUANTITATIVA\nDistribuicao simples de notas "
                "e analise de sentimentos nao disponivel por falta de IA.\n\n"
                "CONCLUSAO\nUse a versao com IA habilitada para insights completos.")

    def gerar_pdf(self, output):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf = FPDF()
            pdf.add_page()
            y_logo_offset = 10

            # Logo
            logo_bytes = self.settings.get("logo")
            if logo_bytes:
                try:
                    img = Image.open(io.BytesIO(logo_bytes))
                    logo_path = os.path.join(tmpdir, "logo.png")
                    img.save(logo_path, "PNG")
                    w = 50
                    x_pos = (pdf.w - w) / 2
                    pdf.image(logo_path, x=x_pos, y=y_logo_offset, w=w)
                    y_logo_offset += 30
                except Exception:
                    y_logo_offset = 20
            else:
                y_logo_offset = 20

            # Cabeçalho
            data_br = datetime.now(pytz.timezone("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M")
            pdf.set_y(y_logo_offset)
            pdf.set_font("Arial", "B", 16)
            pdf.cell(0, 10, "Relatorio de Avaliacoes", ln=True, align="C")
            pdf.ln(5)
            pdf.set_font("Arial", "", 10)
            pdf.cell(0, 10, f"Data de geracao: {data_br}", ln=True)
            pdf.ln(5)

            # Métricas
            total = len(self.df)
            media = float(self.df["nota"].mean()) if total > 0 else 0.0
            pdf.set_font("Arial", "", 12)
            pdf.cell(0, 10, f"Media de nota: {media:.2f}", ln=True)
            if self.media_atual is not None:
                pdf.cell(0, 10, f"Media Atual: {self.media_atual:.2f}", ln=True)
            pdf.ln(5)

            # Prompt
            if len(self.df) > self.MAX_RECORDS_PROMPT:
                use_df = self.df.tail(self.MAX_RECORDS_PROMPT)
            else:
                use_df = self.df
            try:
                dados_prompt = use_df[["nota", "texto"]].to_dict(orient="records")
            except Exception:
                dados_prompt = []

            manager_name = self.settings.get("manager_name") or ""
            business_name = self.settings.get("business_name", "EMPRESA")

            prompt = f"""
Voce e um analista senior de satisfacao do cliente. Gere um relatorio detalhado para a diretoria da empresa "{business_name}", com base nas avaliacoes abaixo.
Nao cite comentarios literais. Nao repita frases. Estruture nos seguintes topicos:

RESUMO EXECUTIVO
ANALISE QUANTITATIVA
ANALISE POR ESTRELA
PONTOS CRITICOS
DESTAQUES POSITIVOS
CONCLUSAO E RECOMENDACOES
METODOLOGIA

DADOS DAS AVALIACOES:
{dados_prompt}
            """.strip()

            # IA GPT-4.1
            analise_limpa = ""
            try:
                client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
                completion = client.chat.completions.create(
                    model="gpt-4.1",
                    messages=[
                        {"role": "system", "content": "Voce e um especialista em analise de satisfacao do cliente."},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=1200,
                    timeout=60
                )
                analise = completion.choices[0].message.content.strip()
                analise_limpa = limpa_markdown(analise)
            except Exception as e:
                print("Erro GPT:", e)
                analise_limpa = self._analise_local()

            # Texto da análise
            pdf.set_font("Arial", "B", 12)
            pdf.cell(0, 10, "Analise da IA sobre as Avaliacoes", ln=True)
            pdf.set_font("Arial", "", 11)
            pdf.multi_cell(0, 7, analise_limpa)
            pdf.ln(5)

            # Gráfico de evolução
            try:
                grafico_path = self.gerar_grafico_media_historica(tmpdir)
                largura = pdf.w - 2 * pdf.l_margin - 2
                pdf.add_page()
                pdf.set_font("Arial", "B", 12)
                pdf.cell(0, 10, "Evolucao da Nota Media por Mes:", ln=True)
                pdf.image(grafico_path, x=pdf.l_margin + 1, w=largura)
            except Exception as e:
                print("Erro grafico:", e)

            # Rodapé
            if manager_name or business_name:
                pdf.ln(8)
                pdf.set_font("Arial", "B", 12)
                if business_name:
                    pdf.cell(0, 10, business_name, ln=True)
                if manager_name:
                    pdf.cell(0, 10, manager_name, ln=True)

            # Saída
            if isinstance(output, (str, os.PathLike)):
                pdf.output(output)
            else:
                raw = pdf.output(dest="S")
                pdf_bytes = raw.encode("latin-1") if isinstance(raw, str) else raw
                output.write(pdf_bytes)
                output.seek(0)
