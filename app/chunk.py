"""Chunking: an AST-boundary splitter (cAST-style, with sibling merging) for
languages tree-sitter understands, plus a character-window chunker used both
as the fallback for unsupported languages and as the Day 5 fixed-size
ablation baseline.
"""

from __future__ import annotations

from dataclasses import dataclass

from tree_sitter import Node

from app.parse import Symbol

MAX_CHARS = 1400
MIN_CHARS = 200
OVERFLOW_TOLERANCE = 1.3  # allow merging a small leftover chunk up to this multiple of MAX_CHARS
OVERLAP_LINES = 5
HEADER_IMPORTS_MAX_CHARS = 300


@dataclass
class Chunk:
    path: str
    start_line: int
    end_line: int
    text: str
    symbol_id: int | None = None


def build_header(chunk: Chunk, file_imports: str, symbols: dict[int, Symbol]) -> str:
    """'# file: <path>' + up to ~300 chars of the file's top-level imports +
    '# in: <kind> <name>' -- only when the chunk maps to exactly one symbol.
    Generated on demand for indexing; never stored alongside chunk.text.
    """
    lines = [f"# file: {chunk.path}"]
    if file_imports:
        lines.append(file_imports[:HEADER_IMPORTS_MAX_CHARS])
    if chunk.symbol_id is not None:
        symbol = symbols.get(chunk.symbol_id)
        if symbol is not None:
            lines.append(f"# in: {symbol.kind} {symbol.name}")
    return "\n".join(lines)


def chunk_fixed(
    text: str,
    path: str,
    start_line: int = 1,
    max_chars: int = MAX_CHARS,
    overlap_lines: int = OVERLAP_LINES,
) -> list[Chunk]:
    """Line-snapped fixed-size windows with a trailing-line overlap between
    consecutive chunks. Never splits mid-line, so start/end lines stay exact.
    A naive baseline on purpose -- unlike the AST chunker, small leftover
    windows are not smoothed away.
    """
    lines = text.splitlines(keepends=True)
    if not lines:
        return []

    chunks: list[Chunk] = []
    start_idx = 0
    n = len(lines)

    while start_idx < n:
        length = 0
        end_idx = start_idx
        while end_idx < n:
            line_len = len(lines[end_idx])
            if length > 0 and length + line_len > max_chars:
                break
            length += line_len
            end_idx += 1
        if end_idx == start_idx:
            # a single line longer than max_chars -- keep it whole rather than
            # split mid-line
            end_idx = start_idx + 1

        chunks.append(Chunk(
            path=path,
            start_line=start_line + start_idx,
            end_line=start_line + end_idx - 1,
            text="".join(lines[start_idx:end_idx]),
        ))

        if end_idx >= n:
            break
        start_idx = max(end_idx - overlap_lines, start_idx + 1)

    return chunks


# ---- AST-boundary splitter, cAST-style ---------------------------------------
#
# Recurse top-down over the tree, greedily merging consecutive small siblings
# into one chunk and recursing further into any single sibling that alone
# exceeds the budget. For a "definition" node (function/class -- anything
# with a `body` field), recursion descends into the body's own children
# rather than the definition's (name, params, body) triple, and the
# signature text (everything before the body) is stitched onto the first
# resulting fragment so a function split across chunks still starts with
# `def foo(...):` on chunk one.

def _make_chunk(path: str, source: bytes, start_byte: int, end_byte: int, start_line: int, end_line: int) -> Chunk:
    return Chunk(
        path=path,
        start_line=start_line,
        end_line=end_line,
        text=source[start_byte:end_byte].decode("utf-8", errors="replace"),
    )


def _split_children(children: list[Node], source: bytes, path: str, max_chars: int) -> list[Chunk]:
    """Greedily merge consecutive children into one chunk while the *actual*
    span from the run's first byte to the candidate child's last byte stays
    within budget -- not the sum of each child's own length, which would
    silently ignore the whitespace/indentation between them.
    """
    chunks: list[Chunk] = []
    run: list[Node] = []

    def flush() -> None:
        if run:
            chunks.append(_make_chunk(
                path, source, run[0].start_byte, run[-1].end_byte,
                run[0].start_point[0] + 1, run[-1].end_point[0] + 1,
            ))

    for child in children:
        child_len = child.end_byte - child.start_byte
        if child_len > max_chars:
            flush()
            run = []
            chunks.extend(_split_node(child, source, path, max_chars))
            continue
        if run and (child.end_byte - run[0].start_byte) > max_chars:
            flush()
            run = []
        run.append(child)

    flush()
    return chunks


def _split_node(node: Node, source: bytes, path: str, max_chars: int) -> list[Chunk]:
    if node.end_byte - node.start_byte <= max_chars:
        return [_make_chunk(
            path, source, node.start_byte, node.end_byte,
            node.start_point[0] + 1, node.end_point[0] + 1,
        )]

    body = node.child_by_field_name("body")
    if body is not None and body.named_child_count > 0:
        body_children = [c for c in body.children if c.is_named]
        sub_chunks = _split_children(body_children, source, path, max_chars)
        if sub_chunks:
            signature = source[node.start_byte:body.start_byte].decode("utf-8", errors="replace")
            first = sub_chunks[0]
            sub_chunks[0] = Chunk(
                path=path,
                start_line=node.start_point[0] + 1,
                end_line=first.end_line,
                text=signature + first.text,
            )
        return sub_chunks

    named_children = [c for c in node.children if c.is_named]
    if named_children:
        return _split_children(named_children, source, path, max_chars)

    # a leaf with nothing to split on (e.g. one huge string/comment)
    text = source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
    return chunk_fixed(text, path, start_line=node.start_point[0] + 1, max_chars=max_chars)


def _smooth(chunks: list[Chunk], min_chars: int, max_chars: int, tolerance: float) -> list[Chunk]:
    """Fold any chunk under min_chars into a contiguous neighbor, forward then
    backward, as long as the merge stays within tolerance * max_chars. A
    chunk with no viable neighbor is left standalone.
    """
    chunks = list(chunks)
    result: list[Chunk] = []
    i = 0
    limit = max_chars * tolerance

    while i < len(chunks):
        current = chunks[i]
        if len(current.text) >= min_chars or len(chunks) == 1:
            result.append(current)
            i += 1
            continue

        if i + 1 < len(chunks) and len(current.text) + len(chunks[i + 1].text) <= limit:
            nxt = chunks[i + 1]
            chunks[i + 1] = Chunk(
                path=current.path,
                start_line=current.start_line,
                end_line=nxt.end_line,
                text=current.text + nxt.text,
            )
            i += 1
            continue

        if result and len(result[-1].text) + len(current.text) <= limit:
            prev = result.pop()
            result.append(Chunk(
                path=prev.path,
                start_line=prev.start_line,
                end_line=current.end_line,
                text=prev.text + current.text,
            ))
            i += 1
            continue

        result.append(current)
        i += 1

    return result


def chunk_ast(
    root: Node,
    source: bytes,
    path: str,
    max_chars: int = MAX_CHARS,
    min_chars: int = MIN_CHARS,
    tolerance: float = OVERFLOW_TOLERANCE,
) -> list[Chunk]:
    named_children = [c for c in root.children if c.is_named]
    chunks = _split_children(named_children, source, path, max_chars)
    return _smooth(chunks, min_chars, max_chars, tolerance)
