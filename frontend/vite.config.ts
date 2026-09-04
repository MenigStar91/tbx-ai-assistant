import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// @vitejs/plugin-react was in the dependencies but never wired up: without a
// config file there is no Fast Refresh, and every edit costs a full reload.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
  },
});
