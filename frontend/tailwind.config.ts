import type { Config } from "tailwindcss";

export default {
  content: ["./app/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"] ,
  theme: {
    extend: {
      boxShadow: {
        glow: "0 0 0 1px rgba(255,255,255,0.06), 0 12px 40px rgba(0,0,0,0.45)",
      },
    },
  },
  plugins: [],
} satisfies Config;
