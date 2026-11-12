import type { Metadata } from "next";
import { LegalPage } from "../legal/legal-content";

export const metadata: Metadata = { title: "Terms of Service" };

export default function TermsPage() {
  return (
    <LegalPage
      title="Terms of Service"
      updated="November 2026"
      sections={[
        { heading: "Service use", body: "SimAPI provides hosted checks for robotics and other engineering datasets. Submit data you are authorized to use and respect the limit of 10,000 samples per validation request. Do not submit unlawful material, overload the service, or attempt unauthorized access." },
        { heading: "Availability", body: "The public service is free while in beta and is provided as available, without warranties of accuracy or fitness for a particular purpose. Features and limits may change; any future paid offering will require separate acceptance. It has no published uptime guarantee, paid service agreement, or enterprise deployment plan." },
        { heading: "Validation results", body: "Reports describe the checks that ran on the supplied data and settings. They support engineering review; they do not certify hardware, prove policy performance, or guarantee safe execution." },
        { heading: "Responsibility and contact", body: "You remain responsible for reviewing results and deciding how to use your data. To the extent permitted by applicable law, the maintainer is not liable for losses from reliance on reports or service interruptions. These terms do not exclude rights that cannot legally be excluded. Contact the maintainer at https://github.com/TaxCollector23/simAPI/issues; never post confidential data in public issues." },
        { heading: "Repairs", body: "Repair previews propose data changes. Review the changes, preserve your original records, and validate any repaired copy before using it." },
      ]}
    />
  );
}
