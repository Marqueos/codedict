"""MCP stdio server exposing the dictionary to agents (Claude Code, etc.)."""
from pathlib import Path

from .query import callees_text, callers_text, group_modules, routes_text, search_text, show_text, tables_text
from .render_ai import module_map, overview
from .store import connect


def run(root: Path):
    try:
        from mcp.server.mcpserver import MCPServer as Server  # mcp >= 2
    except ImportError:
        try:
            from mcp.server.fastmcp import FastMCP as Server  # mcp 1.x
        except ImportError:
            raise SystemExit("MCP support needs: pip install mcp")
    mcp = Server("codedict")

    def con():
        return connect(root)

    @mcp.tool()
    def code_overview(budget_tokens: int = 3000) -> str:
        """Start here: modules, vocabulary, entry points and the most depended-on symbols."""
        return overview(con(), budget_tokens)

    @mcp.tool()
    def code_module(module: str) -> str:
        """L1 map of one module: files, classes, functions with lines, callers (↑) and calls (→)."""
        return module_map(con(), module)

    @mcp.tool()
    def code_search(query: str, limit: int = 10, budget_tokens: int = 0) -> str:
        """Start here with the user's question: top hits with file:line, every call site, caller chain, calls and code.
        Usually enough to answer without reading files. budget_tokens > 0 caps the output."""
        return search_text(con(), query, limit, root=root, budget=budget_tokens or None)

    @mcp.tool()
    def code_show(name: str, source: bool = True, max_lines: int = 200) -> str:
        """Symbol card plus its exact source lines. Accepts names, qualified names or #ids;
        pass several separated by spaces to get them all in one call."""
        return "\n\n".join(show_text(con(), root, n, source, max_lines) for n in name.replace(",", " ").split())

    @mcp.tool()
    def code_callers(name: str) -> str:
        """Who calls this symbol (impact analysis before changing it)."""
        return callers_text(con(), name)

    @mcp.tool()
    def code_callees(name: str) -> str:
        """What this symbol calls (resolved and external)."""
        return callees_text(con(), name)

    @mcp.tool()
    def code_routes(filter: str = "") -> str:
        """HTTP routes / Razor pages and the handlers behind them."""
        return routes_text(con(), filter)

    @mcp.tool()
    def code_tables(filter: str = "") -> str:
        """SQL tables referenced in code and .sql files, with readers/writers."""
        return tables_text(con(), filter)

    @mcp.tool()
    def code_modules() -> str:
        """List module groups usable with code_module."""
        return "\n".join(f"{k} ({len(v)} files)" for k, v in group_modules(con()).items())

    mcp.run()
