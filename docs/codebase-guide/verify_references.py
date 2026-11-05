"""Verifies the references used in docs/codebase-guide.

Run from the repository root:  python docs/codebase-guide/verify_references.py
Checks (1) every `path::symbol` exists (Python via ast, TypeScript by text search) and
(2) every backticked repository path exists. Exits 1 if anything is missing.
"""

import ast
import re
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent
ROOT = DOCS.parents[1]
PREFIX = r"(?:backend|frontend|data|docs|evaluations)"
SYMBOL_REF = re.compile(rf"`({PREFIX}/[\w./-]+\.(?:py|tsx?))::([\w.]+)`")
PATH_REF = re.compile(rf"`({PREFIX}/[\w./*-]+\.(?:py|tsx?|json|md|css))`")


def python_names(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def main() -> None:
    problems: list[str] = []
    symbols = paths = 0
    cache: dict[str, set[str]] = {}
    for doc in sorted(DOCS.glob("*.md")):
        text = doc.read_text(encoding="utf-8")
        for rel in sorted(set(PATH_REF.findall(text))):
            if "*" in rel:
                continue
            paths += 1
            if not (ROOT / rel).exists():
                problems.append(f"{doc.name}: missing file {rel}")
        for rel, symbol in sorted(set(SYMBOL_REF.findall(text))):
            symbols += 1
            path = ROOT / rel
            if not path.exists():
                problems.append(f"{doc.name}: missing file {rel}")
                continue
            if path.suffix == ".py":
                names = cache.setdefault(rel, python_names(path))
                ok = all(part in names for part in symbol.split("."))
            else:
                source = path.read_text(encoding="utf-8")
                ok = all(re.search(rf"\b{re.escape(part)}\b", source) for part in symbol.split("."))
            if not ok:
                problems.append(f"{doc.name}: {rel} has no symbol {symbol}")
    print(f"checked {paths} file references and {symbols} symbol references: {len(problems)} problems")
    for problem in problems:
        print(" -", problem)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()