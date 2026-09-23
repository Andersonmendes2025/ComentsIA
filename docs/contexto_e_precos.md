# Contexto das avaliações e preços

## Respostas com contexto

Os contextos salvos na ficha e na conta são preservados. Antes de redigir uma
resposta, `build_relevant_context` interpreta o comentário e seleciona até dois
trechos que possam enriquecer a resposta naturalmente. A informação da ficha
prevalece em conflitos; a informação geral pode complementar o que for compatível.
As observações específicas do gestor também passam por essa seleção.

A seleção usa uma chamada adicional ao modelo, somente quando há comentário e
contexto. O redator recebe os trechos selecionados. Se a seleção falhar, a geração
continua apenas com a avaliação. Nenhum contexto salvo é apagado ou modificado.
Análises agregadas de satisfação se baseiam nos relatos dos clientes.

## Preços oficiais

`services/stripe_catalog.json` registra os IDs, moedas, valores em centavos e
periodicidades conferidos na conta ComentsIA no Stripe em 23/09/2026.
`services/pricing.py` centraliza o catálogo para as páginas e o checkout.

Como o valor de um Price Stripe é imutável, os IDs conferidos usam esse registro
local. Um novo ID configurado nas variáveis `STRIPE_PRICE_*` ou
`STRIPE_ADDON_PRICE_ID` é consultado no Stripe e validado antes de ser exibido.
Após trocar a configuração, reinicie a aplicação para atualizar também os IDs
carregados pelo checkout. Não altere apenas o valor em centavos no arquivo.

As antigas tabelas locais de preços são preservadas, mas não substituem o valor
Stripe. O painel administrativo mostra os preços em modo de consulta para evitar
anunciar um valor diferente do checkout. Os valores são em BRL em todos os idiomas.

| Produto | Valor |
| --- | --- |
| Pro mensal / anual | R$ 49,99 / R$ 549,99 |
| Business mensal / anual | R$ 79,99 / R$ 899,99 |
| Ficha extra mensal | R$ 29,99 |
| iFood / Mercado Livre mensal | R$ 29,90 cada |
| Histórico de 30 / 60 / 90 / 180 dias | R$ 19,00 / R$ 34,99 / R$ 59,99 / R$ 99,99 |
