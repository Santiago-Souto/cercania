import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { AppShell, Brand } from "@/components/app/shell";

export default function Loading() {
  return (
    <AppShell>
      <div className="flex flex-col gap-4 p-5" aria-busy="true">
        <Brand />
        <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner /> Cargando…
        </p>
        <Skeleton className="h-32 rounded-xl" />
        <Skeleton className="h-24 rounded-xl" />
        <Skeleton className="h-40 rounded-xl" />
      </div>
    </AppShell>
  );
}
