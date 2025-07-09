import pandas as pd
import matplotlib.pyplot as plt
from fpdf import FPDF
from wordcloud import WordCloud
import tempfile
import os
import numpy as np
from datetime import datetime

class RelatorioAvaliacoes:
    def __init__(self, avaliacoes, media_atual=None, analises=None):
        """
        Inicializa a classe com a lista de avaliações e a análise das estrelas.
        
        :param avaliacoes: Lista de avaliações
        :param media_atual: Média atual das notas
        :param analises: Análises por estrelas
        """
        self.df = pd.DataFrame(avaliacoes)
        self.media_atual = media_atual
        self.analises = analises

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

    def gerar_pdf(self, output_path):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Gerar gráficos
            grafico_media_path = self.gerar_grafico_media_historica(tmpdir)

            # Criando o PDF
            pdf = FPDF()
            pdf.add_page()

            # Cabeçalho
            pdf.set_font("Arial", 'B', 16)
            pdf.cell(0, 10, "Relatório de Avaliações", ln=True, align='C')
            pdf.ln(5)

            # Visão geral
            total_avaliacoes = len(self.df)
            media_nota = self.df['nota'].mean() if total_avaliacoes > 0 else 0

            pdf.set_font("Arial", '', 12)
            pdf.cell(0, 10, f"Média de nota: {media_nota:.2f}", ln=True)
            pdf.cell(0, 10, f"Média Atual: {self.media_atual:.2f}", ln=True)
            pdf.ln(5)

            # Gráfico de média histórica
            pdf.cell(0, 8, "Evolução da Média de Notas:", ln=True)
            pdf.image(grafico_media_path, w=100)
            pdf.ln(5)

            # Análise gerada pela IA
            prompt = f""" Você é uma analista de satisfação do cliente. Com base nas avaliações abaixo, escreva um relatório analítico levando em consideração as estrelas e os comentários, mas sem citar diretamente os comentários. Não repita as informações dos comentários, apenas forneça uma análise geral. Para cada quantidade de estrelas (1 a 5), escreva um tópico descrevendo a percepção geral das avaliações com base nas avaliações que deram essa quantidade de estrelas. 
            
            Avaliações: {self.df[['nota', 'texto']].to_dict(orient='records')} """

            try:
                client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
                completion = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "system", "content": "Você é um assistente especializado em análise de satisfação do cliente."},
                              {"role": "user", "content": prompt}]
                )

                analise_gerada = completion.choices[0].message.content.strip()

                pdf.set_font("Arial", 'B', 12)
                pdf.cell(0, 10, "Análise da IA sobre as Avaliações", ln=True)
                pdf.set_font("Arial", '', 11)
                pdf.multi_cell(0, 7, analise_gerada)
            except Exception as e:
                pdf.multi_cell(0, 7, f"Erro ao gerar análise com IA: {str(e)}")

            pdf.output(output_path)


    # Função para analisar os pontos positivos e negativos
def gerar_pdf(self, output_path):
    with tempfile.TemporaryDirectory() as tmpdir:
        # Gerar gráficos e salvar
        nota_grafico, evolucao_grafico, wordcloud_path = self.gerar_graficos(tmpdir)

        # Criando o PDF
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", 'B', 16)
        pdf.cell(0, 10, "Relatório de Avaliações", ln=True, align='C')
        pdf.ln(5)

        # Visão geral das avaliações
        total_avaliacoes = len(self.df)
        total_respostas = self.df['respondida'].sum()
        taxa_resposta = (total_respostas / total_avaliacoes * 100) if total_avaliacoes > 0 else 0
        media_nota = self.df['nota'].mean() if total_avaliacoes > 0 else 0

        pdf.set_font("Arial", '', 12)
        pdf.cell(0, 10, f"Período analisado: {self.df['data'].min().strftime('%d/%m/%Y')} até {self.df['data'].max().strftime('%d/%m/%Y')}", ln=True)
        pdf.cell(0, 8, f"Total de avaliações: {total_avaliacoes}", ln=True)
        pdf.cell(0, 8, f"Total de respostas: {total_respostas}", ln=True)
        pdf.cell(0, 8, f"Taxa de resposta: {taxa_resposta:.1f}%", ln=True)
        pdf.cell(0, 8, f"Média de nota: {media_nota:.2f}", ln=True)
        pdf.cell(0, 8, f"Média Atual: {self.media_atual:.2f}", ln=True)  # Exibe a média atual
        pdf.cell(0, 8, f"Projeção de nota para os próximos 30 dias: {self.projecao_30_dias:.2f}", ln=True)  # Exibe a projeção
        pdf.ln(5)

        # Adicionando gráficos
        pdf.cell(0, 8, "Distribuição das Notas:", ln=True)
        pdf.image(nota_grafico, w=100)
        pdf.ln(5)

        pdf.cell(0, 8, "Evolução da Nota Média:", ln=True)
        pdf.image(evolucao_grafico, w=100)
        pdf.ln(5)

        pdf.cell(0, 8, "Principais Palavras das Avaliações:", ln=True)
        pdf.image(wordcloud_path, w=100)
        pdf.ln(5)

        # Analisando os pontos positivos e negativos
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, "Pontos Positivos", ln=True)
        pdf.set_font("Arial", '', 11)

        # Verificar e preencher os pontos positivos
        if self.analises.get(5):  # Verifica se há pontos positivos
            for ponto in self.analises.get(5, {}).get('comentarios', []):
                pdf.multi_cell(0, 6, f"- {ponto[0]} ({ponto[1]} menções)", ln=True)
        else:
            pdf.multi_cell(0, 6, "- Nenhum ponto positivo identificado", ln=True)
        pdf.ln(5)

        # Adicionando a análise dos pontos negativos
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, "Pontos Negativos", ln=True)
        pdf.set_font("Arial", '', 11)

        if self.analises.get(1):  # Verifica se há pontos negativos
            for ponto in self.analises.get(1, {}).get('comentarios', []):
                pdf.multi_cell(0, 6, f"- {ponto[0]} ({ponto[1]} menções)", ln=True)
        else:
            pdf.multi_cell(0, 6, "- Nenhum ponto negativo identificado", ln=True)
        pdf.ln(5)

        # Conclusão
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, "Conclusão e Recomendações", ln=True)
        pdf.set_font("Arial", '', 11)
        pdf.multi_cell(0, 7, "Aqui entra uma análise automatizada e profissional sobre tendências, pontos de melhoria e pontos fortes, baseada nos dados do período.")
        
        pdf.output(output_path)


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
    
    rel = RelatorioAvaliacoes(avaliacoes, media_atual, projecao_30_dias, analises)
    rel.gerar_pdf("relatorio_avaliacoes.pdf")
