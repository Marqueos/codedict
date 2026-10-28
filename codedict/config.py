"""Language configs (one TOML per language) and ignore rules."""
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

LANG_DIR = Path(__file__).parent / "languages"

DEFAULT_IGNORE_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "bin", "obj", "dist", "build", "out", "target",
    ".venv", "venv", "env", "__pycache__", ".mypy_cache", ".pytest_cache", ".tox", ".idea",
    ".vs", ".vscode", "packages", "vendor", ".next", ".nuxt", "coverage", ".codedict",
    "wwwroot/lib", "site-packages",
}
DEFAULT_IGNORE_GLOBS = [
    "*.min.js", "*.min.css", "*.Designer.cs", "*.g.cs", "*.g.i.cs", "*.generated.*",
    "*.lock", "package-lock.json", "*.map", ".env", ".env.*", "*.pem", "*.key", "*.pfx",
]
# Indexed as file entries only (listed in maps, no symbols).
OTHER_EXTS = {
    ".json", ".yml", ".yaml", ".xml", ".config", ".csproj", ".sln", ".props", ".md",
    ".html", ".css", ".scss", ".xaml", ".toml", ".ini", ".sh", ".ps1", ".dockerfile",
}
MAX_FILE_BYTES = 1_500_000


@dataclass
class LangConfig:
    name: str
    extensions: list[str]
    grammar: str | None = None
    extractor: str = "treesitter"
    module_from_path: bool = False
    kinds: dict = field(default_factory=dict)
    calls: dict = field(default_factory=dict)
    imports: list = field(default_factory=list)
    decorators: list = field(default_factory=list)
    decorator_wrappers: list = field(default_factory=list)
    decorator_containers: list = field(default_factory=list)
    doc_style: str = "comments"
    strings: list = field(default_factory=list)
    var_function_node: str | None = None
    var_function_values: list = field(default_factory=list)
    types: list = field(default_factory=list)  # regexes with (?P<var>) and (?P<type>)
    receiver_field: str | None = None  # methods declared outside their type (Go): field naming the owner


def _load(path: Path) -> LangConfig:
    d = tomllib.loads(path.read_text(encoding="utf-8"))
    vf = d.get("var_functions", {})
    dec = d.get("decorators", {})
    return LangConfig(
        name=d["name"],
        extensions=[e.lower() for e in d["extensions"]],
        grammar=d.get("grammar"),
        extractor=d.get("extractor", "treesitter"),
        module_from_path=d.get("module_from_path", False),
        kinds=d.get("kinds", {}),
        calls=d.get("calls", {}),
        imports=d.get("imports", {}).get("nodes", []),
        decorators=dec.get("nodes", []),
        decorator_wrappers=dec.get("wrappers", []),
        decorator_containers=dec.get("containers", []),
        doc_style=d.get("docs", {}).get("style", "comments"),
        strings=d.get("strings", {}).get("nodes", []),
        var_function_node=vf.get("node"),
        var_function_values=vf.get("values", []),
        types=d.get("types", {}).get("patterns", []),
        receiver_field=d.get("methods", {}).get("receiver_field"),
    )


def load_languages(extra_dir: Path | None = None) -> dict[str, LangConfig]:
    """Return extension -> LangConfig. Project-local .codedict/languages/*.toml override built-ins."""
    by_ext: dict[str, LangConfig] = {}
    dirs = [LANG_DIR] + ([extra_dir] if extra_dir and extra_dir.is_dir() else [])
    for d in dirs:
        for p in sorted(d.glob("*.toml")):
            cfg = _load(p)
            for ext in cfg.extensions:
                by_ext[ext] = cfg
    return by_ext
