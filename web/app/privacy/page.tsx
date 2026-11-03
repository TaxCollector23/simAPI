import type { Metadata } from "next";
import { LegalPage } from "../legal/legal-content";

export const metadata: Metadata = { title: "Privacy Policy" };

export default function PrivacyPage() {
  return (
    <LegalPage
      title="Privacy Policy"
      updated="November 2026"
      sections={[
        { heading: "Submitted data", body: "Validation sends the numeric records you submit to the hosted SimAPI API. ROS recordings and URDF files are decoded in the browser or CLI first; the extracted records are used for validation." },
        { heading: "Browser storage", body: "Saved profiles and validation history are stored in this browser. Clearing site storage removes them. Reports and profiles can be downloaded as files." },
        { heading: "Optional AI review", body: "The robotics playground runs deterministic checks with AI review disabled. When API or CLI callers enable AI review, statistics and selected sample rows may be sent to the configured model provider." },
        { heading: "Service logs", body: "The hosting platform may keep request metadata and operational logs. This service does not offer a published retention guarantee or a private deployment plan." },
        { heading: "Questions", body: "Use the GitHub repository to report product issues. Do not include private datasets, credentials, or personal information in public issues." },
      ]}
    />
  );
}
