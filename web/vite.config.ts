import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the API runs on :8000; these paths are forwarded to it. In production the API serves the
// built app from the same origin, so no proxy is needed.
const API = ["/auth", "/public", "/problems", "/incidents", "/decisions", "/reports", "/readings", "/tasks",
  "/work-orders", "/reviews", "/review", "/policies", "/learned", "/facts", "/crew", "/whoami", "/how-it-works",
  "/agents"];

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: Object.fromEntries(API.map((p) => [p, "http://127.0.0.1:8000"])) },
});
