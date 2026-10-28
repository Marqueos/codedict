"""Identifier splitting, humanizing and small text helpers."""
import re
import unicodedata

_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")

STOPWORDS = {
    "get", "set", "is", "has", "to", "from", "of", "the", "a", "an", "and", "or", "for", "in", "on",
    "by", "with", "self", "this", "init", "new", "do", "on", "at", "as", "it", "if", "not", "no",
    "async", "impl", "base", "default", "main", "test", "tests", "index", "util", "utils", "helper",
    "helpers", "handle", "handler", "run", "make", "create", "build", "update", "delete", "add",
    "remove", "list", "item", "items", "data", "value", "values", "type", "types", "name", "id",
    "obj", "object", "str", "int", "bool", "dict", "args", "kwargs", "src", "lib", "app", "core",
    "de", "do", "da", "dos", "das", "e", "o", "os", "as", "para", "com", "em", "no", "na", "por",
    "py", "cs", "ts", "js", "tsx", "jsx", "java", "go", "sql", "dto", "model", "models", "service",
    "services", "controller", "controllers", "interface", "class", "async", "dbo",
}


# Function words dropped from search questions (accents already stripped).
QUERY_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "to", "of", "in", "on", "at", "by", "for", "with",
    "from", "and", "or", "do", "does", "did", "how", "where", "what", "which", "who", "when", "why", "that",
    "this", "these", "those", "it", "its", "into", "can", "there", "any", "some",
    "o", "os", "as", "um", "uma", "uns", "umas", "de", "do", "da", "dos", "das", "no", "na", "nos", "nas",
    "em", "para", "pra", "por", "pelo", "pela", "pelos", "pelas", "com", "e", "ou", "que", "qual", "quais",
    "onde", "como", "quando", "quem", "se", "ao", "aos", "fica", "ficam", "esta", "estao",
}


def split_identifier(name: str) -> list[str]:
    """CalcularImposto_v2 -> ['calcular', 'imposto', 'v', '2']"""
    words = []
    for part in re.split(r"[^A-Za-z0-9\u00C0-\u024F]+", name or ""):
        if not part:
            continue
        found = _CAMEL.findall(part)
        words.extend(w.lower() for w in (found or [part]))
    return words


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def humanize(name: str) -> str:
    return " ".join(split_identifier(name))


def vocabulary_words(name: str) -> list[str]:
    return [w for w in split_identifier(name) if len(w) > 2 and not w.isdigit() and w not in STOPWORDS]


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def one_line(text: str | None, limit: int = 140) -> str:
    if not text:
        return ""
    line = " ".join(text.split())
    return line if len(line) <= limit else line[: limit - 1] + "…"


def clean_comment(raw: str) -> str:
    """Remove comment markers and XML doc tags; keep the prose."""
    lines = []
    for line in raw.splitlines():
        line = line.strip()
        line = re.sub(r"^(///|//!|//|#|/\*\*|/\*|\*/|\*|--|'''|\"\"\")", "", line).strip()
        line = re.sub(r"\*/$", "", line).strip()
        if line:
            lines.append(line)
    text = " ".join(lines)
    text = re.sub(r"<param name=\"(\w+)\">", r"\1: ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split())


def slug(path: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", path.strip("/").lstrip("./")).strip("._")
    return s or "root"
