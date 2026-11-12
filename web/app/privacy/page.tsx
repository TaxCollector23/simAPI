import type { Metadata } from "next";
import { LegalPage } from "../legal/legal-content";

export const metadata: Metadata = { title: "Privacy Policy" };

export default function PrivacyPage() {
  return (
    <LegalPage
      title="Privacy Policy"
      updated="November 2026"
      sections={[
        { heading: "Submitted data", body: "Validation sends the numeric records you submit to the hosted SimAPI API on Render to compute checks and return a verdict. Vercel hosts this website and forwards validation requests. ROS recordings and URDF files are decoded in the browser or CLI first; the extracted records are used for validation." },
        { heading: "Browser storage", body: "Saved profiles and validation history are stored in this browser. Clearing site storage removes them. Reports and profiles can be downloaded as files." },
        { heading: "Optional AI review", body: "The robotics playground runs deterministic checks with AI review disabled. When API or CLI callers enable AI review, statistics and selected sample rows may be sent to the configured model provider." },
        { heading: "Service logs", body: "The hosting platform may keep request metadata and operational logs. Validation reports and optional AI job results are held in server memory, with a default expiry of one hour and a maximum of 10,000 jobs; restarts or capacity limits can remove them earlier. Operators can change these limits. Hosting providers retain operational logs under their own policies; we do not promise a deletion deadline for those logs. Uploaded files are read to compute a verdict, and recordings are converted using temporary files that are cleaned after processing." },
        { heading: "Questions", body: "Contact the maintainer through https://github.com/TaxCollector23/simAPI/issues for policy questions or data requests. Do not include private datasets, credentials, or personal information in public issues." },
      ]}
    />
  );
}
