# Relatório de Trade-offs — Serviço de Inferência e Armazenamento Vetorial

**Trabalho C3.A2 · Sistemas Distribuídos e Computação em Nuvem · FAESA · 2026/2**

---

## 1. Teorema CAP e Resiliência no Armazenamento Vetorial

### 1.1 Arquitetura adotada (Nó Único vs. Modo Cluster no Qdrant)

Na arquitetura do projeto, o banco vetorial **Qdrant** (`qdrant/qdrant:v1.12.1`) executa como um serviço dedicado com persistência em volume Docker (`qdrant_dados:/qdrant/storage`) em **topologia de nó único (*single-node*)**.

- **Comportamento em nó único:**
  - Enquanto o nó está ativo e acessível na rede do Compose, todas as leituras (`/buscar`) refletem imediatamente as escritas confirmadas (`/documentos`, `DELETE /documentos/{id}`), oferecendo **consistência forte local**.
  - Contudo, o container do Qdrant constitui um **ponto único de falha (*Single Point of Failure* — SPOF)** para as operações vetoriais: se o container parar ou houver partição de rede entre `inferencia` e `qdrant`, o subsistema vetorial fica indisponível.

- **Comparação com o Qdrant em modo Cluster (Distribuído):**
  - Em produção distribuída, o Qdrant utiliza o protocolo de consenso **Raft** para coordenar os metadados do cluster e a topologia das coleções (**CP** para operações de metadados: exige quórum para criar/alterar coleções durante partições).
  - Para operações de dados (inserção e busca de pontos), o Qdrant permite escolher o *trade-off* entre **Consistência (C)** e **Disponibilidade (A)** a cada operação por meio de `replication_factor` e `write_consistency_factor`:
    - Com `write_consistency_factor = N` (`All`), prioriza-se **CP** (escritas falham se uma réplica estiver inacessível, garantindo leitura consistente).
    - Com `write_consistency_factor = 1` e múltiplas réplicas, prioriza-se **AP** (o cluster aceita escritas e buscas mesmo com nós caídos, sob consistência eventual entre réplicas).

### 1.2 Decisão de Engenharia: Degradação Parcial Controlada (AP no Serviço Global)

Para maximizar a **disponibilidade (A)** da plataforma mesmo com o Qdrant em nó único:

1. **Desacoplamento entre `/predict` e o banco vetorial:** o classificador de sentimento (`modelo.joblib`) reside em memória no processo do serviço `inferencia`. Se o Qdrant cair ou sofrer partição de rede, **`POST /predict` continua operando com 100% de disponibilidade (`200 OK`)**.
2. **Falha rápida e explícita nas rotas vetoriais:** as chamadas ao Qdrant possuem *timeout* configurável (`TIMEOUT_VETORIAL=5.0s`) e retentativa com *backoff* exponencial (`0,5s`, `1,0s`, `2,0s`). Esgotadas as tentativas, `/documentos` e `/buscar` retornam **`503 Service Unavailable`** (`{"detail": "banco vetorial indisponivel"}`), nunca `500 Internal Server Error`.
3. **Healthcheck inteligente (`/saude`):** o endpoint `GET /saude` sempre responde `200 OK` quando o processo FastAPI e o modelo de classificação estão saudáveis, reportando o estado da dependência no corpo (`{"status": "ok", "vetorial": "ok" | "indisponivel"}`). Isso impede que um orquestrador (Docker/Kubernetes/Render) mate e reinicie em loop o container de inferência por causa de uma indisponibilidade externa do banco vetorial.
4. **Recuperação automática (*self-healing*):** ao detectar falha no Qdrant, a camada `ArmazenamentoVetorial` invalida a flag local de coleção verificada; assim que o Qdrant volta ao ar, a coleção é verificada/recriada automaticamente na próxima requisição, sem necessidade de reiniciar o serviço `inferencia`.

---

## 2. Análise de Latência

### 2.1 Medições Reais (Benchmark de 50 Requisições por Endpoint)

Foram executadas **50 requisições sequenciais** para `POST /predict` e **50 requisições sequenciais** para `POST /buscar` (com coleção populada e `k=3`):

| Endpoint | Operação Executada | Média (ms) | Mediana / p50 (ms) | Percentil 95 / p95 (ms) |
|---|---|---:|---:|---:|
| `POST /predict` | Vetorização TF-IDF + Regressão Logística em memória | **3,67 ms** | **3,56 ms** | **4,46 ms** |
| `POST /buscar` | `HashingVectorizer` (256d L2) + busca cosseno no Qdrant | **3,14 ms** | **3,03 ms** | **3,64 ms** |

*(Nota: em execução via rede virtual de containers Docker entre `inferencia` e `qdrant:6333`, adiciona-se tipicamente `1,5 ms a 4,0 ms` de sobrecarga de serialização HTTP/TCP na pilha de rede local, mantendo o p95 total de `/buscar` abaixo de `10 ms` em condições normais).*

### 2.2 Comparação de Trade-off: `HashingVectorizer` vs. Embeddings Densos (Transformers)

| Critério | `HashingVectorizer` (256d, L2) — **Escolhido** | Modelo Transformer (`all-MiniLM-L6-v2`) |
|---|---|---|
| Latência de vetorização (CPU) | **< 0,5 ms** por texto | **30 ms a 80 ms** por texto em CPU compartilhada |
| Download na construção/subida | **0 MB** (100% offline) | **~90 MB a 420 MB** (pesos PyTorch/ONNX) |
| Uso de RAM no processo | **~2 MB** adicionais | **~350 MB a 600 MB** adicionais |
| Qualidade semântica | Similaridade léxica / n-gramas (`(1, 2)`) | Similaridade semântica profunda |

Como a rubrica da disciplina prioriza arquitetura distribuída, comunicação e reprodutibilidade (e a sofisticação do modelo de IA não pontua), o `HashingVectorizer` oferece latência **~50x menor** e elimina o risco de *Out-Of-Memory (OOM)* no ambiente gratuito.

---

## 3. Análise de Custo e Limites do Free Tier

Em provedores de nuvem com camada gratuita (*free tier* como Render e Railway), os limites típicos por instância são de **512 MB de RAM** e **0,1 a 0,5 vCPU**, além de armazenamento efêmero ou volumes limitados:

1. **Consumo de Memória RAM:**
   - **Serviço `inferencia` (Python 3.12-slim + FastAPI + scikit-learn):** ~95 MB de RAM em repouso. Como o modelo (`modelo.joblib`, ~8 KB) é carregado **uma única vez na subida** e o `HashingVectorizer` é *stateless* (não armazena vocabulário em memória), o uso de RAM permanece estável mesmo sob carga.
   - **Container `qdrant/qdrant:v1.12.1` (escrito em Rust):** ~45 MB a 70 MB de RAM em repouso para coleções pequenas de 256 dimensões (`256 * 4 bytes = 1 KB` por vetor).
2. **Consumo de Disco e Build:**
   - A geração do modelo (`RUN python treinar.py`) durante o `docker build` leva menos de `1 segundo` e adiciona menos de `20 KB` à imagem final.
   - Dependências de teste (`pytest`, `httpx`) foram isoladas em `requirements-dev.txt` e excluídas via `.dockerignore`, reduzindo o tamanho da imagem de produção e o tempo de *deploy*.
3. **Plano de Contingência para o Free Tier:**
   - Caso o ambiente de *deploy* gratuito não comporte um container separado para o Qdrant, a classe `ArmazenamentoVetorial` aceita injeção direta de `QdrantClient(":memory:")` (ou substituição pela implementação em memória), mantendo o contrato de API intacto sem custo adicional de infraestrutura.
