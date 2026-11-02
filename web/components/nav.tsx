"use client";

import Link from "next/link";
import { useState } from "react";
import { Menu, X } from "lucide-react";
import { site } from "@/lib/site";

export function Nav() {
  const [open, setOpen] = useState(false);

  return (
    <header className="absolute inset-x-0 top-0 z-50 border-b border-white/10 bg-ink-950">
      <nav className="container-tight flex h-20 items-center justify-between gap-6" aria-label="Main navigation">
        <Link href="/" className="text-xl font-semibold tracking-tight text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-cyan" aria-label="SimAPI home">
          SimAPI
        </Link>

        <div className="hidden items-center gap-7 lg:flex">
          {site.nav.map((item) => (
            <Link key={item.href} href={item.href} className="text-sm text-white/65 transition-colors hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-cyan">
              {item.label}
            </Link>
          ))}
        </div>

        <Link href="/play" className="btn-primary hidden lg:inline-flex">Open playground</Link>
        <button
          type="button"
          className="inline-flex h-11 w-11 items-center justify-center rounded-lg border border-white/15 text-white lg:hidden"
          onClick={() => setOpen((value) => !value)}
          aria-label={open ? "Close navigation" : "Open navigation"}
          aria-controls="mobile-navigation"
          aria-expanded={open}
        >
          {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
      </nav>
      {open && (
        <div id="mobile-navigation" className="border-t border-white/10 bg-ink-950 px-5 pb-6 pt-3 lg:hidden">
          <div className="mx-auto flex max-w-7xl flex-col">
            {site.nav.map((item) => (
              <Link key={item.href} href={item.href} onClick={() => setOpen(false)} className="rounded-lg px-3 py-3 text-base text-white/80 hover:bg-white/[0.06] hover:text-white">
                {item.label}
              </Link>
            ))}
            <Link href="/play" onClick={() => setOpen(false)} className="btn-primary mt-4">Open playground</Link>
          </div>
        </div>
      )}
    </header>
  );
}
