// Login screens are logged out: their loading state must not mount the account bar (CIA-61).
import { AppShell, Brand } from "@/components/app/shell";
import { Spinner } from "@/components/ui/spinner";

export default function LoginLoading() {
  return (
    <AppShell publicPage>
      <div className="flex flex-col gap-4 p-5" aria-busy="true">
        <Brand />
        <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner /> Cargando…
        </p>
      </div>
    </AppShell>
  );
}
