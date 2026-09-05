import React, { FormEvent, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

type Evidence = { dataset: string; columns: string[]; rows: Record<string, unknown>[]; calculation: string; export_id?: string };
type ChatMessage = { role: "user" | "assistant"; content: string; confidence?: string; evidence?: Evidence };

function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const apiUrl = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
  const [sessionId] = useState(() => {
    const existing = localStorage.getItem("tbx-session-id");
    if (existing) return existing;
    const created = crypto.randomUUID();
    localStorage.setItem("tbx-session-id", created);
    return created;
  });

  useEffect(() => {
    fetch(`${apiUrl}/api/v1/sessions/${sessionId}`)
      .then((response) => response.ok ? response.json() : Promise.reject())
      .then((data) => setMessages((data.history ?? []).filter(
        (item: ChatMessage) => item.role === "user" || item.role === "assistant"
      )))
      .catch(() => undefined);
  }, [apiUrl, sessionId]);

  async function upload(files: FileList | null) {
    if (!files?.length) return;
    setUploading(true);
    const form = new FormData();
    Array.from(files).forEach((file) => form.append("files", file));
    try {
      const response = await fetch(`${apiUrl}/api/v1/datasets/upload`, { method: "POST", body: form });
      if (!response.ok) throw new Error();
      const data = await response.json();
      setMessages((current) => [...current, { role: "assistant", content: `Imported ${data.uploaded.length} dataset file(s) into the sample MySQL database and refreshed its schema.` }]);
    } catch {
      setMessages((current) => [...current, { role: "assistant", content: "Upload failed. The starter currently accepts CSV files only." }]);
    } finally { setUploading(false); }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const text = input.trim();
    if (!text || loading) return;
    const prior = messages;
    setMessages([...prior, { role: "user", content: text }]);
    setInput("");
    setLoading(true);
    try {
      const response = await fetch(`${apiUrl}/api/v1/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          message: text,
        }),
      });
      if (!response.ok) throw new Error("Assistant unavailable");
      const data = await response.json();
      setMessages((current) => [...current, { role: "assistant", content: data.answer, confidence: data.confidence, evidence: data.evidence }]);
    } catch {
      setMessages((current) => [...current, { role: "assistant", content: "The assistant is temporarily unavailable." }]);
    } finally {
      setLoading(false);
    }
  }

  return <main>
    <section className="shell">
      <header><span>TBX - BVP Tech Catalyst</span><h1>Answers grounded in financial data.</h1><p>Ask about balances, credits, debits, banks and transaction references. Every number is computed from uploaded records.</p></header>
      <details className="info"><summary>How accuracy, privacy and scale are handled</summary><div><p><strong>One model call:</strong> NLP produces a constrained plan; MySQL computes over the connected database.</p><p><strong>Fail closed:</strong> missing vendor or ledger data produces a clarification describing the required dataset or permission.</p><p><strong>Protected:</strong> only approved schema columns can reach chat or exports.</p><p><strong>Measured:</strong> token use and latency are available at <code>/api/v1/metrics</code>; model accuracy is scored by <code>evals/run.py</code>.</p></div></details>
      <label className="upload">{uploading ? "Loading datasets..." : "Upload TBX CSV files"}<input type="file" accept=".csv" multiple onChange={(e) => upload(e.target.files)} disabled={uploading}/></label>
      <div className="messages">
        {messages.length === 0 && <div className="empty">Ask a question to verify the complete local flow.</div>}
        {messages.map((m, i) => <article key={i} className={m.role}>
          <div>{m.content}</div>
          {m.confidence && <small>Confidence: {m.confidence}</small>}
          {m.evidence && <section className="evidence"><strong>Verifiable breakdown</strong><p>{m.evidence.calculation}</p><div className="table-wrap"><table><thead><tr>{m.evidence.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead><tbody>{m.evidence.rows.map((row, r) => <tr key={r}>{m.evidence!.columns.map((c) => <td key={c}>{String(row[c] ?? "")}</td>)}</tr>)}</tbody></table></div>{m.evidence.export_id && <a href={`${apiUrl}/api/v1/exports/${m.evidence.export_id}.csv`}>Export CSV</a>}</section>}
        </article>)}
        {loading && <article className="assistant">Thinking…</article>}
      </div>
      <form onSubmit={submit}><input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask the assistant…"/><button>Send</button></form>
    </section>
  </main>;
}

createRoot(document.getElementById("root")!).render(<React.StrictMode><App /></React.StrictMode>);
