import pandas as pd
import matplotlib.pyplot as plt
from fpdf import FPDF
from wordcloud import WordCloud
import tempfile
import os

class RelatorioAvaliacoes:
    def __init__(self, avaliacoes):
        # avaliacoes: lista de dicionários. Cada dict: {'data', 'nota', 'texto', 'respondida', 'resposta', 'tags', ...}
        self.df = pd.DataFrame(avaliacoes)

    def gerar_graficos(self, output_dir):
        # Distribuição das notas
        plt.figure(figsize=(5, 3))
        self.df['nota'].value_counts().sort_index().plot(kind='bar', color='#007bff')
        plt.title('Distribuição das Notas')
        plt.xlabel('Nota')
        plt.ylabel('Quantidade')
        plt.tight_layout()
        nota_grafico = os.path.join(output_dir, "notas.png")
        plt.savefig(nota_grafico)
        plt.close()

        # Evolução da nota média ao longo do tempo
        self.df['data'] = pd.to_datetime(self.df['data'])
        notas_por_mes = self.df.groupby(self.df['data'].dt.to_period('M'))['nota'].mean()
        plt.figure(figsize=(5, 3))
        notas_por_mes.plot(kind='line', marker='o', color='#28a745')
        plt.title('Evolução da Nota Média')
        plt.xlabel('Mês')
        plt.ylabel('Nota Média')
        plt.tight_layout()
        evolucao_grafico = os.path.join(output_dir, "evolucao.png")
        plt.savefig(evolucao_grafico)
        plt.close()

        # Wordcloud
        all_text = " ".join(self.df['texto'].fillna(''))
        wordcloud = WordCloud(width=400, height=200, background_color='white').generate(all_text)
        wordcloud_path = os.path.join(output_dir, "wordcloud.png")
        wordcloud.to_file(wordcloud_path)

        return nota_grafico, evolucao_grafico, wordcloud_path

    def gerar_pdf(self, output_path):
        # Cria gráficos em temp files
        with tempfile.TemporaryDirectory() as tmpdir:
            nota_grafico, evolucao_grafico, wordcloud_path = self.gerar_graficos(tmpdir)

            pdf = FPDF()
            pdf.add_page()

            pdf.set_font("Arial", 'B', 16)
            pdf.cell(0, 10, "Relatório de Avaliações", ln=True, align='C')
            pdf.ln(5)

            # Visão Geral
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
            pdf.ln(5)

            # Gráfico distribuição das notas
            pdf.cell(0, 8, "Distribuição das Notas:", ln=True)
            pdf.image(nota_grafico, w=100)
            pdf.ln(5)

            # Gráfico evolução da nota
            pdf.cell(0, 8, "Evolução da Nota Média:", ln=True)
            pdf.image(evolucao_grafico, w=100)
            pdf.ln(5)

            # Wordcloud
            pdf.cell(0, 8, "Principais Palavras das Avaliações:", ln=True)
            pdf.image(wordcloud_path, w=100)
            pdf.ln(5)

            # Análise breve por nota (exemplo)
            for star in range(5, 0, -1):
                qtd = (self.df['nota'] == star).sum()
                pct = (qtd / total_avaliacoes * 100) if total_avaliacoes > 0 else 0
                pdf.set_font("Arial", 'B', 11)
                pdf.cell(0, 8, f"Avaliações {star} estrela(s): {qtd} ({pct:.1f}%)", ln=True)
                pdf.set_font("Arial", '', 10)
                frases = self.df[self.df['nota'] == star]['texto'].head(3).tolist()
                for frase in frases:
                    pdf.multi_cell(0, 6, f"- {frase[:120]}", ln=True)
                pdf.ln(2)

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
    rel = RelatorioAvaliacoes(avaliacoes)
    rel.gerar_pdf("relatorio_avaliacoes.pdf")
