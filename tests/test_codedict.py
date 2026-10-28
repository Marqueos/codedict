import shutil
from pathlib import Path

import pytest

from codedict.indexer import index_project
from codedict.query import callers_text, routes_text, search_text, show_text, tables_text
from codedict.render_ai import overview, write_ai
from codedict.render_human import write_docs
from codedict.store import connect

FIXTURE = Path(__file__).parent / "fixture"


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    root = tmp_path_factory.mktemp("proj") / "fx"
    shutil.copytree(FIXTURE, root)
    summary = index_project(root, verbose=False)
    assert summary["errors"] == 0
    con = connect(root)
    write_ai(con, root)
    write_docs(con, root)
    yield root, con
    con.close()


def test_symbols_per_language(project):
    _, con = project
    kinds = dict(con.execute("SELECT f.lang, COUNT(*) FROM symbols s JOIN files f ON f.id = s.file_id GROUP BY f.lang"))
    for lang in ("python", "csharp", "typescript", "sql"):
        assert kinds.get(lang, 0) > 0, lang


def test_cross_file_calls(project):
    _, con = project
    out = callers_text(con, "TaxCalculator.calcular_imposto")
    assert "get_tax" in out and "[high]" in out
    assert "usp_SaveOrder" in callers_text(con, "dbo.usp_RecalcTotal")
    assert "OrderService.Save" in callers_text(con, "usp_SaveOrder")


def test_routes_and_tables(project):
    _, con = project
    routes = routes_text(con)
    assert "/api/Orders/{id}" in routes and "/orders/{order_id}/tax" in routes and "PAGE" in routes
    assert "dbo.Orders" in tables_text(con)


def test_search_and_show(project):
    root, con = project
    assert "calcular_imposto" in search_text(con, "imposto")
    card = show_text(con, root, "OrdersController.Get")
    assert "GET /api/Orders/{id}" in card and "Busca um pedido" in card


def test_outputs(project):
    root, con = project
    assert (root / ".codedict/ai/INDEX.md").exists()
    assert (root / ".codedict/docs/README.md").exists()
    assert "Key symbols" in overview(con, 2000)


def test_incremental(project):
    root, _ = project
    f = root / "src/billing/repo.py"
    f.write_text(f.read_text() + "\n\ndef purge():\n    pass\n")
    s = index_project(root, verbose=False)
    assert s["changed"] == 1


def test_class_graph_helpers_every_language():
    import re
    from codedict.config import load_languages
    from codedict.resolve import _bases, _var_types
    assert _bases("internal sealed class OrdersPanel : TabPanel") == ["TabPanel"]
    assert _bases("public class A : Base<int>, IFoo where T : new()") == ["Base", "IFoo"]
    assert _bases("public class A extends B implements C, D") == ["B", "C", "D"]
    assert _bases("internal sealed partial class MainWindow") == []
    assert _bases("class Repo(base.Base, Mixin, metaclass=Meta):") == ["Base", "Mixin"]
    rx = {c.name: [re.compile(p) for p in c.types] for c in load_languages().values()}
    t = _var_types("private TagList customerTags;\nvar delete = new StyledButton();\nvoid F(Customer c, int n) {}", rx["csharp"])
    assert t["customerTags"] == "TagList" and t["delete"] == "StyledButton" and t["c"] == "Customer"
    assert _var_types("def f(repo: OrderRepo):\n    self.calc = TaxCalc()", rx["python"]) == {"repo": "OrderRepo", "calc": "TaxCalc"}
    assert _var_types("constructor(private repo: OrderRepo) { this.calc = new TaxCalc(); }", rx["typescript"]) == {
        "repo": "OrderRepo", "calc": "TaxCalc"}
    assert _var_types("func (c *Command) Run() {\n\tsrv := &Server{}\n}", rx["go"]) == {"c": "Command", "srv": "Server"}


def test_bridges(tmp_path):
    from codedict.query import _bridges
    (tmp_path / "package.json").write_text('{"scripts": {"report": "tsx scripts/report.ts"}}', encoding="utf-8")
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "sync.py").write_text("", encoding="utf-8")
    code = 'Run("npm run report -- x"); sh("python -m tools.sync"); sh("go run ./missing")'
    assert _bridges(tmp_path, code) == "npm run report = scripts/report.ts, python -m tools.sync = tools/sync.py"


def test_claude_code_hook_and_setup(project, tmp_path):
    import json
    from codedict.claude_code import MARK, hook, setup
    root, _ = project
    ask = lambda p: hook({"hook_event_name": "UserPromptSubmit", "cwd": str(root / "src"), "prompt": p})
    assert "calcular_imposto" in ask("where is the tax amount calculated?")
    assert ask("thanks, looks great") == "" and ask("/help") == ""
    s, mem = tmp_path / "settings.json", tmp_path / "CLAUDE.md"
    s.write_text('{"model": "opus", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "x"}]}]}}')
    mem.write_text("# my notes\n", encoding="utf-8")
    setup(s), setup(s)  # idempotent
    d = json.loads(s.read_text())
    assert d["model"] == "opus" and d["hooks"]["Stop"] and sum(MARK in json.dumps(v) for v in d["hooks"].values()) == 3
    assert mem.read_text(encoding="utf-8").count("codedict:start") == 1 and mem.read_text(encoding="utf-8").startswith("# my notes")
    setup(s, remove=True)
    d = json.loads(s.read_text())
    assert MARK not in json.dumps(d) and d["hooks"] == {"Stop": [{"hooks": [{"type": "command", "command": "x"}]}]}
    assert mem.read_text(encoding="utf-8") == "# my notes\n"
    assert (root / ".codedict" / ".gitignore").read_text() == "*\n"
    from codedict.claude_code import permissions, with_command
    exe = "C:/py/Scripts/codedict.exe"  # pip scripts dir not on PATH: the agent must get the full path
    assert with_command("run `codedict show A`", exe) == f"run `{exe} show A`"
    assert permissions(exe) == ["Bash(codedict:*)", f"Bash({exe}:*)", "PowerShell(codedict *)", f"PowerShell({exe} *)"]


def test_stem():
    from codedict.query import _stem
    assert [_stem(w) for w in ("parsed", "running", "sends", "exclusao", "geracao", "pagamento", "acao")] == [
        "pars", "run", "send", "exclu", "gera", "paga", None]  # 'acao': stem too short to search


def test_used_constants(tmp_path):
    from codedict.query import _used_constants
    (tmp_path / "a.cs").write_text("class A {\n  private static readonly string Folder =\n    \"x\";\n"
                                   "  void F() {\n    Use(Folder);\n  }\n}\n", encoding="utf-8")
    r = {"path": "a.cs", "start_line": 4, "end_line": 6}
    assert _used_constants(tmp_path, r, "Use(Folder);") == [
        '    uses Folder: private static readonly string Folder = "x"; (a.cs:2)']
