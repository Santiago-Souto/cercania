"use client";
// With cacheComponents, Next keeps visited routes mounted (hidden in <Activity>), so a form keeps its
// useState after you leave and come back. Keying the subtree on router.bfcacheId remounts it on every
// push/replace navigation (a Link click, router.push) and still restores it on browser back/forward.
// AppShell wraps every screen with it, so no form needs its own reset. CIA-45.

import { Fragment } from "react";
import { useRouter } from "next/navigation";

export function FreshOnEntry({ children }: { children: React.ReactNode }) {
  const { bfcacheId } = useRouter();
  return <Fragment key={bfcacheId}>{children}</Fragment>;
}
