# CLAUDE.md — Contexto e Diretrizes do Projeto ComentsIA para Claude

Este documento fornece as instruções oficiais de arquitetura, padrões de desenvolvimento, comandos de execução e regras de negócio para o **Claude (Anthropic)** e Claude Code neste repositório.

---

## 🏢 1. Visão Geral do Projeto

O **ComentsIA** é uma plataforma SaaS corporativa desenvolvida para automação, monitoramento e resposta inteligente a avaliações do **Google Business Profile (Google Meu Negócio)**, **iFood** e **Mercado Livre**.

### Principais Funcionalidades:
- **Respostas Automatizadas com IA**: Geração de respostas contextuais utilizando Anthropic (Claude 3.7 / 3.5 Sonnet / Haiku), OpenAI (GPT-4o) e Google Gemini.
- **Multilíngue Inteligente**: Detecção automática do idioma do cliente e geração de respostas em múltiplos idiomas (PT-BR, PT-PT, EN, ES, FR, DE, IT).
- **Personalização de Tom de Voz**: 5 estilos corporativos calibrados (*Profissional*, *Amigável*, *Empático*, *Direto*, *Luxo/Sofisticado*).
- **Gestão Multi-Fichas / Filiais**: Painel individual para cada filial do Google com herança e sobreposição de configurações globais.
- **Relatórios Executivos em PDF**: Auditoria completa com fidelidade matemática 100%, gráficos de 300 DPI (Matplotlib) e parecer estratégico por IA.
- **Integração de Pagamentos**: Stripe e Mercado Pago para assinaturas e add-ons de slots extras de monitoramento.

---

## 🛠️ 2. Stack Tecnológica & Dependências

- **Linguagem Principal**: Python 3.11+ / Python 3.14
- **Framework Web**: Flask (com Blueprints, Flask-Login, Flask-WTF, Flask-Limiter, Flask-Migrate)
- **Banco de Dados & ORM**: SQLite (desenvolvimento) / PostgreSQL (produção no Render) via SQLAlchemy
- **Modelos de IA**:
  - Anthropic (`anthropic` -> `claude-3-7-sonnet-20250219`, `claude-3-5-sonnet-20241022`, `claude-3-5-haiku-20241022`)
  - OpenAI (`openai` -> `gpt-4o`, `gpt-4o-mini`)
  - Google Generative AI (`google-generativeai` -> `gemini-2.0-flash`, `gemini-3.7-flash`)
- **Geração de PDF**: `fpdf2` (versão 2.8+)
- **Visualização de Dados**: Matplotlib 3.x (Agg backend), Chart.js 4.4 (frontend)
- **Front-end**: Jinja2, HTML5 semântico, Bootstrap 5.3, Bootstrap Icons, CSS3 Glassmorphism (Google Material)
- **CI/CD & Deploy**: GitHub Actions + Render Cloud

---

## 🚀 3. Comandos de Ambiente, Execução e Testes

### Ativação do Ambiente Virtual:
```bash
# Windows
venv\Scripts\activate
# Linux/macOS
source venv/bin/activate
```

### Instalação de Dependências:
```bash
pip install -r requirements.txt
```

### Executar a Aplicação Localmente:
```bash
# Windows
venv\Scripts\python.exe main.py
# Linux/macOS
python main.py
```
*O servidor roda por padrão em `http://127.0.0.1:8000`*.

### Executar a Suíte de Testes (Pytest):
```bash
# Executar todos os testes
venv\Scripts\python.exe -m pytest

# Executar arquivo específico
venv\Scripts\python.exe -m pytest tests/test_relatorio.py
venv\Scripts\python.exe -m pytest tests/test_ai_service.py
venv\Scripts\python.exe -m pytest tests/test_google_location.py
```

---

## 📐 4. Regras de Código & Boas Práticas

1. **Integridade de Documentação e Testes**:
   - Sempre execute `pytest` antes de finalizar uma tarefa.
   - Novas funcionalidades devem vir acompanhadas de testes unitários na pasta `tests/`.
2. **Consistência Numérica e Factual na IA**:
   - Nunca permita que a IA recalcule ou invente números diferentes das estatísticas calculadas pelo backend Python.
3. **Design & Estética Google Executive**:
   - Mantenha temas claros, contraste alto, cards translúcidos (*glassmorphism*) e fontes modernas (*Outfit* / *Inter*).
4. **Segurança & Variáveis de Ambiente**:
   - Nunca commite chaves de API (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`).
   - Use `os.getenv()` com variáveis carregadas via `.env`.
5. **Compatibilidade com Render**:
   - Manter configurações em [render.yaml](file:///c:/Users/Anderson%20Mendes/Documents/ComentsIA/render.yaml) atualizadas para deploy contínuo via GitHub.
