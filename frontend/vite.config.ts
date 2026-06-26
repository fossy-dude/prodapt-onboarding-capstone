import { defineConfig, loadEnv, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";
import type { IncomingMessage, ServerResponse } from "node:http";

type NodeHandler = (req: IncomingMessage, res: ServerResponse) => Promise<void>;

function copilotKitPlugin(backendChatUrl: string): Plugin {
  return {
    name: "copilotkit-runtime",
    configureServer(server) {
      let handler: NodeHandler | null = null;

      server.middlewares.use(async (req: IncomingMessage, res: ServerResponse, next: (err?: unknown) => void) => {
        if (!req.url?.startsWith("/api/chat")) {
          return next();
        }
        try {
          if (!handler) {
            const { CopilotRuntime, createCopilotRuntimeHandler } = await import("@copilotkit/runtime/v2");
            const { LangGraphHttpAgent } = await import("@copilotkit/runtime/langgraph");
            const { createCopilotNodeHandler } = await import("@copilotkit/runtime/v2/node");

            handler = createCopilotNodeHandler(
              createCopilotRuntimeHandler({
                runtime: new CopilotRuntime({
                  agents: ({ request }: { request: Request }) => ({
                    support_agent: new LangGraphHttpAgent({
                      url: backendChatUrl,
                      headers: {
                        authorization: request.headers.get("authorization") ?? "",
                        "x-chat-session-id": request.headers.get("x-chat-session-id") ?? "",
                      },
                    }),
                  }),
                }),
                basePath: "/api/chat",
                mode: "single-route",
              }),
            );
          }
          await handler(req, res);
        } catch (err) {
          next(err);
        }
      });
    },
  };
}

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_");
  const backendOrigin = new URL(env.VITE_API_BASE_URL).origin;

  return {
    plugins: [react(), copilotKitPlugin(`${backendOrigin}/api/chat`)],
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
    },
    build: {
      target: "es2020",
      outDir: "dist",
      sourcemap: true,
    },
  };
});
