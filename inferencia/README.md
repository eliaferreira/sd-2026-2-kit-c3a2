# Serviço de Inferência e Armazenamento Vetorial (`inferencia/`)

Microsserviço interno da plataforma **C3.A2** responsável por:
1. **Inferência de sentimento (`/predict`):** classifica textos em português (`positivo` / `negativo`) com pipeline `scikit-learn` (`TfidfVectorizer` + `LogisticRegression`) treinado de forma reproduzível e carregado uma única vez na inicialização.
2. **Armazenamento e busca vetorial (`/documentos`, `/buscar`):** converte textos em vetores densos normalizados (L2) via `HashingVectorizer` e persiste/consulta por similaridade de cosseno no banco vetorial **Qdrant** (`qdrant:6333`).

---

## Onde se encaixa na arquitetura

```
Cliente ──► Gateway (:8000) ──► Inferência (:8001) ──► Qdrant (:6333, volume qdrant_dados)
                 │                     ▲
                 ▼                     │
            Redis (:6379) ◄──── Worker ┘
```

- O serviço escuta na porta `8001` dentro da rede interna do Docker Compose (`http://inferencia:8001`).
- A autenticação JWT e o *rate limiting* ocorrem no **Gateway**; este serviço valida rigorosamente os payloads com Pydantic e propaga o cabeçalho `traceparent` para rastreamento distribuído.

---

## Como executar

### 1. Localmente (com ambiente virtual Python)

```bash
cd inferencia
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

# 1. Gerar o artefato do modelo (modelo.joblib)
python treinar.py

# 2. Subir o serviço na porta 8001
uvicorn app:app --host 0.0.0.0 --port 8001
```

### 2. Com Docker (isolado)

```bash
# A partir da raiz do repositório:
docker build -t inferencia ./inferencia
docker run --rm -p 8001:8001 inferencia
```

### 3. Com Docker Compose (stack completa)

```bash
cp .env.example .env
docker compose up --build
```

### 4. Como rodar os testes automatizados

Os testes unitários usam `TestClient` e uma implementação falsa em memória do banco vetorial (`ArmazenamentoVetorialFalso`), não exigindo que o Qdrant esteja rodando:

```bash
cd inferencia
pytest -v
```

---

## Resumo de Endpoints

> O detalhamento completo de payloads, formatos de resposta e códigos de erro está em [`CONTRATO.md`](./CONTRATO.md).

| Método | Rota | Status de Sucesso | Descrição |
|---|---|---|---|
| `GET` | `/saude` | `200 OK` | Informa saúde do serviço e conectividade com o Qdrant (`ok` ou `indisponivel`) |
| `POST` | `/predict` | `200 OK` | Classifica o sentimento do texto (`positivo` ou `negativo`) e retorna a confiança |
| `POST` | `/documentos` | `201 Created` | Vetoriza e indexa um documento no Qdrant, devolvendo o `id` gerado |
| `POST` | `/buscar` | `200 OK` | Busca os `k` documentos mais similares por distância cosseno |
| `DELETE` | `/documentos/{id}` | `200 OK` | Remove um documento do banco vetorial pelo `id` (direito de eliminação — LGPD) |

---

## Variáveis de Ambiente

Toda a configuração do serviço é controlada por variáveis de ambiente (lidas em [`config.py`](./config.py)):

| Variável | Padrão | Descrição |
|---|---|---|
| `MODEL_PATH` | `inferencia/modelo.joblib` | Caminho do arquivo de modelo treinado pelo `treinar.py` |
| `DADOS_TREINO_PATH` | `inferencia/dados_treino.csv` | Caminho do dataset versionado para treinamento reproduzível |
| `QDRANT_URL` | `http://localhost:6333` (`http://qdrant:6333` no Compose) | URL do serviço Qdrant |
| `QDRANT_COLECAO` | `documentos` | Nome da coleção vetorial no Qdrant |
| `TIMEOUT_VETORIAL` | `5.0` | Timeout (em segundos) por chamada ao Qdrant |
| `VETOR_DIMENSAO` | `256` | Dimensão dos embeddings gerados pelo `HashingVectorizer` |
| `VETORIAL_MAX_TENTATIVAS` | `3` | Número máximo de tentativas em chamadas ao Qdrant |
| `VETORIAL_ESPERA_BASE_S` | `0.5` | Espera base (s) para backoff exponencial (`0.5s`, `1.0s`, `2.0s`) |
| `BUSCA_K_PADRAO` | `3` | Quantidade padrão de resultados retornados em `/buscar` |
| `BUSCA_K_MAX` | `20` | Limite máximo permitido para `k` em `/buscar` |
| `OTEL_SERVICE_NAME` | `inferencia` | Nome do serviço exibido nos logs e no rastreamento distribuído |

---

## Decisões de Projeto

1. **Qdrant em container dedicado com volume nomeado (`qdrant_dados`):** garante isolamento de responsabilidades na arquitetura distribuída e persistência dos vetores após `docker compose down`.
2. **Embeddings com `HashingVectorizer` (`n_features=256`, normalização `L2`):** funciona 100% offline, determinístico, sem estado em disco e sem necessidade de baixar centenas de megabytes de modelos pré-treinados — ideal para o limite de memória do *free tier*.
3. **Desacoplamento via `ArmazenamentoVetorial`:** a aplicação (`app.py`) interage apenas com a classe de domínio em `armazenamento_vetorial.py`, permitindo injeção de dependência em memória nos testes e aplicação centralizada de *timeout* e *retry* com *backoff* exponencial.
4. **Degradação parcial controlada:** se o Qdrant estiver fora do ar, `/documentos` e `/buscar` respondem `503 Service Unavailable`, mas **`/predict` continua respondendo `200 OK` normalmente**, e `/saude` retorna `200 OK` com `{"status": "ok", "vetorial": "indisponivel"}` para evitar reinícios desnecessários pelo orquestrador.

---

## Dados Tratados e Conformidade (LGPD)

Insumo para a seção de conformidade da plataforma:

- **Dados recebidos:** campo `texto` enviado nas rotas `/predict`, `/documentos` e `/buscar`.
- **Logs de aplicação:** o middleware HTTP registra **exclusivamente** método, rota, código HTTP e latência em milissegundos (`[inferencia] POST /predict -> 200 (3.5ms)`). **O conteúdo de `texto` nunca é registrado em logs.**
- **Dados armazenados:**
  - Na rota `/predict`: **nenhum dado é armazenado** (processamento puramente em memória e descarte imediato após a resposta).
  - Na rota `/documentos`: são armazenados no Qdrant o identificador único (`UUID v4`), o vetor numérico de 256 dimensões (`float32`) e o payload `{"texto": "..."}` para permitir a recuperação dos trechos similares em `/buscar`.
- **Finalidade:** recuperação semântica/léxica de documentos similares previamente indexados pelos usuários autenticados da plataforma.
- **Retenção e Eliminação:** os documentos permanecem no volume persistente `qdrant_dados` enquanto necessários para a busca e podem ser **eliminados imediatamente sob demanda** por meio do endpoint `DELETE /documentos/{id}`, atendendo ao direito de eliminação previsto no Art. 18, VI da LGPD.
