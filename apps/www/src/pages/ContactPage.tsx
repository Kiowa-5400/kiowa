export function ContactPage() {
  return (
    <>
      <section className="page-hero">
        <p className="eyebrow">Get in touch</p>
        <h2>Contact Kiowa Gun Club</h2>
        <p>Questions about membership, matches, the range, or club activities? Reach out using the information below.</p>
      </section>

      <section className="content-grid">
        <article className="card">
          <p className="card-kicker">Mailing address</p>
          <h3>Kiowa Gun Club</h3>
          <p>PO Box 562<br />Great Bend, KS 67530</p>
        </article>

        <article className="card">
          <p className="card-kicker">Range location</p>
          <h3>Visit the club</h3>
          <p>369 SW 50 Ave<br />Great Bend, KS 67530</p>
          <a className="secondary-button" href="https://www.google.com/maps/search/?api=1&query=369+SW+50+Ave%2C+Great+Bend%2C+KS+67530" target="_blank" rel="noreferrer">Open map</a>
        </article>

        <article className="card wide-card">
          <p className="card-kicker">Email</p>
          <h3>Club contact</h3>
          <p><a className="text-link" href="mailto:kiowa369@outlook.com">kiowa369@outlook.com</a></p>
          <p className="muted-copy">For match-day questions, membership questions, and general club information.</p>
        </article>
      </section>
    </>
  );
}
