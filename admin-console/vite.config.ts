import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Server in ascolto su 0.0.0.0 per funzionare dentro il container Docker Desktop.
export default defineConfig({
  plugins: [react()],
  server: { host: true, port: 5173 },
  preview: { host: true, port: 5173 },
});
