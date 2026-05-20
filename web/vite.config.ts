import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const buildStamp = new Date().toISOString().replace(/\D/g, "").slice(0, 14);

export default defineConfig({
  define: {
    __VIBELUTION_BUILD_ID__: JSON.stringify(buildStamp),
  },
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
});
