import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Tauri expects a fixed port in dev; harmless in plain-browser dev.
  server: {
    port: 1420,
    strictPort: false,
  },
  build: {
    target: "es2022",
  },
});
