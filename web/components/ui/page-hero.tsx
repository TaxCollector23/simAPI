import type { ReactNode } from "react";

/** Consistent inner-page header. */
export function PageHero({
  eyebrow,
  title,
  lede,
  children,
}: {
  eyebrow?: string;
  title: ReactNode;
  lede?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <section className="border-b border-white/10 pb-16 pt-36 sm:pt-44">
      <div className="container-tight">
        <div className="flex max-w-3xl flex-col gap-5">
          {eyebrow && <span className="eyebrow w-fit">{eyebrow}</span>}
          <h1 className="text-balance text-4xl font-medium tracking-tight text-white sm:text-5xl">
            {title}
          </h1>
          {lede && <p className="max-w-2xl text-lg leading-relaxed text-white/70">{lede}</p>}
          {children}
        </div>
      </div>
    </section>
  );
}
