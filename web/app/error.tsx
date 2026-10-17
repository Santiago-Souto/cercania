"use client";

import { TriangleAlertIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";

export default function ErrorScreen({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="mx-auto flex min-h-dvh w-full max-w-[480px] items-center bg-background p-6">
      <Empty role="alert">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <TriangleAlertIcon />
          </EmptyMedia>
          <EmptyTitle>Algo salió mal</EmptyTitle>
          <EmptyDescription>{error.message || "No pudimos cargar esta pantalla."}</EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          <Button size="xl" onClick={reset}>
            Intentar de nuevo
          </Button>
        </EmptyContent>
      </Empty>
    </div>
  );
}
