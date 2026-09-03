/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./templates/**/*.html", "./static/js/**/*.js"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#effaf5",
          100: "#d9f3e6",
          200: "#b5e6d0",
          300: "#84d2b3",
          400: "#4fb791",
          500: "#2d9c76",
          600: "#1f7d5f",
          700: "#1b644e",
          800: "#185040",
          900: "#144236",
        },
      },
      fontFamily: {
        sans: ["-apple-system", "BlinkMacSystemFont", "PingFang SC", "HarmonyOS Sans SC", "Noto Sans SC", "Segoe UI", "Roboto", "sans-serif"],
      },
      maxWidth: {
        app: "768px",
      },
      minHeight: {
        tap: "44px",
      },
    },
  },
  plugins: [],
};
