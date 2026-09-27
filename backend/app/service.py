import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from uuid import NAMESPACE_URL, uuid5

from qdrant_client.models import PointStruct

from .chunking import semantic_chunks
from .extraction import extract_pdf
from .generation import generate
from .storage import Catalog, VectorStore

logger = logging.getLogger(__name__)


class KnowledgeService:
    def __init__(self, settings, embedder):
        self.settings, self.embedder = settings, embedder
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = settings.data_dir / 'index-config.json'
        manifest = {'embedding_model': settings.embedding_model,
                    'collection': settings.qdrant_collection, 'qdrant_url': settings.qdrant_url,
                    'chunk_tokens': settings.chunk_tokens, 'semantic_threshold': settings.semantic_threshold}
        if manifest_path.exists() and json.loads(manifest_path.read_text()) != manifest:
            raise RuntimeError('Index configuration changed. Use a new DATA_DIR and QDRANT_COLLECTION, then reupload PDFs.')
        self.pdf_dir = settings.data_dir / 'pdfs'
        self.pdf_dir.mkdir(exist_ok=True)
        self.catalog = Catalog(settings.data_dir / 'catalog.db')
        self.vectors = VectorStore(settings, embedder.dimension)
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        self.lock = RLock()
        # Incomplete ingest records never become searchable; recover on restart.
        for record in self.catalog.list():
            if record['status'] != 'ready':
                self.delete(record['id'])

    def ingest(self, name: str, data: bytes):
        if len(data) > self.settings.max_file_mb * 1024 * 1024:
            raise ValueError(f'File exceeds {self.settings.max_file_mb} MB.')
        if not name.lower().endswith('.pdf'):
            raise ValueError('Only PDF files are supported in Milestone 1.')
        document_id = hashlib.sha256(data).hexdigest()
        with self.lock:
            existing = self.catalog.get(document_id)
            if existing and existing['status'] == 'ready':
                return {**existing, 'duplicate': True}
            pages, empty = extract_pdf(data, self.settings.max_pages)
            chunks = semantic_chunks(pages, self.embedder, self.settings.chunk_tokens, self.settings.semantic_threshold)
            if not chunks:
                raise ValueError('No usable text was found.')
            record = {'id': document_id, 'name': Path(name.replace('\\', '/')).name,
                      'pages': len(pages), 'chunks': len(chunks), 'empty_pages': empty,
                      'bytes': len(data), 'status': 'indexing',
                      'created_at': datetime.now(UTC).isoformat(),
                      'embedding_model': self.settings.embedding_model,
                      'warning': f'{empty} pages contain no text and may need OCR.' if empty else None}
            self.catalog.save(record)
            try:
                (self.pdf_dir / f'{document_id}.pdf').write_bytes(data)
                for offset in range(0, len(chunks), 64):
                    batch = chunks[offset:offset + 64]
                    vectors = self.embedder.encode([chunk.text for chunk in batch])
                    self.vectors.put([PointStruct(
                        id=str(uuid5(NAMESPACE_URL, f'{document_id}:{chunk.index}')),
                        vector=vector, payload={'document_id': document_id, 'filename': record['name'],
                                                'page': chunk.page, 'chunk_index': chunk.index,
                                                'text': chunk.text, 'modality': 'pdf'})
                        for chunk, vector in zip(batch, vectors, strict=True)])
                record['status'] = 'ready'
                self.catalog.save(record)
            except Exception:
                logger.exception('Ingestion failed for %s', document_id)
                # Retain an indexing record if cleanup fails so restart can retry cleanup.
                self.delete(document_id)
                raise
            return {**record, 'duplicate': False}

    def delete(self, document_id):
        with self.lock:
            self.vectors.delete(document_id)
            (self.pdf_dir / f'{document_id}.pdf').unlink(missing_ok=True)
            self.catalog.remove(document_id)

    def ask(self, question, document_ids, top_k):
        with self.lock:
            ready = {r['id'] for r in self.catalog.list() if r['status'] == 'ready'}
            if document_ids and not set(document_ids).issubset(ready):
                raise ValueError('One or more selected documents are missing or not ready.')
            selected = document_ids or sorted(ready)
            if not selected:
                return {'answer': 'Upload a PDF before asking a question.', 'sources': [], 'mode': 'no_evidence'}
            hits = self.vectors.search(self.embedder.encode([question])[0], selected, top_k,
                                       self.settings.retrieval_threshold)
            sources = [{'label': f'S{i + 1}', 'document_id': hit.payload['document_id'],
                        'filename': hit.payload['filename'], 'page': hit.payload['page'],
                        'text': hit.payload['text'], 'score': round(hit.score, 4),
                        'url': f'/api/documents/{hit.payload["document_id"]}/file#page={hit.payload["page"]}'}
                       for i, hit in enumerate(hits)]
        if not sources:
            return {'answer': 'I could not find sufficient evidence in the selected PDFs.',
                    'sources': [], 'mode': 'no_evidence'}
        return {'answer': generate(question, sources, self.settings), 'sources': sources,
                'mode': self.settings.generation_mode}

    def close(self):
        self.vectors.close()
