import re
from dataclasses import dataclass

from .embeddings import similarity
from .extraction import Page


@dataclass
class Chunk:
    page: int
    index: int
    text: str


def semantic_chunks(pages: list[Page], embedder, token_limit: int, threshold: float) -> list[Chunk]:
    """Split at semantic changes or tokenizer limits; never cross a PDF page boundary."""
    chunks = []
    for page in pages:
        units = []
        for sentence in re.split(r'(?<=[.!?])\s+|\n\s*\n', page.text):
            sentence = ' '.join(sentence.split())
            if not sentence:
                continue
            tokens = embedder.tokens(sentence)
            # Preserve original text whenever it fits; split unusually long sentences.
            if len(tokens) <= token_limit:
                units.append(sentence)
            else:
                units.extend(embedder.decode(tokens[i:i + token_limit])
                             for i in range(0, len(tokens), token_limit))
        if not units:
            continue
        vectors = embedder.encode(units)
        current = []
        for i, unit in enumerate(units):
            candidate = ' '.join([*current, unit])
            topic_change = i > 0 and similarity(vectors[i - 1], vectors[i]) < threshold
            if current and (topic_change or len(embedder.tokens(candidate)) > token_limit):
                chunks.append(Chunk(page.number, len(chunks), ' '.join(current)))
                current = []
            current.append(unit)
        if current:
            chunks.append(Chunk(page.number, len(chunks), ' '.join(current)))
    return chunks
