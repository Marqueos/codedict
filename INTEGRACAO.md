# Como usar o codedict no seu projeto e com a sua IA

O codedict não depende de uma IA. Ele lê o código uma vez, grava um índice local (SQLite) e responde perguntas sobre o código: onde está, quem chama, o caminho de uma chamada até outra e o trecho de código. É a etapa de busca de um RAG, só que exata e sem gastar tokens para montar.

O mesmo índice gera dois dicionários:

| Para quem | Onde | O que tem |
|---|---|---|
| A IA | `.codedict/ai/` + `codedict search` | Mapa compacto do projeto e respostas prontas por pergunta |
| A pessoa | `.codedict/docs/README.md` | Manual em Markdown com diagramas Mermaid: módulos, rotas, tabelas e quem chama quem |

O índice fica em `.codedict/`. Essa pasta já vem com o próprio `.gitignore`, então o git a ignora sem que você mexa no `.gitignore` do projeto.

## 1. Instalar (uma linha, uma vez por máquina)

Windows (PowerShell):

```powershell
irm https://raw.githubusercontent.com/Marqueos/codedict/main/install.ps1 | iex
```

macOS / Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/Marqueos/codedict/main/install.sh | sh
```

O instalador:
- confere o Python 3.11+;
- cria uma pasta própria em `~/.codedict`, sem admin e sem mexer no PATH;
- instala o codedict nela;
- liga o codedict no Claude Code (passo 2).

Para atualizar, rode a mesma linha de novo.

Instalação manual, se preferir: `pip install git+https://github.com/Marqueos/codedict` e depois `python -m codedict setup`.

## 2. Claude Code: ligado por padrão

O instalador já faz este passo. Na instalação manual, rode `python -m codedict setup`. Vale para todos os projetos. O comando grava três ganchos (hooks) nas configurações globais do Claude Code (`~/.claude/settings.json`) e uma instrução curta na memória global (`~/.claude/CLAUDE.md`).

| Quando | O que acontece | Custo em tokens |
|---|---|---|
| Ao abrir uma sessão num repositório git | Indexa o projeto em segundo plano (só o que mudou) | Zero |
| Depois de cada edição da IA | Atualiza o índice em segundo plano | Zero |
| Ao enviar uma pergunta | Se a pergunta for sobre o código, entrega a resposta do índice junto com ela | ~1.500 a 2.000 por pergunta de código; zero nas outras |

Se o `codedict` não estiver no PATH, o `setup` grava o caminho completo do executável na instrução e nas permissões, para a IA não perder turnos com "command not found".

Conversa que não é sobre código ("obrigado", "faz o commit") não recebe nada. Comandos que começam com `/` também não.

Para desfazer tudo: `~/.codedict/venv/bin/python -m codedict setup --remove` (Windows: `~\.codedict\venv\Scripts\python.exe -m codedict setup --remove`), depois apague a pasta `~/.codedict`. As outras configurações e anotações ficam intactas, e o arquivo anterior é guardado como `settings.json.codedict-bak`.

## 3. Outras IAs com acesso a ferramentas (Cursor, Codex, Gemini CLI, OpenCode, Windsurf)

Todas aceitam servidores MCP. Primeiro instale o extra do MCP na pasta do codedict:

```bash
~/.codedict/venv/bin/python -m pip install "codedict[mcp] @ git+https://github.com/Marqueos/codedict"
```

Depois registre o codedict apontando para o projeto. O instalador mostra o caminho completo do comando `codedict` no fim; use-o se `codedict` não estiver no PATH:

```json
{
  "mcpServers": {
    "codedict": { "command": "codedict", "args": ["--root", "/caminho/do/projeto", "mcp"] }
  }
}
```

O nome do arquivo muda de ferramenta para ferramenta (`.cursor/mcp.json`, `~/.codex/config.toml`, `~/.gemini/settings.json`…). O conteúdo é sempre esse comando.

Depois, coloque a instrução no arquivo de regras que a ferramenta lê. Codex, Cursor e OpenCode leem o `AGENTS.md`:

```bash
codedict index .
codedict agent-snippet >> AGENTS.md
```

Sem hooks, mantenha o índice atualizado com um gancho do git:

```bash
# .git/hooks/post-commit
codedict index . >/dev/null 2>&1 &
```

## 4. Qualquer modelo, inclusive local (modo RAG)

Para qualquer LLM, até um modelo local via Ollama ou LiteLLM sem ferramentas: busque o contexto e coloque no prompt.

```bash
codedict search "onde o desconto é calculado?" --budget 2000
```

`--budget` limita a saída em tokens, para caber em modelos com contexto pequeno. Exemplo em Python com qualquer API compatível com OpenAI:

```python
import subprocess
from openai import OpenAI

pergunta = "Onde o desconto é calculado e quem chama?"
contexto = subprocess.run(["codedict", "--root", "/caminho/do/projeto", "search", pergunta, "--budget", "2000"],
                          capture_output=True, text=True).stdout

cliente = OpenAI(base_url="http://localhost:11434/v1", api_key="local")  # Ollama, LiteLLM, OpenAI...
resposta = cliente.chat.completions.create(model="qwen2.5-coder", messages=[
    {"role": "system", "content": "Responda só com base no contexto do índice de código."},
    {"role": "user", "content": f"{contexto}\n\nPergunta: {pergunta}"},
])
print(resposta.choices[0].message.content)
```

Para usar como biblioteca, sem subprocesso:

```python
from pathlib import Path
from codedict.store import connect
from codedict.query import search_text

raiz = Path("/caminho/do/projeto")
contexto = search_text(connect(raiz), "onde o desconto é calculado?", root=raiz, budget=2000)
```

## 5. Linguagens

Python, JavaScript, TypeScript/TSX, C#, Java, Go, SQL e Razor já vêm prontas. Para outra linguagem, copie um `.toml` de `codedict/languages/` para `.codedict/languages/` do projeto e ajuste:

- `[kinds]`: quais nós da gramática são classe, função e método. A gramática vem do `tree-sitter-language-pack`, que tem mais de 160 linguagens.
- `[calls]`: qual nó é uma chamada.
- `[types]`: como a linguagem declara o tipo de uma variável. Exemplo: `repo: OrderRepo`. Serve para ligar `repo.save()` à classe certa.
- `[methods]`: só se os métodos ficam fora do tipo, como em Go (`func (c *Command) Run()`).

## 6. Conferir que funciona no seu projeto, sem gastar tokens

```bash
python bench/answerability.py <projeto> <casos.json>
```

O script roda as suas perguntas e diz se a primeira busca já traz a resposta e todos os pontos de chamada que o grep acharia. Veja os exemplos em `bench/public/` e o método completo em [BENCHMARK.md](BENCHMARK.md).
