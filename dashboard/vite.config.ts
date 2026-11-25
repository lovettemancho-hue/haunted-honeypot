import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// API calls use relative `/api` paths only. In production Caddy proxies /api
// to the Brain. No hostnames or secrets belong in this file.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist" },
});
