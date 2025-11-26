# Visão geral das comunicações

A tela de "Visão geral das comunicações" resume todos os canais configurados e as ações recentes. Os campos visíveis na captura são:

- **ID**: identificador numérico de cada canal cadastrado. Útil para localizar registros específicos em logs ou para suporte.
- **Canal**: tipo de comunicação associado ao ID (por exemplo, e-mail transacional, SMS ou WhatsApp). Ajuda a diferenciar fluxos e provedores.
- **Status**: situação operacional do canal, indicando se está **ativo** (pode enviar mensagens) ou **inativo** (desabilitado ou em configuração).
- **Último resultado**: mostra o desfecho da última tentativa de envio (por exemplo, *Sucesso* ou *Falha*), facilitando a identificação de problemas recentes.
- **Ações pendentes**: tabela inferior com as últimas interações disparadas. Cada linha indica o **OS** (ordem de serviço ou ticket que originou a mensagem), a **Ação** solicitada (ex.: atualização de status), os **Destinatários** e o estado do envio (**Pendente**, **Enviada**, etc.).

Use esses campos para confirmar rapidamente se os canais estão prontos para uso, investigar falhas de entrega recentes e acompanhar as comunicações associadas a cada ordem de serviço.
