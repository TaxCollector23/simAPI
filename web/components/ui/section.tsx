import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** A consistent heading and supporting copy for page sections. */
export function SectionHeader({
  eyebrow,
  title,
  lede,
  align = "left",
}: {
  eyebrow?: string;
  title: ReactNode;
  lede?: ReactNode;
  align?: "center" | "left";
}) {
  return (
    <div
      className={cn(
        "flex w-full flex-col gap-4",
        align === "center" ? "items-center text-center" : "items-start text-left",
      )}
    >
      {eyebrow && <span className="eyebrow">{eyebrow}</span>}
      <h2 className="w-full max-w-2xl text-balance text-3xl font-medium tracking-tight text-white sm:text-4xl">
        {title}
      </h2>
      {lede && <p className="w-full max-w-2xl text-base leading-relaxed text-white/65">{lede}</p>}
    </div>
  );
}

export function Section({
  id,
  className,
  children,
}: {
  id?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section id={id} className={cn("relative py-24 sm:py-32", className)}>
      <div className="container-tight">{children}</div>
    </section>
  );
}
