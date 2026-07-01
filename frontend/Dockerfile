# Runs the Vite DEV server (not a production build) — CopilotKit's chat proxy
# (frontend/vite.config.ts, copilotKitPlugin) is wired via Vite's `configureServer`
# middleware, which only exists in dev mode. `vite build` produces static files
# with no Node process, so the chat feature would have nothing to serve /api/chat.
FROM docker.io/library/node:20-slim

RUN groupadd --system --gid 999 nonroot \
 && useradd --system --gid 999 --uid 999 --create-home nonroot

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY --chown=nonroot:nonroot . .
RUN chown -R nonroot:nonroot /app

USER nonroot
EXPOSE 5173

# --no-open: vite.config.ts sets server.open=true for local dev convenience
# (launches the host browser); inside a container there is no browser to open,
# and on this WSL host it crashes trying to spawn powershell.exe.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173", "--no-open"]
