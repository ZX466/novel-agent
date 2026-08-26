# Frontend image — built on the Tencent Cloud server via docker compose.
# Multi-stage: build the Next.js standalone output, then run on a slim image.
# Uses output: "standalone" from next.config.mjs to minimize image size.

FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci || npm install

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# NEXT_PUBLIC_BACKEND_URL is NOT baked in at build time.
# The frontend uses relative paths (empty string default) so nginx proxies
# /v1/* to the backend. For local dev, set it in .env.local.
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=7421
RUN addgroup --system --gid 1001 nodejs && adduser --system --uid 1001 nextjs
COPY --from=builder /app/public ./public
# Standalone output includes a minimal server + node_modules — no full copy needed.
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
USER nextjs
EXPOSE 7421
CMD ["node", "server.js"]
