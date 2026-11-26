# Operação e revisão do rastreamento

## Ler um trace

O gateway cria um contexto quando não recebe um `traceparent` válido. O
`trace_id` permanece igual durante a operação; cada span tem um `span_id`
próprio e aponta para o anterior por `parent_span_id`.

No fluxo assíncrono, a sequência esperada é:

1. Gateway: `HTTP POST`, recebimento da solicitação autenticada.
2. Gateway: `fila.publicar`, contexto incluído na mensagem do Redis.
3. Worker: `fila.processar`, contexto recuperado da mensagem.
4. Worker: `inferencia.predict`, chamada HTTP com o contexto atual.
5. Inferência: `HTTP POST`, processamento da classificação.

Para localizar os spans no PowerShell:

```powershell
docker compose logs --no-color --no-log-prefix gateway worker inferencia |
    Select-String '"tipo": "span"'
```

Escolha um `trace_id` e filtre por ele. Compare os IDs de pai e filho para
identificar onde o fluxo terminou. Tempos são durações locais de cada span;
não some spans que se sobrepõem. O tempo de espera na fila não é medido por
um span dedicado nesta implementação.

## Diagnosticar falhas

- Sem `fila.publicar`: confira autenticação, validação e rate limit antes da fila.
- `fila.publicar` com resultado `erro`: confira a conexão do gateway com Redis.
- Publicação sem `fila.processar`: confira se o worker está ativo e conectado ao Redis.
- `inferencia.predict` com erro: confira disponibilidade, timeout e retentativas da inferência.
- Status `falhou`: confira os logs do worker e a fila de descarte conforme o contrato da fila.

Uma resposta de saúde do gateway não comprova que toda a cadeia funciona.
O teste ponta a ponta publica uma tarefa e espera a conclusão pelo gateway.

## Verificar a integração

Com a stack isolada em execução e as dependências de `tests/e2e/requirements.txt`
instaladas, execute os testes descritos no README. O teste assíncrono usa um
trace conhecido; em seguida, execute:

```powershell
python tests/e2e/verificar_integracao.py
```

O script usa Docker Compose: verifica inserção, busca e remoção no Qdrant real
e confere os vínculos dos spans nos logs dos containers. Use uma stack de teste
limpa, como o job `ponta-a-ponta` da CI, pois mais de uma execução com o mesmo
trace nos logs fará a verificação de unicidade falhar.

## Limites e privacidade

O contexto usa `ContextVar`, separando requisições concorrentes e restaurando
o contexto anterior ao sair de um span. A revisão automatizada cobre saída
normal, saída com exceção, concorrência e cabeçalhos inválidos.

Os spans contêm serviço, operação, IDs, resultado e duração. Não inclua texto
do usuário, tokens ou credenciais nos nomes ou atributos. Cabeçalhos de trace
servem para correlação e não são uma prova de identidade nem autorização.

Os registros são JSON no stdout dos processos, sujeitos à retenção de logs
do ambiente. Não há exportação OTLP, coletor, painel ou amostragem implementados.
O campo de flags é propagado, mas não controla a emissão dos logs.
