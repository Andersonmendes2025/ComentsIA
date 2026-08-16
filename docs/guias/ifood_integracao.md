# 🍔 Guia de Integração e Respostas Automáticas para o iFood

O **ComentsIA** oferece automação inteligente de respostas a avaliações para restaurantes e empresas de delivery cadastradas no **iFood**.

---

## 🌟 1. Vantagens da Automação no iFood

- **Respostas Instantâneas para Pedidos:** A IA analisa a nota (estrelas) e o comentário do cliente no app do iFood.
- **Reconhecimento de Pratos Elogiados:** Se o cliente elogiou a massa, o sabor do hambúrguer ou a entrega rápida, a IA destaca esses pontos positivos.
- **Acolhimento Empático em Queixas de Entrega:** Se o cliente reclamar de demora ou embalagem, a IA se solidariza, preserva a reputação do restaurante e não transfere a culpa para o entregador parceiro.
- **Publicação Oficial:** A resposta é enviada diretamente pela API do iFood e fica visível para o cliente no histórico do pedido.

---

## 💳 2. Assinatura do Add-on iFood (R$ 29,90/mês)

A integração com o iFood funciona como uma extensão (**Add-on** de R$ 29,90 por mês via Stripe):
1. Acesse o menu **"Integrações"** no topo da página.
2. No card do iFood, clique em **"Assinar Add-on iFood (R$ 29,90/mês)"**.
3. Conclua o pagamento seguro no Stripe. Sua conta terá o recurso liberado imediatamente.

---

## 🔗 3. Passo a Passo para Conectar sua Loja

1. No ComentsIA, vá em **"Integrações"**.
2. Clique em **"Conectar Loja"** no card do iFood.
3. Copie o **Código de Pareamento** gerado (ex: `HJLX-LPSQ`).
4. Clique no link para abrir o [Portal do Parceiro iFood](https://portal.ifood.com.br/apps/code).
5. No Portal do iFood, cole o código e clique em **"Autorizar"**.
6. Volte à janela do ComentsIA e clique em **"Concluir Pareamento"**.
7. Pronto! Sua loja aparecerá na lista de lojas conectadas.

---

## ⚙️ 4. Configurações por Loja

Ao clicar no ícone de engrenagem da loja conectada, você pode definir:
- **Ativar/Desativar Respostas Automáticas**
- **Tom de Voz da IA:** (*Amigável & Caloroso*, *Profissional*, *Sofisticado*, etc.)
- **Saudação e Despedida Personalizadas**
- **Contexto da Cozinha / Regras:** Instruções específicas sobre seus pratos e diferencial do restaurante.
