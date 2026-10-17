export default function App() {
  return (
    <main className="page-shell">
      <section className="welcome-card" aria-labelledby="page-title">
        <p className="eyebrow">Logic Escape Room · Tunja</p>
        <h1 id="page-title">Asistente conversacional</h1>
        <p className="intro">
          Aquí podrás consultar información de las salas y resolver dudas sobre tu visita.
        </p>
        <div className="status-note" role="status">
          Interfaz inicial lista. El chat estará disponible cuando conectemos el backend.
        </div>
      </section>
    </main>
  );
}
