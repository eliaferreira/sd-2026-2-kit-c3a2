# Testes automatizados

Três camadas, da mais rápida para a mais completa.

| Camada | Onde | Precisa de Docker? | Roda no CI? |
|---|---|---|---|
| Unitário do gateway | `gateway/tests/` | Não | Sim |
| Unitário da inferência | `inferencia/tests/` | Não | Sim |
| Ponta a ponta | `tests/e2e/` | Sim (ou URL publicada) | Não |

## 1. Testes de cada serviço

O CI roda estes testes em todo push e PR, e também um `docker build` de cada
serviço do `docker-compose.yml`.

```bash
cd gateway                         # ou: cd inferencia
python -m venv .venv
.venv\Scripts\activate             # Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -v -rxX
```

Os testes do gateway **não** precisam da inferência no ar: a chamada HTTP é
substituída por um dublê. Eles cobrem:

- `/saude` e o repasse do `/predict` para a inferência
- inferência fora do ar, lenta ou com erro 5xx → `503`
- tempo-limite definido na chamada à inferência
- entrada inválida → `422`
- log sem o texto enviado pelo usuário (LGPD)

### Critérios de aceite de JWT e rate limit

`gateway/tests/test_seguranca.py` descreve o comportamento esperado das
TAREFAS 1 e 2:

- `401` sem token, com token de outro segredo e com token expirado
- rota `/login` existente
- `429` quando o cliente passa do limite

Enquanto essas tarefas não forem implementadas, os testes aparecem como
**XFAIL** (falha esperada) e não quebram o CI. Quando a implementação entrar,
eles passam a aparecer como **XPASS**. Nesse momento, remova o marcador
`AGUARDANDO_JWT` / `AGUARDANDO_RATE_LIMIT` correspondente.

Premissas usadas nos testes: cabeçalho `Authorization: Bearer <token>`,
assinatura **HS256** com o segredo de `JWT_SEGREDO` e resposta `429` no
rate limit.

## 2. Ponta a ponta (sistema inteiro)

Fala com a plataforma real, sempre pelo gateway. Use com a stack local **e**
com a URL pública do deploy.

```bash
pip install -r tests/e2e/requirements.txt

# stack local
docker compose up --build -d
E2E_URL=http://localhost:8000 JWT_SEGREDO=<valor do .env> pytest tests/e2e -v

# deploy publicado (também confere HTTPS)
E2E_URL=https://<app-publicado> JWT_SEGREDO=<segredo do deploy> pytest tests/e2e -v
```

No PowerShell, defina as variáveis antes com `$env:E2E_URL="http://localhost:8000"`.

| Variável | Para quê |
|---|---|
| `E2E_URL` | Endereço do gateway (sem ela, os testes são pulados) |
| `E2E_TOKEN` | Token JWT pronto (opcional) |
| `JWT_SEGREDO` | Gera um token HS256 quando `E2E_TOKEN` não é informado |
| `E2E_TIMEOUT` | Tempo-limite por requisição, em segundos (padrão 30; o free tier demora a "acordar") |
