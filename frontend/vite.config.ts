import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the API runs on its own port. Proxying /api through Vite puts
// both on one origin, which is what lets the httpOnly session cookie work
// without CORS or a token in JavaScript - the same arrangement nginx gives us
// in production.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_API_TARGET ?? "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
