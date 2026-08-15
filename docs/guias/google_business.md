# Guia Completo: Google Business Profile e Grupos de Fichas

> ⚠️ **ATENÇÃO MÁXIMA:** Esta é a regra técnica mais importante de todo o aplicativo. Leia antes de tentar conectar sua empresa.

---

## 1. Por que preciso de um "Grupo de Locais" no Google?

A API oficial do Google (o sistema que permite o ComentsIA ler e responder avaliações por você) possui uma exigência de segurança:

👉 **Para responder avaliações automaticamente via sistema, a ficha da sua empresa precisa OBRIGATORIAMENTE estar dentro de um "Grupo de Locais" (também chamado de "Conta de Local" ou "Location Group").**

Se a ficha estiver solta no painel do Google, o Google bloqueia o acesso e o ComentsIA não consegue sincronizar nem responder nada.

---

## 2. Como Resolver: Identifique o seu Caso

### 👉 CASO 1: VOCÊ É O DONO DA FICHA (Mais Simples)
**Você se enquadra aqui se:** Você mesmo criou a ficha no Google ou tem o cargo de "Proprietário Principal".

**Passo a passo para resolver:**
1. Acesse o painel do Google: [business.google.com](https://business.google.com).
2. No menu lateral à esquerda, clique em **"Empresas"** ou **"Grupos de empresas"**.
3. Clique no botão **"Criar grupo"** e coloque qualquer nome (Ex: *"Minha Empresa"* ou *"Lojas"*).
4. Agora vá na lista de fichas, marque a sua ficha e clique em **"Adicionar empresa ao grupo"** (ou transferir para o grupo criado).
5. Pronto! Aguarde 2 minutos, volte ao ComentsIA, vá em **Locais Google** e clique em **"Sincronizar Fichas"**.

---

### 👉 CASO 2: VOCÊ É APENAS GERENTE (Outra pessoa criou a ficha)
**Você se enquadra aqui se:** Uma agência de marketing, o dono da franquia ou um ex-sócio criou a ficha e só adicionou seu e-mail como "Gerente" ou "Administrador" na ficha individual.

**Por que não funciona direto:** Ter permissão apenas na ficha individual NÃO concede acesso à API. Você precisa ser administrador do **Grupo de Locais**.

**O que o PROPRIETÁRIO ORIGINAL precisa fazer para liberar seu acesso:**
1. O proprietário original acessa [business.google.com](https://business.google.com).
2. Ele cria um **Grupo de Locais** (se ainda não existir).
3. Ele move a ficha da empresa para dentro desse grupo.
4. Ele clica em **"Configurações do Grupo"** > **"Gerenciar Administradores"** (ou Gerenciar Usuários do Grupo).
5. Ele adiciona o **SEU E-MAIL** (o mesmo e-mail que você usa no ComentsIA) como **Administrador do Grupo**.
6. **MUITO IMPORTANTE:** Você receberá um e-mail do Google com o convite. Você precisa abrir esse e-mail e clicar em **"Aceitar Convite"**.
7. Após aceitar, saia e entre novamente no ComentsIA, vá em **Locais Google** e clique em **"Sincronizar Fichas"**.

---

## 3. Configurando a Ficha Conectada

Após a ficha aparecer na tela de **Locais Google**:
1. **Ativar:** Clique no botão azul "Ativar".
2. **Engrenagem ⚙️ (Configurações da Unidade):**
   - **Nome do Gerente:** Quem assina a resposta.
   - **WhatsApp/Telefone:** Canal para clientes com reclamações entrarem em contato no privado.
   - **Saudação e Despedida:** Frases de início e fim da mensagem.
   - **Contexto Exclusivo:** Diferenciais dessa loja específica (ex: *"Temos espaço kids e estacionamento com manobrista"*).

---

## 4. Sincronização Histórica (Buscar avaliações antigas)
Se você acabou de entrar no ComentsIA e quer puxar avaliações de **30, 60, 90 ou 180 dias atrás** para alimentar seus relatórios, use o botão **"Sincronização Histórica"** na página de Locais Google.
