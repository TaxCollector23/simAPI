"use client";

import Link from "next/link";
import { useState } from "react";
import { Menu, X } from "lucide-react";
import { site } from "@/lib/site";

export function Nav() {
  const [open, setOpen] = useState(false);

  return (
    <header className="landing-nav z-50">
      <nav className="landing-nav-inner flex items-center justify-between gap-6" aria-label="Main navigation">
        <Link href="/" className="landing-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-cyan" aria-label="SimAPI home">
          SimAPI
        </Link>

        <div className="hidden items-center gap-7 lg:flex">
          {site.nav.map((item) => (
            <Link key={item.href} href={item.href} className="landing-nav-link text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-cyan">
              {item.label}
            </Link>
          ))}
        </div>

        <Link href="/play" className="landing-nav-cta hidden min-h-10 items-center px-4 text-sm font-medium lg:inline-flex">Open playground</Link>
        <button
          type="button"
          className="landing-mobile-toggle inline-flex h-11 w-11 items-center justify-center rounded-lg border lg:hidden"
          onClick={() => setOpen((value) => !value)}
          aria-label={open ? "Close navigation" : "Open navigation"}
          aria-controls="mobile-navigation"
          aria-expanded={open}
        >
          {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
      </nav>
      {open && (
        <div id="mobile-navigation" className="landing-mobile-menu border-t px-5 pb-6 pt-3 lg:hidden">
          <div className="mx-auto flex max-w-7xl flex-col">
            {site.nav.map((item) => (
              <Link key={item.href} href={item.href} onClick={() => setOpen(false)} className="landing-mobile-link rounded-lg px-3 py-3 text-base">
                {item.label}
              </Link>
            ))}
            <Link href="/play" onClick={() => setOpen(false)} className="landing-nav-cta mt-4 inline-flex min-h-11 items-center justify-center px-4 text-sm font-medium">Open playground</Link>
          </div>
        </div>
      )}
    </header>
  );
}
