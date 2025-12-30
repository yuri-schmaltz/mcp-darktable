# Governança de Prompts e Configs — darktable-mcp

## Objetivo
Garantir rastreabilidade, versionamento e validação dos prompts e configurações usados nos fluxos críticos.

## Estrutura Recomendada
- Todos os prompts devem estar em `config/prompts/`.
- Nomeação: `<fluxo>_<variante>.md` (ex: rating_basico.md, export_avancado.md).
- Cada prompt deve conter cabeçalho YAML opcional com metadados:
  ```yaml
  ---
  fluxo: rating
  variante: basico
  autor: userX
  data: 2025-12-30
  changelog:
    - 2025-12-30: Criação inicial
    - 2025-12-31: Ajuste de instrução para LLM
  ---
  ```

## Processo de Alteração
1. Toda alteração deve ser registrada no changelog do cabeçalho YAML.
2. Alterações críticas exigem revisão por outro membro do time.
3. Prompts em uso devem ser validados por schema (estrutura mínima: fluxo, variante, instrução principal).

## Versionamento
- Recomenda-se versionar prompts junto ao código (git).
- Mudanças de comportamento devem ser documentadas no changelog do prompt e no PR.

## Validação
- Scripts de validação podem ser criados para checar presença de cabeçalho, campos obrigatórios e schema.
- Prompts sem cabeçalho ou com campos ausentes devem ser sinalizados no CI.

## Referências
- [Exemplo de prompt com cabeçalho](../config/prompts/rating_basico.md)
