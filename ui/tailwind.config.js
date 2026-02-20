/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        glitch: {
          primary: '#6366f1',
          secondary: '#8b5cf6',
          accent: '#22d3ee',
        },
      },
    },
  },
  plugins: [require("daisyui")],
  daisyui: {
    themes: [
      {
        night: {
          ...require("daisyui/src/theming/themes")["night"],
          primary: "#6366f1",
          secondary: "#8b5cf6",
          accent: "#22d3ee",
        },
      },
      {
        winter: {
          ...require("daisyui/src/theming/themes")["winter"],
          primary: "#6366f1",
          secondary: "#8b5cf6",
          accent: "#0891b2",
        },
      },
    ],
    darkTheme: "night",
  },
}
