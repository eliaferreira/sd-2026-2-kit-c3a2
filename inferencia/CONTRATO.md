# Contrato: serviço de inferência

- Endereço na rede do compose: `http://inferencia:8001`
- Formato: JSON UTF-8
- Autenticação: nenhuma (serviço interno; o JWT é validado no gateway)
- Cabeçalhos de rastreamento: aceita e propaga `traceparent`

## Endpoints

### GET /saude
- **200 OK** → `{"status": "ok", "vetorial": "ok" | "indisponivel"}`

### POST /predict
- **Entrada:** `{"texto": "..."}`
- **200 OK** → `{"texto": "...", "sentimento": "positivo" | "negativo", "confianca": 0.5688, "tempo_ms": 1.02}`
- **422 Unprocessable Entity** → `texto` ausente ou vazio/em branco

### POST /documentos
- **Entrada:** `{"texto": "..."}`
- **201 Created** → `{"id": "uuid-v4"}`
- **422 Unprocessable Entity** → entrada inválida (`texto` ausente ou vazio)
- **503 Service Unavailable** → `{"detail": "banco vetorial indisponivel"}`

### POST /buscar
- **Entrada:** `{"texto": "...", "k": 3}` (`k` opcional, padrão `3`, inteiro de `1` a `20`)
- **200 OK** → `{"resultados": [{"id": "uuid-v4", "score": 0.7559, "texto": "..."}]}`
- **422 Unprocessable Entity** → entrada inválida (`texto` vazio ou `k` fora do intervalo `1..20`)
- **503 Service Unavailable** → `{"detail": "banco vetorial indisponivel"}`

### DELETE /documentos/{id}
- **200 OK** → `{"id": "uuid-v4", "removido": true}`
- **503 Service Unavailable** → `{"detail": "banco vetorial indisponivel"}`

## Variáveis de ambiente

| Variável | Padrão | Descrição |
|---|---|---|
| `MODEL_PATH` | `inferencia/modelo.joblib` | Caminho do arquivo de modelo treinado (`treinar.py`) |
| `DADOS_TREINO_PATH` | `inferencia/dados_treino.csv` | Caminho do dataset CSV de treino |
| `QDRANT_URL` | `http://localhost:6333` (`http://qdrant:6333` no compose) | Endereço do banco vetorial Qdrant |
| `QDRANT_COLECAO` | `documentos` | Nome da coleção no Qdrant |
| `TIMEOUT_VETORIAL` | `5.0` | Timeout (s) nas chamadas ao Qdrant |
| `VETOR_DIMENSAO` | `256` | Dimensão dos vetores gerados pelo `HashingVectorizer` |
| `VETORIAL_MAX_TENTATIVAS` | `3` | Total de tentativas antes de retornar `503` |
| `VETORIAL_ESPERA_BASE_S` | `0.5` | Espera base (s) do backoff exponencial (`0.5s`, `1.0s`, `2.0s`) |
| `BUSCA_K_PADRAO` | `3` | Valor padrão de `k` no endpoint `/buscar` |
| `BUSCA_K_MAX` | `20` | Valor máximo aceito para `k` no endpoint `/buscar` |
| `OTEL_SERVICE_NAME` | `inferencia` | Nome do serviço para logs e rastreamento distribuído |

## Garantias e limites

- **Latência típica medida (50 requisições):**
  - `/predict`: média **3,67 ms**, p95 **4,46 ms**
  - `/buscar`: média **3,14 ms**, p95 **3,64 ms** (processamento local; ~5 a 8 ms com salto de rede até o container `qdrant`)
- **`/predict` não depende do banco vetorial:** continua respondendo `200 OK` mesmo se o Qdrant estiver fora do ar.
- **Códigos `503` indicam falha temporária:** o serviço já executa 3 tentativas internas com espera progressiva (`0,5s`, `1,0s`, `2,0s`); o chamador (gateway) pode aplicar *circuit breaker* sobre respostas `503`.
- **Privacidade (LGPD):** nenhum log registra o conteúdo de `texto`. Documentos indexados em `/documentos` podem ser removidos sob demanda via `DELETE /documentos/{id}`.
