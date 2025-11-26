# Guia da tela de configuração de LLM

A captura exibida mostra o painel da interface gráfica usado para conectar o host aos provedores locais de LLM (Ollama ou LM Studio). Cada campo da tela controla como o host se conecta e qual modelo será utilizado.

- **Framework (Ollama / LM Studio)**: troca o provedor de LLM. Escolha **Ollama** para usar a API local do Ollama ou **LM Studio** para a API compatível com OpenAI do LM Studio.
- **URL do servidor**: endereço HTTP onde o provedor selecionado está ouvindo. O padrão `http://localhost:11434` aponta para uma instância local do Ollama; altere para o endpoint do LM Studio quando usar esse framework.
- **Modelo**: nome do checkpoint que será solicitado ao provedor. Ex.: `llama3.1` para Ollama ou `llama3.2-vision` para um modelo multimodal.
- **Verificar conectividade**: envia uma chamada de teste para o endpoint configurado e confirma se o servidor está respondendo. Útil para validar URL/porta antes de iniciar uma sessão.
- **Listar modelos**: consulta o provedor para retornar a lista de modelos disponíveis localmente. Ajuda a descobrir o nome correto a preencher no campo **Modelo**.
- **Baixar modelo**: dispara o download de um modelo diretamente pelo provedor (quando ele suporta pull automático, como no Ollama). Use para obter o checkpoint antes de executar jobs reais.
- **Executar host**: inicia o host MCP com as configurações atuais (framework, URL e modelo). A partir daí o host conversa com o darktable e com o LLM escolhido para executar rating/tagging/export.

Preencha a URL e o modelo, teste a conexão e só então execute o host para evitar erros de rede ou nomes de modelos incorretos.
