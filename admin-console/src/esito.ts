// Esito del sistema (disposition dell'alert) come etichetta e colore del chip.
export type ChipColor = "default" | "success" | "warning" | "error" | "info";

export const ESITO: Record<string, [string, ChipColor]> = {
  ESCALATION_I_LIVELLO: ["Escalation", "error"],
  AUTO_CHIUSO: ["Chiuso", "success"],
  ESITO_INCOMPLETO: ["Incompleto", "warning"],
  HITL_ENTITY_RESOLUTION: ["Da disambiguare", "info"],
};
