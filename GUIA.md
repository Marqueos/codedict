# Guia rápido: usar o codedict no dia a dia

## 1. Instalar (uma vez por máquina)

Windows (PowerShell):

```powershell
irm https://raw.githubusercontent.com/Marqueos/codedict/main/install.ps1 | iex
```

macOS / Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/Marqueos/codedict/main/install.sh | sh
```

Requer Python 3.11+. No fim, o instalador mostra o caminho completo do comando `codedict`. Se o comando não for reconhecido no terminal, use esse caminho.

## 2. Ligar em cada projeto

No Claude Code, não há nada a fazer: ao abrir um repositório git, ele indexa sozinho e passa a responder pelo índice.

Em outras IAs, veja o [INTEGRACAO.md](INTEGRACAO.md).

## 3. Manter atualizado

No Claude Code, é automático: o índice é atualizado ao abrir o projeto e depois de cada edição.

Fora dele, rode `codedict index .`, que é incremental e só relê o que mudou. Para atualizar a cada commit, crie `.git/hooks/post-commit` (sem extensão) com:

```sh
#!/bin/sh
codedict index . >/dev/null 2>&1 &
```

## 4. Usar ativamente

O Claude Code usa sozinho as ferramentas `code_search`, `code_show`, `code_callers` etc. Para ajudar:

- Peça por intenção: "onde validamos o CPF? use o codedict antes de abrir arquivos".
- Antes de mudar algo: "veja com code_callers quem usa `OrderService.Save`".
- Para entender uma área: "leia code_module de `src/Billing/` e resuma".

Manual, no terminal:

| Quero | Comando |
|---|---|
| Visão geral do projeto | `codedict overview` |
| Mapa de uma pasta | `codedict map src/Billing/` |
| Achar por palavras | `codedict search "calcular imposto"` |
| Ver o código exato | `codedict show TaxCalculator.Calcular` |
| Quem chama / o que chama | `codedict callers X` / `codedict callees X` |
| Rotas HTTP | `codedict routes api/orders` |
| Tabelas SQL e quem usa | `codedict tables Orders` |

## 5. Ensinar o que o código não diz

Se um símbolo não tem comentário, deixe uma nota. Ela aparece nas buscas e sobrevive à reindexação:

```powershell
codedict note TaxCalculator.Calcular "Regra fiscal: ICMS por estado"
```

Dica: os comentários de documentação do código (docstring, `///`) viram a descrição. Quanto mais você escreve, melhor a busca.

## 6. Documentação para pessoas

Gerada junto com o índice em `.codedict/docs/README.md` (Markdown + diagramas Mermaid; abre no VS Code ou no GitHub). Para outra pasta ou em inglês:

```powershell
codedict index . --docs-out docs\codigo --docs-lang en
```

## 7. Verificar se está bom

Copie `AVALIACAO.md` para a raiz do projeto e diga ao Claude Code: `Execute AVALIACAO.md`.

## 8. Problemas comuns

| Sintoma | Solução |
|---|---|
| `codedict` não encontrado | use o caminho completo que o instalador mostrou, ou rode o instalador de novo |
| Resultado desatualizado | `codedict index .` |
| Busca não acha em português | o código está em inglês: busque pelos termos do código ou use `codedict note` |
| Índice estranho | `codedict index . --rebuild` (suas notas são preservadas) |
| Arquivo indesejado indexado | adicione o padrão em `.codedictignore` na raiz |
| Linguagem nova | copie um `.toml` de `codedict/languages/` para `.codedict/languages/` do projeto |

---

# Quick guide (EN)

```bash
curl -fsSL https://raw.githubusercontent.com/Marqueos/codedict/main/install.sh | sh   # Windows: irm .../install.ps1 | iex
# Claude Code: nothing else to do; it indexes each git repo and answers from the index
# other agents: see INTEGRACAO.md (MCP + AGENTS.md)
# keep fresh outside Claude Code: codedict index .   (incremental; or git post-commit hook)
# use: codedict search "<words>" | show <name> | callers <name> | routes | tables
# annotate: codedict note <name> "<text>"
# evaluate: copy AVALIACAO.md to the project root and tell Claude Code to run it
```
