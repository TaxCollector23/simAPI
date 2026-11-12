import Link from "next/link";
import { site } from "@/lib/site";

export function Footer() {
  return (
    <footer className="landing-footer border-t py-6">
      <div className="container-tight">
        <nav aria-label="Footer">
          <ul className="flex flex-wrap items-center gap-x-8 gap-y-3">
            {site.footerLinks.map((link) => (
              <li key={link.label}>
                <Link href={link.href} className="text-sm text-white/60 transition-colors hover:text-white">
                  {link.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      </div>
    </footer>
  );
}
