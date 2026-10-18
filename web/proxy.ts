// No session cookie -> /login before any app screen renders. An expired or revoked session still has a
// cookie; lib/api.ts redirects on the backend's 401 for that case, using the path passed on here.
import { NextResponse, type NextRequest } from "next/server";

const SESSION_COOKIE = "cercania_session"; // same as lib/api-shared.ts
const PATH_HEADER = "x-cercania-path"; // same as lib/api.ts

export function proxy(request: NextRequest) {
  const path = request.nextUrl.pathname + request.nextUrl.search;
  if (request.cookies.has(SESSION_COOKIE)) {
    // Server components cannot read the URL; lib/api.ts reads this to keep `next` on a 401.
    const headers = new Headers(request.headers);
    headers.set(PATH_HEADER, path);
    return NextResponse.next({ request: { headers } });
  }
  const url = new URL("/login", request.url);
  url.searchParams.set("mode", "login");
  url.searchParams.set("next", path);
  return NextResponse.redirect(url);
}

export const config = {
  matcher: ["/patients/:path*"],
};
