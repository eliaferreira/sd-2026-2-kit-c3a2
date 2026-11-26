# Resiliência e testes de falha — Vinicius

## Gateway → inferência

`gateway/resiliencia.py` protege `POST /predict`. A classificação não altera
dados, portanto pode ser repetida. Essa política não deve ser aplicada
automaticamente a endpoints de criação ou a chamadas com efeitos externos.

| Configuração | Padrão | Comportamento |
|---|---|---|
| `INFERENCIA_TIMEOUT_S` | `3` | Timeout de conexão e de inatividade de leitura, em segundos, por tentativa |
| `INFERENCIA_MAX_TENTATIVAS` | `3` | Total de chamadas HTTP, incluindo a primeira |
| `INFERENCIA_BACKOFF_S` | `0.2` | Esperas exponenciais entre tentativas: `0.2s`, `0.4s` |
| `CIRCUITO_INFERENCIA_FALHAS` | `3` | Operações consecutivas que falharam para abrir o circuito |
| `CIRCUITO_INFERENCIA_ESPERA_S` | `20` | Espera antes de permitir uma sondagem |

Somente falhas de conexão, timeout e HTTP `429`, `500`, `502`, `503`, `504`
recebem novas tentativas. Não há espera depois da última tentativa.
O timeout do Requests não é um prazo global para a operação: conexão,
leitura e backoff têm seus próprios tempos.

Uma operação esgotada retorna `503` com
`{"detail":"servico de inferencia indisponivel"}`. A resposta não inclui
exceções, URLs internas nem corpos de erro da dependência. JSON inválido,
contrato de classificação incompatível e status inesperados também retornam
`503`, sem retry. Redirecionamentos não são seguidos.

Erros `4xx`, exceto `429`, não são retentados nem contados como falha do
circuito. Seu status é preservado com mensagem genérica. Por exemplo, texto
em branco recusado pela inferência continua sendo `422`.

### Circuit breaker

1. **Fechado:** permite chamadas. Um sucesso zera as falhas consecutivas.
   As três tentativas de uma requisição contam como uma única operação.
2. **Aberto:** após três operações falhas, rejeita novas chamadas sem acessar
   a inferência ou executar backoff. Responde `503` e `Retry-After` em segundos.
3. **Meio aberto:** após 20 segundos, permite uma única operação de sondagem,
   com o mesmo limite de tentativas. As chamadas concorrentes recebem `503`.
   Se a dependência responde normalmente, fecha; se falha, abre por mais 20s.

O estado usa relógio monotônico e lock. Nenhum lock fica preso durante a
chamada HTTP. Resultados de chamadas anteriores à abertura não podem fechar
o circuito. O estado é local a cada processo do gateway e reinicia com ele;
vários processos/réplicas têm circuitos independentes.

JWT e rate limit continuam sendo executados antes de acessar a inferência.
`GET /saude` continua sendo uma verificação do próprio gateway e responde
`{"status":"ok"}` mesmo com o circuito aberto. Isso não garante que a
dependência esteja disponível. Logs de resiliência contêm tentativa, categoria
da falha e transição do circuito, sem texto de usuário ou token.

## Worker e armazenamento vetorial

O worker chama a inferência diretamente e mantém **um único** ciclo de retry,
preservando a fila, os estados e a fila de descarte implementados por Lucas.

| Configuração | Padrão | Comportamento |
|---|---|---|
| `WORKER_TIMEOUT_S` | `3` | Timeout HTTP por tentativa |
| `WORKER_MAX_TENTATIVAS` | `3` | Total de tentativas por tarefa |
| `WORKER_BACKOFF_S` | `0.5` | Esperas exponenciais: `0.5s`, `1.0s` |

O worker repete somente falhas transitórias da mesma lista usada no gateway.
Erros permanentes ou JSON inválido seguem para descarte sem novas chamadas.
Depois do esgotamento, registra `falhou`. Erros em logs, status e motivo do
descarte registram somente a categoria da exceção. O conteúdo da tarefa
permanece na fila conforme o contrato existente. O worker não compartilha o
circuito do gateway e não possui circuit breaker próprio nesta entrega.

A implementação vetorial de Luis foi preservada: já possui timeout e retry
exponencial dentro da inferência. `/predict` não depende do Qdrant. Não foi
adicionado outro ciclo externo em torno das operações vetoriais.

As novas variáveis estão em `.env.example` e são repassadas aos respectivos
containers no `docker-compose.yml`. Para implantação fora do Compose, configure
as variáveis no processo/serviço correspondente. Valores inválidos impedem a
inicialização, em vez de desativar silenciosamente o timeout.

## Executar os testes no PowerShell

Na raiz do repositório, use ambientes separados para evitar conflitos entre
as versões das dependências dos serviços:

```powershell
python -m venv gateway/.venv
Push-Location gateway
./.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
./.venv/Scripts/python.exe -m pytest -v
Pop-Location

python -m venv worker/.venv
Push-Location worker
./.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
./.venv/Scripts/python.exe -m pytest -v
Pop-Location

python -m venv inferencia/.venv
Push-Location inferencia
./.venv/Scripts/python.exe -m pip install -r requirements.txt -r requirements-dev.txt
./.venv/Scripts/python.exe -m pytest -v -rs
Pop-Location
```

Em Linux/macOS, substitua `.venv/Scripts/python.exe` por `.venv/bin/python`.
Execute cada suíte na pasta do serviço, como a matriz da CI já faz.

| Cenário automatizado | Resultado esperado |
|---|---|
| Conexão recusada/timeout | Tentativas limitadas e `503` tratado |
| HTTP transitório seguido de sucesso | Retry com backoff e `200` |
| Inferência lenta via conexão TCP real | Timeout de leitura e `503` |
| Três operações falhas consecutivas | Circuito aberto |
| Requisição durante circuito aberto | `503` + `Retry-After`, nenhuma chamada HTTP |
| Inferência volta após a espera | Sondagem bem-sucedida fecha circuito |
| Duas chamadas concorrentes em meio aberto | Apenas uma sondagem permitida |
| Sucesso atrasado de operação antiga | Não fecha circuito aberto |
| HTTP `422` / JSON inválido | Sem retry; `422` / `503`, respectivamente |
| JWT inválido ou rate limit excedido | `401` / `429`, antes de acessar inferência |
| Worker esgota tentativas | Status `falhou` e descarte |
| Worker recupera após falha transitória | Status `concluido`, sem descarte |
| Qdrant indisponível | Testes existentes preservam `503` vetorial e `/predict` funcional |

`gateway/tests/test_falhas_http.py` inicia uma dependência controlada em
loopback com porta temporária e usa Requests real. Os testes de abertura e
recuperação avançam um relógio injetado, sem aguardar 20 segundos. Os demais
testes usam dublês para conferir limites, backoff, concorrência e privacidade.
Não precisam de Redis, Qdrant, Docker ou acesso ao deploy público.
O teste de integração com Qdrant real da suíte de inferência é pulado quando
o banco não está disponível. Esses testes isolados não substituem o teste
final da stack em containers, que faz parte da integração do grupo.

### Validação local em 26/11/2026

| Suíte | Resultado |
|---|---|
| Gateway, incluindo os testes HTTP em loopback | 50 passaram |
| Worker | 20 passaram |
| Inferência, sem alterações no código do serviço | 17 passaram, 1 pulado por ausência de Qdrant |

Também foi realizado um ensaio com gateway e inferência reais, em processos
locais com portas temporárias: login e classificação `200`, inferência
desligada `503`, circuito aberto com `Retry-After` e recuperação `200` após
reiniciar a inferência. Os processos temporários foram encerrados.

O YAML do Compose e o repasse das oito variáveis novas foram conferidos.
A construção das imagens e o ensaio manual com Compose ainda precisam ser
executados em uma máquina com Docker, indisponível no ambiente desta validação.

## Demonstração manual com Compose

Com Docker instalado e `.env` configurado, execute `docker compose up --build -d`.
No PowerShell, autentique usando as credenciais configuradas no gateway:

```powershell
$login = @{ usuario = "admin"; senha = "admin" } | ConvertTo-Json
# Ajuste as credenciais acima para a configuração do gateway.
$token = (Invoke-RestMethod http://localhost:8000/login -Method Post `
    -ContentType "application/json" -Body $login).access_token
$headers = @{ Authorization = "Bearer $token" }
$body = @{ texto = "atendimento excelente" } | ConvertTo-Json

Invoke-RestMethod http://localhost:8000/predict -Method Post `
    -Headers $headers -ContentType "application/json" -Body $body
docker compose stop inferencia
```

Repita a chamada `/predict` três vezes: cada operação recebe `503` e tem até
três tentativas internas. Na quarta, o circuito já aberto devolve `503`
imediatamente, sem acessar a inferência. O PowerShell mostra erro para `503`;
isso é esperado. Veja as transições com `docker compose logs gateway`.

Execute `docker compose start inferencia`, aguarde o serviço iniciar e a janela
de 20 segundos terminar, então repita `/predict`. A sondagem retorna `200` e
fecha o circuito. Para um novo ensaio limpo, reinicie apenas o gateway:
`docker compose restart gateway`. Limite o ensaio para não atingir o rate limit.
