import { NextRequest, NextResponse } from "next/server";

/**
 * CSP nonce strategy (R8 audit L5).
 *
 * App Router injects inline RSC bootstrap scripts, so a static CSP with only
 * host sources would break rendering. Per request we:
 *  1. generate a nonce and pass it to the app renderer via the `x-nonce`
 *     request header (the root layout stamps it onto inline scripts, and
 *     Next.js auto-nonces its own inline RSC scripts by reading the
 *     `Content-Security-Policy` request header below);
 *  2. hand the same nonce to nginx through the `X-CSP-Nonce` response header
 *     so the reverse proxy can emit the browser-facing CSP with the matching
 *     nonce (see deploy/nginx/app.conf).
 */
export function middleware(request: NextRequest) {
  const nonce = btoa(crypto.randomUUID());

  const csp = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}'`,
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "img-src 'self' data: blob:",
    "font-src 'self' data: https://fonts.gstatic.com",
    "connect-src 'self' https://fonts.googleapis.com https://fonts.gstatic.com",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "upgrade-insecure-requests",
  ].join("; ");

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("content-security-policy", csp);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("X-CSP-Nonce", nonce);
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
