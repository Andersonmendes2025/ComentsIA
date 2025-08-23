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
    def __init__(self, avaliacoes, media_atual=None, analises=None, settings=None):
        # Garante chaves mínimas
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
        # Converte 'data' para tz-aware e cria uma coluna "naive" (sem tz) só para agrupar
        self.df["data"] = pd.to_datetime(self.df.get("data"), errors="coerce", utc=True)

        data_local = self.df["data"].dt.tz_convert("America/Sao_Paulo")
        self.df["data_local"] = data_local.dt.strftime("%d/%m/%Y %H:%M")
        self.df["data_local_naive"] = data_local.dt.tz_localize(None)

        # Agrupa por mês sem timezone (evita o warning do pandas)
        if "nota" not in self.df.columns:
            self.df["nota"] = None
        notas_por_mes = (
            self.df.dropna(subset=["data_local_naive"])
                   .groupby(self.df["data_local_naive"].dt.to_period("M"))["nota"]
                   .mean()
        )

        plt.figure(figsize=(9, 4))
        if len(notas_por_mes) > 0:
            notas_por_mes.plot(kind="line", marker="o", color="#28a745")
        else:
            # gráfico vazio, mas válido
            plt.plot([], [])
        plt.title("Evolução da Nota Média por Mês")
        plt.xlabel("Mês")
        plt.ylabel("Nota Média")
        plt.tight_layout()

        grafico_path = os.path.join(output_dir, "evolucao_medio.png")
        plt.savefig(grafico_path, dpi=140)
        plt.close()
        return grafico_path

    def gerar_pdf(self, output):
        """
        Gera o PDF em:
          - um buffer BytesIO (se 'output' for BytesIO), ou
          - um arquivo no disco (se 'output' for caminho str/Path).
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf = FPDF()
            pdf.add_page()
            y_logo_offset = 10

            # --- LOGO DA EMPRESA ---
            logo_bytes = self.settings.get("logo")
            if logo_bytes:
                try:
                    img = Image.open(io.BytesIO(logo_bytes))
                    logo_path = os.path.join(tmpdir, "logo_temp.png")
                    img.save(logo_path, "PNG")

                    # dimensionamento simples
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
                except Exception as e:
                    print("Erro ao processar logo:", e)
                    y_logo_offset = 20
            else:
                y_logo_offset = 20

            # --- Cabeçalho ---
            br_tz = pytz.timezone("America/Sao_Paulo")
            data_br = datetime.now(br_tz).strftime("%d/%m/%Y %H:%M")
            pdf.set_y(y_logo_offset)
            pdf.set_font("Arial", "B", 16)
            pdf.cell(0, 10, "Relatorio de Avaliacoes", ln=True, align="C")
            pdf.ln(5)
            pdf.set_font("Arial", "", 10)
            pdf.cell(0, 10, f"Data de geracao: {data_br}", ln=True)
            pdf.ln(1)

            total_avaliacoes = len(self.df)
            media_nota = float(self.df["nota"].mean()) if total_avaliacoes > 0 else 0.0
            pdf.set_font("Arial", "", 12)
            pdf.cell(0, 10, f"Media de nota: {media_nota:.2f}", ln=True)
            if self.media_atual is not None:
                try:
                    pdf.cell(0, 10, f"Media Atual: {float(self.media_atual):.2f}", ln=True)
                except Exception:
                    pdf.cell(0, 10, "Media Atual: --", ln=True)
            pdf.ln(5)

            # Normaliza 'data_local' (pode ser util em outras secoes)
            try:
                self.df["data"] = pd.to_datetime(self.df.get("data"), errors="coerce", utc=True)
                self.df["data_local"] = self.df["data"].dt.tz_convert("America/Sao_Paulo").dt.strftime("%d/%m/%Y %H:%M")
            except Exception:
                pass

            manager_name = self.settings.get("manager_name") or ""
            manager_str = f'O gerente responsavel e "{manager_name}".' if manager_name else ""

            # --- ANÁLISE DA IA ---
            # Garante colunas para o prompt
            if "texto" not in self.df.columns:
                self.df["texto"] = ""
            if "nota" not in self.df.columns:
                self.df["nota"] = None

            try:
                dados_prompt = self.df[["nota", "texto"]].to_dict(orient="records")
            except Exception:
                dados_prompt = []

            prompt = f"""
Voce e um analista senior de satisfacao do cliente. Gere um relatorio analitico detalhado para a diretoria da empresa "{self.settings.get('business_name', 'EMPRESA')}", usando analise de sentimentos e metricas relevantes. Nao cite diretamente comentarios. Nao repita palavras.
{manager_str}

Estruture o relatorio com topicos bem destacados, assim:

RESUMO EXECUTIVO
- Apresente um panorama geral, principais tendencias e os insights mais importantes.

ANALISE QUANTITATIVA
- Mostre a distribuicao das notas.
- Informe o percentual de avaliacoes positivas, neutras e negativas.
- Apresente os temas e palavras mais frequentes.

ANALISE POR ESTRELA
- Para cada nota de 1 a 5, explique o sentimento predominante, pontos principais e sugestoes de resposta ou acao.

PONTOS CRITICOS
- Destaque no minimo 3 principais problemas ou riscos identificados.

DESTAQUES POSITIVOS
- Aponte de 1 a 3 pontos fortes e diferenciais competitivos da empresa.

CONCLUSAO E RECOMENDACOES
- Apresente acoes praticas para o proximo trimestre, oportunidades de melhoria e estrategias para aumentar a satisfacao dos clientes.

METODOLOGIA
- Informe que foi utilizado IA com analise de sentimentos e linguagem natural, sem citar comentarios literais.

ORIENTACOES ADICIONAIS:
- Se os comentarios forem inconclusivos, ressalte esse ponto.
- Nao use negrito, italico ou sublinhado: apenas destaque cada topico com o TITULO EM MAIUSCULAS no inicio de cada secao.
- Nao repita palavras, nao cite comentarios literais.
- O relatorio deve ser claro, bem detalhado, objetivo, sem repeticao e com extensao entre 2 e 5 paginas.

Siga exatamente esse roteiro, mantendo os titulos dos topicos conforme o exemplo acima.

DADOS DAS AVALIACOES:
{dados_prompt}
            """

            try:
                client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
                completion = client.chat.completions.create(
                    model="gpt-4.1",
                    messages=[
                        {"role": "system", "content": "Voce e um assistente especializado em analise de satisfacao do cliente."},
                        {"role": "user", "content": prompt}
                    ],
                    timeout=60
                )
                analise_gerada = (completion.choices[0].message.content or "").strip()
                analise_limpa = limpa_markdown(analise_gerada)

                pdf.set_font("Arial", "B", 12)
                pdf.cell(0, 10, "Analise da IA sobre as Avaliacoes", ln=True)
                pdf.set_font("Arial", "", 11)

                partes = analise_limpa.split("ANALISE QUANTITATIVA", 1)
                if len(partes) == 2:
                    pdf.multi_cell(0, 7, partes[0].strip())
                    pdf.ln(4)
                    grafico_media_path = self.gerar_grafico_media_historica(tmpdir)
                    largura_grafico = pdf.w - 2 * pdf.l_margin - 2
                    pdf.set_font("Arial", "", 12)
                    pdf.cell(0, 10, "Evolucao da Nota Media por Mes:", ln=True)
                    pdf.image(grafico_media_path, x=pdf.l_margin + 1, w=largura_grafico)
                    pdf.ln(8)
                    pdf.set_font("Arial", "", 11)
                    pdf.multi_cell(0, 7, "ANALISE QUANTITATIVA" + partes[1].strip())
                else:
                    pdf.multi_cell(0, 7, analise_limpa)
                    pdf.ln(4)
                    grafico_media_path = self.gerar_grafico_media_historica(tmpdir)
                    largura_grafico = pdf.w - 2 * pdf.l_margin - 2
                    pdf.set_font("Arial", "", 12)
                    pdf.cell(0, 10, "Evolucao da Nota Media por Mes:", ln=True)
                    pdf.image(grafico_media_path, x=pdf.l_margin + 1, w=largura_grafico)
                    pdf.ln(8)

            except Exception as e:
                print(f"Erro ao gerar analise com IA: {str(e)}")
                pdf.multi_cell(0, 7, f"Erro ao gerar analise com IA: {str(e)}")

            if manager_name:
                pdf.ln(8)
                pdf.set_font("Arial", "B", 12)
                pdf.cell(0, 10, f"{self.settings.get('business_name','')}", ln=True)
                pdf.cell(0, 10, f"{manager_name}", ln=True)

            # --- Saída: arquivo ou buffer ---
            if isinstance(output, (str, os.PathLike)):
                pdf.output(output)  # grava direto no disco
                print("PDF gerado com sucesso:", output)
            else:
                # PyFPDF (1.x) retorna string em output(dest='S'); converte para bytes
                raw = pdf.output(dest="S")
                if isinstance(raw, str):
                    pdf_bytes = raw.encode("latin-1")  # encoding usado pelo FPDF
                else:
                    pdf_bytes = raw  # fpdf2 já retorna bytes
                output.write(pdf_bytes)
                output.seek(0)
                print("PDF gerado em buffer.")