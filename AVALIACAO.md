# Avaliação do codedict (tarefa para o Claude Code)

Objetivo: medir se o índice do `codedict` neste projeto é confiável. Executar tudo em sequência, sem pedir confirmação, e entregar `AVALIACAO-RESULTADO.md` na raiz.

## Regras

1. Não alterar o código do `codedict` durante a avaliação. Só medir e reportar.
2. O gabarito (passo 2) deve ser feito lendo o código com `grep`/leitura direta. Nunca usar `codedict search`, `callers` ou `routes` para decidir a resposta certa, senão o teste fica circular.
3. Se não conseguir verificar um item, marcar `?` e excluir do cálculo. Nunca chutar.
4. Reportar sempre o `n` de cada medida. Não arredondar para cima.
5. Não imprimir segredos (`.env`, chaves, connection strings) no resultado.

## Passo 1: indexar

```bash
codedict index . --rebuild
codedict stats
```

Registrar: nº de arquivos, símbolos por tipo, chamadas por confiança, `parse errors`, tempo da indexação.
Depois medir a reindexação sem mudanças (esperado: poucos segundos):

```bash
time codedict index .
```

## Passo 2: gabarito de busca (`gold.toml`)

Criar `gold.toml` com 25 casos reais e variados, tirados lendo o projeto sem usar o `codedict`:

- 15 casos `[[search]]`: uma pergunta como um desenvolvedor faria ("onde valida CPF?") e o símbolo que é a resposta certa. Usar mistura de português e inglês, e incluir casos em que o nome do símbolo não contém as palavras da pergunta.
- 6 casos `[[calls]]`: pares `src` → `dst` que existem de fato (conferir abrindo o arquivo).
- 4 casos `[[routes]]` (se for projeto web): método e caminho reais.

Formato:

```toml
[[search]]
query = "onde calcula imposto"
expect = "TaxCalculator.Calcular"

[[calls]]
src = "OrdersController.Get"
dst = "OrderService.FindOrder"

[[routes]]
method = "GET"
path = "/api/orders/{id}"
```

```bash
codedict eval gold.toml
```

Registrar a saída completa, incluindo a lista de `FAILURES`.

## Passo 3: precisão das chamadas

Para cada faixa de confiança, sortear 30 ligações e verificar uma a uma:

```bash
codedict audit calls -n 30 --confidence high
codedict audit calls -n 30 --confidence medium
codedict audit calls -n 30 --confidence low
```

Para cada item: abrir a linha do código chamador e o símbolo `linked`. Marcar `OK` se a chamada realmente vai para aquele símbolo, `WRONG` se vai para outro, `?` se não der para saber. Calcular precisão por faixa = OK / (OK + WRONG).

## Passo 4: chamadas perdidas

```bash
codedict audit missed -n 30
```

Para cada item, decidir se a chamada deveria ter sido ligada a algum dos `candidates`. Taxa de perda = deveria / total verificado.

## Passo 5: rotas e tabelas (projetos web/SQL)

```bash
codedict routes
codedict tables
```

Comparar com a realidade por `grep` (atributos `[Http*]`, `[Route]`, `MapGet/MapPost`, `@app.get`, `@page`, strings SQL). Reportar: rotas reais encontradas, rotas reais perdidas, rotas inventadas. Para tabelas, conferir 10 aleatórias.

## Passo 6: economia de tokens (estimativa)

Escolher 10 tarefas reais pequenas ("achar onde X é validado e como é chamado"). Para cada uma, estimar tokens (caracteres / 4):

- Caminho com índice: saída de `codedict search` + `codedict show` do símbolo certo.
- Caminho sem índice: tamanho dos arquivos que seriam abertos inteiros para achar o mesmo.

Reportar a economia média e a mediana.

## Passo 7: teste A/B real (manual, do usuário)

Não executar. Apenas incluir no resultado esta tabela vazia para o usuário preencher com 10 tarefas reais, cada uma feita duas vezes no Claude Code (com e sem o MCP `codedict`):

| # | Tarefa | Tokens sem MCP | Tokens com MCP | Resposta correta sem | Resposta correta com |
|---|---|---|---|---|---|

## Critérios de aprovação

| Medida | Mínimo |
|---|---|
| Parse errors | 0 |
| Reindexação sem mudanças | < 5 s |
| Busca recall@5 | ≥ 85% |
| Precisão `high` | ≥ 95% |
| Precisão `medium` | ≥ 85% |
| Precisão `low` | só reportar |
| Taxa de chamadas perdidas | ≤ 20% |
| Rotas reais encontradas | ≥ 95% |
| Rotas inventadas | 0 |
| Economia de tokens (mediana) | ≥ 60% |

## Entrega: `AVALIACAO-RESULTADO.md`

Conter, nesta ordem:

1. Veredito em uma linha: `APROVADO`, `APROVADO COM RESSALVAS` ou `REPROVADO`, com o motivo.
2. Tabela: medida, resultado, `n`, mínimo, passou/falhou.
3. Falhas: até 10 exemplos concretos (arquivo:linha, o que o índice fez, o que era o certo), do tipo mais frequente ao menos frequente.
4. Causas prováveis agrupadas (ex.: "receptor com nome diferente da classe", "rota por convenção", "pergunta em português sem comentário em português").
5. Correções sugeridas, em ordem de impacto. Apenas propor; não aplicar.
6. A tabela vazia do passo 7.
