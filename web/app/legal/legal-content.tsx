import { PageHero } from "@/components/ui/page-hero";

export function LegalPage({
  title,
  updated,
  sections,
}: {
  title: string;
  updated: string;
  sections: { heading: string; body: string }[];
}) {
  return (
    <>
      <PageHero eyebrow="Legal" title={title} lede={`Last updated ${updated}.`} />
      <section className="container-tight max-w-2xl space-y-8 pb-24">
        {sections.map((s) => (
          <div key={s.heading}>
            <h2 className="text-lg font-semibold text-white">{s.heading}</h2>
            <p className="mt-2 text-sm leading-relaxed text-white/55">{s.body}</p>
          </div>
        ))}

      </section>
    </>
  );
}
