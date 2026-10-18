import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from 'react';

type Role = 'user' | 'assistant';
type Message = { id: string; role: Role; content: string; createdAt: number };
type ChatTurn = Pick<Message, 'role' | 'content'>;
type ChatResponse = { answer?: unknown };

const MAX_CONTEXT_TURNS = 8;
const SUGGESTIONS = [
  '¿Qué salas tienen?',
  '¿Qué incluye la experiencia?',
  '¿Puedo llevar una torta de cumpleaños?',
];

function makeId() {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
}

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryRequest, setRetryRequest] = useState<{ message: string; history: ChatTurn[] } | null>(null);
  const transcriptEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const requestLock = useRef(false);

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, isLoading, error]);

  async function requestAnswer(message: string, history: ChatTurn[]) {
    if (requestLock.current) return;
    requestLock.current = true;
    setIsLoading(true);
    setError(null);
    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ message, history: history.slice(-MAX_CONTEXT_TURNS) }),
      });

      if (!response.ok) {
        throw new Error(response.status === 503
          ? 'El asistente no está disponible por ahora. Inténtalo de nuevo en un momento.'
          : 'No pudimos enviar tu mensaje. Revisa tu conexión e inténtalo otra vez.');
      }

      const payload = (await response.json()) as ChatResponse;
      const answer = payload.answer;
      if (typeof answer !== 'string' || !answer.trim()) {
        throw new Error('Recibimos una respuesta inesperada. Inténtalo de nuevo.');
      }

      setMessages((current) => [...current, {
        id: makeId(), role: 'assistant', content: answer.trim(), createdAt: Date.now(),
      }]);
      setRetryRequest(null);
    } catch (requestError) {
      setError(requestError instanceof Error
        ? requestError.message
        : 'No pudimos conectar con el asistente. Inténtalo otra vez.');
      setRetryRequest({ message, history });
    } finally {
      requestLock.current = false;
      setIsLoading(false);
      inputRef.current?.focus();
    }
  }

  async function sendMessage(message: string) {
    const trimmed = message.trim();
    if (!trimmed || isLoading || requestLock.current) return;

    const history = messages.slice(-MAX_CONTEXT_TURNS).map(({ role, content }) => ({ role, content }));
    setMessages((current) => [...current, { id: makeId(), role: 'user', content: trimmed, createdAt: Date.now() }]);
    setDraft('');
    setRetryRequest({ message: trimmed, history });
    await requestAnswer(trimmed, history);
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void sendMessage(draft);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void sendMessage(draft);
    }
  }

  function startNewConversation() {
    if (isLoading || requestLock.current) return;
    setMessages([]);
    setDraft('');
    setError(null);
    setRetryRequest(null);
    inputRef.current?.focus();
  }

  return (
    <main className="app-shell">
      <section className="chat-card" aria-labelledby="chat-title">
        <header className="chat-header">
          <div className="brand-mark" aria-hidden="true">L</div>
          <div className="brand-copy">
            <p className="eyebrow">Logic Escape Room <span>· Tunja</span></p>
            <h1 id="chat-title">Asistente virtual</h1>
            <p className="availability"><span className="online-dot" /> Aquí para ayudarte</p>
          </div>
          <button className="new-chat-button" type="button" onClick={startNewConversation} disabled={isLoading}>
            <span aria-hidden="true">＋</span> <span className="new-chat-label">Nueva conversación</span>
          </button>
        </header>

        <div className="conversation" aria-label="Conversación con el asistente" aria-live="polite" aria-busy={isLoading}>
          {messages.length === 0 ? (
            <div className="welcome-state">
              <div className="welcome-icon" aria-hidden="true">✦</div>
              <h2>¡Hola! ¿Qué te gustaría saber?</h2>
              <p>Pregúntame sobre las salas, tu visita o cómo funciona la experiencia.</p>
              <div className="suggestions" aria-label="Preguntas sugeridas">
                {SUGGESTIONS.map((suggestion) => (
                  <button key={suggestion} type="button" onClick={() => void sendMessage(suggestion)} disabled={isLoading}>
                    {suggestion}<span aria-hidden="true"> ↗</span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="message-list">
              {messages.map((message) => (
                <article key={message.id} className={`message message-${message.role}`}>
                  {message.role === 'assistant' && <span className="message-avatar" aria-hidden="true">L</span>}
                  <div className="message-bubble">
                    <p>{message.content}</p>
                    <time>{new Intl.DateTimeFormat('es-CO', { hour: 'numeric', minute: '2-digit' }).format(new Date(message.createdAt))}</time>
                  </div>
                </article>
              ))}
              {isLoading && (
                <div className="message message-assistant" role="status" aria-label="El asistente está escribiendo">
                  <span className="message-avatar" aria-hidden="true">L</span>
                  <div className="typing-indicator"><span /><span /><span /></div>
                  <span className="visually-hidden">El asistente está preparando una respuesta…</span>
                </div>
              )}
              {error && (
                <div className="error-notice" role="alert">
                  <p>{error}</p>
                  {retryRequest && <button type="button" onClick={() => void requestAnswer(retryRequest.message, retryRequest.history)} disabled={isLoading}>Reintentar</button>}
                </div>
              )}
              <div ref={transcriptEndRef} />
            </div>
          )}
        </div>

        <footer className="composer-area">
          {messages.length === 0 && <div ref={transcriptEndRef} />}
          <form className="composer" onSubmit={handleSubmit}>
            <label className="visually-hidden" htmlFor="message-input">Escribe tu mensaje</label>
            <textarea
              id="message-input"
              ref={inputRef}
              rows={1}
              maxLength={4000}
              placeholder="Escribe tu pregunta…"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isLoading}
            />
            <button className="send-button" type="submit" aria-label="Enviar mensaje" disabled={isLoading || !draft.trim()}>
              <span aria-hidden="true">↑</span>
            </button>
          </form>
          <p className="composer-hint">Enter para enviar <span>·</span> Shift + Enter para nueva línea</p>
          <p className="human-note">Algunos casos especiales pueden requerir confirmación del equipo.</p>
        </footer>
      </section>
    </main>
  );
}
