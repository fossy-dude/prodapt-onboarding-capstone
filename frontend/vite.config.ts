import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_");
  const backendOrigin = new URL(env.VITE_API_BASE_URL).origin;

  return {
    plugins: [react()],
    resolve: {
      alias: {
        "@": fileURLToPath(new URL("./src", import.meta.url)),
        "@app": fileURLToPath(new URL("./src/app", import.meta.url)),
        "@features": fileURLToPath(new URL("./src/features", import.meta.url)),
        "@entities": fileURLToPath(new URL("./src/entities", import.meta.url)),
        "@shared": fileURLToPath(new URL("./src/shared", import.meta.url)),
        "@routes": fileURLToPath(new URL("./src/routes", import.meta.url)),
      },
    },
    server: {
      port: 3000,
      open: true,
      proxy: {
        "/api/chat": {
          target: backendOrigin,
          changeOrigin: true,
        },
      },
    },
    build: {
      target: "es2020",
      outDir: "dist",
      sourcemap: true,
    },
  };
});
