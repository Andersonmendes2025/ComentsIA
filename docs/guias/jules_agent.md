# Guia de Integração e Uso do Google Jules (Jules Tools)

O **Jules** é o agente autônomo de programação em inteligência artificial do Google Labs. Ele conecta-se diretamente ao repositório GitHub do ComentsIA para executar tarefas, criar Pull Requests e auditar o código.

---

## 🛠️ 1. Instalação do Jules Tools CLI

Para interagir com o Jules diretamente pelo terminal:

```bash
npm install -g @google/jules
```

---

## 🔐 2. Autenticação

Faça login com a sua conta Google conectada ao projeto:

```bash
jules login
```
*O comando abrirá uma janela do navegador para autenticação segura.*

Para encerrar a sessão:
```bash
jules logout
```

---

## 💻 3. Comandos Principais

### Criar uma Nova Tarefa / Sessão Remota:
O Jules detecta automaticamente o repositório atual (`Andersonmendes2025/ComentsIA`):

```bash
# Executa uma tarefa no repositório atual
jules remote new --session "Criar novos testes para o módulo de relatórios"

# Executar com múltiplas sessões em paralelo
jules remote new --session "Otimizar consultas de avaliações do Google" --parallel 2
```

### Listar Repositórios e Sessões Ativas:
```bash
# Listar repositórios conectados
jules remote list --repo

# Listar todas as sessões ativas e anteriores
jules remote list --session
```

### Puxar Alterações de uma Sessão Finalizada:
```bash
jules remote pull --session <ID_DA_SESSAO>
```

---

## 🖥️ 4. Dashboard Interativo no Terminal (TUI)

Para abrir a interface interativa com visualizador de diffs lado a lado e gerenciamento de sessões:

```bash
jules
```

Você também pode alternar entre os temas claro e escuro:
```bash
jules --theme light
```

---

## 📄 5. Como o Jules Entende Este Projeto

O Jules lê automaticamente o arquivo [`AGENTS.md`](file:///c:/Users/Anderson%20Mendes/Documents/ComentsIA/AGENTS.md) na raiz do projeto. Ele contém:
- Stack tecnológica (Python/Flask/SQLAlchemy).
- Comandos de teste (`pytest`).
- Estrutura de arquivos e padrões de código.
