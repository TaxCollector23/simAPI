import Image from "next/image";

/** Official Claude Spark symbol from Anthropic's media press kit. */
export function ClaudeSpark() {
  return (
    <Image
      src="/claude-spark-clay.svg"
      alt=""
      aria-hidden="true"
      width={18}
      height={18}
      className="shrink-0"
    />
  );
}
