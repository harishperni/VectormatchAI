import type { Config } from "tailwindcss";

export default {
  content: ["./app/**/*.{js,ts,jsx,tsx}", "./components/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0F172A",
        teal: "#0F766E",
        cloud: "#F8FAFC",
      },
      fontFamily: {
        heading: ["'Space Grotesk'", "sans-serif"],
        body: ["'Source Sans 3'", "sans-serif"],
      },
    },
  },
  plugins: [],
} satisfies Config;
