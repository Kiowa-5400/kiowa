import { Html } from '@shared/ui';
import type { Section } from '../site';

/** A CMS section as a card: optional kicker, heading and sanitized body. */
export function SectionCard({ section, kicker, className = 'card', headingLevel = 2 }: {
  section: Section | undefined;
  kicker?: string;
  className?: string;
  headingLevel?: 2 | 3;
}) {
  if (!section) return null;
  const Heading = headingLevel === 2 ? 'h2' : 'h3';
  return (
    <article className={className}>
      {kicker && <p className="kicker">{kicker}</p>}
      {section.heading && <Heading>{section.heading}</Heading>}
      <Html html={section.body_html} />
    </article>
  );
}

/** Sections the board added with "Add a section", shown after a page's built-in content. */
export function CustomSections({ sections }: { sections: Section[] | undefined }) {
  const custom = sections?.filter((s) => s.is_custom) ?? [];
  if (custom.length === 0) return null;
  return (
    <div className="stack" style={{ marginTop: '1rem' }}>
      {custom.map((s) => <SectionCard key={s.id} section={s} />)}
    </div>
  );
}

export function PageIntro({ section, kicker }: { section: Section | undefined; kicker: string }) {
  return (
    <header className="page-hero">
      <p className="kicker">{kicker}</p>
      <h1 id="page-title">{section?.heading ?? ''}</h1>
      {section && <Html html={section.body_html} className="prose lead" />}
    </header>
  );
}
