import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // host: true so a phone on the same Wi-Fi can open the dev server
  server: { host: true, port: 5180, proxy: { "/api": "http://localhost:8000" } },
});
