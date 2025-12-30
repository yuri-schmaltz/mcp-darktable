# Roadmap de Refactor e Desacoplamento

## Pontos de Acoplamento Identificados

- Chamadas diretas entre host/batch_processor.py e server/dt_mcp_server.lua via McpClient.
- Dependência de formatos de mensagem específicos em build_messages.
- Configuração de prompts e variantes diretamente em arquivos .md.

## Propostas de Refactor

1. **Definir contratos/interfaces para comunicação host ↔ server:**
   - Especificar payloads e respostas esperadas para cada método.
   - Documentar erros e códigos de status.
2. **Abstrair providers LLM:**
   - Interface única para providers, facilitando troca/mocks.
3. **Governança de prompts/configs:**
   - Centralizar e versionar prompts.
   - Validar schema dos prompts antes de uso.
4. **Separação de responsabilidades:**
   - Dividir lógica de processamento, I/O e integração LLM em módulos distintos.

## Próximos Passos
- Mapear dependências cruzadas e propor interfaces.
- Implementar testes de contrato para comunicação host/server.
- Refatorar batch_processor.py para usar injeção de dependências.

## Validação
- Testes unitários e integração para cada boundary.
- Facilidade de mock e extensão de providers.
