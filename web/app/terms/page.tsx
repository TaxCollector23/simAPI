import type { Metadata } from "next";
import { LegalPage } from "../legal/legal-content";

export const metadata: Metadata = { title: "Terms of Service" };

export default function TermsPage() {
  return (
    <LegalPage
      title="Terms of Service"
      updated="November 2026"
      sections={[
        { heading: "Service use", body: "SimAPI provides hosted checks for robotics and other engineering datasets. Submit data you are authorized to use and respect the request limits." },
        { heading: "Availability", body: "The public service is available for evaluation. It has no published uptime guarantee, paid service agreement, or enterprise deployment plan." },
        { heading: "Validation results", body: "Reports describe the checks that ran on the supplied data and settings. They support engineering review; they do not certify hardware, prove policy performance, or guarantee safe execution." },
        { heading: "Repairs", body: "Repair previews propose data changes. Review the changes, preserve your original records, and validate any repaired copy before using it." },
      ]}
    />
  );
}
