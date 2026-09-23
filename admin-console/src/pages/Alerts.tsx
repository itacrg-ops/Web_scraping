import { useCallback, useEffect, useState } from "react";
import {
  Alert as MuiAlert, Box, Button, Chip, IconButton, Paper, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, Typography,
} from "@mui/material";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import {
  downloadDataset, getLabelStats, listAlerts, listMyLabels,
  type Alert, type CaseLabelSummary, type LabelStats,
} from "../api";
import CaseDrawer from "../components/CaseDrawer";

type ChipColor = "default" | "success" | "warning" | "error" | "info";

const erColor = (s?: string): ChipColor =>
  s === "resolved" ? "success" : s === "unresolved" ? "default" : "warning";

// Etichette brevi (il valore completo è nel tooltip): la tabella deve entrare nella
// pagina anche su un portatile, senza scroll orizzontale.
const ESITO: Record<string, [string, ChipColor]> = {
  ESCALATION_I_LIVELLO: ["Escalation", "error"],
  AUTO_CHIUSO: ["Chiuso", "success"],
  ESITO_INCOMPLETO: ["Incompleto", "warning"],
  HITL_ENTITY_RESOLUTION: ["Da disambiguare", "info"],
};
const SVI: Record<string, [string, ChipColor]> = {
  published: ["pubblicato", "success"],
  failed: ["fallita", "error"],
  pending: ["in corso", "warning"],
  skipped: ["non pubblicato", "default"],
};

const plural = (k: number, one: string, many: string) => `${k} ${k === 1 ? one : many}`;
// Colonna nascosta sotto i 1200 px (resta visibile nella scheda del caso).
const WIDE_ONLY = { display: { xs: "none", lg: "table-cell" } } as const;

// Avanzamento del dataset di valutazione + export. La distribuzione per esito del
// sistema rende visibile il bias di selezione (solo escalation = niente falsi negativi).
function DatasetBar({ stats }: { stats: LabelStats }) {
  const [error, setError] = useState<string | null>(null);
  const soloEscalation = stats.etichettati >= 10
    && (stats.per_disposition.ESCALATION_I_LIVELLO ?? 0) === stats.etichettati;
  const perEsito = Object.entries(stats.per_disposition)
    .map(([d, n]) => `${ESITO[d]?.[0] ?? d} ${n}`).join(" · ");
  return (
    <Paper variant="outlined" sx={{ p: 1.5, mt: 2 }}>
      <Box sx={{ display: "flex", gap: 2, alignItems: "center", flexWrap: "wrap" }}>
        <Typography variant="body2" sx={{ flex: "1 1 320px" }}>
          <strong>Dataset di valutazione:</strong>{" "}
          {plural(stats.affidabili, "caso affidabile", "casi affidabili")} su{" "}
          {plural(stats.etichettati, "etichettato", "etichettati")} (obiettivo 100–200) ·{" "}
          {plural(stats.revisori, "revisore", "revisori")}
          {perEsito && <> · per esito del sistema: {perEsito}</>}
        </Typography>
        <Button size="small" variant="outlined"
          onClick={() => downloadDataset(true).catch((e) => setError(e instanceof Error ? e.message : String(e)))}>
          Esporta dataset (NDJSON)
        </Button>
      </Box>
      {soloEscalation && (
        <Typography variant="caption" color="warning.main" component="div" sx={{ mt: 0.5 }}>
          Stai etichettando solo escalation: aggiungi casi chiusi o incompleti, altrimenti non si
          possono misurare i falsi negativi.
        </Typography>
      )}
      {error && <MuiAlert severity="error" sx={{ mt: 1 }}>{error}</MuiAlert>}
    </Paper>
  );
}

type RowProps = { a: Alert; label?: CaseLabelSummary; onOpen: () => void };

function AlertRow({ a, label, onOpen }: RowProps) {
  const er = a.entity_resolution;
  const [esito, esitoColor] = ESITO[a.disposition] ?? [a.disposition, "default"];
  const [svi, sviColor] = SVI[a.svi_status ?? ""] ?? ["—", "default"];
  return (
    <TableRow hover onClick={onOpen} sx={{ cursor: "pointer" }}>
      <TableCell padding="checkbox">
        <IconButton size="small" aria-label="apri il caso"
          onClick={(ev) => { ev.stopPropagation(); onOpen(); }}>
          <ChevronRightIcon />
        </IconButton>
      </TableCell>
      <TableCell>
        <Box sx={{ display: "flex", alignItems: "center", gap: 0.75 }}>
          <Chip size="small" variant="outlined" label={a.tipo_soggetto === "persona_fisica" ? "PF" : "PG"}
            title={a.tipo_soggetto === "persona_fisica" ? "persona fisica" : "persona giuridica"}
            color={a.tipo_soggetto === "persona_fisica" ? "info" : "default"} />
          <Box>
            <Typography variant="body2">{a.subject}</Typography>
            <Typography variant="caption" color="text.secondary">{a.cf_piva ?? "—"}</Typography>
          </Box>
        </Box>
      </TableCell>
      <TableCell sx={WIDE_ONLY}>{a.cup.join(", ") || "—"}</TableCell>
      <TableCell align="right">{a.ami_score}</TableCell>
      <TableCell>
        <Chip size="small" label={a.risk_level}
          color={a.risk_level === "ALTO" ? "error" : a.risk_level === "BASSO" ? "success" : "warning"} />
      </TableCell>
      <TableCell>
        {er ? (
          <Chip size="small" label={er.status} color={erColor(er.status)}
            title={`${er.method} (confidenza ${er.confidence.toFixed(2)})`} />
        ) : "—"}
      </TableCell>
      <TableCell>
        <Chip size="small" variant="outlined" label={esito} color={esitoColor} title={a.disposition} />
      </TableCell>
      <TableCell align="right">{a.evidence?.length ?? 0}</TableCell>
      <TableCell>
        <Chip size="small" variant="outlined" label={svi} color={sviColor}
          title={a.svi_status === "failed" ? (a.svi_error ?? undefined) : (a.svi_alert_id ?? undefined)} />
      </TableCell>
      <TableCell>
        {label ? (
          <Chip size="small" color={label.affidabile ? "success" : "default"}
            label={label.affidabile ? "affidabile" : "bozza"} />
        ) : "—"}
      </TableCell>
    </TableRow>
  );
}

export default function Alerts() {
  const [rows, setRows] = useState<Alert[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [labels, setLabels] = useState<Record<string, CaseLabelSummary>>({});
  const [stats, setStats] = useState<LabelStats | null>(null);
  const [open, setOpen] = useState<number | null>(null);

  const refreshStats = useCallback(() => {
    getLabelStats().then(setStats).catch(() => setStats(null));
  }, []);

  useEffect(() => {
    listAlerts().then(setRows).catch((e) => setError(String(e)));
    listMyLabels()
      .then((ls) => setLabels(Object.fromEntries(ls.map((l) => [l.alert_id, l]))))
      .catch(() => setLabels({}));
    refreshStats();
  }, [refreshStats]);

  const onLabelSaved = (s: CaseLabelSummary) => {
    setLabels((prev) => ({ ...prev, [s.alert_id]: s }));
    refreshStats();
  };

  return (
    <div>
      <Typography variant="h5" gutterBottom>Alert (sintesi)</Typography>
      <Typography variant="body2" color="text.secondary" gutterBottom>
        Vista di monitoraggio. Clicca un caso per aprire la scheda: esito del sistema,
        <strong> articoli con le evidenze</strong> (URL, snippet, hash, WARC) ed
        <strong> etichettatura</strong> per il dataset di valutazione. La lavorazione
        investigativa avviene in <strong>SAS Visual Investigator</strong>.
      </Typography>
      {error && <MuiAlert severity="error" sx={{ my: 2 }}>{error}</MuiAlert>}
      {stats && <DatasetBar stats={stats} />}
      <TableContainer component={Paper} sx={{ mt: 2 }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell />
              <TableCell>Soggetto</TableCell>
              <TableCell sx={WIDE_ONLY}>CUP</TableCell>
              <TableCell align="right">AMI</TableCell>
              <TableCell>Rischio</TableCell>
              <TableCell>Entity Resolution</TableCell>
              <TableCell>Esito</TableCell>
              <TableCell align="right">Articoli</TableCell>
              <TableCell>SVI</TableCell>
              <TableCell>Etichetta</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((a, i) => (
              <AlertRow key={a.id} a={a} label={labels[a.id]} onOpen={() => setOpen(i)} />
            ))}
          </TableBody>
        </Table>
      </TableContainer>
      <CaseDrawer alerts={rows} index={open} onNavigate={setOpen} onSaved={onLabelSaved} />
    </div>
  );
}
