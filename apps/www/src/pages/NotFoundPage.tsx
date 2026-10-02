import { Link, usePageTitle } from '@shared/router';

export function NotFoundPage() {
  usePageTitle('Page not found');
  return (
    <section className="page-hero">
      <p className="kicker">404</p>
      <h1>We couldn't find that page</h1>
      <p className="lead">It may have moved. Try the <Link to="/">home page</Link> or the <Link to="/calendar">calendar</Link>.</p>
    </section>
  );
}
