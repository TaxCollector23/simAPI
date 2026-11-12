export const site = {
  name: "SimAPI",
  domain: "simapilander.vercel.app",
  url: "https://simapilander.vercel.app",
  tagline: "Clear checks for robot recordings",
  description:
    "Check robot recordings against limits you choose and see what needs a closer look.",
  github: "https://github.com/TaxCollector23/simAPI",
  nav: [
    { label: "How it works", href: "/platform" },
    { label: "Docs", href: "/docs" },
  ],
  footerGroups: [
    { title: "Product", links: [
      { label: "How it works", href: "/platform" },
      { label: "Benchmarks", href: "/benchmark" },
      { label: "Use cases", href: "/use-cases" },
      { label: "Pricing", href: "/pricing" },
    ] },
    { title: "Developers", links: [
      { label: "Documentation", href: "/docs" },
      { label: "API reference", href: "/docs#api" },
      { label: "CLI guide", href: "https://github.com/TaxCollector23/simAPI/tree/main/sdk-node#cli" },
      { label: "GitHub", href: "https://github.com/TaxCollector23/simAPI" },
    ] },
    { title: "Legal", links: [
      { label: "Privacy", href: "/privacy" },
      { label: "Terms", href: "/terms" },
    ] },
  ],
} as const;
