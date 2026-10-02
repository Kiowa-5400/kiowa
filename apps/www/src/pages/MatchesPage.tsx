const matches = [
  ['March 14', '1:00 PM', 'Defensive Pistol'],
  ['April 11', '1:00 PM', 'Defensive Pistol'],
  ['May 9', '9:00 AM', 'Defensive Pistol'],
  ['June 13', '8:00 AM', 'Great Plains Speed Shooting Championship'],
  ['July 11', '9:00 AM', 'Defensive Pistol'],
  ['August 8', '9:00 AM', 'Defensive Pistol'],
  ['September 12', '9:00 AM', 'Defensive Pistol'],
  ['October 10', '9:00 AM', 'Defensive Pistol'],
  ['November 14', '1:00 PM', 'Defensive Pistol'],
] as const;

export function MatchesPage() {
  return (
    <>
      <section className="page-hero">
        <p className="eyebrow">Competition</p>
        <h2>Matches</h2>
        <p>2026 defensive pistol match dates and times. The published schedule is subject to change.</p>
      </section>

      <section className="card wide-card">
        <div className="section-heading">
          <div>
            <p className="card-kicker">2026 season</p>
            <h3>Defensive pistol match schedule</h3>
          </div>
          <span className="status-pill">Members & non-members welcome</span>
        </div>

        <div className="match-list">
          {matches.map(([date, time, name]) => (
            <div className="match-row" key={date}>
              <div>
                <strong>{date}, 2026</strong>
                <span>{name}</span>
              </div>
              <time>{time}</time>
            </div>
          ))}
        </div>
      </section>

      <section className="content-grid">
        <article className="card">
          <p className="card-kicker">Match participation</p>
          <h3>Everyone is welcome</h3>
          <p>Kiowa Gun Club's scheduled defensive pistol matches are open to members and non-members. First-time shooters shoot free; subsequent shoots are $15, including immediate family.</p>
        </article>

        <article className="card">
          <p className="card-kicker">Registration</p>
          <h3>Match details</h3>
          <p>Registration and current match information should be confirmed with the club before attending. PractiScore registration links can be added here as the club publishes them.</p>
        </article>
      </section>
    </>
  );
}
