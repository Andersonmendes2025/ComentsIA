import pandas as pd
import matplotlib.pyplot as plt
from fpdf import FPDF
import tempfile
import os
from datetime import datetime
from openai import OpenAI
import re
import unicodedata
import pytz
from PIL import Image
import io

def limpa_markdown(texto):
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
        self.df = pd.DataFrame(avaliacoes)
        self.media_atual = media_atual
        self.analises = analises
        self.settings = settings or {}

    def gerar_grafico_media_historica(self, output_dir):
        # Converte a coluna 'data' com segurança, tratando valores inválidos e timezone
        self.df['data'] = pd.to_datetime(self.df['data'], errors='coerce', utc=True).dt.tz_convert('America/Sao_Paulo')

        # Cria uma coluna formatada para exibir datas no relatório
        self.df['data_local'] = self.df['data'].dt.strftime('%d/%m/%Y %H:%M')
        notas_por_mes = self.df.groupby(self.df['data'].dt.to_period('M'))['nota'].mean()
        plt.figure(figsize=(9, 4))  # Gráfico largo
        notas_por_mes.plot(kind='line', marker='o', color='#28a745')
        plt.title('Evolução da Nota Média por Mês')
        plt.xlabel('Mês')
        plt.ylabel('Nota Média')
        plt.tight_layout()
        grafico_path = os.path.join(output_dir, "evolucao_medio.png")
        plt.savefig(grafico_path, dpi=140)
        plt.close()
        return grafico_path

    def gerar_pdf(self, output):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf = FPDF()
            pdf.add_page()
            y_logo_offset = 10

            # --- LOGO DA EMPRESA ---
            logo_bytes = self.settings.get('logo')
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
                except Exception as e:
                    print("Erro ao processar logo:", e)
                    y_logo_offset = 20
            else:
                y_logo_offset = 20

            # --- Cabeçalho e informações básicas ---
            br_tz = pytz.timezone('America/Sao_Paulo')
            data_br = datetime.now(br_tz).strftime('%d/%m/%Y %H:%M')
            pdf.set_y(y_logo_offset)
            pdf.set_font("Arial", 'B', 16)
            pdf.cell(0, 10, "Relatório de Avaliações", ln=True, align='C')
            pdf.ln(5)
            pdf.set_font("Arial", '', 10)
            pdf.cell(0, 10, f"Data de geração: {data_br}", ln=True)
            pdf.ln(1)

            total_avaliacoes = len(self.df)
            media_nota = self.df['nota'].mean() if total_avaliacoes > 0 else 0
            pdf.set_font("Arial", '', 12)
            pdf.cell(0, 10, f"Média de nota: {media_nota:.2f}", ln=True)
            if self.media_atual is not None:
                pdf.cell(0, 10, f"Média Atual: {self.media_atual:.2f}", ln=True)
            pdf.ln(5)

            # Opcional: formatar a data de cada avaliação no DataFrame (para uso posterior, se quiser)
            self.df['data_local'] = pd.to_datetime(self.df['data']).dt.tz_convert('America/Sao_Paulo').dt.strftime('%d/%m/%Y %H:%M')

            manager_name = self.settings.get("manager_name")
            manager_str = f'O gerente responsável é "{manager_name}".' if manager_name else ""

            # --- ANÁLISE DA IA ---
            prompt = f"""
    Você é um analista sênior de satisfação do cliente. Gere um relatório analítico detalhado para a diretoria da empresa "{self.settings.get('business_name', 'EMPRESA')}", usando análise de sentimentos e métricas relevantes. Não cite diretamente comentários. Não repita palavras.
    {manager_str}

    Estruture o relatório com tópicos bem destacados, assim:

    RESUMO EXECUTIVO
    - Apresente um panorama geral, principais tendências e os insights mais importantes.

    ANÁLISE QUANTITATIVA
    - Mostre a distribuição das notas.
    - Informe o percentual de avaliações positivas, neutras e negativas.
    - Apresente os temas e palavras mais frequentes.

    ANÁLISE POR ESTRELA
    - Para cada nota de 1 a 5, explique o sentimento predominante, pontos principais e sugestões de resposta ou ação.

    PONTOS CRÍTICOS
    - Destaque no mínimo 3 principais problemas ou riscos identificados.

    DESTAQUES POSITIVOS
    - Aponte de 1 a 3 pontos fortes e diferenciais competitivos da empresa.

    CONCLUSÃO E RECOMENDAÇÕES
    - Apresente ações práticas para o próximo trimestre, oportunidades de melhoria e estratégias para aumentar a satisfação dos clientes.

    METODOLOGIA
    - Informe que foi utilizado IA com análise de sentimentos e linguagem natural, sem citar comentários literais.

    ORIENTAÇÕES ADICIONAIS:
    - Se os comentários forem inconclusivos, ressalte esse ponto.
    - Não use negrito, itálico ou sublinhado: apenas destaque cada tópico com o TÍTULO EM MAIÚSCULAS no início de cada seção.
    - Não repita palavras, não cite comentários literais.
    - O relatório deve ser claro, bem detalhado, objetivo, sem repetição e com extensão entre 2 e 5 páginas.

    Siga exatamente esse roteiro, mantendo os títulos dos tópicos conforme o exemplo acima.

    DADOS DAS AVALIAÇÕES:
    {self.df[['nota', 'texto']].to_dict(orient='records')}
            """

            try:
                client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
                completion = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "Você é um assistente especializado em análise de satisfação do cliente."},
                        {"role": "user", "content": prompt}
                    ]
                )
                analise_gerada = completion.choices[0].message.content.strip()
                analise_limpa = limpa_markdown(analise_gerada)
                pdf.set_font("Arial", 'B', 12)
                pdf.cell(0, 10, "Análise da IA sobre as Avaliações", ln=True)
                pdf.set_font("Arial", '', 11)

                partes = analise_limpa.split("ANÁLISE QUANTITATIVA", 1)
                if len(partes) == 2:
                    pdf.multi_cell(0, 7, partes[0].strip())
                    pdf.ln(4)
                    grafico_media_path = self.gerar_grafico_media_historica(tmpdir)
                    largura_grafico = pdf.w - 2*pdf.l_margin - 2
                    pdf.set_font("Arial", '', 12)
                    pdf.cell(0, 10, "Evolução da Nota Média por Mês:", ln=True)
                    pdf.image(grafico_media_path, x=pdf.l_margin+1, w=largura_grafico)
                    pdf.ln(8)
                    pdf.set_font("Arial", '', 11)
                    pdf.multi_cell(0, 7, "ANÁLISE QUANTITATIVA" + partes[1].strip())
                else:
                    pdf.multi_cell(0, 7, analise_limpa)
                    pdf.ln(4)
                    grafico_media_path = self.gerar_grafico_media_historica(tmpdir)
                    largura_grafico = pdf.w - 2*pdf.l_margin - 2
                    pdf.set_font("Arial", '', 12)
                    pdf.cell(0, 10, "Evolução da Nota Média por Mês:", ln=True)
                    pdf.image(grafico_media_path, x=pdf.l_margin+1, w=largura_grafico)
                    pdf.ln(8)

            except Exception as e:
                print(f"Erro ao gerar análise com IA: {str(e)}")
                pdf.multi_cell(0, 7, f"Erro ao gerar análise com IA: {str(e)}")

            if manager_name:
                pdf.ln(8)
                pdf.set_font("Arial", 'B', 12)
                pdf.cell(0, 10, f"{self.settings['business_name']}", ln=True)
                pdf.cell(0, 10, f"{manager_name}", ln=True)

            if isinstance(output, str):
                pdf.output(output)
                print("PDF gerado com sucesso:", output)
            else:
                pdf_bytes = pdf.output(dest='S')
                output.write(pdf_bytes)
                output.seek(0)
                print("PDF gerado em buffer.")
