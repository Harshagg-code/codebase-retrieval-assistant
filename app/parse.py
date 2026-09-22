"""tree-sitter parsing: language grammars -> raw syntax trees -> symbols."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from tree_sitter import Node
from tree_sitter_language_pack import get_parser

JS_LANGUAGES = {"javascript", "typescript", "tsx"}


def parse_file(path: Path, language: str) -> Node:
    parser = get_parser(language)
    source = path.read_bytes()
    tree = parser.parse(source)
    return tree.root_node


def dump_tree(node: Node, source: bytes, depth: int = 0, max_depth: int | None = None) -> None:
    """Print every node's type and line range, indented by depth. Named nodes only."""
    if max_depth is not None and depth > max_depth:
        return
    if node.is_named:
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        snippet = source[node.start_byte:node.end_byte].split(b"\n", 1)[0][:40].decode(
            "utf-8", errors="replace"
        )
        print(f"{'  ' * depth}{node.type} [{start_line}-{end_line}] {snippet!r}")
    for child in node.children:
        dump_tree(child, source, depth + 1, max_depth)


@dataclass
class Symbol:
    name: str
    kind: str  # "function" | "method" | "class"
    path: str
    start_line: int
    end_line: int
    parent: str | None
    id: int | None = None  # set once inserted into sqlite; None for freshly-extracted symbols


def _text(node: Node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def extract_symbols(root: Node, source: bytes, path: str, language: str) -> list[Symbol]:
    if language == "python":
        return _extract_python(root, source, path)
    if language in JS_LANGUAGES:
        return _extract_javascript(root, source, path)
    raise ValueError(f"no symbol extractor for language: {language!r}")


IMPORT_NODE_TYPES = {
    "python": {"import_statement", "import_from_statement", "future_import_statement"},
    "javascript": {"import_statement"},
    "typescript": {"import_statement"},
    "tsx": {"import_statement"},
}


def extract_imports(root: Node, source: bytes, language: str) -> str:
    """Top-level import statements only, in source order, joined by newlines."""
    types = IMPORT_NODE_TYPES.get(language, set())
    if not types:
        return ""
    return "\n".join(_text(child, source) for child in root.children if child.type in types)


# ---- Python -----------------------------------------------------------------
# function_definition / class_definition, both with a `name` field and a
# `body` field. A `@decorator` wraps its target in decorated_definition,
# whose own range (not the inner def's) is what we record as the symbol's
# span, via the `definition` field.

def _extract_python(root: Node, source: bytes, path: str) -> list[Symbol]:
    symbols: list[Symbol] = []

    def walk(node: Node, parent_name: str | None, parent_kind: str | None) -> None:
        for child in node.children:
            span_node = child
            target = child

            if target.type == "decorated_definition":
                inner = target.child_by_field_name("definition")
                if inner is None:
                    continue
                target = inner
                # span_node stays as decorated_definition so decorators are included

            if target.type in ("function_definition", "class_definition"):
                name_node = target.child_by_field_name("name")
                name = _text(name_node, source) if name_node else "<anonymous>"
                if target.type == "class_definition":
                    kind = "class"
                elif parent_kind == "class":
                    kind = "method"
                else:
                    kind = "function"

                symbols.append(Symbol(
                    name=name,
                    kind=kind,
                    path=path,
                    start_line=span_node.start_point[0] + 1,
                    end_line=span_node.end_point[0] + 1,
                    parent=parent_name,
                ))

                body = target.child_by_field_name("body")
                if body is not None:
                    walk(body, name, kind)
                continue

            walk(target, parent_name, parent_kind)

    walk(root, None, None)
    return symbols


# ---- JavaScript / TypeScript / TSX ------------------------------------------
# Unlike Python, there is no single definition node: a name can come from
# function_declaration, class_declaration, method_definition (name field is
# property_identifier, not identifier), or a variable_declarator whose value
# is an arrow_function/function_expression (the function node itself has no
# name -- it lives on the declarator). All four expose a `name` field, so we
# read by field rather than by child node type throughout.

def _extract_javascript(root: Node, source: bytes, path: str) -> list[Symbol]:
    symbols: list[Symbol] = []

    def add(name: str, kind: str, node: Node, parent_name: str | None) -> None:
        symbols.append(Symbol(
            name=name,
            kind=kind,
            path=path,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            parent=parent_name,
        ))

    def walk(node: Node, parent_name: str | None, parent_kind: str | None) -> None:
        for child in node.children:
            if child.type in ("function_declaration", "function_expression"):
                name_node = child.child_by_field_name("name")
                name = _text(name_node, source) if name_node else "<anonymous>"
                kind = "method" if parent_kind == "class" else "function"
                add(name, kind, child, parent_name)
                body = child.child_by_field_name("body")
                if body is not None:
                    walk(body, name, kind)
                continue

            if child.type == "class_declaration":
                name_node = child.child_by_field_name("name")
                name = _text(name_node, source) if name_node else "<anonymous>"
                add(name, "class", child, parent_name)
                body = child.child_by_field_name("body")
                if body is not None:
                    walk(body, name, "class")
                continue

            if child.type == "method_definition":
                name_node = child.child_by_field_name("name")
                name = _text(name_node, source) if name_node else "<anonymous>"
                add(name, "method", child, parent_name)
                body = child.child_by_field_name("body")
                if body is not None:
                    walk(body, name, "method")
                continue

            if child.type == "variable_declarator":
                value = child.child_by_field_name("value")
                name_node = child.child_by_field_name("name")
                if (
                    value is not None
                    and value.type in ("arrow_function", "function_expression")
                    and name_node is not None
                    and name_node.type == "identifier"
                ):
                    name = _text(name_node, source)
                    kind = "method" if parent_kind == "class" else "function"
                    add(name, kind, child, parent_name)
                    body = value.child_by_field_name("body")
                    if body is not None:
                        walk(body, name, kind)
                    continue

            walk(child, parent_name, parent_kind)

    walk(root, None, None)
    return symbols


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        "data/repos/requests/src/requests/structures.py"
    )
    language = sys.argv[2] if len(sys.argv) > 2 else "python"
    root = parse_file(path, language)
    dump_tree(root, path.read_bytes())
