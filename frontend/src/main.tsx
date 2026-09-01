import React, { FormEvent, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

type ChatMessage = { role: "user" | "assistant"; content: string };

function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const text = input.trim();
    if (!text || loading) return;
    const prior = messages;
    setMessages([...prior, { role: "user", content: text }]);
    setInput("");
    setLoading(true);
    try {
      const response = await fetch(`${import.meta.env.VITE_API_URL ?? "http://localhost:8000"}/api/v1/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, history: prior }),
      });
      if (!response.ok) throw new Error("Assistant unavailable");
      const data = await response.json();
      setMessages((current) => [...current, { role: "assistant", content: data.answer }]);
    } catch {
      setMessages((current) => [...current, { role: "assistant", content: "The assistant is temporarily unavailable." }]);
    } finally {
      setLoading(false);
    }
  }

  return <main>
    <section className="shell">
      <header><span>TBX starter</span><h1>Financial intelligence, ready to adapt.</h1><p>Neutral AI boilerplate awaiting the final problem statement.</p></header>
      <div className="messages">
        {messages.length === 0 && <div className="empty">Ask a question to verify the complete local flow.</div>}
        {messages.map((m, i) => <article key={i} className={m.role}>{m.content}</article>)}
        {loading && <article className="assistant">Thinking…</article>}
      </div>
      <form onSubmit={submit}><input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask the assistant…"/><button>Send</button></form>
    </section>
  </main>;
}

createRoot(document.getElementById("root")!).render(<React.StrictMode><App /></React.StrictMode>);

