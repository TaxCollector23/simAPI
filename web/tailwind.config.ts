import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    container: {
      center: true,
      padding: "1.5rem",
      screens: { "2xl": "1200px" },
    },
    extend: {
      colors: {
        ink: {
          950: "#101619",
          900: "#171f22",
          850: "#1d2629",
          800: "#253035",
          700: "#2f3b40",
          600: "#3c494d",
        },
        line: "rgba(255,255,255,0.08)",
        accent: {
          cyan: "#d5a266",
          blue: "#d5a266",
          violet: "#d5a266",
        },
        pass: "#8db99e",
        warn: "#d5a266",
        fail: "#df8a80",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      borderRadius: {
        "2xl": "1rem",
        "3xl": "1.5rem",
      },
    },
  },
  plugins: [],
};

export default config;
