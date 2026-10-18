// No session cookie -> /login before any app screen renders. An expired or revoked session still has a
// cookie; lib/api.ts redirects on the backend's 401 for that case.
import { NextResponse, type NextRequest } from "next/server";

const SESSION_COOKIE = "cercania_session"; // same as lib/api-shared.ts

export function proxy(request: NextRequest) {
  if (request.cookies.has(SESSION_COOKIE)) return NextResponse.next();
  const url = new URL("/login", request.url);
  url.searchParams.set("mode", "login");
  url.searchParams.set("next", request.nextUrl.pathname + request.nextUrl.search);
  return NextResponse.redirect(url);
}

export const config = {
  matcher: ["/patients/:path*"],
};
