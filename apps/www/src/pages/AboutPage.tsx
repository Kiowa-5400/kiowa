export function AboutPage() {
  return (
    <>
      <section className="page-hero">
        <p className="eyebrow">Club information</p>
        <h2>About Kiowa Gun Club</h2>
        <p>Kiowa Gun Club is a membership-driven club serving the Great Bend, Kansas community with a focus on safe, responsible range use and organized shooting activities.</p>
      </section>

      <section className="content-grid">
        <article className="card">
          <p className="card-kicker">The club</p>
          <h3>A community range in central Kansas</h3>
          <p>Kiowa Gun Club is one of the oldest established clubs in the central Kansas region and is affiliated with the National Rifle Association. Club membership currently requires active NRA membership.</p>
          <p>Membership dues are $150 annually, with the membership year running from August 1 through July 31. Prospective new members are also required to complete a background check and range orientation.</p>
        </article>

        <article className="card">
          <p className="card-kicker">Range activities</p>
          <h3>More than a monthly match</h3>
          <ul className="feature-list">
            <li>Defensive pistol matches held on the second Saturday of the month during the scheduled season.</li>
            <li>Member social shoots on the fourth Tuesday of each month at 6:00 PM.</li>
            <li>Carbine and other organized shooting events as scheduled.</li>
            <li>Open range use for members, subject to club rules and scheduled activities.</li>
          </ul>
        </article>
      </section>

      <section className="card wide-card">
        <p className="card-kicker">Location</p>
        <h3>Great Bend, Kansas</h3>
        <p>Physical location: 369 SW 50 Ave, Great Bend, KS 67530.</p>
        <a className="secondary-button" href="https://www.google.com/maps/search/?api=1&query=369+SW+50+Ave%2C+Great+Bend%2C+KS+67530" target="_blank" rel="noreferrer">Get directions</a>
      </section>
    </>
  );
}
