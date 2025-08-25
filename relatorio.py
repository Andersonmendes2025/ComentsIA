# relatorio.py — otimizado p/ memória e processamento (sem mudar chamadas públicas)
import os
import io
import re
import json
import unicodedata
import tempfile
from datetime import datetime

import pytz  # leve; ok manter no topo

# ───────────────────────── helpers ─────────────────────────

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


def limpar_json_invalido(json_str: str) -> str:
    # corrige deslizes comuns em JSON vindo de LLMs
    json_str = json_str.replace("(", "{").replace(")", "}")
    json_str = re.sub(r',\s*([}\]])', r'\1', json_str)
    json_str = re.sub(r'([a-zA-Z_]\w*)\s*:', r'"\1":', json_str)
    json_str = re.sub(r'\s+', ' ', json_str)
    return json_str


# ───────────────────── classe principal ────────────────────

class RelatorioAvaliacoes:
    """
    Mantém a API original:
      - __init__(avaliacoes, media_atual=None, analises=None, settings=None)
      - gerar_pdf(output)
    Incluí também gerar_grafico_temas_mais_falados / gerar_grafico_evolucao_notas
    (sem seaborn) e um gerar_grafico_media_historica compatível.
    """
    # Limites defensivos para não estourar RAM/CPU
    MAX_ROWS_DF = 2000              # máximo de linhas para gráficos
    MAX_RECORDS_PROMPT = 600        # máximo de itens no prompt da IA
    FIGSIZE_TEMAS = (9, 5)
    FIGSIZE_LINHA = (9, 4)

    def __init__(self, avaliacoes, media_atual=None, analises=None, settings=None):
        # Armazena linhas “leves”; DataFrame só quando necessário (lazy)
        self._rows = []
        for a in (avaliacoes or []):
            self._rows.append({
                "data": a.get("data"),
                "nota": a.get("nota"),
                "texto": a.get("texto") or a.get("text") or "",
                "respondida": a.get("respondida", 0),
                "tags": a.get("tags", ""),
            })
        self.media_atual = media_atual
        self.analises = analises
        self.settings = settings or {}

    # ── util interno: df sob demanda
    def _as_dataframe(self):
        import pandas as pd  # lazy
        base = self._rows[-self.MAX_ROWS_DF:] if len(self._rows) > self.MAX_ROWS_DF else self._rows
        return pd.DataFrame(base)

    # ── gráfico: temas (elogios x críticas) usando só matplotlib
    def gerar_grafico_temas_mais_falados(self, data_analise: dict, output_dir: str) -> str:
        if not data_analise or not isinstance(data_analise, dict):
            return ""
        temas_elogios = data_analise.get("temas_elogios", []) or []
        temas_criticas = data_analise.get("temas_criticas", []) or []

        if not temas_elogios and not temas_criticas:
            return ""

        # Normaliza e limita top-N
        def _norm(lista):
            out = []
            for item in lista:
                tema = (item.get("tema") or "").strip()
                try:
                    cont = int(item.get("contagem") or 0)
                except Exception:
                    cont = 0
                if tema and cont > 0:
                    out.append((tema, cont))
            # top 15 por contagem
            out.sort(key=lambda x: x[1], reverse=True)
            return out[:15]

        elog = _norm(temas_elogios)
        crit = _norm(temas_criticas)

        # Constrói vetores lado a lado
        temas = list({t for t, _ in elog} | {t for t, _ in crit})
        if not temas:
            return ""

        elog_map = dict(elog)
        crit_map = dict(crit)
        elog_vals = [elog_map.get(t, 0) for t in temas]
        crit_vals = [crit_map.get(t, 0) for t in temas]

        # Lazy matplotlib + backend Agg
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig = plt.figure(figsize=self.FIGSIZE_TEMAS)
        try:
            import numpy as np
            idx = np.arange(len(temas))
            bar_h = 0.35

            plt.barh(idx + bar_h/2, elog_vals, height=bar_h, label="Elogios")
            plt.barh(idx - bar_h/2, crit_vals, height=bar_h, label="Críticas")

            plt.yticks(idx, temas, fontsize=8)
            plt.xlabel("Frequência")
            plt.title("Temas Mais Mencionados (Elogios x Críticas)")
            plt.legend()
            plt.tight_layout()

            path = os.path.join(output_dir, "temas_falados.png")
            plt.savefig(path, dpi=140)
            return path
        finally:
            plt.close(fig)

    # ── gráfico: evolução de notas (linha simples)
    def gerar_grafico_evolucao_notas(self, data_analise: dict, output_dir: str) -> str:
        if not data_analise or not isinstance(data_analise, dict):
            return ""
        evolucao = data_analise.get("evolucao_notas", []) or []
        if not evolucao:
            return ""

        # Normaliza e ordena por data
        from datetime import datetime as _dt
        series = []
        for item in evolucao:
            sdata = str(item.get("data") or "").strip()
            try:
                # aceita YYYY-MM ou YYYY-MM-DD
                dt = _dt.strptime(sdata, "%Y-%m")
            except Exception:
                try:
                    dt = _dt.strptime(sdata, "%Y-%m-%d")
                except Exception:
                    continue
            try:
                nota = float(item.get("nota_media"))
            except Exception:
                continue
            series.append((dt, nota))

        if not series:
            return ""

        series.sort(key=lambda x: x[0])
        xs = [x for x, _ in series]
        ys = [y for _, y in series]

        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig = plt.figure(figsize=self.FIGSIZE_LINHA)
        try:
            plt.plot(xs, ys, marker="o")
            plt.title("Evolução da Nota Média ao Longo do Tempo")
            plt.xlabel("Data")
            plt.ylabel("Nota Média")
            fig.autofmt_xdate()
            plt.tight_layout()

            path = os.path.join(output_dir, "evolucao_notas.png")
            plt.savefig(path, dpi=140)
            return path
        finally:
            plt.close(fig)

    # ── gráfico compatível com a variante que usava “média por mês”
    def gerar_grafico_media_historica(self, output_dir: str) -> str:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        df = self._as_dataframe()
        try:
            import pandas as pd  # lazy
            # datas para BRT
            df["data"] = pd.to_datetime(df.get("data"), errors="coerce", utc=True)
            data_local = df["data"].dt.tz_convert("America/Sao_Paulo")
            df["data_local_naive"] = data_local.dt.tz_localize(None)

            if "nota" not in df.columns:
                df["nota"] = None

            notas_por_mes = (
                df.dropna(subset=["data_local_naive"])
                  .groupby(df["data_local_naive"].dt.to_period("M"))["nota"]
                  .mean()
            )

            fig = plt.figure(figsize=self.FIGSIZE_LINHA)
            if len(notas_por_mes) > 0:
                plt.plot(notas_por_mes.index.to_timestamp(), notas_por_mes.values, marker="o")
            else:
                plt.plot([], [])
            plt.title("Evolução da Nota Média por Mês")
            plt.xlabel("Mês")
            plt.ylabel("Nota Média")
            plt.tight_layout()

            path = os.path.join(output_dir, "evolucao_mensal.png")
            plt.savefig(path, dpi=140)
            return path
        finally:
            plt.close()

    # ── PDF principal (mantém assinatura de chamada)
    def gerar_pdf(self, output):
        # lazy imports pesados
        from fpdf import FPDF
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmpdir:
            pdf = FPDF()
            pdf.add_page()
            y_logo_offset = 10

            # ── Logo da empresa (fecha imagem SEMPRE)
            logo_bytes = self.settings.get("logo")
            if logo_bytes:
                img = None
                try:
                    img = Image.open(io.BytesIO(logo_bytes))
                    logo_path = os.path.join(tmpdir, "logo_temp.png")
                    img.save(logo_path, "PNG")

                    max_width_mm = 60
                    max_height_mm = 25
                    # aproximação de px→mm sem carregar libs extras
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
                finally:
                    try:
                        if img is not None:
                            img.close()
                    except Exception:
                        pass
            else:
                y_logo_offset = 20

            # ── Cabeçalho
            br_tz = pytz.timezone("America/Sao_Paulo")
            data_br = datetime.now(br_tz).strftime("%d/%m/%Y %H:%M")
            pdf.set_y(y_logo_offset)
            pdf.set_font("Arial", "B", 16)
            pdf.cell(0, 10, "Relatorio de Avaliacoes", ln=True, align="C")
            pdf.ln(5)
            pdf.set_font("Arial", "", 10)
            pdf.cell(0, 10, f"Data de geracao: {data_br}", ln=True)
            pdf.ln(1)

            # ── Métricas básicas
            df = self._as_dataframe()
            total_avaliacoes = len(df)
            try:
                media_nota = float(df["nota"].mean()) if total_avaliacoes > 0 else 0.0
            except Exception:
                media_nota = 0.0
            pdf.set_font("Arial", "", 12)
            pdf.cell(0, 10, f"Media de nota: {media_nota:.2f}", ln=True)
            if self.media_atual is not None:
                try:
                    pdf.cell(0, 10, f"Media Atual: {float(self.media_atual):.2f}", ln=True)
                except Exception:
                    pdf.cell(0, 10, "Media Atual: --", ln=True)
            pdf.ln(5)

            # datas localizadas auxiliares (sem explodir)
            try:
                import pandas as pd
                df["data"] = pd.to_datetime(df.get("data"), errors="coerce", utc=True)
                df["data_local"] = df["data"].dt.tz_convert("America/Sao_Paulo").dt.strftime("%d/%m/%Y %H:%M")
            except Exception:
                pass

            manager_name = (self.settings.get("manager_name") or "").strip()
            business_name = (self.settings.get("business_name") or "").strip()
            manager_str = f'O gerente responsavel e "{manager_name}".' if manager_name else ""

            # ── Dados p/ IA (limitados)
            if "texto" not in df.columns:
                df["texto"] = ""
            if "nota" not in df.columns:
                df["nota"] = None

            try:
                # reduz memória/tokens: últimas N avaliações
                if len(df) > self.MAX_RECORDS_PROMPT:
                    use_df = df.tail(self.MAX_RECORDS_PROMPT)
                else:
                    use_df = df
                dados_prompt = use_df[["nota", "texto"]].to_dict(orient="records")
            except Exception:
                dados_prompt = []

            # ── Prompt
            prompt = f"""
Voce e um analista senior de satisfacao do cliente. Gere um relatorio analitico detalhado para a diretoria da empresa "{business_name or 'EMPRESA'}", usando analise de sentimentos e metricas relevantes. Nao cite diretamente comentarios. Nao repita palavras.
{manager_str}

RESUMO EXECUTIVO
- Apresente panorama geral e principais insights.

ANALISE QUANTITATIVA
- Distribuicao das notas; percentual de positivas, neutras e negativas; temas frequentes.

ANALISE POR ESTRELA
- Para cada nota 1..5, sentimento predominante e sugestoes de acao.

PONTOS CRITICOS
- Minimo de 3 riscos/problemas.

DESTAQUES POSITIVOS
- 1 a 3 pontos fortes.

CONCLUSAO E RECOMENDACOES
- Acoes praticas para o proximo trimestre.

METODOLOGIA
- Informe que foi utilizada IA de linguagem natural (sem citar comentarios literais).

Regras: titulos em MAIUSCULAS; sem negrito/italico; texto objetivo, 2-5 paginas; sem repetir frases.

DADOS DAS AVALIACOES (amostra limitada):
{dados_prompt}
            """.strip()

            # ── IA (Gemini) — lazy import e tolerante a falhas
                        # ── IA (Gemini) — forçando modelo 1.5 Pro
            dados_gerados = {}
            analise_limpa = "A IA não retornou texto de análise."
            try:
                gemini_api_key = os.getenv("GEMINI_API_KEY")
                if not gemini_api_key:
                    raise ValueError("GEMINI_API_KEY ausente")

                import google.generativeai as genai  # lazy
                genai.configure(api_key=gemini_api_key)
                # força o Gemini 1.5 Pro
                model = genai.GenerativeModel("gemini-1.5-pro")

                response = model.generate_content(prompt)

                # tenta pegar texto de forma robusta
                response_text = ""
                if hasattr(response, "text") and response.text:
                    response_text = response.text
                elif getattr(response, "candidates", None):
                    parts = response.candidates[0].content.parts
                    response_text = "".join(getattr(p, "text", "") for p in parts)

                # se não veio nada, gera aviso
                if not response_text.strip():
                    response_text = "A IA não conseguiu gerar uma análise para os dados fornecidos."

                # tenta extrair JSON opcional
                json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
                if json_match:
                    try:
                        json_str = limpar_json_invalido(json_match.group(1))
                        dados_gerados = json.loads(json_str)
                    except Exception as e:
                        print(f"Erro ao parsear o JSON: {e}")
                        dados_gerados = {}

                final_analise = dados_gerados.get("analise_texto") or response_text
                analise_limpa = limpa_markdown(final_analise)

            except Exception as e:
                print(f"Erro ao gerar analise com IA (Gemini 1.5 Pro): {str(e)}")
                analise_limpa = "Falha na chamada ao Gemini 1.5 Pro. Verifique sua chave de API."


            # ── Texto da análise
            pdf.set_font("Arial", "B", 12)
            pdf.cell(0, 10, "Analise da IA sobre as Avaliacoes", ln=True)
            pdf.set_font("Arial", "", 11)
            pdf.multi_cell(0, 7, analise_limpa)
            pdf.ln(5)

            # ── Gráficos (todos fecham figura)
            # 1) Temas
            try:
                grafico_temas_path = self.gerar_grafico_temas_mais_falados(dados_gerados, tmpdir)
                if grafico_temas_path:
                    pdf.add_page()
                    pdf.set_font("Arial", "B", 12)
                    pdf.cell(0, 10, "Grafico de Temas Mais Mencionados:", ln=True)
                    largura = pdf.w - 2 * pdf.l_margin - 2
                    pdf.image(grafico_temas_path, x=pdf.l_margin + 1, w=largura)
                    pdf.ln(8)
            except Exception as e:
                print("Falha ao gerar gráfico de temas:", e)

            # 2) Evolução (se vier da IA)
            try:
                grafico_evol_path = self.gerar_grafico_evolucao_notas(dados_gerados, tmpdir)
                if grafico_evol_path:
                    pdf.add_page()
                    pdf.set_font("Arial", "B", 12)
                    pdf.cell(0, 10, "Grafico de Evolucao da Nota Media:", ln=True)
                    largura = pdf.w - 2 * pdf.l_margin - 2
                    pdf.image(grafico_evol_path, x=pdf.l_margin + 1, w=largura)
                    pdf.ln(8)
            except Exception as e:
                print("Falha ao gerar gráfico de evolução:", e)

            # 3) Evolução mensal (fallback se não houve dados de IA)
            if not dados_gerados.get("evolucao_notas"):
                try:
                    grafico_hist_path = self.gerar_grafico_media_historica(tmpdir)
                    if grafico_hist_path:
                        pdf.add_page()
                        pdf.set_font("Arial", "B", 12)
                        pdf.cell(0, 10, "Evolucao da Nota Media por Mes:", ln=True)
                        largura = pdf.w - 2 * pdf.l_margin - 2
                        pdf.image(grafico_hist_path, x=pdf.l_margin + 1, w=largura)
                        pdf.ln(8)
                except Exception as e:
                    print("Falha ao gerar gráfico mensal:", e)

            # ── Assinatura/rodapé (se houver)
            if manager_name or business_name:
                pdf.ln(8)
                pdf.set_font("Arial", "B", 12)
                if business_name:
                    pdf.cell(0, 10, f"{business_name}", ln=True)
                if manager_name:
                    pdf.cell(0, 10, f"{manager_name}", ln=True)

            # ── Saída: caminho (str) ou buffer (BytesIO)
            if isinstance(output, (str, os.PathLike)):
                pdf.output(output)
                print("PDF gerado com sucesso:", output)
            else:
                raw = pdf.output(dest="S")
                pdf_bytes = raw.encode("latin-1") if isinstance(raw, str) else raw
                output.write(pdf_bytes)
                output.seek(0)
                print("PDF gerado em buffer.")
