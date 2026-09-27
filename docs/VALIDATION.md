# Delivery validation

Checked on Windows with Python 3.13 and Node.js 22.14.0 on 27 September 2026.

| Check | Result |
|---|---|
| Backend suite | 19 tests passed |
| Python lint | `ruff check .` passed |
| TypeScript and production bundle | Passed; 1,578 modules transformed |
| npm dependency audit during install | 0 vulnerabilities reported |
| Browser inspection | Built interface rendered at compact and desktop widths; empty-library and backend-offline states inspected |
| Actual embedding model | Passed: real MiniLM, semantic chunking, embedded Qdrant, and expected page-2 citation |
| Live Ollama generation | Not run: Ollama is not installed on the host |
| Docker Compose startup | Not run: Docker is not installed on the host |

The backend tests use real PyMuPDF and persistent embedded Qdrant. A deterministic embedding double and mocked Ollama responses isolate ingestion, retrieval, persistence, source scoping, HTTP validation, and citation handling. Generation quality and factual entailment are not measured by these tests.

The installed FastAPI/Starlette version emitted one deprecation warning about its `httpx` test-client adapter; all tests passed.

The Windows sandbox prevented Vite's default bundled-config loader from traversing a parent directory. The build passed using `npm run build -- --configLoader runner`. The delivered default build command remains standard for ordinary local and CI environments. Vite development dependency optimization encountered the same sandbox restriction; the production preview was used for visual inspection.

The npm registry certificate chain was resolved for this session using the Windows trusted certificate store. No certificate verification was disabled and no machine-wide settings were changed.

## Smoke-test note

The real-model smoke test completed successfully, including temporary data cleanup, using Sentence Transformers 5.7.0, PyTorch 2.14.0, and Qdrant Client 1.19.1. A question about wind turbines correctly retrieved the second page of a generated two-page PDF and returned `[S1]` with a page-2 PDF link. This verifies the actual embedding/retrieval path in extractive mode, not generative answer quality.

The first smoke run exposed unclosed SQLite connections during Windows temporary-directory cleanup. Connections now close explicitly, and a regression test covers handle release. The rerun exited successfully. Sentence Transformers emitted a non-failing deprecation warning for its embedding-dimension accessor, retained for compatibility with the supported older versions.

Container startup and live Ollama answers still require verification on a host with those runtimes installed.
