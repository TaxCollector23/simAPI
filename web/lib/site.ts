export const site = {
  name: "SimAPI",
  domain: "simapilander.vercel.app",
  url: "https://simapilander.vercel.app",
  tagline: "Simulations you can trust",
  description:
    "Simulation checks for robot arms and Physical AI. Find bad samples before you use them.",
  github: "https://github.com/TaxCollector23/simAPI",
  nav: [
    { label: "Use cases", href: "/use-cases" },
    { label: "How it works", href: "/platform" },
    { label: "Test results", href: "/benchmark" },
    { label: "Docs", href: "/docs" },
  ],
  footerGroups: [
    { title: "Product", links: [
      { label: "Platform", href: "/platform" },
      { label: "Benchmarks", href: "/benchmark" },
      { label: "Pricing", href: "/pricing" },
      { label: "Dashboard", href: "/dashboard" },
      { label: "Changelog", href: "/changelog" },
      { label: "Status", href: "/status" },
    ] },
    { title: "Developers", links: [
      { label: "Documentation", href: "/docs" },
      { label: "API reference", href: "https://simapidocs.github.io" },
      { label: "GitHub", href: "https://github.com/TaxCollector23/simAPI" },
      { label: "npm", href: "https://www.npmjs.com/package/simapi-cli" },
    ] },
    { title: "Company", links: [
      { label: "Blog", href: "/blog" },
      { label: "FAQ", href: "/faq" },
      { label: "Roadmap", href: "/roadmap" },
      { label: "Security", href: "/security" },
      { label: "Privacy", href: "/privacy" },
      { label: "Terms", href: "/terms" },
    ] },
  ],
} as const;
