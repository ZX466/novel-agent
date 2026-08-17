/**
 * Frontend API configuration — backend URL and derived endpoints.
 *
 * NEXT_PUBLIC_BACKEND_URL is injected at build time from .env.local.
 * Defaults to http://localhost:8000 for local development.
 */

function resolveBackendUrl(): string {
  const fromEnv = process.env.NEXT_PUBLIC_BACKEND_URL;
  if (fromEnv) return fromEnv.replace(/\/+$/, "");
  if (typeof window !== "undefined") {
    // Same-origin fallback when running behind the Next.js proxy.
    const { protocol, host } = window.location;
    return `${protocol}//${host}`;
  }
  return "http://localhost:8000";
}

export const backendUrl = resolveBackendUrl();

export const chatEndpoint = `${backendUrl}/v1/chat`;
