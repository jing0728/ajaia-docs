import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development, Vite serves the UI on :5173 and forwards /api to FastAPI.
// If the backend runs on another port: API_URL=http://localhost:8010 npm run dev
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": process.env.API_URL || "http://localhost:8000" },
  },
});
