import type { Metadata } from "next";
import { DashboardApp } from "@/components/dashboard-app";

export const metadata: Metadata = {
  title: "Dashboard",
  description: "Review simulation validations and browser-local run history.",
  robots: { index: false, follow: false },
};

export default function DashboardPage() {
  return <DashboardApp />;
}
