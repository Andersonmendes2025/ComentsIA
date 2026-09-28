# Manual Completo e Base de Conhecimento Oficial — ComentsIA
> **Versão:** 2.0 (Completa e Didática)  
> **Objetivo:** Este manual explica, passo a passo, em linguagem simples e acessível a qualquer pessoa, 100% das ferramentas e regras do ComentsIA. Ele serve tanto de guia para os usuários na Central de Ajuda quanto de cérebro para o Assistente Virtual (IA).

---

# 📖 SUMÁRIO GERAL

1. **O que é o ComentsIA e como ele ajuda sua empresa**
2. **Primeiro Acesso: Como entrar e configurar sua conta**
3. **⚠️ REGRA DE OURO: Google Business Profile (Grupos de Fichas)**
4. **Locais Google: Como conectar e sincronizar suas fichas**
5. **Automação com IA: Como configurar o Cérebro e as Respostas Automáticas**
6. **Gerenciamento de Avaliações: Como responder, editar e aprovar**
7. **Adicionar Avaliações Manuais e Importação (Booking, CSV, etc.)**
8. **Relatórios em PDF e Análise de Sentimento dos Clientes**
9. **Pesquisas de Satisfação (NPS, CSAT e QR Code para balcão/mesas)**
10. **Painel Matriz: Gestão de Redes, Franquias e Múltiplas Lojas**
11. **Planos, Assinaturas, Slots Extras e Cobrança**
12. **Configurações da Conta, Segurança e Privacidade**
13. **Central de Ajuda, Chat com IA e Atendimento Humano (Chamados)**
14. **Perguntas Frequentes (FAQ) com Resoluções Práticas**

---

# 1. O que é o ComentsIA e como ele ajuda sua empresa?

O **ComentsIA** é uma plataforma inteligente criada para ajudar donos de negócios, gerentes e equipes de atendimento a cuidarem da reputação da sua empresa no Google de forma automática e profissional.

### O que a plataforma faz:
- **Responde avaliações no Google 24h por dia:** Você não precisa passar horas pensando no que responder. A Inteligência Artificial analisa se a avaliação foi boa ou ruim e escreve uma resposta educada, personalizada e profissional em segundos.
- **Identifica o idioma do cliente:** Se um turista estrangeiro avaliar seu restaurante ou hotel em inglês, espanhol ou francês, a IA responde perfeitamente no mesmo idioma dele.
- **Analisa o que os clientes estão falando:** O sistema lê todos os comentários e gera relatórios em PDF mostrando os pontos mais elogiados e os principais motivos de reclamação.
- **Ajuda a subir nas buscas do Google:** Empresas que respondem 100% das suas avaliações ganham mais relevância no algoritmo do Google e aparecem na frente dos concorrentes.
- **Pesquisas de Satisfação:** Cria formulários rápidos com QR Code para seus clientes avaliarem no balcão ou nas mesas antes de irem embora.
- **Gestão de Redes (Matriz e Filiais):** Permite controlar várias lojas num único painel centralizado.

---

# 2. Primeiro Acesso: Como entrar e configurar sua conta

### Passo 1: Como fazer login
1. Acesse o site oficial do ComentsIA: `https://comentsia.com.br` (ou `http://127.0.0.1:8000` em ambiente local).
2. No canto superior direito da página inicial, clique no botão azul **"Entrar com Google"** (ou **"Entrar"**).
3. Selecione a sua **Conta Google** (de preferência o mesmo e-mail que tem acesso à sua ficha do Google Meu Negócio).
4. Pronto! O sistema cria seu cadastro imediatamente e você é levado para o painel principal.

### Passo 2: O Tour de Boas-Vindas
- Ao entrar pela primeira vez, um tour interativo na tela vai guiar você pelos principais botões do menu.
- Você pode clicar em **"Próximo"** para conhecer cada área ou clicar em **"Pular"** a qualquer momento.

### Passo 3: O Menu Superior (Navegação)
Quando você está conectado, o menu superior mostra as seguintes opções:
- **Avaliações:** Onde você vê a lista de comentários dos clientes e respostas.
- **Adicionar:** Para cadastrar avaliações de outros lugares manualmente.
- **Dashboard:** Gráficos com média de estrelas, total de avaliações e desempenho do mês.
- **Relatórios:** Onde você gera e baixa análises em PDF.
- **Planos:** Tabela com os planos disponíveis para upgrade.
- **Ajuda:** Central de ajuda completa com manuais e tutoriais.
- **Painel Matriz:** (Para assinantes do plano Business) Para gerenciar redes e filiais.
- **Sininho 🔔:** Avisa quando você recebe convites de vinculação de outras lojas.
- **Seu Nome (Menu do Usuário):** Abre as opções de *Configurações*, *Sair* e *Apagar Conta*.

---

# 3. ⚠️ REGRA DE OURO: Google Business Profile (Grupos de Fichas)

> **ATENÇÃO MÁXIMA:** Esta é a regra técnica mais importante de todo o aplicativo. Leia com muita atenção para não ter erros de sincronização!

### Por que essa regra existe?
O Google possui uma regra de segurança rigorosa para a sua API oficial (a ponte de comunicação entre o ComentsIA e o Google):  
**Para que qualquer sistema consiga buscar e responder avaliações automaticamente, a ficha da sua empresa precisa OBRIGATORIAMENTE estar dentro de um "Grupo de Locais" (também chamado de "Conta de Local" ou "Location Group").**

Se a sua ficha estiver "solta" no painel do Google, o sistema não conseguirá permissão para responder avaliações por você.

---

### 👉 Cenário 1: VOCÊ É O DONO/CRIADOR DA FICHA (Mais Simples)
**Quem se enquadra aqui:** Você mesmo criou a ficha da sua empresa no Google ou tem o cargo de "Proprietário Principal".

**Como resolver em 3 minutos:**
1. Acesse o painel do Google: [business.google.com](https://business.google.com).
2. No menu lateral esquerdo, procure por **"Empresas"** ou **"Grupos de empresas"**.
3. Clique no botão **"Criar grupo"** e dê um nome qualquer (por exemplo: *"Minha Empresa"* ou *"Lojas"*).
4. Agora vá na lista de fichas, selecione a sua ficha e clique em **"Adicionar ao grupo"** (ou transferir para o grupo que você acabou de criar).
5. Pronto! Agora volte ao ComentsIA, vá em **Locais Google** e clique em **"Sincronizar Fichas"**. Sua ficha vai aparecer perfeitamente.

---

### 👉 Cenário 2: VOCÊ É APENAS GERENTE (Outra pessoa criou a ficha)
**Quem se enquadra aqui:** Uma agência, o dono da franquia ou um antigo sócio criou a ficha e apenas colocou seu e-mail como "Gerente" ou "Administrador" na ficha individual.

**Por que dá erro:** Ter cargo de gerente apenas na ficha solta NÃO dá acesso à API do Google. O seu e-mail precisa ter cargo de administrador no **Grupo de Locais**.

**Como resolver (O que o Dono da ficha precisa fazer):**
1. O proprietário original da ficha deve acessar [business.google.com](https://business.google.com).
2. Ele deve criar um **Grupo de Locais** (se ainda não tiver criado).
3. Ele deve mover a ficha da empresa para dentro desse Grupo.
4. Dentro do Grupo de Locais, ele deve clicar em **"Configurações do Grupo"** > **"Gerenciar Administradores"** (ou Gerenciar Usuários do Grupo).
5. Ele deve adicionar o **SEU E-MAIL** (o mesmo que você usa no ComentsIA) como **Administrador do Grupo**.
6. **MUITO IMPORTANTE:** Você receberá um e-mail do Google com o convite. Você precisa abrir esse e-mail e clicar em **"Aceitar Convite"**.
7. Após aceitar, faça logout e login novamente no ComentsIA. Vá em **Locais Google** e clique em **"Sincronizar Fichas"**.

---

# 4. Locais Google: Como conectar e sincronizar suas fichas

A tela de **Locais Google** (`/auto/locations`) é o coração da integração.

### 1. Sincronizando as Fichas
- Ao clicar no botão azul **"Sincronizar Fichas"**, o ComentsIA consulta sua conta do Google e lista todas as empresas encontradas.
- Se você tiver mais de uma loja, todas as unidades aparecerão como cartões na tela.

### 2. Ativando ou Desativando uma Ficha
- Cada ficha tem um botão **"Ativar" / "Desativar"**.
- Ao ativar uma ficha, o ComentsIA passa a monitorar diariamente as avaliações daquele estabelecimento.
- **Limite por plano:** O plano Free não possui slots de automação. O plano Pro inclui 1 ficha ativa. O plano Business inclui 1 ficha + suporte a filiais. Se você precisar de mais fichas no mesmo usuário, pode adquirir **Slots Extras** na própria tela.

### 3. Configurações Individuais da Ficha (Botão ⚙️ Engrenagem)
Clicando na engrenagem de uma ficha específica, você pode personalizar como a IA vai responder naquela unidade:
- **Nome Comercial da Unidade:** Ex: *"Pizzaria Bella Moema"*.
- **Nome do Gerente / Responsável:** Ex: *"Carlos Andrade"*.
- **Informações de Contato:** Telefone ou WhatsApp para clientes insatisfeitos entrarem em contato (Ex: `(11) 98765-4321`).
- **Saudação Padrão:** Como a resposta deve começar (Ex: *"Olá, [Nome do Cliente]! Muito obrigado por nos avaliar."*).
- **Despedida Padrão:** Como a resposta deve terminar (Ex: *"Esperamos te receber novamente em breve! Um abraço da equipe."*).
- **Contexto Personalizado da Ficha:** Detalhes exclusivos daquela loja (Ex: *"Nesta unidade temos espaço kids e estacionamento com manobrista gratuito."*).

### 4. Sincronização Retroativa (Buscar avaliações antigas)
- Por padrão, o Google sincroniza as avaliações mais recentes.
- Se você acabou de criar a conta e quer puxar as avaliações dos últimos **30, 60, 90 ou 180 dias atrás**, use o botão **"Sincronização Histórica"**.
- O sistema processa o histórico completo e traz todas as avaliações passadas para alimentar seus relatórios e dashboards.

---

# 5. Automação com IA: Como configurar o Cérebro e as Respostas

Acesse o menu **Configurações** (`/settings`) para definir a personalidade da Inteligência Artificial.

### 1. Escolhendo o Tom de Voz
Você pode escolher como deseja que a IA converse com seus clientes:
- **Amigável (Recomendado para comércio e restaurantes):** Respostas calorosas, simpáticas, usando emojis e tom acolhedor.
- **Formal (Recomendado para clínicas, advocacia e consultórios):** Respostas sóbrias, respeitosas, com vocabulário formal e polido.
- **Neutro:** Respostas diretas, profissionais, equilibradas e objetivas.
- **Empático (Excelente para serviços com reclamações sensíveis):** Foco em acolhimento, pedido de desculpas sincero e convite para resolver o problema no privado.
- **Técnico:** Foco em procedimentos, termos técnicos e precisão de informações.

### 2. Caixa de Contexto Personalizado (Muito importante!)
Neste campo, você explica para a IA quem é a sua empresa e como ela deve se comportar.
**Exemplo prático de um bom contexto:**
> *"Somos o Restaurante Sabor da Terra, localizado em Campinas. Servimos comida caseira no fogão a lenha no almoço e pizzas artesanais à noite. Temos estacionamento grátis e espaço pet friendly. Quando o cliente reclamar de demora, peça desculpas com carinho e informe nosso WhatsApp (19) 9999-9999 para que a gerência possa oferecer uma cortesia na próxima visita. Nunca prometa devolução de dinheiro em respostas públicas."*

### 3. Idioma de Resposta
- **Português (Brasil):** Responde sempre em português.
- **Automático:** A IA detecta a língua em que o cliente escreveu e responde no mesmo idioma dele (Português, Inglês, Espanhol, Alemão, Italiano, etc.).

### 4. Respostas Hiper-Compreensivas (2 por dia no plano Pro)
- Quando ativada, a IA cria respostas muito mais profundas e detalhadas para avaliações longas ou críticas, analisando cada frase escrita pelo cliente.

---

# 6. Gerenciamento de Avaliações (`/reviews`)

Na tela de **Avaliações**, você acompanha tudo o que os clientes publicam.

### 1. Filtros e Busca Rápida
No topo da página, você pode filtrar por:
- **Nota em Estrelas:** Ver só 1 estrela, só 5 estrelas, etc.
- **Status:** Avaliações *Respondidas* ou *Pendentes de resposta*.
- **Ficha/Local:** Escolher qual loja deseja visualizar.
- **Barra de Pesquisa:** Digite o nome do cliente ou uma palavra (ex: "comida", "demora", "excelente").

### 2. Modos de Resposta: Manual vs Automático
- **No modo Automático:** O sistema roda um processo diário que busca novas avaliações e publica a resposta diretamente no Google. Na lista, essas respostas ganham a etiqueta verde **"Auto (GBP)"**.
- **No modo Manual:** Cada avaliação tem o botão azul **"Sugerir Resposta"**. Você clica, a IA gera um rascunho instantâneo na caixa de texto, você pode alterar qualquer palavra se quiser e clicar em **"Publicar Resposta"**.

### 3. Editar ou Excluir uma Resposta
- Se quiser mudar o que foi respondido, clique em **"Editar Resposta"**, modifique o texto e salve. A alteração é sincronizada com o Google.
- Se quiser remover a resposta, clique no ícone de **Lixeira** ao lado da resposta.

---

# 7. Adicionar Avaliações Manuais e Importação

Acesse **Adicionar** (`/add_review`) no menu.

### Para que serve?
Se você também recebe avaliações em outros canais (como Reclame Aqui, Booking.com, TripAdvisor, iFood ou pesquisas internas em papel/WhatsApp) e quer reunir tudo no ComentsIA para gerar relatórios unificados, você pode cadastrá-las aqui.

### Como preencher:
1. **Nome do Avaliador:** Ex: *"Mariana Silva"*.
2. **Nota:** De 1 a 5 estrelas.
3. **Data:** Dia em que a pessoa avaliou.
4. **Fonte/Canal:** Ex: *"Booking"*, *"Reclame Aqui"*, *"Balcão"*, *"WhatsApp"*.
5. **Comentário:** O texto do cliente.
6. **Resposta (Opcional):** Você pode usar a IA para sugerir a resposta ou escrever a sua.
7. Clique em **"Salvar Avaliação"**.

---

# 8. Relatórios em PDF e Análise de Sentimento

Acesse **Relatórios** (`/relatorio`) no menu.

### 1. Como gerar um Relatório Executivo Passo a Passo
1. **Filtro de Loja / Unidade (Topo):**
   - Escolha se deseja ver os dados de **Todas as Lojas / Unidades** ou de uma filial específica.
2. **Filtros do Relatório:**
   - **Período de Análise:**
     - *Últimos 90 dias*
     - *Últimos 6 meses*
     - *Último 1 ano*
   - **Filtrar por Nota:**
     - *Todas as notas*
     - *⭐ 1 Estrela*
     - *⭐⭐ 2 Estrelas*
     - *⭐⭐⭐ 3 Estrelas*
     - *⭐⭐⭐⭐ 4 Estrelas*
     - *⭐⭐⭐⭐⭐ 5 Estrelas*
   - **Status da Resposta:**
     - *Qualquer status* (Todas)
     - *✅ Apenas Respondidas*
     - *⚠️ Apenas Pendentes*
3. Clique no botão azul **"Gerar PDF da Ficha Atual"**.
4. O sistema processa os dados com Inteligência Artificial e gera o PDF completo com gráficos profissionais.

### 2. Regras de Acesso ao Relatório PDF por Plano
- **Plano Free:** Não possui geração de PDF (recurso exclusivo de planos pagos).
- **Plano Pro (Mensal / Anual):** Permite gerar **1 relatório executivo em PDF por mês**.
- **Plano Business (Mensal / Anual):** Geração de relatórios PDF **ilimitada**.

### 3. O que tem dentro do Relatório PDF?
- **Resumo Executivo:** Média geral da nota, volume total de avaliações e taxa de resposta.
- **Gráfico de Pizza:** Distribuição percentual de cada estrela (1 a 5).
- **Gráfico de Evolução Temporal:** Linha do tempo mostrando se a nota da empresa está subindo ou descendo mês a mês.
- **Análise de Sentimento por IA:** Destaque dos termos mais elogiados (pontos fortes) e das maiores queixas dos clientes (pontos de atenção).
- **Lista Completa das Avaliações:** Todas as avaliações do período com suas respectivas respostas.

### 4. Histórico de Relatórios (`/historico_relatorios`)
- Todos os relatórios gerados ficam salvos no histórico para você baixar novamente quando quiser ou excluir relatórios antigos.

---

# 9. Pesquisas de Satisfação (Formulários estilo Forms e QR Code)

Acesse **Pesquisas** (`/dashboard/pesquisa`) no menu.

### O que são e como funcionam?
É um construtor de formulários dinâmicos (estilo Google Forms) integrado ao ComentsIA para você coletar a opinião dos clientes no seu estabelecimento físico ou pós-venda.

### 1. Tipos de Perguntas Disponíveis:
Ao criar ou editar perguntas na pesquisa (`/dashboard/pesquisa/criar`), você pode adicionar perguntas com os seguintes formatos:
- ⭐ **Avaliação por Estrelas (1 a 5 estrelas):** Ex: *"Como você avalia nosso atendimento hoje?"*
- 🔘 **Múltipla Escolha:** Você define as opções separadas por vírgula (Ex: *"Qual prato você mais gostou?"* -> Opções: *"Pizza, Hambúrguer, Sobremesa, Bebidas"*).
- ✍️ **Texto Livre:** Campo aberto para elogios, críticas ou sugestões detalhadas.
- **Configuração de Obrigatoriedade:** Você pode marcar qualquer pergunta como obrigatória (Sim/Não).

### 2. 🚀 Redirecionamento Estratégico para o Google (Filtro de Avaliação 5 Estrelas):
Esta é uma das funções mais inteligentes do ComentsIA:
- Você cadastra o **Link de Avaliação do Google** da sua empresa.
- Ativa a opção **"Redirecionar Positivo Automático"**.
- Escolhe qual pergunta de estrelas serve como **Pergunta Gatilho**.
- **Como funciona na prática:**
  - Se o cliente der nota máxima (**5 estrelas**), ao enviar o formulário ele é **redirecionado automaticamente para o Google** para deixar 5 estrelas lá também!
  - Se o cliente der uma nota menor (1 a 4 estrelas), a avaliação fica salva **apenas internamente** no ComentsIA para sua gerência resolver, evitando que uma crítica pública vá parar no Google!

### 3. Identificação do Cliente (Opcional):
- O cliente pode preencher Nome, E-mail e WhatsApp para você entrar em contato no pós-venda.

### 4. Proteção Anti-Spam (Blindagem de Sessão):
- O sistema possui uma trava inteligente de 15 minutos por sessão/navegador para evitar que a mesma pessoa envie respostas repetidas acidentalmente.

### 5. Link Curto e QR Code para Impressão:
- **URL Pública:** O sistema cria um link seguro e exclusivo (Ex: `comentsia.com.br/p/minha-loja`).
- **QR Code Automático:** Em `/dashboard/pesquisa`, você clica no botão de QR Code e baixa a imagem em PNG pronta para imprimir em displays de mesa, na comanda, no verso da conta ou no balcão de pagamento.

### 6. Painel de Resultados em Tempo Real (`/dashboard/pesquisa/<id>/respostas`):
- **Estatísticas por Pergunta:** Gráficos com a porcentagem e contagem de cada estrela (5 a 1) ou opção de múltipla escolha.
- **Feed de Comentários:** Lista com todos os textos digitados pelos clientes, data e dados de contato (Nome, WhatsApp, E-mail).

---

# 10. Painel Matriz: Gestão de Redes e Múltiplas Lojas

Acesse **Painel Matriz** (`/matriz/dashboard`) no menu.  
*(Disponível exclusivamente para assinantes do Plano Business).*

### Para que serve?
Ideal para redes de lojas, franquias, escritórios com filiais ou grupos empresariais. Permite que o dono da Matriz enxergue a performance de todas as filiais num único lugar, sem precisar ficar trocando de conta.

### Como funciona:
1. **Convidar uma Filial (`/matriz/filiais`):**
   - O gestor da Matriz digita o e-mail da conta do responsável pela filial e clica em **"Enviar Convite"**.
2. **A Filial Aceita o Convite:**
   - O responsável pela filial faz login no ComentsIA.
   - Um número vermelho aparece no **Sininho 🔔** no topo da tela.
   - Ele clica no convite e aperta **"Aceitar Vinculação"**.
3. **Visão Consolidada da Matriz:**
   - O painel da Matriz passa a exibir:
     - Ranking das melhores e piores filiais por nota de satisfação.
     - Comparativo de volume de avaliações entre as lojas.
     - Botão **"Acessar como Filial"**: o gestor da Matriz pode entrar no painel de qualquer unidade para ver avaliações ou responder em nome dela com 1 clique.

---

# 11. Planos, Assinaturas e Cobrança

Acesse **Planos** (`/planos` ou `/upgrade`) no menu.

### Tabela Oficial de Preços e Recursos:

| Recurso / Benefício | Starter Free | Pro Mensal | Pro Anual (2 meses OFF) | Business (Redes) | Business Anual |
|---|:---:|:---:|:---:|:---:|:---:|
| **Preço** | **R$ 0 / mês** | **R$ 49,99 / mês** | **R$ 499,00 / ano** (~R$ 41,58/mês) | **R$ 79,99 / mês** | **R$ 799,00 / ano** (~R$ 66,58/mês) |
| **Fichas Google Conectadas** | 0 (Manual) | 1 ficha | 1 ficha | 1 ficha + Multi Filiais | 1 ficha + Multi Filiais |
| **Limite de Avaliações/Mês** | 20 avaliações | 200 avaliações | 200 avaliações | **Ilimitado** | **Ilimitado** |
| **Respostas Hiper-Empáticas** | ❌ Não | 2 por dia | 2 por dia | **Ilimitado** | **Ilimitado** |
| **Considerações do Negócio** | ❌ Não | 2 por dia | 2 por dia | **Ilimitado** | **Ilimitado** |
| **Automação Google 24h** | ❌ Não | ✅ Sim | ✅ Sim | ✅ Sim | ✅ Sim |
| **Relatórios em PDF por Mês** | 0 (Bloqueado) | **1 por mês** | **1 por mês** | **Ilimitado** | **Ilimitado** |
| **Marca d'Água** | Sim | Sem marca | Sem marca | Sem marca | Sem marca |
| **Painel Matriz (Filiais)** | ❌ Não | ❌ Não | ❌ Não | ✅ Sim | ✅ Sim |
| **Pesquisas de Satisfação** | ❌ Não | ✅ Sim | ✅ Sim | ✅ Sim | ✅ Sim |
| **Nível de Suporte** | Básico | Prioritário | Prioritário | VIP | VIP |
| **Slots Extras de Fichas** | ❌ | Disponível | Disponível | Disponível | Disponível |

### Como assinar ou fazer Upgrade:
1. Vá na página de **Planos**.
2. Escolha o plano desejado e clique em **"Assinar Agora"** (ou **"Fazer Upgrade"**).
3. Você será direcionado para o checkout seguro da **Stripe** (líder mundial em pagamentos online).
4. Insira os dados do seu cartão de crédito.
5. Assim que o pagamento é aprovado, sua conta é liberada instantaneamente!

### Como cancelar a assinatura:
- Você pode cancelar a qualquer momento sem multa.
- Basta abrir o Chat Inteligente no canto da tela e dizer *"Quero cancelar meu plano"* ou enviar um e-mail para `suporte@comentsia.com.br`.
- O plano continuará ativo até o final do período que já foi pago.

---

# 12. Configurações da Conta, Segurança e Privacidade

### 1. Segurança Máxima dos Dados
- **Criptografia Fernet (AES-128):** Todos os tokens de acesso ao Google e dados sensíveis são criptografados no banco de dados. Ninguém tem acesso às suas credenciais.
- **Conexão HTTPS Segura:** Todo o tráfego é protegido com certificado SSL/TLS de alta segurança.
- **Processamento de Pagamento Isolado:** O ComentsIA não armazena números de cartão de crédito. Tudo fica sob a custódia da Stripe (certificação PCI-DSS Nível 1).

### 2. Apagar Minha Conta (`/delete_account`)
- Respeitamos 100% a LGPD (Lei Geral de Proteção de Dados).
- Se você desejar encerrar sua conta e apagar todos os seus dados:
  1. Clique no seu nome no canto superior direito.
  2. Selecione a opção em vermelho **"Apagar minha conta"**.
  3. Confirme na caixa de diálogo.
  4. Todos os seus dados, avaliações, configurações e tokens são apagados imediatamente de forma irreversível e você recebe um e-mail de confirmação.

---

# 13. Central de Ajuda, Chat com IA e Atendimento Humano

### 1. Central de Ajuda (`/ajuda`)
- Contém todos os tutoriais deste manual organizados por categorias com barra de busca em tempo real.

### 2. Chat Inteligente 24h (Bolinha Azul Flutuante)
- Fica visível no canto inferior direito de todas as telas do sistema.
- Ao clicar, você pode conversar em linguagem natural com a nossa IA.
- Ela conhece todo este manual e responde qualquer dúvida sobre como usar cada botão ou tela do aplicativo.

### 3. Abertura Automática de Chamado para Atendente Humano (Function Calling)
- Se a IA não souber responder a sua dúvida, se houver um erro no sistema ou se você disser explicitamente:
  - *"Quero falar com um humano"*
  - *"Falar com atendente"*
  - *"Abrir um chamado de suporte"*
- A IA aciona automaticamente o sistema de chamados.
- **O que acontece:**
  1. O sistema gera um número de protocolo oficial (Ex: `CSUP-20260815-4821`).
  2. O sistema envia um e-mail formal para `suporte@comentsia.com.br` contendo seu nome, seu e-mail cadastrado, seu plano e o histórico recente da conversa.
  3. O bot informa o número do protocolo na tela do chat.
  4. Nossa equipe humana responde por e-mail em até 24 horas úteis.

---

# 14. Perguntas Frequentes (FAQ) com Resoluções Práticas

**P: Minha ficha do Google não aparece de jeito nenhum em Locais Google. O que fazer?**  
**R:** Na imensa maioria das vezes, a ficha não está dentro de um "Grupo de Locais" no Google Meu Negócio, ou você foi adicionado como gerente apenas na ficha e não no Grupo. Siga os passos detalhados na **Seção 3** deste manual.

**P: Como a IA sabe responder clientes mal-educados ou com notas baixas?**  
**R:** A IA é programada para jamais discutir com o cliente. Em avaliações de 1 ou 2 estrelas, ela se desculpa pelo transtorno, valida o sentimento do cliente e oferece os canais de contato cadastrados em suas configurações para resolução privada.

**P: Posso alterar o texto que a IA sugeriu antes de enviar pro Google?**  
**R:** Sim! No modo manual, a resposta sugerida fica numa caixa de texto editável. Você pode adicionar, apagar ou mudar qualquer palavra antes de clicar em publicar.

**P: A automação responde comentários antigos que eu recebi meses atrás?**  
**R:** A automação diária foca nas avaliações novas que chegam a partir do momento em que você liga o sistema. Se quiser responder ou analisar avaliações antigas, basta usar a ferramenta de *Sincronização Histórica* em Locais Google.

**P: Como imprimir o QR Code da minha pesquisa de satisfação?**  
**R:** Acesse *Pesquisas* > clique na pesquisa criada > clique no botão *QR Code*. Você pode salvar a imagem em PNG ou imprimir diretamente para colocar nas mesas ou no balcão.

**P: O que acontece se meu cartão falhar na renovação do plano?**  
**R:** A Stripe tenta processar novamente por alguns dias e envia e-mails de aviso para você atualizar o cartão. Caso a assinatura seja suspensa, sua conta volta temporariamente para o plano Free sem perda de nenhum dado histórico.

**P: O ComentsIA tem aplicativo para celular?**  
**R:** O site do ComentsIA é 100% responsivo (otimizado para telas de celular e tablets). Você pode acessá-lo pelo navegador do seu smartphone ou clicar em "Adicionar à tela inicial" no Chrome/Safari para usá-lo como um app.

---

# 15. 🍔 Integração iFood & Respostas Automáticas para Restaurantes e Delivery

O **ComentsIA** oferece integração oficial com o **iFood Delivery** através do modelo de aplicativo distribuído e seguro via OAuth 2.0.

### 🌟 Principais Vantagens para Restaurantes:
1. **Respostas Instantâneas para Pedidos Delivery:** A IA lê o comentário e a nota (estrelas) atribuídos ao restaurante no app do iFood.
2. **Reconhecimento de Pratos e Itens Elogiados:** Se o cliente elogiou o sabor do hambúrguer, o ponto da pizza ou a temperatura da comida, a IA valoriza o prato e o trabalho da cozinha.
3. **Gestão Inteligente de Reclamações de Entrega:** Caso o cliente reclame de demora ou embalagem, a IA responde com empatia profissional, acolhe o feedback sem transferir culpa para o entregador parceiro e preserva a reputação do restaurante.
4. **Publicação Direta na API do iFood:** As respostas geradas pela IA são enviadas diretamente para a API oficial do iFood e aparecem no app do cliente.

---

### 💳 Como Funciona a Assinatura do Add-on iFood:
- A integração com o iFood funciona como uma extensão (**Add-on de R$ 29,90/mês** via Stripe).
- Usuários com Add-on ativo podem conectar e gerenciar suas lojas do iFood.
- Para assinar, acesse o menu **"Integrações"** no topo do ComentsIA e clique em **"Assinar Add-on iFood (R$ 29,90/mês)"**.

---

### 🔗 Passo a Passo: Como Conectar sua Loja do iFood:
1. Acesse o menu **"Integrações"** no ComentsIA.
2. No card do **iFood**, clique no botão **"Conectar Loja"**.
3. Um modal interativo abrirá com o seu **Código de Pareamento** exclusivo (ex: `HJLX-LPSQ`).
4. Clique no link **"Abrir Portal do Parceiro iFood"** (ou acesse `https://portal.ifood.com.br/apps/code`).
5. No Portal do iFood, cole o código e clique em **"Autorizar"**.
6. Volte à janela do ComentsIA e clique em **"Concluir Pareamento"**.
7. Pronto! A sua loja será detectada e adicionada automaticamente ao seu painel.

---

### ⚙️ Personalização de Tom de Voz para o iFood:
Para cada loja conectada, você pode clicar no botão **"Configurar"** (ícone de engrenagem) e definir:
- **Ativar/Desativar Respostas Automáticas:** Escolha se as novas avaliações serão respondidas no piloto automático.
- **Tom de Voz:** *Amigável & Caloroso* (mais indicado para gastronomia), *Profissional*, *Sofisticado*, etc.
- **Saudação e Despedida:** Personalize como seu restaurante cumprimenta e se despede dos clientes.
- **Contexto da Cozinha / Regras Especiais:** Ex: *"Nossos pratos são artesanais", "Agradecer por pedir em nossa hamburgueria familiar"*.

---

### ❓ Perguntas Frequentes sobre o iFood:

**P: As respostas da IA aparecem para o cliente no app do iFood?**  
**R:** Sim! A resposta é publicada oficialmente através da API do iFood e fica visível para o cliente no histórico do pedido e na página do seu restaurante.

**P: Como sincronizar avaliações pendentes do iFood?**  
**R:** Em **Integrações**, clique no botão **"Sincronizar Avaliações"** da sua loja. O ComentsIA buscará as últimas avaliações recebidas e gerará as respostas automaticamente.

**P: Posso conectar mais de uma filial ou loja do iFood?**  
**R:** Sim! Se a sua conta no Portal do Parceiro do iFood gerencia múltiplas lojas/filiais, o ComentsIA permite conectar e configurar cada unidade individualmente.

