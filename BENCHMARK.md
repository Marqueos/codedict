# Benchmark: o codedict economiza tokens no Claude Code?

Este documento mostra como medimos e o que encontramos. Os scripts estão em `bench/`.

## Por que o número de turnos decide

Numa sessão do Claude Code, cada turno relê o contexto inteiro. Na nossa medição, isso foi de 35 a 50 mil tokens por turno: prompt, ferramentas e skills. O que as ferramentas devolvem pesa pouco, de 30 a 1.000 tokens.

Por isso, o codedict só economiza quando **reduz o número de turnos**. A busca precisa responder de uma vez, sem que a sessão confira tudo depois com grep.

## Regras do teste justo

Elas nasceram de erros nossos (veja "Lições").

1. Use duas cópias idênticas do projeto. Só a cópia **B** tem `.codedict/` e o trecho de `codedict agent-snippet` no `CLAUDE.md`.
2. Nenhuma das cópias pode ter memória do Claude, notas manuais ou `CLAUDE.md` próprio.
3. Nenhum arquivo com as respostas pode ficar dentro das cópias (gabarito, relatório de avaliação).
4. Mantenha mesmo prompt, mesma lista de ferramentas liberadas (só leitura) e mesmo modelo.
5. Rode 3 repetições por tarefa e reporte a mediana. A mesma tarefa variou até 45% de uma execução para outra.
6. A resposta conta como certa quando cita os símbolos e arquivos esperados. Essa conferência é automática.

## Como rodar

```bash
# 1. Checagem sem tokens: a primeira busca já responde? (segundos, sem LLM)
python bench/answerability.py <projeto-B> <casos.json>

# 2. A/B com sessões reais do Claude Code (gasta tokens; retoma de onde parou)
python bench/ab_test.py --a <projeto-A> --b <projeto-B> --tasks bench/tasks.example.json --reps 3
```

Use a checagem sem tokens a cada mudança. Rode o A/B só para confirmar, com poucas tarefas.

## Resultados

Projeto privado real, com cerca de 250 arquivos em TypeScript, C# e Python. Modelo padrão do Claude Code, outubro de 2026.

### Tarefas curtas: "onde está X e quem chama"

São 10 tarefas, com 3 repetições em cada lado.

| Medida | Sem codedict | Com codedict | Diferença |
|---|---|---|---|
| Tokens | 6.357.798 | 3.108.274 | −51% |
| Economia mediana por tarefa | | | 51,5% |
| Custo | US$ 9,79 | US$ 8,04 | −18% |
| Tempo | 522 s | 329 s | −37% |
| Turnos | 147 | 72 | −51% |
| Respostas certas | 30/30 | 30/30 | = |

Depois da rodada principal corrigimos a resolução de chamadas em C#. O codedict passou a seguir herança, `partial class`, o tipo declarado de variáveis e sobrecargas. A busca passou a mostrar o código do melhor resultado e as constantes que ele usa.

Repetimos só as duas tarefas de C#, que ainda gastavam 3 a 5 turnos, com 1 execução cada:

| Tarefa | Sem codedict (mediana de 3) | Com codedict (1 execução) |
|---|---|---|
| Tarefa de C# nº 1 | 186 mil | 88 mil (2 turnos) |
| Tarefa de C# nº 2 | 186 mil | 85 mil (2 turnos) |

### Tarefas de fluxo: "explique a cadeia do clique até o resultado"

São 2 tarefas. A primeira medição teve 1 execução em cada lado.

| Medida | Sem codedict | Com codedict | Diferença |
|---|---|---|---|
| Tokens | 1.230.840 | 795.156 | −35% |
| Custo | US$ 1,46 | US$ 1,00 | −32% |
| Turnos | 40 | 17 | −58% |
| Respostas certas | 2/2 | 2/2 | = |

A economia aqui foi **menor** que nas tarefas curtas. O `search` mostrava só um nível de quem chama; para montar a cadeia até o ponto de entrada, a sessão voltava ao grep.

**Depois da correção.** Nos 3 primeiros resultados, o `search` passou a mostrar:
- `caller chain`: quem chama, até 3 níveis acima;
- `calls`: o que o símbolo chama;
- `runs`: a ponte `npm run X`, que liga o app C# ao script TypeScript;
- o código de cada um.

O `codedict show` também passou a aceitar vários nomes numa chamada. Depois da correção rodamos 3 execuções por tarefa em cada lado (medianas):

| Tarefa | Sem codedict | Com codedict | Economia |
|---|---|---|---|
| Fluxo nº 1 | 500.132 | 266.187 | 47% |
| Fluxo nº 2 | 641.467 | 199.981 | 69% |
| **Mediana por tarefa** | | | **57,8%** |

| Medida (6 execuções por lado) | Sem codedict | Com codedict | Diferença |
|---|---|---|---|
| Tokens | 3.484.535 | 1.672.639 | −52% |
| Custo | US$ 4,02 | US$ 2,67 | −34% |
| Turnos | 114 | 33 | −71% |
| Tempo | 340 s | 228 s | −33% |
| Respostas certas | 6/6 | 6/6 | = |

A variação entre execuções foi grande: o lado com codedict ficou entre 146 mil e 403 mil tokens na mesma tarefa.

Com a mesma versão, duas tarefas curtas continuaram em 2 turnos: 224 mil → 88 mil (61%) e 131 mil → 85 mil (35%). A saída maior do `search` não piorou as tarefas curtas.

### Resumo

| Tipo de tarefa | Economia de tokens | Como foi medido |
|---|---|---|
| Fluxo ("explique a cadeia") | mediana de 57,8% (47% e 69%), −52% no total | 2 tarefas × 3 execuções |
| Instalação padrão com hook (fluxo + busca) | mediana de 63%, −63% no total | 4 tarefas × 3 execuções |
| Busca curta ("onde está X") | mediana de 51,5%, −51% no total | 10 tarefas × 3 execuções (rodada principal) |

Nas buscas curtas o codedict já responde no mínimo possível, 2 turnos. A economia esbarra no custo fixo da sessão: com cerca de 85 mil tokens por resposta, uma tarefa que sem índice gasta 130 mil não passa de 35%.

### Instalação padrão (`codedict setup`): resposta entregue junto com a pergunta

Aqui o lado com codedict usa o que `codedict setup` instala:
- o hook, que busca no índice com a pergunta do usuário e entrega o resultado junto com ela;
- a instrução no `CLAUDE.md`.

Assim a sessão pode responder sem chamar ferramenta nenhuma. Comparamos com as execuções sem codedict já medidas. Foram 3 execuções por tarefa em cada lado (medianas):

| Tarefa | Sem codedict | Com codedict + hook | Economia |
|---|---|---|---|
| Busca curta nº 1 | 129.319 | 41.095 (1 turno nas 3) | 68% |
| Busca curta nº 2 | 223.653 | 94.248 | 58% |
| Fluxo nº 2 | 641.467 | 162.121 | 75% |
| Fluxo nº 1 | 500.132 | 213.523 | 57% |
| **Mediana por tarefa** | | | **63%** |

| Medida (12 execuções por lado) | Sem codedict | Com codedict + hook | Diferença |
|---|---|---|---|
| Tokens | 4.543.176 | 1.666.033 | −63% |
| Custo | US$ 5,76 | US$ 4,27 | −26% |
| Turnos | 138 | 34 | −75% |
| Respostas certas | 12/12 | 12/12 | = |

**Fluxo nº 1: de 29% para 57%.** A pergunta usava o substantivo ("exclusão") e o código, o verbo (`Excluir...`). A busca agora reduz substantivos do português ao radical (-ção, -são, -mento: "exclusão" vira `exclu*`, "geração" vira `gera*`). Assim o lado C# entra no contexto do hook. As 3 execuções do fluxo nº 1 na tabela são as feitas depois dessa correção. Antes dela, a mediana era 356 mil.

- **1 turno.** A busca curta nº 1 foi respondida em 1 turno nas 3 execuções, com cerca de 41 mil tokens. Isso fica abaixo do piso de ~85 mil, porque a busca deixou de custar um turno.
- **Fluxo nº 1.** Continua sendo a tarefa mais cara: o fluxo atravessa C# e TypeScript, e a sessão ainda abre alguns arquivos (4 a 6 turnos).
- **O hook sozinho não basta.** Sem a instrução no `CLAUDE.md`, a sessão recebeu o contexto e mesmo assim conferiu tudo com grep: 4 turnos e 189 mil tokens. A instrução diz que o contexto vem de um índice completo, e é ela que faz a sessão confiar nele. Por isso `codedict setup` grava as duas coisas.

### Checagem sem tokens

As 17 buscas que as sessões reais digitaram foram rodadas com `answerability.py`:
- Resultado: 17/17 respondem numa chamada só.
- Com a lista de chamadores escondida de propósito, cai para 0/17. Isso mostra que a checagem detecta regressão.

### Outras linguagens: projetos públicos (sem tokens, qualquer um reproduz)

Para não depender de um projeto privado, rodamos a checagem sem tokens em dois projetos open source. As perguntas são em linguagem natural, do jeito que uma pessoa digitaria, e estão em `bench/public/`.

| Projeto | Linguagem | Commit | Resultado |
|---|---|---|---|
| [psf/requests](https://github.com/psf/requests) | Python | `3c7baaa` | 3/4 respondem numa busca só |
| [spf13/cobra](https://github.com/spf13/cobra) | Go | `adbc881` | 3/3 respondem numa busca só |

```bash
git clone https://github.com/spf13/cobra && git -C cobra checkout adbc881
codedict index cobra
python bench/answerability.py cobra bench/public/cobra.json
```

O que falha: em `requests`, o fluxo de `requests.get` até `HTTPAdapter.send` não cabe numa busca. A sessão ainda precisa de um `codedict show`.

Antes das correções genéricas desta etapa, o Go dava 1/3. As correções valem para qualquer linguagem:
- **Métodos fora do tipo:** em Go, `func (c *Command) Run()` agora vira `Command.Run`. Isso triplicou as chamadas ligadas com confiança alta (480 → 1.460).
- **Testes rebaixados:** funções de teste não ocupam mais o topo da busca, a menos que a pergunta fale de teste.
- **Cadeia de chamadas para baixo** (`call chain`): nas perguntas "de X até Y", segue o que X chama, priorizando nomes citados na pergunta.
- **Inflexões:** "parsed" também acha `ParseFlags`, e "exclusão" acha `Excluir...`.

No projeto privado nada piorou: 22/22 buscas e 100% das chamadas do gabarito. Uma busca do gabarito passou do 1º para o 2º lugar.

## Limites

- **Custo fixo.** Cerca de 37 mil tokens por turno são do Claude Code, não da busca. Com 2 turnos, a sessão ainda custa uns 85 mil tokens. Em tarefas que sem índice já se resolvem em 3 turnos, a economia máxima fica perto de 33%.
- **O custo cai menos que os tokens (−18% contra −51%).** Gravar o contexto em cache, que é a parte fixa, é o tipo de token mais caro.
- **Correção automática.** "Certa" significa que a resposta cita os nomes esperados. Uma leitura humana amostral não achou erro, mas a conferência não é completa.

## Lições (erros que invalidaram rodadas anteriores)

- **Arquivos de resposta na pasta.** `gold.toml` e o relatório de avaliação estavam dentro do projeto testado, e em 8 de 20 sessões o grep encontrou as respostas. A rodada foi descartada.
- **Memória contra índice.** Comparar uma sessão com memória e sem índice contra outra sem memória e com índice mede duas coisas ao mesmo tempo. A economia de custo daquela rodada vinha quase toda da memória menor.
- **Permissões diferentes.** Liberar `codedict` só pelo Bash fez sessões que tentaram pelo PowerShell perderem turnos. Hoje os dois lados recebem a mesma lista.
- **Comando fora do PATH.** No meio da rodada com hook, o `codedict` saiu do PATH. Em 6 de 12 sessões, a chamada deu "command not found" e a sessão voltou para o grep, e a mediana caiu para 52%. Hoje `codedict setup` grava o caminho completo do executável quando ele não está no PATH. As 6 sessões foram descartadas e refeitas.
- **Uma execução só não basta.** Com n = 1, o ruído entre execuções escondeu o efeito de duas correções.
