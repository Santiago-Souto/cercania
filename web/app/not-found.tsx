import Link from "next/link";
import { SearchXIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Empty, EmptyContent, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";

export default function NotFound() {
  return (
    <div className="mx-auto flex min-h-dvh w-full max-w-[480px] items-center bg-background p-6">
      <Empty>
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <SearchXIcon />
          </EmptyMedia>
          <EmptyTitle>No encontramos esta página</EmptyTitle>
        </EmptyHeader>
        <EmptyContent>
          <Button asChild size="xl">
            <Link href="/patients">Ir a mis pacientes</Link>
          </Button>
        </EmptyContent>
      </Empty>
    </div>
  );
}
