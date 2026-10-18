// Sign-up / login (artboard "SignIn"). Ticket: CIA-32.
import Link from "next/link";
import { AppShell, Brand } from "@/components/app/shell";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { LoginForm } from "./login-form";

const NOTICES: Record<string, string> = {
  expired: "Para seguir, entrá con tu celular.",
  logged_out: "Cerraste sesión.",
};

export default async function LoginPage(props: PageProps<"/login">) {
  const { mode, notice: noticeKey } = await props.searchParams;
  const isLogin = mode === "login";
  const notice = typeof noticeKey === "string" ? NOTICES[noticeKey] : undefined;

  return (
    <AppShell anonymous>
      <main className="flex flex-1 flex-col gap-7 px-6 py-8">
        <Brand />
        <section className="flex flex-col gap-2">
          <h1 className="text-[30px] leading-tight font-bold">{isLogin ? "Entrar" : "Crear cuenta"}</h1>
          <p className="text-ink-2">Te mandamos un código de 6 dígitos por SMS para entrar. Sin contraseñas.</p>
        </section>

        <Tabs value={isLogin ? "login" : "signup"}>
          <TabsList className="grid h-12 w-full grid-cols-2">
            <TabsTrigger value="signup" asChild className="text-base">
              <Link href="/login">Crear cuenta</Link>
            </TabsTrigger>
            <TabsTrigger value="login" asChild className="text-base">
              <Link href="/login?mode=login">Ya tengo cuenta</Link>
            </TabsTrigger>
          </TabsList>
        </Tabs>

        <LoginForm key={isLogin ? "login" : "signup"} isLogin={isLogin} notice={notice} />
      </main>
    </AppShell>
  );
}
