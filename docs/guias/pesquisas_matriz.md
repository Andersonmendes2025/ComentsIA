# Guia Completo: Pesquisas de Satisfação e Painel Matriz

Neste guia, você vai aprender a usar duas ferramentas poderosas do **ComentsIA**: como criar formulários de pesquisa de satisfação com QR Code (e filtro estratégico para o Google) e como gerenciar redes de filiais centralizadamente.

---

# PARTE 1: Pesquisas de Satisfação (Estilo Forms com QR Code)

Acesse **Pesquisas** (`/dashboard/pesquisa`) no menu superior.

### 1. O que são e como funcionam?
É um construtor de formulários dinâmicos (estilo Google Forms) integrado ao ComentsIA para você coletar a opinião dos clientes no seu estabelecimento físico, balcão, mesas ou pós-venda no WhatsApp.

### 2. Tipos de Perguntas Disponíveis:
Ao criar sua pesquisa em `/dashboard/pesquisa/criar`, você pode adicionar perguntas nos seguintes formatos:
- ⭐ **Estrelas (1 a 5 estrelas):** Ex: *"Como você avalia nosso atendimento hoje?"*
- 🔘 **Múltipla Escolha:** Você digita as opções separadas por vírgula (Ex: *"Qual prato você mais gostou?"* -> Opções: *"Pizza, Hambúrguer, Sobremesa, Bebidas"*).
- ✍️ **Texto Livre:** Campo de texto aberto para elogios, críticas ou sugestões detalhadas.
- **Pergunta Obrigatória:** Chave para definir se o cliente é obrigado a responder aquela pergunta antes de enviar.

### 3. 🚀 Redirecionamento Estratégico para o Google (Filtro 5 Estrelas)
Esta é uma das funções mais inteligentes da plataforma:
1. Ao criar a pesquisa, cole o **Link de Avaliação do Google** da sua empresa.
2. Marque a opção **"Redirecionamento Positivo Automático"**.
3. Selecione qual pergunta de estrelas serve como **Pergunta Gatilho**.
4. **O que acontece na prática:**
   - Se o cliente der **5 estrelas**, ao clicar em Enviar ele é **redirecionado automaticamente para o Google** para publicar a nota máxima lá também!
   - Se o cliente der **1, 2, 3 ou 4 estrelas**, a resposta fica guardada **apenas internamente** no ComentsIA para sua gerência resolver no privado, evitando que uma nota baixa manche a sua reputação no Google!

### 4. Como Coletar Respostas dos Clientes
- **Link Público:** O sistema gera um link curto e seguro (Ex: `comentsia.com.br/p/sua-loja`).
- **QR Code Automático:** Na lista de pesquisas, clique no botão de **QR Code** e baixe a imagem em PNG pronta para imprimir em:
  - Displays acrílicos nas mesas.
  - Cartãozinho entregue junto com a conta.
  - Adesivo no balcão de pagamento ou recepção.
  - Embalagem do delivery.

*(O cliente aponta a câmera do celular, responde em 20 segundos sem precisar de cadastro nem login).*

### 5. Proteção Anti-Spam (Blindagem de Sessão)
- O sistema possui uma trava de segurança de 15 minutos por sessão para impedir que a mesma pessoa envie múltiplas respostas duplicadas por engano.

### 6. Acompanhando os Resultados (`/dashboard/pesquisa/<id>/respostas`)
- No painel da pesquisa, você vê:
  - Gráficos de barras e porcentagens de cada nota de 1 a 5 estrelas.
  - Distribuição das respostas de múltipla escolha.
  - Feed de comentários abertos com nome, WhatsApp e e-mail dos clientes.

---

# PARTE 2: Painel Matriz (Gestão de Filiais e Redes)

Acesse **Painel Matriz** (`/matriz/dashboard`) no menu.  
*(Disponível exclusivamente para assinantes do Plano Business).*

### 1. Para quem serve o Painel Matriz?
Para empresários, franqueadores e diretores que possuem 2, 5, 10 ou mais unidades e precisam:
- Saber qual unidade tem o melhor atendimento e qual filial está recebendo mais reclamações.
- Ter uma visão consolidada de todas as notas sem precisar ficar deslogando e logando em contas diferentes.
- Acessar o painel de qualquer filial para responder avaliações com apenas 1 clique.

### 2. Como Vincular uma Nova Filial
1. O gestor da Matriz acessa **Painel Matriz > Filiais** (`/matriz/filiais`).
2. Digita o e-mail cadastrado pelo gerente da filial no ComentsIA e clica em **"Enviar Convite"**.
3. O gerente da filial faz login na conta dele e verá uma notificação no **Sininho 🔔** no topo da tela.
4. Ao clicar no sininho, a filial aperta em **"Aceitar Vinculação"**.

### 3. O que a Matriz Consegue Fazer
- **Ranking das Lojas:** Veja a lista das filiais ordenadas pela melhor média de estrelas no Google.
- **Comparativo de Volume:** Descubra quais lojas recebem mais avaliações por mês.
- **Entrar na Filial:** O gestor da Matriz clica no botão **"Entrar como Filial"** e assume temporariamente a visualização daquela unidade para responder ou configurar a IA, e depois clica em **"Sair da Filial"** para voltar à Matriz.
