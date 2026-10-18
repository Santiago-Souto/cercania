"use client";
// Opening a patient clears its plain-message news on "Mis pacientes" (CIA-60); urgent rows (emergencies,
// help, red flags) stay unread so the watcher still announces them. The header badge catches up on
// the next inbox poll. Fire and forget: a failed call only leaves the dot until the next visit.
import { useEffect } from "react";
import { markPatientNotificationsRead } from "@/lib/client-api";

export function MarkPatientSeen({ patientId }: { patientId: string }) {
  useEffect(() => {
    markPatientNotificationsRead(patientId).catch(() => {});
  }, [patientId]);
  return null;
}
