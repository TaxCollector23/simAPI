import Link from "next/link";
import { site } from "@/lib/site";

export function Footer() {
  return (
    <footer className="landing-footer border-t border-white/10 py-12">
      <div className="container-tight">
        <div className="grid gap-10 md:grid-cols-[1.5fr_repeat(3,1fr)]">
          <div className="max-w-sm">
            <Link href="/" className="landing-footer-brand text-xl font-semibold">SimAPI</Link>
            <p className="mt-4 text-sm leading-6 text-white/60">
              Simulation validation for Physical AI and robotics. Inspect the evidence before you use the data.
            </p>
          </div>
          {site.footerGroups.map((group) => (
            <nav key={group.title} aria-label={group.title}>
              <h2 className="text-sm font-medium">{group.title}</h2>
              <ul className="mt-4 space-y-3">
                {group.links.map((link) => (
                  <li key={link.label}><Link href={link.href} className="text-sm text-white/60 transition-colors hover:text-white">{link.label}</Link></li>
                ))}
              </ul>
            </nav>
          ))}
        </div>
        <div className="landing-footer-bottom mt-12 flex flex-col gap-2 border-t border-white/10 pt-6 text-sm sm:flex-row sm:justify-between">
          <p>© {new Date().getFullYear()} SimAPI</p>
          <p>{site.domain}</p>
        </div>
      </div>
    </footer>
  );
}
