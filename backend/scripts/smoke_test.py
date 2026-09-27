"""Optional integration smoke test; downloads the real MiniLM model on first run."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymupdf

from app.config import Settings
from app.embeddings import Embedder
from app.service import KnowledgeService


def main():
    with tempfile.TemporaryDirectory() as directory:
        settings = Settings(data_dir=Path(directory), qdrant_url='', generation_mode='extractive')
        service = KnowledgeService(settings, Embedder(settings.embedding_model))
        try:
            with pymupdf.open() as pdf:
                pdf.new_page().insert_text((72, 72), 'Solar panels convert sunlight into electricity.')
                pdf.new_page().insert_text((72, 72), 'Wind turbines convert the kinetic energy of wind into electrical power.')
                document = service.ingest('renewable-energy.pdf', pdf.tobytes())
            response = service.ask('How do wind turbines generate electricity?', [document['id']], 1)
            assert response['sources'][0]['page'] == 2, response
            assert '[S1]' in response['answer'], response
            print('PASS: real embeddings -> Qdrant -> page 2 citation')
        finally:
            service.close()


if __name__ == '__main__':
    main()
