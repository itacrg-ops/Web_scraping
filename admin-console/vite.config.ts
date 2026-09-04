import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Server in ascolto su 0.0.0.0 per funzionare dentro il container Docker Desktop.
// `watch.usePolling`: il file-watching nativo (inotify) non è affidabile sui
// bind mount di Docker Desktop (macOS/Windows), quindi l'HMR non vedrebbe le
// modifiche. Il polling risolve (costo CPU accettabile in sviluppo).
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    watch: { usePolling: true, interval: 300 },
  },
  preview: { host: true, port: 5173 },
});
