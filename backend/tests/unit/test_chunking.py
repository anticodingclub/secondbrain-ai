"""Chunking.

The properties that matter are not "text comes out" but: does a chunk stay
citable, does it stay inside the embedding window, and does the text survive
intact rather than losing characters at every boundary.
"""

from __future__ import annotations

import pytest

from app.services.chunking import RecursiveChunker, normalise_whitespace
from app.services.parsing.base import TextBlock


def block(text: str, **kwargs: object) -> TextBlock:
    return TextBlock(text=text, **kwargs)  # type: ignore[arg-type]


@pytest.fixture
def chunker() -> RecursiveChunker:
    return RecursiveChunker(chunk_size=200, overlap=20, min_chars=0)


# ── Packing ──────────────────────────────────────────────────────────────────


def test_small_blocks_are_packed_together(chunker: RecursiveChunker) -> None:
    """One chunk per paragraph would waste the window and strand context."""
    chunks = chunker.split([block("First sentence."), block("Second sentence.")])

    assert len(chunks) == 1
    assert "First sentence." in chunks[0].text
    assert "Second sentence." in chunks[0].text


def test_chunks_never_exceed_the_window(chunker: RecursiveChunker) -> None:
    """Text past the model's window is silently dropped, so an oversized chunk
    is a chunk with an invisible hole in it."""
    long_text = ". ".join(f"Sentence number {index} here" for index in range(200))

    chunks = chunker.split([block(long_text)])

    assert len(chunks) > 1
    # Overlap is added after splitting, so the ceiling is size + overlap.
    assert all(len(chunk.text) <= 200 + 20 for chunk in chunks)


def test_ordinals_are_sequential(chunker: RecursiveChunker) -> None:
    chunks = chunker.split([block(f"Paragraph {i} " * 20) for i in range(5)])

    assert [chunk.ordinal for chunk in chunks] == list(range(len(chunks)))


def test_no_text_is_lost_when_splitting(chunker: RecursiveChunker) -> None:
    """Every word of the source must appear somewhere in the output."""
    words = [f"word{index}" for index in range(300)]
    chunks = chunker.split([block(" ".join(words))])

    combined = " ".join(chunk.text for chunk in chunks)
    missing = [word for word in words if word not in combined]
    assert missing == []


# ── Citation anchors ─────────────────────────────────────────────────────────


def test_a_chunk_never_spans_a_page_break(chunker: RecursiveChunker) -> None:
    """Merging pages 4 and 5 makes the citation a lie: it must claim one page
    while containing the other."""
    chunks = chunker.split(
        [
            block("Text from page four.", page_number=4),
            block("Text from page five.", page_number=5),
        ]
    )

    assert len(chunks) == 2
    assert chunks[0].page_number == 4
    assert chunks[1].page_number == 5
    assert "page five" not in chunks[0].text


def test_a_chunk_never_spans_a_section_change(chunker: RecursiveChunker) -> None:
    """Sections are the author's own statement about what belongs together."""
    chunks = chunker.split(
        [
            block("Install with pip.", section_title="Installation"),
            block("Set the API key.", section_title="Configuration"),
        ]
    )

    assert len(chunks) == 2
    assert chunks[0].section_title == "Installation"
    assert chunks[1].section_title == "Configuration"


def test_oversized_blocks_keep_their_anchor_on_every_piece(
    chunker: RecursiveChunker,
) -> None:
    """A 10-page section split into 30 chunks must not lose its page on 29."""
    long_text = ". ".join(f"Detail {index}" for index in range(150))

    chunks = chunker.split([block(long_text, page_number=7, section_title="Appendix")])

    assert len(chunks) > 1
    assert all(chunk.page_number == 7 for chunk in chunks)
    assert all(chunk.section_title == "Appendix" for chunk in chunks)


def test_the_heading_is_embedded_in_the_text_not_only_stored() -> None:
    """A paragraph about build steps should retrieve for "Docker" even when
    the paragraph itself never says the word — the heading carries it."""
    chunker = RecursiveChunker(chunk_size=500, overlap=0)

    chunks = chunker.split(
        [block("Run the build and push the image.", section_title="Docker Setup")]
    )

    assert "Docker Setup" in chunks[0].text


def test_heading_is_not_duplicated_when_already_present() -> None:
    chunker = RecursiveChunker(chunk_size=500, overlap=0)

    chunks = chunker.split([block("Docker Setup", section_title="Docker Setup")])

    assert chunks[0].text.count("Docker Setup") == 1


# ── Overlap ──────────────────────────────────────────────────────────────────


def test_adjacent_chunks_overlap() -> None:
    """A sentence straddling a boundary must remain findable from one side."""
    chunker = RecursiveChunker(chunk_size=120, overlap=30)
    text = ". ".join(f"Fact number {index}" for index in range(60))

    chunks = chunker.split([block(text)])

    assert len(chunks) > 2
    # Checked slightly inside the 30-character overlap: `_emit` strips the
    # joined text, so the boundary itself can shift by a character.
    for index in range(len(chunks) - 1):
        tail = chunks[index].text[-20:]
        assert tail in chunks[index + 1].text, f"chunk {index} does not overlap chunk {index + 1}"


def test_overlap_must_be_smaller_than_the_chunk() -> None:
    """Otherwise every chunk contains the whole of its predecessor and the
    splitter never advances."""
    with pytest.raises(ValueError, match="smaller"):
        RecursiveChunker(chunk_size=100, overlap=100)


# ── Degenerate input ─────────────────────────────────────────────────────────


def test_text_with_no_separators_is_hard_split(chunker: RecursiveChunker) -> None:
    """A base64 blob or a minified line has no natural break at all."""
    chunks = chunker.split([block("A" * 900)])

    assert len(chunks) > 1
    assert all(len(chunk.text) <= 220 for chunk in chunks)


def test_empty_and_whitespace_blocks_are_dropped(chunker: RecursiveChunker) -> None:
    chunks = chunker.split([block("   "), block("\n\n"), block("Real content.")])

    assert len(chunks) == 1
    assert chunks[0].text == "Real content."


def test_no_blocks_yields_no_chunks(chunker: RecursiveChunker) -> None:
    assert chunker.split([]) == []


def test_tiny_chunks_are_discarded() -> None:
    """A stray page number matches everything weakly and nothing well."""
    chunker = RecursiveChunker(chunk_size=200, overlap=0, min_chars=20)

    chunks = chunker.split([block("7"), block("A genuinely useful paragraph here.")])

    assert len(chunks) == 1
    assert "useful paragraph" in chunks[0].text


# ── Whitespace ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a  \t  b", "a b"),
        ("line\n\n\n\n\nnext", "line\n\nnext"),
        ("  padded  ", "padded"),
    ],
)
def test_whitespace_normalisation(raw: str, expected: str) -> None:
    """PDF extraction produces ragged spacing that inflates chunks and embeds
    as noise."""
    assert normalise_whitespace(raw) == expected
