import Image from "next/image";

/** Official ChatGPT symbol, taken from chatgpt.com's SVG favicon. */
export function ChatGPTMark({ size = 18 }: { size?: number }) {
  return (
    <Image
      src="/chatgpt-logo.svg"
      alt=""
      aria-hidden="true"
      width={size}
      height={size}
      className="shrink-0"
    />
  );
}
