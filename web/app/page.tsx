import { redirect } from "next/navigation";
import { getSession } from "@/lib/api";
import { landingFor } from "@/lib/landing";

// A device that already logged in goes straight to its home; everyone else to the login.
export default async function Home() {
  const me = await getSession();
  redirect(me ? landingFor(me.memberships) : "/login");
}
