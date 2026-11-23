# Análise do Teorema CAP na Plataforma de IA como Serviço

**Disciplina:** Sistemas Distribuídos  
**Trabalho:** C3.A2 — Plataforma de IA como Serviço  
**Responsável pela análise:** Lucas Melo

## 1. Introdução

O Teorema CAP, também conhecido como Teorema de Brewer, apresenta uma limitação fundamental dos sistemas distribuídos. Ele estabelece que, durante uma partição de rede, não é possível garantir simultaneamente consistência forte e disponibilidade total em um sistema de dados distribuídos.

As três propriedades consideradas são:

- **Consistência (Consistency — C):** as operações de leitura devem observar os dados mais recentes, respeitando uma ordem consistente de operações.
- **Disponibilidade (Availability — A):** as requisições recebidas por nós operacionais devem obter respostas válidas, mesmo diante de determinadas falhas.
- **Tolerância a Partições (Partition Tolerance — P):** capacidade de continuar operando diante de falhas de comunicação entre componentes do sistema.

Na prática, quando ocorre uma partição de rede, o sistema precisa administrar o conflito entre manter a consistência dos dados e continuar atendendo às requisições.

## 2. Aplicação do Teorema CAP no Projeto

O projeto C3.A2 consiste em uma plataforma de Inteligência Artificial como Serviço, organizada em componentes distribuídos que se comunicam pela rede.

Na implementação analisada, destacam-se:

- **Gateway:** responsável pela entrada e pelo encaminhamento das requisições.
- **Redis:** utilizado como sistema de filas e armazenamento temporário do estado das tarefas.
- **Worker:** responsável pelo consumo das mensagens e pelo processamento assíncrono.
- **Serviço de inferência:** executa as previsões solicitadas pelo worker.
- **Qdrant:** utilizado no armazenamento e na recuperação de informações vetoriais.

A utilização de componentes separados permite organizar as responsabilidades e executar tarefas de maneira assíncrona. Entretanto, também cria dependências de comunicação entre os serviços.

Por exemplo, quando uma tarefa é publicada no Redis, o worker precisa conseguir acessar a fila para consumi-la. Em seguida, deve comunicar-se com o serviço de inferência e armazenar o resultado do processamento.

Caso alguma dessas conexões apresente falhas, a disponibilidade da operação poderá ser afetada.

## 3. Análise dos Trade-offs

### 3.1 Consistência

A consistência é importante para garantir que o status consultado represente corretamente a situação de uma tarefa.

Na implementação desenvolvida, cada tarefa possui um identificador único e pode apresentar estados como `na_fila`, `processando`, `concluido` ou `falhou`.

Os estados são armazenados no Redis, permitindo consultar o andamento do processamento.

Entretanto, o registro do estado e a movimentação das mensagens não são realizados como uma única transação atômica. Por isso, uma interrupção entre essas operações pode gerar inconsistências temporárias entre o status registrado e a situação real da tarefa.

### 3.2 Disponibilidade

A disponibilidade representa a capacidade da plataforma de continuar atendendo às solicitações.

O uso de uma fila assíncrona permite desacoplar parcialmente o recebimento das tarefas de seu processamento. Com isso, as mensagens podem aguardar no Redis enquanto o worker executa outras atividades.

Além disso, o worker implementa até três tentativas de comunicação com o serviço de inferência, utilizando intervalos progressivos entre as tentativas.

Caso todas falhem, a tarefa é encaminhada para uma fila de descarte (*dead-letter queue*), permitindo identificar os processamentos que não foram concluídos.

Essas estratégias melhoram o tratamento de falhas, mas não garantem disponibilidade contínua. Por exemplo, se o Redis estiver inacessível, novas tarefas não poderão ser publicadas por esse mecanismo.

### 3.3 Tolerância a Partições

Uma partição de rede ocorre quando componentes de um sistema distribuído deixam de conseguir se comunicar, mesmo que alguns continuem funcionando individualmente.

Na plataforma, isso pode acontecer quando o worker perde acesso ao Redis ou ao serviço de inferência.

As retentativas ajudam a lidar com falhas temporárias de comunicação. Entretanto, uma falha persistente pode impedir o processamento das tarefas.

Além disso, a configuração analisada utiliza instâncias únicas de Redis e Qdrant, sem comprovação de replicação ou mecanismos de consenso. Portanto, não é possível afirmar que esses serviços garantem disponibilidade ou consistência forte durante partições de rede.

## 4. Decisões Arquiteturais e Limitações

A arquitetura desenvolvida procura equilibrar simplicidade de implementação, processamento assíncrono e tratamento de falhas.

O Redis foi escolhido como intermediário para permitir que tarefas sejam armazenadas temporariamente e consumidas por um worker independente.

Essa abordagem reduz o acoplamento entre a publicação e o processamento das tarefas. Entretanto, a implementação atual utiliza a operação `BLPOP` para retirar mensagens da fila.

Isso representa uma limitação: se o worker for interrompido após remover uma mensagem, mas antes de registrar o resultado, a tarefa poderá ser perdida.

Para uma evolução futura, poderiam ser consideradas filas com confirmação de processamento, mecanismos de recuperação de tarefas e estratégias de replicação.

É importante destacar que o projeto não pode ser classificado rigorosamente como um sistema CP ou AP apenas pela utilização do Redis. Essa classificação depende das garantias efetivas dos componentes e de seu comportamento durante uma partição de rede.

## 5. Validação Prática

Durante o desenvolvimento, foram realizados oito testes automatizados, envolvendo publicação e consumo de mensagens, consulta de status, processamento das tarefas, retentativas e fila de descarte.

Também foi realizado um teste de integração com Redis, worker e serviço de inferência executados em containers Docker.

Uma tarefa contendo o texto "Eu gostei muito deste produto" foi publicada na fila, consumida pelo worker e enviada ao serviço de inferência.

O processamento foi concluído e o resultado armazenado no Redis apresentou:

- Status: `concluido`
- Sentimento: `positivo`
- Confiança: `0.5474` (54,74%)
- Tempo informado pela inferência: `28.96 ms`

Esse teste confirmou o funcionamento do fluxo básico de processamento assíncrono, mas não constitui uma demonstração de tolerância a partições de rede.

## 6. Conclusão

A análise do Teorema CAP demonstra que a construção de uma plataforma distribuída envolve decisões relacionadas à consistência, disponibilidade e tolerância a falhas de comunicação.

No projeto C3.A2, a utilização de Redis e workers assíncronos contribui para separar o recebimento das tarefas de seu processamento, enquanto as retentativas e a fila de descarte auxiliam no tratamento de determinadas falhas.

Entretanto, essas estratégias não eliminam as limitações relacionadas à indisponibilidade dos serviços, à perda de mensagens e à consistência dos estados.

Conclui-se que a arquitetura apresenta uma solução funcional para o escopo acadêmico proposto, mas exige mecanismos adicionais de confiabilidade e recuperação para oferecer garantias mais fortes em ambientes distribuídos sujeitos a partições de rede.

## Referências

GILBERT, Seth; LYNCH, Nancy. *Brewer's Conjecture and the Feasibility of Consistent, Available, Partition-Tolerant Web Services*. ACM SIGACT News, v. 33, n. 2, p. 51–59, 2002.

AMAZON WEB SERVICES. *CAP Theorem — Availability and Beyond: Understanding and Improving the Resilience of Distributed Systems on AWS*. Disponível em: https://docs.aws.amazon.com/whitepapers/latest/availability-and-beyond-improving-resilience/cap-theorem.html

IBM. *What Is the CAP Theorem?* Disponível em: https://www.ibm.com/think/topics/cap-theorem