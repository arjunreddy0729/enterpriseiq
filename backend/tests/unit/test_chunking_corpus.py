"""The same invariants, asserted against the real corpus.

Synthetic unit tests prove the chunker handles the cases I thought of. This
module proves it handles the 22 documents it will actually be run against -
which is where the cases I did not think of live.

It is also the regression net for chunker tuning: change a packing rule and
this tells you immediately whether a code fence started getting cut in half.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import get_settings
from app.ingestion.chunking import ChunkingConfig, chunk_document
from app.ingestion.parsers import parse_file, supported_extensions

# from_settings, not the dataclass literals: this file calls itself the
# regression net for chunker tuning, so it has to test the numbers the system
# actually runs with.
CONFIG = ChunkingConfig.from_settings()


def corpus_files() -> list[Path]:
    corpus = get_settings().corpus_dir
    if not corpus.is_dir():
        return []
    extensions = set(supported_extensions())
    return sorted(p for p in corpus.rglob("*") if p.suffix.lower() in extensions)


FILES = corpus_files()
pytestmark = pytest.mark.skipif(not FILES, reason="corpus directory not available")


@pytest.fixture(scope="module")
def all_chunks() -> list[tuple[Path, object]]:
    result = []
    for path in FILES:
        document = parse_file(path)
        for chunk in chunk_document(document, CONFIG):
            result.append((path, chunk))
    return result


def test_every_corpus_file_parses() -> None:
    for path in FILES:
        document = parse_file(path)
        assert document.blocks, f"{path} produced no blocks"
        assert document.title


def test_every_corpus_file_produces_chunks() -> None:
    for path in FILES:
        chunks = chunk_document(parse_file(path), CONFIG)
        assert chunks, f"{path} produced no chunks"


def test_no_chunk_exceeds_the_ceiling(all_chunks: list) -> None:
    offenders = [
        (path.name, chunk.index, chunk.token_count)
        for path, chunk in all_chunks
        if chunk.token_count > CONFIG.max_tokens and not chunk.is_split_block
    ]
    assert not offenders, f"chunks over {CONFIG.max_tokens} tokens: {offenders}"


def test_no_code_fence_is_cut_in_half(all_chunks: list) -> None:
    offenders = [
        (path.name, chunk.index) for path, chunk in all_chunks if chunk.text.count("```") % 2 != 0
    ]
    assert not offenders, f"unbalanced code fences in: {offenders}"


def test_no_chunk_is_empty_or_whitespace(all_chunks: list) -> None:
    for path, chunk in all_chunks:
        assert chunk.text.strip(), f"{path.name} chunk {chunk.index} is empty"


def test_almost_every_chunk_has_a_heading_path(all_chunks: list) -> None:
    # A handful of preamble chunks legitimately precede the first heading.
    without = [c for _, c in all_chunks if not c.heading_path]
    assert len(without) / len(all_chunks) < 0.05


def test_embed_text_contains_the_body(all_chunks: list) -> None:
    for path, chunk in all_chunks:
        assert chunk.text in chunk.embed_text, f"{path.name} chunk {chunk.index}"


def test_chunk_indices_are_contiguous_per_document() -> None:
    for path in FILES:
        chunks = chunk_document(parse_file(path), CONFIG)
        assert [c.index for c in chunks] == list(range(len(chunks))), path.name


def test_corpus_chunking_is_deterministic() -> None:
    first = [c.text for p in FILES for c in chunk_document(parse_file(p), CONFIG)]
    second = [c.text for p in FILES for c in chunk_document(parse_file(p), CONFIG)]
    assert first == second


def test_the_txt_document_gets_headings() -> None:
    """The plain-text handbook must not degrade to one giant blob."""
    txt = [p for p in FILES if p.suffix == ".txt"]
    if not txt:
        pytest.skip("no .txt file in corpus")
    chunks = chunk_document(parse_file(txt[0]), CONFIG)
    assert len(chunks) > 3
    assert any(c.heading_path for c in chunks)


def test_size_distribution_is_sane(all_chunks: list) -> None:
    """Guard against a tuning change that collapses or explodes chunk sizes."""
    sizes = [c.token_count for _, c in all_chunks]
    mean = sum(sizes) / len(sizes)
    assert 120 <= mean <= CONFIG.max_tokens, f"mean chunk size {mean:.0f} looks wrong"
    assert max(sizes) <= CONFIG.max_tokens
    # Chunks this small are stubs that will never win a retrieval.
    tiny = [s for s in sizes if s < 30]
    assert len(tiny) / len(sizes) < 0.05, f"{len(tiny)} stub chunks"
