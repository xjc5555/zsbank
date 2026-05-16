import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{js,ts,jsx,tsx}", "./components/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        mint: {
          50: "#effdf8",
          100: "#d7fbef",
          200: "#b3f4df",
          300: "#78e9c7",
          400: "#36d1a8",
          500: "#12b892",
          600: "#079678",
        },
      },
      boxShadow: {
        soft: "0 20px 60px rgba(15, 118, 110, 0.12)",
      },
    },
  },
  plugins: [],
};

export default config;
