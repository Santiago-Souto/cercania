// Sign-up / login (artboard "SignIn"). Ticket: CIA-32.
// Skeleton: submit calls POST /auth/signup or /auth/login in CIA-32. For now it links to the code screen.
import Link from "next/link";
import { AppShell, Brand } from "@/components/app/shell";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

export default async function LoginPage(props: PageProps<"/login">) {
  const { mode } = await props.searchParams;
  const isLogin = mode === "login";

  return (
    <AppShell>
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

        <form>
          <FieldGroup>
            {!isLogin && (
              <Field>
                <FieldLabel htmlFor="name">Nombre</FieldLabel>
                <Input id="name" autoComplete="name" placeholder="Ana Pérez" className="h-12 bg-card text-base" />
              </Field>
            )}
            {!isLogin && (
              <Field>
                <FieldLabel htmlFor="email">Email</FieldLabel>
                <Input id="email" type="email" autoComplete="email" placeholder="ana@ejemplo.com" className="h-12 bg-card text-base" />
              </Field>
            )}
            <Field>
              <FieldLabel htmlFor="phone">Celular</FieldLabel>
              <Input id="phone" type="tel" autoComplete="tel" placeholder="+598 9X XXX XXX" className="h-12 bg-card text-base" />
              <FieldDescription>Ahí te llega el código por SMS. Con este mismo número mandás los reportes por WhatsApp.</FieldDescription>
            </Field>
          </FieldGroup>
        </form>

        <div className="mt-auto flex flex-col gap-3">
          <Button asChild size="xl">
            <Link href="/login/code">Enviar código por SMS</Link>
          </Button>
          <p className="text-center text-[13px] text-muted-foreground">Al continuar aceptás recibir el código por SMS y mensajes de CercanIA por WhatsApp.</p>
        </div>
      </main>
    </AppShell>
  );
}
