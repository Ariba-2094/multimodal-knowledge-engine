import hashlib
import json
import math
import re

import httpx
import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.chunking import semantic_chunks
from app.config import Settings
from app.extraction import Page, extract_pdf
from app.generation import GenerationError, generate
from app.main import create_app
from app.service import KnowledgeService
from app.storage import Catalog


class FakeEmbedder:
    """Deterministic test double; production always uses sentence-transformers."""
    dimension = 64

    def encode(self, texts):
        result = []
        for text in texts:
            vector = [0.0] * self.dimension
            for word in re.findall(r'\w+', text.lower()):
                vector[int(hashlib.sha256(word.encode()).hexdigest(), 16) % self.dimension] += 1
            norm = math.sqrt(sum(x * x for x in vector)) or 1
            result.append([x / norm for x in vector])
        return result

    def tokens(self, text):
        return text.split()

    def decode(self, tokens):
        return ' '.join(tokens)


def pdf_bytes(*pages):
    with pymupdf.open() as document:
        for text in pages:
            page = document.new_page()
            page.insert_text((72, 72), text)
        return document.tobytes()


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path, generation_mode='extractive', retrieval_threshold=0.1)


@pytest.fixture
def service(settings):
    engine = KnowledgeService(settings, FakeEmbedder())
    yield engine
    engine.close()


def test_extraction_preserves_one_based_physical_pages():
    pages, empty = extract_pdf(pdf_bytes('Solar energy is renewable.', '', 'Wind turbines produce power.'), 10)
    assert [page.number for page in pages] == [1, 2, 3]
    assert pages[2].text == 'Wind turbines produce power.'
    assert empty == 1


@pytest.mark.parametrize('data', [b'not a pdf', b'%PDF-broken', pdf_bytes('')])
def test_invalid_and_scanned_pdfs_are_rejected(data):
    with pytest.raises(ValueError):
        extract_pdf(data, 10)


def test_page_limit():
    with pytest.raises(ValueError, match='page limit'):
        extract_pdf(pdf_bytes('one', 'two'), 1)


def test_semantic_boundaries_and_token_budget():
    class TopicEmbedder(FakeEmbedder):
        def encode(self, texts):
            return [[1.0, 0.0] if 'solar' in text.lower() else [0.0, 1.0] for text in texts]
    embedder = TopicEmbedder()
    pages = [Page(1, 'Solar energy is clean. Solar panels collect light. Fish live in oceans.'), Page(4, 'solar ' * 50)]
    chunks = semantic_chunks(pages, embedder, 12, 0.5)
    assert chunks[0].text == 'Solar energy is clean. Solar panels collect light.'
    assert chunks[1].text == 'Fish live in oceans.'
    assert all(len(embedder.tokens(chunk.text)) <= 12 for chunk in chunks)
    assert {chunk.page for chunk in chunks} == {1, 4}
    assert len({chunk.index for chunk in chunks}) == len(chunks)


def test_duplicate_upload_and_citations(service):
    data = pdf_bytes('Solar energy comes from sunlight.', 'Wind turbines convert wind into power.')
    first = service.ingest('../../research.pdf', data)
    duplicate = service.ingest('renamed.pdf', data)
    assert duplicate['duplicate'] is True
    assert first['name'] == 'research.pdf'
    assert len(service.catalog.list()) == 1
    answer = service.ask('wind turbines power', [first['id']], 1)
    assert answer['sources'][0]['page'] == 2
    assert answer['sources'][0]['url'].endswith('#page=2')
    assert '[S1]' in answer['answer']


def test_document_scope_and_delete(service):
    solar = service.ingest('solar.pdf', pdf_bytes('Solar panels harvest sunlight.'))
    wind = service.ingest('wind.pdf', pdf_bytes('Wind turbines harvest wind.'))
    answer = service.ask('harvest wind', [solar['id']], 5)
    assert all(s['document_id'] == solar['id'] for s in answer['sources'])
    service.delete(wind['id'])
    assert service.catalog.get(wind['id']) is None
    assert not (service.pdf_dir / f'{wind["id"]}.pdf').exists()
    with pytest.raises(ValueError, match='missing'):
        service.ask('wind', [wind['id']], 3)


def test_empty_library_and_low_evidence(service):
    assert service.ask('question', [], 3)['mode'] == 'no_evidence'
    service.ingest('paper.pdf', pdf_bytes('Solar panels harvest sunlight.'))
    service.settings.retrieval_threshold = 1
    assert service.ask('completely unrelated novel medical treatment', [], 3)['sources'] == []


def test_ingest_rollback(service, monkeypatch):
    def fail(_):
        raise RuntimeError('simulated vector write failure')
    monkeypatch.setattr(service.vectors, 'put', fail)
    with pytest.raises(RuntimeError):
        service.ingest('test.pdf', pdf_bytes('Useful extracted text.'))
    assert service.catalog.list() == []
    assert list(service.pdf_dir.iterdir()) == []


def test_persistence_and_incomplete_ingest_recovery(settings):
    first = KnowledgeService(settings, FakeEmbedder())
    record = first.ingest('paper.pdf', pdf_bytes('Persistent solar knowledge.'))
    first.catalog.save({'id': 'incomplete', 'status': 'indexing'})
    first.close()
    second = KnowledgeService(settings, FakeEmbedder())
    try:
        assert second.catalog.get(record['id'])['status'] == 'ready'
        assert second.catalog.get('incomplete') is None
        assert second.ask('solar knowledge', [], 1)['sources'][0]['page'] == 1
    finally:
        second.close()


def test_upload_batch_validation_and_download(settings):
    service = KnowledgeService(settings, FakeEmbedder())
    with TestClient(create_app(settings, service)) as client:
        response = client.post('/api/documents', files=[('files', ('valid.pdf', pdf_bytes('Cited content.'), 'application/pdf')),
                                                       ('files', ('bad.pdf', b'not a pdf', 'application/pdf'))])
        assert response.status_code == 200
        results = response.json()['results']
        assert results[0]['ok'] and not results[1]['ok']
        document_id = results[0]['document']['id']
        downloaded = client.get(f'/api/documents/{document_id}/file')
        assert downloaded.content.startswith(b'%PDF')
        assert downloaded.headers['content-type'] == 'application/pdf'
        assert client.post('/api/chat', json={'question': '  '}).status_code == 422
        assert client.post('/api/chat', json={'question': 'content', 'top_k': 50}).status_code == 422
        assert client.get('/api/documents/unknown/file').status_code == 404
        assert client.delete(f'/api/documents/{document_id}').status_code == 204
        assert client.get('/api/documents').json() == []


def test_file_limits(service):
    with pytest.raises(ValueError, match='Only PDF'):
        service.ingest('file.txt', b'text')
    service.settings.max_file_mb = 1
    with pytest.raises(ValueError, match='exceeds'):
        service.ingest('file.pdf', b'a' * (1024 * 1024 + 1))


@pytest.mark.parametrize('answer,valid', [('Supported answer [S1].', True), ('No citation', False), ('Invented [S99]', False)])
def test_generation_validates_citation_ids(settings, monkeypatch, answer, valid):
    settings.generation_mode = 'ollama'
    def mock_post(url, **kwargs):
        payload = kwargs['json']
        assert payload['stream'] is False
        assert 'untrusted data' in payload['messages'][0]['content']
        assert json.loads(payload['messages'][1]['content'])['question'] == 'Question?'
        return httpx.Response(200, json={'message': {'content': answer}}, request=httpx.Request('POST', url))
    monkeypatch.setattr(httpx, 'post', mock_post)
    sources = [{'label': 'S1', 'text': 'Evidence'}]
    if valid:
        assert generate('Question?', sources, settings) == answer
    else:
        with pytest.raises(GenerationError):
            generate('Question?', sources, settings)


def test_generation_outage(settings, monkeypatch):
    settings.generation_mode = 'ollama'
    def fail(*args, **kwargs):
        raise httpx.ConnectError('offline')
    monkeypatch.setattr(httpx, 'post', fail)
    with pytest.raises(GenerationError, match='Check Ollama'):
        generate('Question?', [{'label': 'S1', 'text': 'Evidence'}], settings)


def test_configuration_drift_is_rejected(settings):
    engine = KnowledgeService(settings, FakeEmbedder())
    engine.close()
    settings.embedding_model = 'different-model-same-dimension'
    with pytest.raises(RuntimeError, match='Index configuration changed'):
        KnowledgeService(settings, FakeEmbedder())


def test_catalog_closes_connections(tmp_path):
    path = tmp_path / 'catalog.db'
    catalog = Catalog(path)
    catalog.save({'id': 'example'})
    assert catalog.get('example') == {'id': 'example'}
    assert catalog.list() == [{'id': 'example'}]
    catalog.remove('example')
    # Windows refuses unlink while any SQLite handle remains open.
    path.unlink()
    assert not path.exists()
