"use client";

// Caregiver correction of a recorded report (CIA-50). One field per checklist item, prefilled with the
// current value; only changed items are sent and the backend creates a new version. People type the
// values: no model, no quote.
import { useState } from "react";
import { useRouter } from "next/navigation";
import { PencilIcon } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field, FieldLabel } from "@/components/ui/field";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { ClientApiError, correctReport } from "@/lib/client-api";
import { CHECKLIST_LABEL } from "@/lib/format";
import type { ChecklistItem, ReportItem } from "@/lib/types";

const ITEMS = Object.keys(CHECKLIST_LABEL) as ChecklistItem[];

export function CorrectionForm({ reportId, items }: { reportId: string; items: ReportItem[] }) {
  const router = useRouter();
  const current = Object.fromEntries(ITEMS.map((k) => [k, items.find((i) => i.item === k)?.value ?? ""]));
  const [open, setOpen] = useState(false);
  const [values, setValues] = useState<Record<string, string>>(current);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const changed = ITEMS.filter((k) => values[k].trim() !== current[k]);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await correctReport(
        reportId,
        changed.map((item) => ({ item, value: values[item].trim() })),
      );
      setOpen(false);
      router.replace(`?`); // back to the latest version, which is the new one
      router.refresh();
    } catch (e) {
      setError(e instanceof ClientApiError ? e.message : "No pudimos guardar la corrección. Probá de nuevo.");
    } finally {
      setSaving(false);
    }
  }

  if (!open) {
    return (
      <Button
        variant="outline"
        size="xl"
        className="rounded-2xl"
        onClick={() => {
          setValues(current);
          setError(null);
          setOpen(true);
        }}
      >
        <PencilIcon />
        Corregir
      </Button>
    );
  }

  return (
    <form
      className="flex flex-col gap-3 rounded-xl border bg-card p-4"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <p className="text-[13px] text-muted-foreground">
        Cambiá solo lo que haga falta. Vaciar un campo lo deja como “No mencionado”. Se crea una versión nueva y la
        anterior queda guardada.
      </p>
      {ITEMS.map((k) => (
        <Field key={k}>
          <FieldLabel htmlFor={`corr-${k}`}>{CHECKLIST_LABEL[k]}</FieldLabel>
          <Textarea
            id={`corr-${k}`}
            value={values[k]}
            onChange={(e) => setValues((v) => ({ ...v, [k]: e.target.value }))}
            disabled={saving}
            rows={1}
          />
        </Field>
      ))}
      {error && (
        <Alert variant="destructive" role="alert">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <div className="flex gap-2">
        <Button type="submit" size="xl" className="flex-1 rounded-2xl" disabled={saving || changed.length === 0}>
          {saving && <Spinner />}
          {saving ? "Guardando…" : "Guardar corrección"}
        </Button>
        <Button type="button" variant="outline" size="xl" className="w-auto rounded-2xl" disabled={saving} onClick={() => setOpen(false)}>
          Cancelar
        </Button>
      </div>
    </form>
  );
}
