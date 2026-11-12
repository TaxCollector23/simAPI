import type { Metadata, Viewport } from "next";
import { Instrument_Serif, Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { site } from "@/lib/site";
import { Nav } from "@/components/nav";
import { Footer } from "@/components/footer";
import { FirebaseAnalytics } from "@/components/firebase-analytics";

const sans = Inter({ subsets: ["latin"], variable: "--font-sans", display: "swap" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono", display: "swap" });
const display = Instrument_Serif({ subsets: ["latin"], variable: "--font-display", weight: "400", display: "swap" });

export const metadata: Metadata = {
  metadataBase: new URL(site.url),
  title: {
    default: `${site.name}: ${site.tagline}`,
    template: `%s — ${site.name}`,
  },
  description: site.description,
  keywords: [
    "simulation validation",
    "CFD validation",
    "FEA validation",
    "physics validation API",
    "Physical AI simulation validation",
    "multiphysics",
    "robotics simulation validation",
    "ML dataset validation",
  ],
  authors: [{ name: "SimAPI" }],
  openGraph: {
    type: "website",
    url: site.url,
    title: `${site.name}: ${site.tagline}`,
    description: site.description,
    siteName: site.name,
  },
  twitter: {
    card: "summary_large_image",
    title: `${site.name}: ${site.tagline}`,
    description: site.description,
  },
  robots: { index: true, follow: true },
  alternates: { canonical: site.url },
  icons: { icon: "/icon.svg", shortcut: "/icon.svg" },
};

export const viewport: Viewport = {
  themeColor: "#f6f3ec",
  colorScheme: "dark",
};

const jsonLd = {
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  name: site.name,
  applicationCategory: "DeveloperApplication",
  operatingSystem: "Any",
  description: site.description,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable} ${display.variable} dark`}>
      <body className="min-h-screen font-sans">
        <FirebaseAnalytics />
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
        />
        <Nav />
        <main className="site-page">{children}</main>
        <Footer />
      </body>
    </html>
  );
}
