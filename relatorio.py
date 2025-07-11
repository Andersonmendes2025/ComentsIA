import pandas as pd
import matplotlib.pyplot as plt
from fpdf import FPDF
from wordcloud import WordCloud
import tempfile
import os
import numpy as np
from datetime import datetime
from openai import OpenAI
import re

import re

def limpa_markdown(texto):
    # Remove títulos tipo #, ##, ###
    texto = re.sub(r'^\s*#+\s*', '', texto, flags=re.MULTILINE)
    # Remove negritos **
    texto = re.sub(r'\*\*([^*]+)\*\*', r'\1', texto)
    # Remove bullets -, *, números seguidos de ponto
    texto = re.sub(r'^[\-\*]\s+', '', texto, flags=re.MULTILINE)
    texto = re.sub(r'^\d+\.\s+', '', texto, flags=re.MULTILINE)
    # Remove linhas horizontais ---
    texto = re.sub(r'^---+', '', texto, flags=re.MULTILINE)
    # Remove excesso de espaços em branco
    texto = re.sub(r'\n{3,}', '\n\n', texto)
    return texto.strip()

class RelatorioAvaliacoes:
    def __init__(self, avaliacoes, media_atual=None, analises=None, settings=None):
        self.df = pd.DataFrame(avaliacoes)
        self.media_atual = media_atual
        self.analises = analises
        self.settings = settings or {}

    def gerar_grafico_media_historica(self, output_dir):
        # Evolução da nota média ao longo do tempo
        self.df['data'] = pd.to_datetime(self.df['data'])
        notas_por_mes = self.df.groupby(self.df['data'].dt.to_period('M'))['nota'].mean()
        plt.figure(figsize=(5, 3))
        notas_por_mes.plot(kind='line', marker='o', color='#28a745')
        plt.title('Evolução da Nota Média')
        plt.xlabel('Mês')
        plt.ylabel('Nota Média')
        plt.tight_layout()
        grafico_path = os.path.join(output_dir, "evolucao_medio.png")
        plt.savefig(grafico_path)
        plt.close()

        return grafico_path

    # Função para analisar os pontos positivos e negativos
    def gerar_pdf(self, output_path):
        with tempfile.TemporaryDirectory() as tmpdir:
            print("Gerando gráfico...")
            grafico_media_path = self.gerar_grafico_media_historica(tmpdir)
            print("Gráfico gerado:", grafico_media_path)

            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", 'B', 16)
            pdf.cell(0, 10, "Relatório de Avaliações", ln=True, align='C')
            pdf.ln(5)

            total_avaliacoes = len(self.df)
            media_nota = self.df['nota'].mean() if total_avaliacoes > 0 else 0

            print("Adicionando dados ao PDF...")
            pdf.set_font("Arial", '', 12)
            pdf.cell(0, 10, f"Média de nota: {media_nota:.2f}", ln=True)
            pdf.cell(0, 10, f"Média Atual: {self.media_atual:.2f}", ln=True)
            pdf.ln(5)

            print("Adicionando gráfico ao PDF...")
            pdf.cell(0, 8, "Evolução da Média de Notas:", ln=True)
            pdf.image(grafico_media_path, w=100)
            pdf.ln(5)

            # Prompt customizável (pode trocar o texto conforme acima)
            prompt = f"""
            Você é um analista sênior de satisfação do cliente. Gere um relatório analítico detalhado para a diretoria da empresa "{self.settings.get('business_name', 'EMPRESA')}", usando análise de sentimentos e métricas relevantes. Não cite diretamente comentários. Não repita palavras. Siga este roteiro:

            1. Resumo Executivo: Panorama geral, tendências e insights mais importantes.
            2. Análise Quantitativa: Distribuição das notas, % de avaliações positivas, neutras e negativas. Temas e palavras mais frequentes.
            3. Análise por Estrela: Para cada nota de 1 a 5, explique o sentimento predominante, pontos principais e sugestões de resposta/ação.
            4. Pontos Críticos (mínimo 3): Destaque os principais problemas ou riscos.
            5. Destaques Positivos (1 a 3): Aponte pontos fortes e diferenciais competitivos.
            6. Conclusão e Recomendações: Ações práticas para o próximo trimestre, oportunidades e estratégias para melhorar a satisfação.
            7. Metodologia: Diga que foi usado IA com análise de sentimentos e linguagem natural, sem citar comentários literais.

            - Se os comentários forem inconclusivos, ressalte.
            - O relatório deve ter de 2 a 5 páginas, claro, objetivo, sem repetição.

            DADOS DAS AVALIAÇÕES:
            {self.df[['nota', 'texto']].to_dict(orient='records')}
            """

            try:
                client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
                completion = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "system", "content": "Você é um assistente especializado em análise de satisfação do cliente."},
                            {"role": "user", "content": prompt}]
                )

                analise_gerada = completion.choices[0].message.content.strip()
                analise_limpa = limpa_markdown(analise_gerada)
                pdf.set_font("Arial", 'B', 12)
                pdf.cell(0, 10, "Análise da IA sobre as Avaliações", ln=True)
                pdf.set_font("Arial", '', 11)
                pdf.multi_cell(0, 7, analise_limpa)
            except Exception as e:
                print(f"Erro ao gerar análise com IA: {str(e)}")
                pdf.multi_cell(0, 7, f"Erro ao gerar análise com IA: {str(e)}")

            pdf.output(output_path)
            print("PDF gerado com sucesso:", output_path)



def limpa_markdown(texto):
    # Remove títulos tipo #, ##, ###
    texto = re.sub(r'^\s*#+\s*', '', texto, flags=re.MULTILINE)
    # Remove negritos **
    texto = re.sub(r'\*\*([^*]+)\*\*', r'\1', texto)
    # Remove bullets -, *, números seguidos de ponto
    texto = re.sub(r'^[\-\*]\s+', '', texto, flags=re.MULTILINE)
    texto = re.sub(r'^\d+\.\s+', '', texto, flags=re.MULTILINE)
    # Remove linhas horizontais ---
    texto = re.sub(r'^---+', '', texto, flags=re.MULTILINE)
    # Remove excesso de espaços em branco
    texto = re.sub(r'\n{3,}', '\n\n', texto)
    return texto.strip()

# Exemplo de uso:
if __name__ == "__main__":
    # Simulação de avaliações
    avaliacoes = [
        {'data': '2024-06-01', 'nota': 5, 'texto': 'Excelente atendimento!', 'respondida': 1, 'tags': 'atendimento'},
        {'data': '2024-06-02', 'nota': 4, 'texto': 'Muito bom, mas pode melhorar.', 'respondida': 1, 'tags': 'preço'},
        {'data': '2024-06-05', 'nota': 2, 'texto': 'Demorou demais.', 'respondida': 0, 'tags': 'atraso'},
        # ... adicione suas avaliações aqui
    ]
    
    media_atual = 4.2  # Exemplo de média
    projecao_30_dias = 4.4  # Exemplo de projeção para os próximos 30 dias
    
    rel = RelatorioAvaliacoes(avaliacoes, media_atual=media_atual, settings=user_settings)
    rel.gerar_pdf("relatorio_avaliacoes.pdf")
