import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ArrowUp, BookOpen, Check, FileText, Layers3, LoaderCircle, Plus, Search, Sparkles, Trash2, Upload, X } from 'lucide-react';
import './style.css';

type Doc = { id: string; name: string; pages: number; chunks: number; warning: string | null };
type Source = { label: string; filename: string; page: number; text: string; score: number; url: string };
type Answer = { answer: string; sources: Source[]; mode: string };
type Turn = { question: string; response: Answer };

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, init);
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(typeof error.detail === 'string' ? error.detail : `Request failed (${response.status}).`);
  }
  return response.status === 204 ? undefined as T : response.json();
}

function App() {
  const [docs, setDocs] = useState<Doc[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [question, setQuestion] = useState('');
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState<'upload' | 'ask' | 'delete' | null>(null);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [online, setOnline] = useState(false);
  const [mode, setMode] = useState('');
  const [activeSource, setActiveSource] = useState<Source | null>(null);
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const bottom = useRef<HTMLDivElement>(null);

  async function refresh() {
    const list = await api<Doc[]>('/documents');
    setDocs(list);
    setSelected(previous => previous.filter(id => list.some(doc => doc.id === id)));
  }
  useEffect(() => {
    async function initialize() {
      try {
        const health = await api<{ generation_mode: string }>('/health');
        setOnline(true); setMode(health.generation_mode); await refresh(); setError('');
      } catch { setOnline(false); setError('Cannot connect to the backend. Start the API, then retry.'); }
    }
    void initialize();
    const interval = window.setInterval(() => { void api('/health').then(() => setOnline(true)).catch(() => setOnline(false)); }, 30000);
    return () => window.clearInterval(interval);
  }, []);
  useEffect(() => { if (turns.length || busy) bottom.current?.scrollIntoView({ behavior: 'smooth' }); }, [turns, busy]);

  async function upload(files: FileList | File[]) {
    if (busy) return;
    const batch = Array.from(files);
    if (!batch.length) return;
    if (batch.length > 10 || batch.some(file => !file.name.toLowerCase().endsWith('.pdf') || file.size > 25 * 1024 * 1024)) {
      setError('Choose up to 10 PDF files, each no larger than 25 MB.'); return;
    }
    setBusy('upload'); setError(''); setNotice('');
    const body = new FormData(); batch.forEach(file => body.append('files', file));
    try {
      const result = await api<{ results: { ok: boolean; document?: Doc & { duplicate: boolean }; filename?: string; error?: string }[] }>('/documents', { method: 'POST', body });
      const failures = result.results.filter(item => !item.ok);
      const success = result.results.filter(item => item.ok);
      setNotice(`${success.length} PDF${success.length === 1 ? '' : 's'} ready. ${success.filter(item => item.document?.duplicate).length} already indexed.`);
      if (failures.length) setError(failures.map(item => `${item.filename}: ${item.error}`).join('\n'));
      await refresh(); setOnline(true);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(null); if (fileInput.current) fileInput.current.value = ''; }
  }
  async function ask(event: React.FormEvent) {
    event.preventDefault();
    if (!question.trim() || busy || !docs.length) return;
    const prompt = question.trim(); setBusy('ask'); setError('');
    try {
      const response = await api<Answer>('/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: prompt, document_ids: selected, top_k: 5 }) });
      setTurns(previous => [...previous, { question: prompt, response }]); setQuestion('');
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(null); }
  }
  async function remove(doc: Doc) {
    if (!window.confirm(`Delete “${doc.name}” and its indexed content?`)) return;
    setBusy('delete'); setError('');
    try { await api(`/documents/${doc.id}`, { method: 'DELETE' }); await refresh(); setActiveSource(null); setTurns([]); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(null); }
  }
  function citedAnswer(response: Answer) {
    return response.answer.split(/(\[S\d+\])/g).map((part, index) => {
      const source = response.sources.find(item => `[${item.label}]` === part);
      return source ? <button key={index} className="inline-cite" onClick={() => setActiveSource(source)} title={`${source.filename}, page ${source.page}`}>{source.label}</button> : <React.Fragment key={index}>{part}</React.Fragment>;
    });
  }

  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="/"><span className="brand-icon"><Layers3 size={23}/></span><span>Knowledge<span className="brand-second">Engine</span></span></a>
      <div className="workspace-label">YOUR WORKSPACE</div>
      <div className="workspace-nav"><BookOpen size={18}/> Research library <span className="badge">01</span></div>
      <div className="library-heading"><span>Sources <b>{docs.length}</b></span><button className="icon-button" disabled={!!busy} onClick={() => fileInput.current?.click()} aria-label="Add PDFs"><Plus size={18}/></button></div>
      <p className="helper">Select sources to narrow your answers.<br/>No selection searches the whole library.</p>
      <div className="document-list">
        {docs.length === 0 ? <div className="empty-library"><FileText size={27}/><p>Your library starts here</p><small>Add a PDF to get started.</small></div> : docs.map(doc => <div className={`document ${selected.includes(doc.id) ? 'selected' : ''}`} key={doc.id}>
          <label><input type="checkbox" checked={selected.includes(doc.id)} disabled={!!busy} onChange={() => setSelected(previous => previous.includes(doc.id) ? previous.filter(id => id !== doc.id) : [...previous, doc.id])}/><FileText size={20}/><span><strong title={doc.name}>{doc.name}</strong><small>{doc.pages} pages · {doc.chunks} passages</small>{doc.warning && <small className="warning">{doc.warning}</small>}</span></label>
          <button className="icon-button delete" aria-label={`Delete ${doc.name}`} disabled={!!busy} onClick={() => void remove(doc)}><Trash2 size={14}/></button>
        </div>)}
      </div>
      <div className={`upload-box ${dragging ? 'dragging' : ''}`} onDragOver={e => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={e => { e.preventDefault(); setDragging(false); void upload(e.dataTransfer.files); }}>
        <Upload size={21}/><button disabled={!!busy} onClick={() => fileInput.current?.click()}>{busy === 'upload' ? 'Extracting & indexing…' : 'Click to upload PDFs'}</button><small>or drop files here · up to 25 MB each</small>
      </div>
      <input ref={fileInput} type="file" accept=".pdf,application/pdf" multiple hidden onChange={e => e.target.files && void upload(e.target.files)}/>
      <div className="sidebar-footer"><span className={`status-dot ${online ? 'online' : ''}`}/>{online ? 'Backend connected' : 'Backend offline'}<span className="local-badge">M1</span></div>
    </aside>
    <main>
      <header><div><span className="breadcrumb">Workspace <span>/</span></span> Research library</div><span className="privacy"><span className="status-dot online"/> Local-first knowledge</span></header>
      <section className="workspace-title"><div><div className="eyebrow">READ LESS. UNDERSTAND MORE.</div><h1>Your documents, connected.</h1><p>Ask a question. Follow the evidence. Find your next insight.</p></div><span className="milestone">PDF KNOWLEDGE · MILESTONE 1</span></section>
      <div className="stats"><div><FileText size={18}/><strong>{docs.length}</strong><span>documents</span></div><div><BookOpen size={18}/><strong>{docs.reduce((sum, doc) => sum + doc.pages, 0)}</strong><span>pages indexed</span></div><div><Search size={18}/><strong>{selected.length || docs.length}</strong><span>sources in scope</span></div></div>
      <section className="conversation-panel">
        <div className="panel-heading"><span><Sparkles size={18}/> Ask your library</span><span className="mode-tag">{mode === 'extractive' ? 'EXTRACTIVE MODE' : 'SOURCE-GROUNDED ANSWERS'}</span></div>
        <div className="conversation" aria-live="polite">
          {!turns.length && <div className="welcome"><span className="welcome-icon"><Sparkles size={28}/></span><h2>A little curiosity goes a long way.</h2><p>{docs.length ? 'Your sources are ready. What would you like to understand?' : 'Add your PDFs, then turn scattered information into answers you can trace.'}</p><div className="suggestions">{['What are the main findings?', 'Compare the key ideas across these documents.', 'What limitations do the authors mention?'].map(prompt => <button key={prompt} disabled={!docs.length || !!busy} onClick={() => setQuestion(prompt)}>{prompt}<ArrowUp size={15}/></button>)}</div><span className="evidence-note"><Check size={14}/> Every source includes its original page number</span></div>}
          {turns.map((turn, i) => <article className="turn" key={i}><div className="question"><span>YOU</span><p>{turn.question}</p></div><div className="answer"><div className="answer-label"><Sparkles size={16}/> KNOWLEDGE ENGINE <small>{turn.response.mode === 'extractive' ? 'Retrieved excerpts' : ''}</small></div><div className="answer-text">{citedAnswer(turn.response)}</div>{turn.response.sources.length > 0 && <div className="source-links">{turn.response.sources.map(source => <button key={source.label} onClick={() => setActiveSource(source)}><span>{source.label}</span>{source.filename}<b>p. {source.page}</b></button>)}</div>}</div></article>)}
          {busy && <div className="loading"><LoaderCircle className="spin" size={17}/>{busy === 'upload' ? 'Extracting pages, finding semantic boundaries, and indexing…' : busy === 'ask' ? 'Searching your sources and preparing an answer…' : 'Removing document…'}</div>}
          <div ref={bottom}/>
        </div>
        <div className="composer-area">{error && <div className="alert" role="alert">{error}<button onClick={() => { setError(''); void refresh().catch(() => setError('Backend is still unavailable.')); }}>Retry library</button></div>}{notice && <div className="notice" role="status">{notice}</div>}<form onSubmit={ask}><textarea rows={2} aria-label="Ask a question about your PDFs" placeholder={docs.length ? 'Ask anything about your documents…' : 'Upload your first PDF to start exploring…'} value={question} onChange={e => setQuestion(e.target.value)} maxLength={2000} disabled={!!busy || !docs.length} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); e.currentTarget.form?.requestSubmit(); } }}/><div className="composer-bottom"><span><Layers3 size={14}/>{selected.length ? `${selected.length} selected sources` : 'All sources'} · page citations included</span><button type="submit" className="send" aria-label="Send question" disabled={!question.trim() || !!busy || !docs.length}><ArrowUp size={19}/></button></div></form><p className="disclaimer">Answers can be imperfect. Open the cited pages to check the evidence.</p></div>
      </section>
    </main>
    {activeSource && <div className="source-overlay" onClick={() => setActiveSource(null)}><section className="source-detail" role="dialog" aria-modal="true" aria-label="Source evidence" onClick={e => e.stopPropagation()}><div className="panel-heading"><span>Source {activeSource.label}</span><button autoFocus className="icon-button" onClick={() => setActiveSource(null)} aria-label="Close source" onKeyDown={e => e.key === 'Escape' && setActiveSource(null)}><X size={20}/></button></div><h2>{activeSource.filename}</h2><p className="source-meta">Page {activeSource.page} · similarity {activeSource.score.toFixed(2)}</p><blockquote>{activeSource.text}</blockquote><a className="open-source" href={activeSource.url} target="_blank" rel="noreferrer">Open PDF at page {activeSource.page} ↗</a><p className="helper">Similarity is a retrieval score, not a confidence probability.</p></section></div>}
  </div>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
