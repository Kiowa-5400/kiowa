export function CalendarPage() {
  return (
    <>
      <section className="page-hero">
        <p className="eyebrow">Schedule</p>
        <h2>Club Calendar</h2>
        <p>Use the recurring schedule below as a quick reference. Scheduled events and range conditions take precedence, so check the club's current announcements before heading out.</p>
      </section>

      <section className="content-grid">
        <article className="card">
          <p className="card-kicker">Monthly</p>
          <h3>Defensive pistol matches</h3>
          <p><strong>Second Saturday</strong> during the scheduled 2026 match season.</p>
          <p>Match times vary by month. See the full 2026 schedule on the Matches page.</p>
          <a className="primary-button" href="/matches">View match schedule</a>
        </article>

        <article className="card">
          <p className="card-kicker">Members</p>
          <h3>Tuesday social shoot</h3>
          <p><strong>Fourth Tuesday of each month at 6:00 PM.</strong></p>
          <p>This recurring evening is for club members and is intended as an informal opportunity to shoot and spend time with other members.</p>
        </article>
      </section>

      <section className="card wide-card">
        <p className="card-kicker">Planning note</p>
        <h3>Scheduled events take priority</h3>
        <p>Range rules state that the club calendar and scheduled shoots take precedence. Event times are subject to change, so use the current club schedule when planning a visit.</p>
      </section>
    </>
  );
}
