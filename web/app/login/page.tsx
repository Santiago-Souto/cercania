// Sign-up / login (artboard "SignIn"). Ticket: CIA-32.
import Link from "next/link";
import { redirect } from "next/navigation";
import { AppShell, Brand } from "@/components/app/shell";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { getSession } from "@/lib/api";
import { landingFor, safeNext } from "@/lib/landing";
import { LoginForm } from "./login-form";

export default async function LoginPage(props: PageProps<"/login">) {
  const { mode, next } = await props.searchParams;
  // The session cookie lasts SESSION_TTL_DAYS: a device that already logged in skips the form.
  // Checked against GET /me, not just the cookie, so a stale cookie cannot loop back here.
  const me = await getSession();
  if (me) redirect(landingFor(me.memberships, safeNext(typeof next === "string" ? next : undefined)));
  const isLogin = mode === "login";
  const nextParam = typeof next === "string" ? `&next=${encodeURIComponent(next)}` : "";

  return (
    <AppShell publicPage>
      <main className="flex flex-1 flex-col gap-7 px-6 py-8">
        <Brand />
        <section className="flex flex-col gap-2">
          <h1 className="text-[30px] leading-tight font-bold">{isLogin ? "Entrar" : "Crear cuenta"}</h1>
          <p className="text-ink-2">Te mandamos un código de 6 dígitos por SMS para entrar. Sin contraseñas.</p>
        </section>

        <Tabs value={isLogin ? "login" : "signup"}>
          <TabsList className="grid h-12 w-full grid-cols-2">
            <TabsTrigger value="signup" asChild className="text-base">
              <Link href={`/login?mode=signup${nextParam}`}>Crear cuenta</Link>
            </TabsTrigger>
            <TabsTrigger value="login" asChild className="text-base">
              <Link href={`/login?mode=login${nextParam}`}>Ya tengo cuenta</Link>
            </TabsTrigger>
          </TabsList>
        </Tabs>

        <LoginForm key={isLogin ? "login" : "signup"} mode={isLogin ? "login" : "signup"} next={typeof next === "string" ? next : undefined} />
      </main>
    </AppShell>
  );
}
