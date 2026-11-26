# Plataforma de IA como Serviço — C3.A2

Projeto integrador de Sistemas Distribuídos e Computação em Nuvem, FAESA. A plataforma classifica sentimentos por uma API protegida e também processa tarefas assíncronas.

## Componentes

- **Gateway** (`:8000`): login, JWT, rate limit, rota síncrona e publicação de tarefas.
- **Inferência** (`:8001` na rede interna): classificação e operações vetoriais.
- **Redis**: fila de tarefas, status por 24 horas e fila de descarte.
- **Worker**: consome tarefas e chama a inferência.
- **Qdrant**: armazena vetores e metadados dos documentos.

O gateway é a única porta publicada pelo Compose. JWT é validado no gateway; os demais serviços ficam na rede interna. A implantação existente e seus limites estão em [deploy/INSTRUCOES.md](deploy/INSTRUCOES.md).

## Começar do zero com Docker

Pré-requisitos: Git, Docker Desktop com Docker Compose e internet para baixar imagens e dependências. No PowerShell:

```powershell
git clone https://github.com/eliaferreira/sd-2026-2-kit-c3a2.git
cd sd-2026-2-kit-c3a2
Copy-Item .env.example .env
notepad .env
```

No `.env`, preencha `JWT_SEGREDO` com um valor longo e aleatório e `LOGIN_SENHA` com uma senha própria. Ajuste `LOGIN_USUARIO` se desejar. Salve o arquivo; ele não deve ser enviado ao Git. Depois:

```powershell
docker compose config --quiet
docker compose up --build -d
docker compose ps
docker compose logs --tail 50 gateway inferencia worker
Invoke-RestMethod http://localhost:8000/saude
```

O build pode demorar na primeira execução. `/saude` verifica o gateway, sem garantir que as dependências estejam disponíveis. Para autenticar, substitua os valores pelas credenciais definidas no `.env`:

```powershell
$cred = @{ usuario = "admin"; senha = "SUA_SENHA" } | ConvertTo-Json
$token = (Invoke-RestMethod http://localhost:8000/login -Method Post -ContentType "application/json" -Body $cred).access_token
$headers = @{ Authorization = "Bearer $token" }
$body = @{ texto = "atendimento excelente" } | ConvertTo-Json
Invoke-RestMethod http://localhost:8000/predict -Method Post -Headers $headers -ContentType "application/json" -Body $body
```

Para verificar fila e worker pelo gateway:

```powershell
$tarefa = Invoke-RestMethod http://localhost:8000/tarefas -Method Post -Headers $headers -ContentType "application/json" -Body $body
Invoke-RestMethod "http://localhost:8000/tarefas/$($tarefa.id)" -Headers $headers
```

Consulte novamente até o status ser `concluido` ou `falhou`. O status fica disponível por 24 horas e só pode ser consultado pelo usuário que criou a tarefa. A fila de descarte preserva tarefas com falha para análise operacional.

Para encerrar, execute `docker compose down`. Os volumes de Redis e Qdrant são preservados; removê-los também apaga os dados persistidos.

## Observabilidade

Cada operação emite um span JSON nos logs com `trace_id`, `span_id`, `parent_span_id`, serviço, operação, resultado e duração. O gateway aceita um `traceparent` W3C versão `00` válido ou cria um novo trace; ele encaminha o contexto à inferência ou o inclui na mensagem da fila. O worker recupera esse contexto e o repassa à inferência. Assim, os spans podem ser correlacionados pelo mesmo `trace_id`:

```powershell
docker compose logs --no-color gateway worker inferencia | Select-String '"tipo": "span"'
```

Os spans não incluem texto, token ou credenciais. Logs existentes dos serviços também devem ser considerados na política de privacidade. A implementação gera logs estruturados e propaga `traceparent`; ela não instala OpenTelemetry Collector, exportador OTLP ou painel de visualização. O estado do trace não altera o comportamento do endpoint. Cabeçalhos de versões desconhecidas ou inválidos iniciam outro trace.

## Testes

A [validação em ambiente limpo na CI](https://github.com/eliaferreira/sd-2026-2-kit-c3a2/actions/runs/45755374559)
construiu as imagens e executou os fluxos síncrono e assíncrono com Redis real,
as operações de inserção/busca/remoção no Qdrant e a correlação dos spans entre
gateway, fila, worker e inferência. Os cinco jobs terminaram com sucesso.

Execute as suítes de cada serviço em ambientes virtuais separados, pois as dependências possuem versões diferentes. A CI executa `python -m pytest -v -rxX` nas pastas `gateway`, `worker` e `inferencia` após instalar seus arquivos `requirements.txt` e `requirements-dev.txt`. O teste de integração do Qdrant é pulado se o serviço local não estiver disponível.

Com a stack do Compose funcionando, teste de ponta a ponta usando Python 3.12:

```powershell
python -m venv .venv-e2e
.\.venv-e2e\Scripts\python.exe -m pip install -r tests/e2e/requirements.txt
$env:E2E_URL = "http://localhost:8000"
$env:E2E_TOKEN = $token
.\.venv-e2e\Scripts\python.exe -m pytest tests/e2e -v -rs
```

O teste local de HTTPS é pulado; em uma URL pública, HTTPS é exigido. A execução cria uma tarefa de teste no Redis. Não rode contra produção sem considerar os dados e limites da implantação.

## Implantação

O README anterior informa uma implantação do gateway em <https://sd-2026-2-kit-c3a2.onrender.com>. A disponibilidade e o funcionamento completo de inferência, Redis e worker no deploy precisam ser verificados separadamente; `GET /saude` não comprova o fluxo inteiro. Siga [deploy/INSTRUCOES.md](deploy/INSTRUCOES.md) e configure os segredos no provedor.

## Dados e LGPD

O gateway recebe textos para classificação. Tarefas assíncronas e seus resultados transitam pelo Redis; status expira em 24 horas, enquanto mensagens na fila e descarte permanecem conforme a operação do Redis. Documentos e metadados indexados no Qdrant permanecem até remoção ou gestão do volume. Não coloque dados pessoais em textos de teste. Restrinja acesso à infraestrutura e defina com o grupo finalidade, retenção e procedimentos de exclusão adequados à implantação. A API vetorial oferece remoção de documentos por ID.

## Distribuição do trabalho

Consulte [TAREFAS.md](TAREFAS.md) e os relatórios em `docs/`. A configuração das dependências e as credenciais são lidas do ambiente; não inclua `.env` ou segredos nos commits.

## Resiliência

O gateway usa timeout, retry e circuit breaker na chamada de inferência; o worker possui retentativas limitadas. Veja [docs/RESILIENCIA.md](docs/RESILIENCIA.md) para limites, configuração e testes de falha.
