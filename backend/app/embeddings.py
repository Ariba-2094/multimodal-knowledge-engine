from threading import Lock

import numpy as np


class Embedder:
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model_name, device='cpu')
        self.dimension = self.model.get_sentence_embedding_dimension()
        self.lock = Lock()

    def encode(self, texts: list[str]) -> list[list[float]]:
        with self.lock:
            return self.model.encode(texts, batch_size=32, normalize_embeddings=True,
                                     show_progress_bar=False).tolist()

    def tokens(self, text: str) -> list[int]:
        return self.model.tokenizer.encode(text, add_special_tokens=False)

    def decode(self, tokens: list[int]) -> str:
        return self.model.tokenizer.decode(tokens, skip_special_tokens=True)


def similarity(a: list[float], b: list[float]) -> float:
    return float(np.dot(a, b))
