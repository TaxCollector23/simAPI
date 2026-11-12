import Link from "next/link";
import { site } from "@/lib/site";
export const metadata = {
  title: "Documentation",
  description:
    "Robotics profiles, recording imports, CLI commands, and the hosted validation API.",
};
const command = `simapi profile import arm.urdf --name arm --output arm-profile.json
simapi import capture.mcap --topic /joint_states --profile arm --output run.json
simapi validate run.json --profile arm --no-ai --format github --report report.json --fail-on failed
simapi compare baseline.json report.json --fail-on regression
simapi repair run.json
simapi repair run.json --apply --output run.repaired.json`;
export default function DocsPage() {
  return (
    <div className="container-tight pb-24 pt-36">
      <div className="max-w-3xl">
        <h1 className="text-4xl font-medium">
          Robotics validation, from file to CI
        </h1>
        <p className="mt-6 text-lg leading-8">
          Load a run, choose your arm’s limits, inspect findings, then reuse the
          same profile in your own workflow.
        </p>
        <div className="mt-8 flex flex-wrap gap-4">
          <Link href="/play" className="landing-button landing-button-primary">
            Open playground
          </Link>
          <a
            href={`${site.github}#readme`}
            className="landing-button landing-button-secondary"
          >
            Full documentation
          </a>
        </div>
        <section className="mt-12">
          <h2 className="text-2xl font-medium">CLI workflow</h2>
          <pre className="mt-5 overflow-x-auto rounded-lg border border-white/10 p-5 font-mono text-sm leading-7">
            {command}
          </pre>
          <p className="mt-5 text-base leading-7">
            Import ROS 1 .bag or ROS 1/2 .mcap recordings containing JointState
            messages. Multiple channels require a topic selection. ROS 2 SQLite
            .db3 recordings must be exported to MCAP first.
          </p>
          <p className="mt-4 text-base leading-7">
            URDF limits keep declared units. Continuous joints have no imported
            position bound; acceleration limits must be entered manually. Named
            profiles are saved locally and can be exported as JSON.
          </p>
          <a
            className="mt-5 inline-block text-base underline"
            href={`${site.github}/tree/main/sdk-node#cli`}
          >
            CLI installation and all commands
          </a>
        </section>
        <section id="api" className="mt-12 scroll-mt-24">
          <h2 className="text-2xl font-medium">Hosted API</h2>
          <p className="mt-4 text-base leading-7">
            POST numeric records to <code>/api/v1/validate</code>. The report
            includes the verdict, per-sample evidence, episode summaries, and
            the settings used.
          </p>
          <pre className="mt-5 overflow-x-auto rounded-lg border border-white/10 p-5 font-mono text-sm leading-7">{`curl ${site.url}/api/v1/validate \\
  -H 'Content-Type: application/json' \\
  -d '{"simulation_type":"robotics","run_ai":false,"robotics_limits":{"joint_1_velocity":[-2,2]},"data":[{"time":0,"joint_1_velocity":0.5},{"time":0.1,"joint_1_velocity":0.5}]}'`}</pre>
          <h3 className="mt-8 text-xl font-medium">Validate a recording</h3>
          <p className="mt-4 text-base leading-7">
            Upload a ROS 2 SQLite bag (.db3), MCAP file, LeRobot parquet file,
            or a ZIP containing one rosbag2 bag or LeRobot dataset. Content is
            detected from the file bytes. The upload and expanded ZIP are each
            limited to 100 MB; converted recordings are limited to 10,000
            samples. Install the optional <code>robotics-data</code> server
            dependencies to enable these readers.
          </p>
          <pre className="mt-5 overflow-x-auto rounded-lg border border-white/10 p-5 font-mono text-sm leading-7">{`curl ${site.url}/api/v1/validate/recording \\
  -F 'file=@run.mcap' \\
  -F 'topic_hint=/joint_states' \\
  -F 'robotics_limits={"joint_1_position":[-1.57,1.57]}' \\
  -F 'conditions={}'`}</pre>
          <p className="mt-4 text-base leading-7">
            <code>topic_hint</code> selects matching JointState topics and
            defaults to <code>joint_states</code>. Both <code>robotics_limits</code>
            and <code>conditions</code> are JSON objects sent as multipart form
            fields. The response uses the standard robotics report and adds a
            <code> recording</code> object with the detected format, source
            filename, and converted sample count.
          </p>
          <p className="mt-5 text-base leading-7">
            Use <code>POST /api/v1/repair</code> with <code>data</code> to
            preview structural repairs. Set <code>apply: true</code> to receive
            a repaired copy. The service does not modify your source file.
          </p>
        </section>
        <section className="mt-12">
          <h2 className="text-2xl font-medium">Read the evidence</h2>
          <p className="mt-4 text-base leading-7">
            Findings identify the episode, sample, time, signal, observed value,
            and expected range. Derivatives are interval averages. Missing
            information is reported as unavailable. A passing report supports
            engineering review and does not certify hardware or a policy.
          </p>
        </section>
      </div>
    </div>
  );
}
