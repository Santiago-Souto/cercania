// One-tap call to the patient's emergency number (CIA-51). A plain tel: link: nothing is called or
// sent automatically, and the fixed emergency text next to it stays as is (AGENTS.md 4.2, 7).
import { PhoneIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { EmergencyContact } from "@/lib/types";

export const DEFAULT_EMERGENCY_NUMBER = "911";

export function EmergencyCallButton({ contact, className }: { contact: EmergencyContact | null | undefined; className?: string }) {
  const href = `tel:${contact ? contact.phone : DEFAULT_EMERGENCY_NUMBER}`;
  const label = contact ? `Llamar a ${contact.name}` : `Llamar al ${DEFAULT_EMERGENCY_NUMBER}`;
  return (
    <Button asChild variant="danger" size="touch" className={className}>
      <a href={href}>
        <PhoneIcon />
        {label}
      </a>
    </Button>
  );
}
