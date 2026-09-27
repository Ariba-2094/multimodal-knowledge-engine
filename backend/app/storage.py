import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from qdrant_client import QdrantClient, models


class Catalog:
    def __init__(self, path: Path):
        self.path = path
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, record TEXT NOT NULL)')

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def list(self):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute('SELECT record FROM documents ORDER BY rowid DESC')]

    def get(self, document_id):
        with self.connect() as db:
            row = db.execute('SELECT record FROM documents WHERE id=?', (document_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def save(self, record):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO documents VALUES (?,?)', (record['id'], json.dumps(record)))

    def remove(self, document_id):
        with self.connect() as db:
            db.execute('DELETE FROM documents WHERE id=?', (document_id,))


class VectorStore:
    def __init__(self, settings, dimension):
        self.collection = settings.qdrant_collection
        self.client = (QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key, timeout=60)
                       if settings.qdrant_url else QdrantClient(path=str(settings.data_dir / 'qdrant')))
        if not self.client.collection_exists(self.collection):
            self.client.create_collection(self.collection, vectors_config=models.VectorParams(
                size=dimension, distance=models.Distance.COSINE))
        config = self.client.get_collection(self.collection).config.params.vectors
        if not isinstance(config, models.VectorParams) or config.size != dimension:
            raise RuntimeError('Embedding dimension differs from collection. Use a new collection and reindex.')

    def put(self, points):
        for start in range(0, len(points), 64):
            self.client.upsert(self.collection, points=points[start:start + 64], wait=True)

    def delete(self, document_id):
        self.client.delete(self.collection, points_selector=models.FilterSelector(filter=models.Filter(
            must=[models.FieldCondition(key='document_id', match=models.MatchValue(value=document_id))])), wait=True)

    def search(self, vector, document_ids, limit, threshold):
        return self.client.query_points(self.collection, query=vector, query_filter=models.Filter(
            must=[models.FieldCondition(key='document_id', match=models.MatchAny(any=document_ids))]),
            limit=limit, score_threshold=threshold, with_payload=True).points

    def close(self):
        self.client.close()
