// Scheda del caso in un pannello laterale: largo quanto lo schermo (non quanto la
// tabella), con navigazione tra i casi e avviso se si esce con modifiche non salvate.
import { useCallback, useRef } from "react";
import { Box, Chip, Drawer, IconButton, Typography } from "@mui/material";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import CloseIcon from "@mui/icons-material/Close";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import type { Alert, CaseLabelSummary } from "../api";
import CaseLabelPanel from "./CaseLabelPanel";
import RoleChips from "./RoleChips";

type Props = {
  alerts: Alert[];
  index: number | null;                 // caso aperto (null = chiuso)
  onNavigate: (index: number | null) => void;
  onSaved: (s: CaseLabelSummary) => void;
  onDelete?: (a: Alert) => void;        // caso duplicato o errato
};

export default function CaseDrawer({ alerts, index, onNavigate, onSaved, onDelete }: Props) {
  const a = index !== null ? alerts[index] : undefined;
  const dirty = useRef(false);
  const onDirtyChange = useCallback((d: boolean) => { dirty.current = d; }, []);

  // Esce dal caso corrente (chiusura o altro caso) chiedendo conferma se non salvato.
  const go = (target: number | null) => {
    if (dirty.current && !window.confirm("L'etichetta di questo caso ha modifiche non salvate. Scartarle?")) {
      return;
    }
    dirty.current = false;
    onNavigate(target);
  };

  const last = index === null || index >= alerts.length - 1;
  return (
    <Drawer anchor="right" open={a !== undefined} onClose={() => go(null)}
      PaperProps={{ role: "dialog", "aria-label": "Scheda del caso",
                    sx: { width: { xs: "100%", sm: 640, md: 760 } } }}>
      {a && index !== null && (
        <Box sx={{ display: "flex", flexDirection: "column", height: "100%" }}>
          <Box sx={{ px: 2, pt: 1, pb: 1.5, borderBottom: 1, borderColor: "divider" }}>
            <Box sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
              <IconButton size="small" aria-label="caso precedente" disabled={index === 0}
                onClick={() => go(index - 1)}>
                <ChevronLeftIcon />
              </IconButton>
              <Typography variant="body2" color="text.secondary">
                Caso {index + 1} di {alerts.length}
              </Typography>
              <IconButton size="small" aria-label="caso successivo" disabled={last}
                onClick={() => go(index + 1)}>
                <ChevronRightIcon />
              </IconButton>
              <Box sx={{ flex: 1 }} />
              {onDelete && (
                <IconButton size="small" aria-label="elimina il caso" title="Elimina il caso (duplicato o errato)"
                  onClick={() => onDelete(a)}>
                  <DeleteOutlineIcon />
                </IconButton>
              )}
              <IconButton size="small" aria-label="chiudi la scheda" onClick={() => go(null)}>
                <CloseIcon />
              </IconButton>
            </Box>
            <Box sx={{ display: "flex", alignItems: "center", gap: 1, mt: 0.5 }}>
              <Chip size="small" variant="outlined"
                label={a.tipo_soggetto === "persona_fisica" ? "PF" : "PG"}
                title={a.tipo_soggetto === "persona_fisica" ? "persona fisica" : "persona giuridica"} />
              <Typography variant="h6" sx={{ wordBreak: "break-word", lineHeight: 1.3 }}>{a.subject}</Typography>
            </Box>
            <Typography variant="caption" color="text.secondary" component="div" sx={{ wordBreak: "break-word" }}>
              CF/P.IVA {a.cf_piva ?? "—"} · CUP {a.cup.length ? a.cup.join(", ") : "—"}
            </Typography>
            <RoleChips roles={a.roles} pep={a.pep} />
          </Box>
          <CaseLabelPanel key={a.id} a={a} onSaved={onSaved} onDirtyChange={onDirtyChange}
            onNext={last ? undefined : () => onNavigate(index + 1)} onClose={() => onNavigate(null)}
            onOpenCase={(id) => { const i = alerts.findIndex((x) => x.id === id); if (i >= 0) go(i); }}
            isListed={(id) => alerts.some((x) => x.id === id)} />
        </Box>
      )}
    </Drawer>
  );
}
