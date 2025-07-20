import pandas as pd
import matplotlib.pyplot as plt
from fpdf import FPDF
import tempfile
import os
import numpy as np
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
        self.df['data'] = pd.to_datetime(self.df['data'])
        notas_por_mes = self.df.groupby(self.df['data'].dt.to_period('M'))['nota'].mean()
        plt.figure(figsize=(9, 4))  # Mais largo e mais alto
        notas_por_mes.plot(kind='line', marker='o', color='#28a745')
        plt.title('Evolução da Nota Média por Mês')
        plt.xlabel('Mês')
        plt.ylabel('Nota Média')
        plt.tight_layout()
        grafico_path = os.path.join(output_dir, "evolucao_medio.png")
        plt.savefig(grafico_path, dpi=130)  # DPI maior para qualidade boa
        plt.close()
        return grafico_path

    def gerar_pdf(self, output):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Prepara PDF
            pdf = FPDF()
            pdf.add_page()
            y_logo_offset = 10

            # --- LOGO DA EMPRESA ---
            logo_bytes = self.settings.get('logo')
            if logo_bytes:
                try:
                    img = Image.open(io.BytesIO(logo_bytes))
                    logo_path = os.path.join(tmpdir, "logo_temp.png")
                    max_width = 140
                    max_height = 60
                    img.thumbnail((max_width, max_height))
                    img.save(logo_path, "PNG")
                    img_width, img_height = img.size
                    page_width = pdf.w - 2 * pdf.l_margin
                    x_pos = (pdf.w - img_width) / 2
                    pdf.image(logo_path, x=x_pos, y=y_logo_offset, w=img_width, h=img_height)
                    y_logo_offset += img_height + 7
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
            pdf.cell(0, 10, f"Média Atual: {self.media_atual:.2f}", ln=True)
            pdf.ln(5)

            # --- ANÁLISE DA IA ---
            prompt = f"""
Você é um analista sênior de satisfação do cliente. Gere um relatório analítico detalhado para a diretoria da empresa "{self.settings.get('business_name', 'EMPRESA')}", usando análise de sentimentos e métricas relevantes. Não cite diretamente comentários. Não repita palavras.

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

                # === Divide para inserir o gráfico após RESUMO EXECUTIVO ===
                if "ANÁLISE QUANTITATIVA" in analise_limpa:
                    partes = analise_limpa.split("ANÁLISE QUANTITATIVA", 1)
                    # Parte 0: Resumo Executivo e o que vier antes
                    pdf.multi_cell(0, 7, partes[0].strip())
                    pdf.ln(4)
                    # Gráfico GRANDE após Resumo Executivo
                    grafico_media_path = self.gerar_grafico_media_historica(tmpdir)
                    largura_grafico = pdf.w - 2*pdf.l_margin - 2
                    pdf.set_font("Arial", '', 12)
                    pdf.cell(0, 10, "Evolução da Nota Média por Mês:", ln=True)
                    pdf.image(grafico_media_path, x=pdf.l_margin+1, w=largura_grafico)
                    pdf.ln(8)
                    # Continua a partir da Análise Quantitativa
                    pdf.set_font("Arial", '', 11)
                    pdf.multi_cell(0, 7, "ANÁLISE QUANTITATIVA" + partes[1].strip())
                else:
                    # fallback
                    pdf.multi_cell(0, 7, analise_limpa)

            except Exception as e:
                print(f"Erro ao gerar análise com IA: {str(e)}")
                pdf.multi_cell(0, 7, f"Erro ao gerar análise com IA: {str(e)}")

            if isinstance(output, str):
                pdf.output(output)
                print("PDF gerado com sucesso:", output)
            else:
                pdf_bytes = pdf.output(dest='S')
                output.write(pdf_bytes)
                output.seek(0)
                print("PDF gerado em buffer.")

# --- Exemplo de uso/teste ---
if __name__ == "__main__":
    avaliacoes = [
        {'data': '2024-06-01', 'nota': 5, 'texto': 'Excelente atendimento!', 'respondida': 1, 'tags': 'atendimento'},
        {'data': '2024-06-02', 'nota': 4, 'texto': 'Muito bom, mas pode melhorar.', 'respondida': 1, 'tags': 'preço'},
        {'data': '2024-06-05', 'nota': 2, 'texto': 'Demorou demais.', 'respondida': 0, 'tags': 'atraso'},
    ]

    # Exemplo de user_settings com logo (leia os bytes de um arquivo PNG/JPG real se for testar no PC)
    with open("logo_da_empresa.png", "rb") as f:
        logo_bytes = f.read()

    user_settings = {
        "business_name": "Padaria do João",
        "logo": logo_bytes,
    }
    media_atual = 4.2

    rel = RelatorioAvaliacoes(avaliacoes, media_atual=media_atual, settings=user_settings)
    rel.gerar_pdf("relatorio_avaliacoes.pdf")
