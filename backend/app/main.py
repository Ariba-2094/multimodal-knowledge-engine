import logging
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from .config import Settings
from .embeddings import Embedder
from .generation import GenerationError
from .service import KnowledgeService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    document_ids: list[str] = Field(default_factory=list, max_length=100)
    top_k: int = Field(default=5, ge=1, le=10)

    @field_validator('question')
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError('Enter a question.')
        return value.strip()


def create_app(settings=None, service=None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        app.state.service = service or KnowledgeService(settings, Embedder(settings.embedding_model))
        yield
        app.state.service.close()

    app = FastAPI(title='Multimodal Knowledge Engine', version='0.1.0', lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                       allow_methods=['GET', 'POST', 'DELETE'], allow_headers=['Content-Type'])

    @app.get('/api/health')
    def health():
        return {'status': 'ok', 'generation_mode': settings.generation_mode,
                'embedding_model': settings.embedding_model}

    @app.get('/api/documents')
    def documents():
        return [r for r in app.state.service.catalog.list() if r['status'] == 'ready']

    @app.post('/api/documents')
    def upload(files: Annotated[list[UploadFile], File()]):
        try:
            if len(files) > settings.max_files:
                raise HTTPException(400, f'Upload at most {settings.max_files} PDFs per request.')
            results = []
            for file in files:
                try:
                    data = file.file.read(settings.max_file_mb * 1024 * 1024 + 1)
                    record = app.state.service.ingest(file.filename or 'upload.pdf', data)
                    results.append({'ok': True, 'document': record})
                except ValueError as exc:
                    results.append({'ok': False, 'filename': file.filename, 'error': str(exc)})
                except Exception:
                    logger.exception('Upload processing failed')
                    results.append({'ok': False, 'filename': file.filename,
                                    'error': 'Indexing failed. Check backend logs and Qdrant availability.'})
            return {'results': results}
        finally:
            for file in files:
                file.file.close()

    @app.get('/api/documents/{document_id}/file')
    def pdf(document_id: str):
        record = app.state.service.catalog.get(document_id)
        if not record or record['status'] != 'ready':
            raise HTTPException(404, 'Document not found.')
        return FileResponse(app.state.service.pdf_dir / f'{record["id"]}.pdf', media_type='application/pdf',
                            filename=record['name'], content_disposition_type='inline')

    @app.delete('/api/documents/{document_id}', status_code=204)
    def delete(document_id: str):
        if not app.state.service.catalog.get(document_id):
            raise HTTPException(404, 'Document not found.')
        app.state.service.delete(document_id)

    @app.post('/api/chat')
    def chat(request: Question):
        try:
            return app.state.service.ask(request.question, request.document_ids, request.top_k)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except GenerationError as exc:
            raise HTTPException(502, str(exc)) from exc
        except Exception as exc:
            logger.exception('Retrieval failed')
            raise HTTPException(503, 'Retrieval unavailable. Check the backend logs.') from exc

    return app


app = create_app()
