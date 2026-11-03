import Link from "next/link";
export const metadata = {
  title: "Pricing",
  description: "Try the hosted robotics validator.",
};
export default function PricingPage() {
  return (
    <div className="container-tight pb-24 pt-36">
      <div className="max-w-2xl">
        <h1 className="text-4xl font-medium">Free to try</h1>
        <p className="mt-6 text-lg leading-8">
          Use the hosted playground, CLI, or SDK to evaluate robotics data. No
          account is required.
        </p>
        <p className="mt-4 text-base leading-7">
          A validation request accepts up to 10,000 samples. Split larger
          datasets into complete episodes before submitting them.
        </p>
        <Link
          className="landing-button landing-button-primary mt-8"
          href="/play"
        >
          Try SimAPI
        </Link>
      </div>
    </div>
  );
}
