// App chrome shared by every screen, composed only of shadcn primitives.
// Kept as one file because the same layout repeats on all 13 screens (docs/design/DESIGN.md).
import Link from "next/link";
import type { Route } from "next";
import { BellIcon, ChevronLeftIcon, HouseIcon, MessageCircleIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { USE_FAKE } from "@/lib/api";
import { cn } from "@/lib/utils";

/** Centered 480px column on desktop, full width on phones. */
export function AppShell({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("mx-auto flex min-h-dvh w-full max-w-[480px] flex-col bg-background sm:border-x", className)}>
      {USE_FAKE && (
        <Badge variant="warning" className="w-full justify-center rounded-none">
          Datos de prueba ficticios
        </Badge>
      )}
      {children}
    </div>
  );
}

/** The two overlapping dots: green forms the C that holds the amber dot (the person). Logo, so custom SVG. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <svg aria-hidden="true" viewBox="14 20 72 64" className={cn("h-7 w-auto", className)}>
      <circle cx="44" cy="52" r="26" className="fill-primary" />
      <circle cx="62" cy="52" r="17" className="fill-background" />
      <circle cx="62" cy="52" r="13" className="fill-brand-amber" />
    </svg>
  );
}

/** Logo lockup: mark + "Cercanía" with "ía" in amber (docs/design/DESIGN.md, Marca). */
export function Brand() {
  return (
    <span role="img" aria-label="Cercanía" className="inline-flex items-center gap-2">
      <BrandMark />
      <span aria-hidden="true" className="font-heading text-[22px] font-extrabold tracking-tight text-foreground">
        Cercan<span className="text-brand-amber-ink">ía</span>
      </span>
    </span>
  );
}

/** Back button + title, for screens below a tab. */
export function TopBar({ back, title, subtitle }: { back: string; title: string; subtitle?: string }) {
  return (
    <header className="flex items-center gap-2 px-4 pt-4 pb-3">
      <Button asChild variant="outline" size="icon-touch" aria-label="Volver">
        <Link href={back as Route}>
          <ChevronLeftIcon />
        </Link>
      </Button>
      <div className="flex flex-col">
        <h1 className="text-xl leading-tight font-bold">{title}</h1>
        {subtitle && <span className="text-[13px] text-muted-foreground">{subtitle}</span>}
      </div>
    </header>
  );
}

export function ScreenHeader({ title, subtitle, children }: { title: string; subtitle?: string; children?: React.ReactNode }) {
  return (
    <header className="flex items-start justify-between gap-3 px-5 pt-5 pb-3">
      <div className="flex flex-col gap-0.5">
        <h1 className="text-[26px] leading-tight font-bold">{title}</h1>
        {subtitle && <p className="text-sm text-muted-foreground">{subtitle}</p>}
      </div>
      {children}
    </header>
  );
}

/** Bottom bar for a single primary action. */
export function BottomBar({ children }: { children: React.ReactNode }) {
  return (
    <div className="sticky bottom-0 border-t bg-card px-4 pt-3 pb-[calc(16px+env(safe-area-inset-bottom))]">{children}</div>
  );
}

type Tab = "home" | "alerts" | "ask";

export function BottomNav({ patientId, active }: { patientId: string; active: Tab }) {
  const tabs = [
    { key: "home", href: `/patients/${patientId}`, label: "Inicio", Icon: HouseIcon },
    { key: "alerts", href: `/patients/${patientId}/alerts`, label: "Alertas", Icon: BellIcon },
    { key: "ask", href: `/patients/${patientId}/ask`, label: "Preguntar", Icon: MessageCircleIcon },
  ] as const;
  return (
    <nav aria-label="Principal" className="sticky bottom-0 grid grid-cols-3 border-t bg-card px-2 pt-2 pb-[calc(12px+env(safe-area-inset-bottom))]">
      {tabs.map(({ key, href, label, Icon }) => (
        <Button
          key={key}
          asChild
          variant="ghost"
          className={cn(
            "h-12 flex-col gap-0.5 text-xs font-normal text-muted-foreground",
            key === active && "font-bold text-primary",
          )}
        >
          <Link href={href as Route} aria-current={key === active ? "page" : undefined}>
            <Icon className="size-6" />
            {label}
          </Link>
        </Button>
      ))}
    </nav>
  );
}
