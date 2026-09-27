# Design and extension plan

## Boundaries

`extraction.py` owns document parsing; `chunking.py` owns text segmentation; `embeddings.py` owns model inference; `storage.py` owns persistence; `generation.py` owns answer generation; `service.py` coordinates them. Keep future modality-specific decoding out of HTTP routes.

## Data model

The document catalog stores JSON records in SQLite, keyed by SHA-256 of original bytes. Fields include filename, page count, empty-page count, chunk count, byte count, status, embedding model, warning, and timestamp. File names are labels only; filesystem paths derive from content hashes.

Each Qdrant point uses a deterministic UUID derived from document ID and chunk index. Payload: `document_id`, `filename`, `page`, `chunk_index`, `text`, and `modality`. `page` is the physical page, starting at 1. The current modality is always `pdf`.

Only catalog records marked `ready` participate in retrieval. A failed ingestion attempts to remove partially written vectors and files. An interrupted ingest remains `indexing` and is cleaned up on next startup. Vector operations are idempotent. SQLite and Qdrant are not one distributed transaction; cleanup failure is surfaced and can block restart until Qdrant is reachable. This is a deliberate M1 simplification.

Deletion removes vectors before removing the catalog record. It is retryable if interrupted. A query already generating an answer when its source is deleted may return evidence whose original file is no longer available. The UI clears conversation history on its own deletion actions.

## Retrieval and grounding limits

Semantic segmentation compares adjacent sentence embeddings, then enforces a tokenizer budget. There is no overlap in this milestone. Keeping chunks within pages preserves unambiguous citations, at the cost of context across page breaks. The next retrieval iteration can fetch neighboring chunks after matching.

The default embedding model is primarily English-oriented. Tables, columns, mathematical notation, and scanned PDFs require better parsing/OCR. No-text pages are omitted from indexing and counted in the document warning. Partially scanned pages cannot reliably be detected from text extraction alone.

The prompt separates system instructions from source text and treats sources as untrusted. It is not a complete prompt-injection defense. Citation validation checks that IDs exist, not that each claim is entailed by the cited text. The evidence viewer exposes retrieved passages for review; it does not prove answer correctness. Relevant retrieval with insufficient answering evidence can still produce an uncited model abstention, which is returned as a generation error in M1.

Source cards contain all retrieved passages, including ones the model might not cite. Inline citations identify the model's cited passages. Scores are cosine similarities, not confidence percentages.

## Runtime limits

- One backend process/worker; embedded Qdrant takes a local directory lock.
- Sentence embedding is CPU-based and locked during inference. Upload operations are serialized to prevent duplicate-ingest races.
- No persistent job queue, progress percentages, streaming answers, or resumable uploads yet.
- File size is checked on read; multipart parsing happens first. Nginx caps the aggregate request size in Compose. A directly exposed development API lacks a reverse-proxy request cap.
- PDFs can be computationally expensive even below file/page limits. Public deployment needs isolated parsing workers, time/memory quotas, authentication, rate limits, and request/body controls.
- The backend health route indicates initialization, not live Ollama/model availability or remote Qdrant readiness after startup.
- Original PDFs, extracted passages, vectors, and metadata persist until deletion. Backups should include both the catalog/PDF volume and Qdrant volume at a consistent point.
- Model downloads require internet on first use. Once models are cached, document processing runs locally. The UI has a Google Fonts stylesheet with system-font fallback; remove the import for strictly offline presentation.

## Extension contracts

1. **OCR/images:** replace the extraction result with a shared segment type carrying text, modality, source locator, and optional bounding box. Keep original physical page metadata.
2. **Audio/video:** add extraction adapters emitting timestamp ranges and frame references. Generalize evidence links to a locator union (`page`, `timestamp`, `region`).
3. **Hybrid retrieval:** extend the vector repository with sparse vectors and a retrieval strategy returning the same source DTO. Add reranking before source labels are assigned.
4. **Workspaces/auth:** introduce workspace ownership in the catalog and vector payload, enforce it at every document and query route, and migrate existing records explicitly.
5. **Jobs:** move ingestion into an idempotent job worker with durable status transitions. Replace process-local locks with queue/transaction coordination before adding API workers.
6. **Analytics/evaluation:** store latency, retrieval rank, feedback, and a versioned evaluation corpus; avoid logging document content by default.
7. **Deployment:** introduce object storage, a relational metadata service, managed Qdrant, authentication, migrations, structured metrics, deployment-specific secrets, and backup/restore checks.

## Suggested quality evaluation

Create a set of PDFs with questions, expected answers, and gold physical pages. Measure retrieval recall@k, citation page accuracy, unsupported-claim rate, abstention accuracy, and p50/p95 latency. Compare dense retrieval against hybrid search and reranking on that same fixed set before adopting additional complexity.
