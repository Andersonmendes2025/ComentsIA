# AGENTS.md — Contexto e Diretrizes do Projeto ComentsIA para o Jules (Google Coding Agent)

Este documento fornece as instruções oficiais de arquitetura, padrões de desenvolvimento, comandos de execução e regras de negócio para o **Google Jules** e outros agentes de IA que atuam neste repositório.

---

## 🏢 1. Visão Geral do Projeto

O **ComentsIA** é uma plataforma SaaS corporativa desenvolvida para automação, monitoramento e resposta inteligente a avaliações do **Google Business Profile (Google Meu Negócio)** e outros canais de feedback.

### Principais Funcionalidades:
- **Respostas Automatizadas com IA**: Geração de respostas contextuais utilizando OpenAI (GPT-4o) e Gemini.
- **Multilíngue Inteligente**: Detecção automática do idioma do cliente e geração de respostas em múltiplos idiomas (PT-BR, PT-PT, EN, ES, FR, DE, IT).
- **Personalização de Tom de Voz**: 5 estilos corporativos calibrados (*Profissional*, *Amigável*, *Empático*, *Direto*, *Luxo/Sofisticado*).
- **Gestão Multi-Fichas / Filiais**: Painel individual para cada filial do Google com herança e sobreposição de configurações globais.
- **Relatórios Executivos em PDF**: Auditoria completa com fidelidade matemática 100%, gráficos de 300 DPI (Matplotlib) e parecer estratégico via GPT-4o.
- **Integração de Pagamentos**: Stripe e Mercado Pago para assinaturas e add-ons de slots extras de monitoramento.

---

## 🛠️ 2. Stack Tecnológica & Dependências

- **Linguagem Principal**: Python 3.11+ / Python 3.14
- **Framework Web**: Flask (com Blueprints, Flask-Login, Flask-WTF, Flask-Limiter, Flask-Migrate)
- **Banco de Dados & ORM**: SQLite (desenvolvimento) / PostgreSQL (produção) via SQLAlchemy
- **Modelos de IA**: OpenAI API (`gpt-4o`, `gpt-4o-mini`), Google Generative AI (`gemini-2.0-flash`)
- **Geração de PDF**: `fpdf2` (versão 2.8+)
- **Visualização de Dados**: Matplotlib 3.x (Agg backend), Chart.js 4.4 (frontend)
- **Front-end**: Jinja2, HTML5 semântico, Bootstrap 5.3, Bootstrap Icons, CSS3 Glassmorphism (Google Material)

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

## 📂 4. Mapa da Arquitetura de Arquivos

```
ComentsIA/
├── AGENTS.md                  # Este guia de contexto para agentes de IA
├── main.py                    # Ponto de entrada, rotas centrais, relatórios, auth e dashboard
├── google_auto.py             # Automação Google Business Profile, OAuth, polling e fichas
├── models.py                  # Modelos SQLAlchemy (User, Review, GoogleLocation, etc.)
├── relatorio.py               # Motor de relatórios executivos PDF com GPT-4o e Matplotlib
├── admin.py                   # Painel administrativo e suporte
├── routes_ajuda.py            # Central de ajuda e chat de suporte com IA
├── matriz.py                  # Gestão de franquias, matriz e redes de lojas
├── services/
│   └── ai_service.py          # Limpeza de texto, detecção de idioma e diretrizes de tom
├── templates/                 # Templates Jinja2 com estética Google Executive
│   ├── base.html              # Layout base, navbar, footer e toast system
│   ├── index.html             # Landing page deslogada / Dashboard logado com seletor de filial
│   ├── reviews.html           # Gestão de avaliações, modal de IA multilíngue
│   ├── relatorio.html         # Dashboard de relatórios e emissão de PDF
│   ├── google_locations.html  # Gestão e exclusão de fichas sincronizadas
│   └── settings.html          # Configurações globais de tom, idioma e negócio
├── tests/                     # Testes automatizados (pytest)
└── static/                    # Arquivos estáticos (CSS, JS, imagens)
```

---

## 📐 5. Regras de Código & Boas Práticas para o Jules

Ao gerar Pull Requests ou alterar código:

1. **Integridade de Documentação e Testes**:
   - Sempre execute `pytest` antes de finalizar uma tarefa.
   - Qualquer nova funcionalidade deve vir acompanhada de testes unitários na pasta `tests/`.
2. **Consistência Numérica e Factual na IA**:
   - Nunca permita que a IA recalcule ou invente números diferentes das estatísticas calculadas pelo backend Python.
3. **Design & Estética Google Executive**:
   - Mantenha temas claros, contraste alto, cards translúcidos (*glassmorphism*) e fontes modernas (*Outfit* / *Inter*).
   - Evite fundos escuros ou elementos visuais com névoas que comprometam a legibilidade.
4. **Segurança & Variáveis de Ambiente**:
   - Nunca commite chaves de API, credenciais ou segredos em texto plano.
   - Use `os.getenv()` com variáveis carregadas via `.env`.
5. **Compatibilidade com Windows e Linux (Produção no Render)**:
   - Use caminhos relativos ou `os.path.join`.
   - Trate codificações `utf-8` e sanitizações `latin-1` adequadas ao manipular bibliotecas de PDF.
