import { useCallback, useEffect, useState } from "react";
import {
  Alert as MuiAlert, Box, Button, Chip, Collapse, IconButton, Link, Paper, Table, TableBody,
  TableCell, TableContainer, TableHead, TableRow, Typography,
} from "@mui/material";
import KeyboardArrowDownIcon from "@mui/icons-material/KeyboardArrowDown";
import KeyboardArrowUpIcon from "@mui/icons-material/KeyboardArrowUp";
import {
  downloadDataset, getLabelStats, listAlerts, listMyLabels,
  type Alert, type CaseLabelSummary, type LabelStats,
} from "../api";
import CaseLabelPanel from "../components/CaseLabelPanel";

const erColor = (s?: string): "success" | "warning" | "default" =>
  s === "resolved" ? "success" : s === "unresolved" ? "default" : "warning";

// Persona fisica (PF) vs persona giuridica (PG): etichetta compatta col titolo esteso.
const tipoLabel = (t?: string) => (t === "persona_fisica" ? "PF" : "PG");
const tipoTitle = (t?: string) => (t === "persona_fisica" ? "persona fisica" : "persona giuridica");

function ResolutionDetail({ a }: { a: Alert }) {
  const er = a.entity_resolution;
  if (!er) return null;
  return (
    <Box sx={{ p: 2, pb: 1 }}>
      <Typography variant="subtitle2" gutterBottom>Entity Resolution</Typography>
      <Typography variant="body2">
        stato: <strong>{er.status}</strong> · metodo: {er.method} · confidence: {er.confidence.toFixed(2)}
        {er.identifier_valid !== undefined && <> · identificatore valido: {er.identifier_valid ? "sì" : "no"}</>}
      </Typography>
      {er.warnings && er.warnings.length > 0 && (
        <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
          {er.warnings.map((w, i) => (
            <li key={i}><Typography variant="caption" color="text.secondary">{w}</Typography></li>
          ))}
        </ul>
      )}
    </Box>
  );
}

function MotivazioneDetail({ a }: { a: Alert }) {
  const cats = a.fatf_categories ?? [];
  const drivers = a.drivers ?? [];
  if (cats.length === 0 && drivers.length === 0) return null;
  return (
    <Box sx={{ p: 2, pb: 1 }}>
      <Typography variant="subtitle2" gutterBottom>Motivazione (AMI {a.ami_score})</Typography>
      {cats.length > 0 && (
        <Box sx={{ display: "flex", gap: 0.5, flexWrap: "wrap", mb: 1 }}>
          {cats.map((c) => <Chip key={c} size="small" label={c} color="warning" variant="outlined" />)}
        </Box>
      )}
      {drivers.length > 0 && (
        <ul style={{ margin: 0, paddingLeft: 18 }}>
          {drivers.map((d, i) => (
            <li key={i}><Typography variant="caption" color="text.secondary">{d}</Typography></li>
          ))}
        </ul>
      )}
    </Box>
  );
}

function EvidenceDetail({ a }: { a: Alert }) {
  const ev = a.evidence ?? [];
  if (ev.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary" sx={{ p: 2 }}>
        Nessuna evidenza ancorata (es. gate Entity Resolution non superato, o fetch bloccato/senza contenuto).
      </Typography>
    );
  }
  return (
    <Box sx={{ p: 2 }}>
      <Typography variant="subtitle2" gutterBottom>Evidenze ({ev.length})</Typography>
      {ev.map((e, i) => (
        <Paper key={i} variant="outlined" sx={{ p: 1.5, mb: 1 }}>
          <Box sx={{ display: "flex", alignItems: "center", gap: 1, flexWrap: "wrap" }}>
            <Typography variant="body2">
              <strong>{e.testata || "—"}</strong>{e.data ? ` · ${e.data}` : ""}
              {e.url && <> · <Link href={e.url} target="_blank" rel="noreferrer">fonte</Link></>}
            </Typography>
            {e.fonte_credibilita && (
              <Chip size="small" variant="outlined" label={`credibilità: ${e.fonte_credibilita}`}
                color={e.fonte_credibilita === "alta" ? "success"
                  : e.fonte_credibilita === "media" ? "warning" : "default"} />
            )}
          </Box>
          {e.title && <Typography variant="body2">{e.title}</Typography>}
          {e.snippet && (
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, fontStyle: "italic" }}>
              “{e.snippet}”
            </Typography>
          )}
          <Typography variant="caption" color="text.secondary" component="div" sx={{ mt: 0.5 }}>
            hash: <code>{e.content_hash || "—"}</code> · fetch: {e.fetch_ts || "—"}
            {e.warc_key && <> · WARC: <code>{e.warc_key}</code></>}
          </Typography>
        </Paper>
      ))}
    </Box>
  );
}

const plural = (k: number, one: string, many: string) => `${k} ${k === 1 ? one : many}`;

// Avanzamento del dataset di valutazione + export. La distribuzione per esito del
// sistema rende visibile il bias di selezione (solo escalation = niente falsi negativi).
function DatasetBar({ stats }: { stats: LabelStats }) {
  const [error, setError] = useState<string | null>(null);
  const soloEscalation = stats.etichettati >= 10
    && (stats.per_disposition.ESCALATION_I_LIVELLO ?? 0) === stats.etichettati;
  const perEsito = Object.entries(stats.per_disposition).map(([d, n]) => `${d} ${n}`).join(" · ");
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

type RowProps = { a: Alert; label?: CaseLabelSummary; onLabelSaved: (s: CaseLabelSummary) => void };

function AlertRow({ a, label, onLabelSaved }: RowProps) {
  const [open, setOpen] = useState(false);
  const evCount = a.evidence?.length ?? 0;
  return (
    <>
      <TableRow>
        <TableCell padding="checkbox">
          <IconButton size="small" onClick={() => setOpen(!open)} aria-label="dettagli">
            {open ? <KeyboardArrowUpIcon /> : <KeyboardArrowDownIcon />}
          </IconButton>
        </TableCell>
        <TableCell>
          <Box sx={{ display: "flex", alignItems: "center", gap: 0.75 }}>
            <Chip size="small" variant="outlined" label={tipoLabel(a.tipo_soggetto)}
              title={tipoTitle(a.tipo_soggetto)}
              color={a.tipo_soggetto === "persona_fisica" ? "info" : "default"} />
            {a.subject}
          </Box>
        </TableCell>
        <TableCell>{a.cf_piva ?? "—"}</TableCell>
        <TableCell>{a.cup.join(", ")}</TableCell>
        <TableCell align="right">{a.ami_score}</TableCell>
        <TableCell>
          <Chip size="small" label={a.risk_level}
            color={a.risk_level === "ALTO" ? "error" : a.risk_level === "BASSO" ? "success" : "warning"} />
        </TableCell>
        <TableCell>
          {a.entity_resolution ? (
            <Box sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
              <Chip size="small" label={a.entity_resolution.status}
                color={erColor(a.entity_resolution.status)} />
              <Typography variant="caption" color="text.secondary">
                {a.entity_resolution.method} ({a.entity_resolution.confidence.toFixed(2)})
              </Typography>
            </Box>
          ) : "—"}
        </TableCell>
        <TableCell>{a.disposition}</TableCell>
        <TableCell align="right">{evCount}</TableCell>
        <TableCell>
          {a.svi_status === "failed" ? (
            <Chip size="small" color="error" label="pubblicazione fallita" title={a.svi_error ?? undefined} />
          ) : a.svi_status === "pending" ? (
            <Chip size="small" color="warning" label="in pubblicazione" />
          ) : (a.svi_alert_id ?? "—")}
        </TableCell>
        <TableCell>
          {label ? (
            <Chip size="small" color={label.affidabile ? "success" : "default"}
              label={label.affidabile ? "affidabile" : "bozza"} />
          ) : "—"}
        </TableCell>
      </TableRow>
      <TableRow>
        <TableCell sx={{ py: 0 }} colSpan={11}>
          <Collapse in={open} timeout="auto" unmountOnExit>
            <MotivazioneDetail a={a} />
            <ResolutionDetail a={a} />
            <EvidenceDetail a={a} />
            <CaseLabelPanel a={a} onSaved={onLabelSaved} />
          </Collapse>
        </TableCell>
      </TableRow>
    </>
  );
}

export default function Alerts() {
  const [rows, setRows] = useState<Alert[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [labels, setLabels] = useState<Record<string, CaseLabelSummary>>({});
  const [stats, setStats] = useState<LabelStats | null>(null);

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
        Vista di monitoraggio. Espandi una riga per le <strong>evidenze ancorate</strong>
        (URL, snippet, hash, timestamp, WARC) e per <strong>etichettare il caso</strong> nel
        dataset di valutazione. La lavorazione investigativa avviene in
        <strong> SAS Visual Investigator</strong>.
      </Typography>
      {error && <MuiAlert severity="error" sx={{ my: 2 }}>{error}</MuiAlert>}
      {stats && <DatasetBar stats={stats} />}
      <TableContainer component={Paper} sx={{ mt: 2 }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell />
              <TableCell>Soggetto</TableCell>
              <TableCell>CF/P.IVA</TableCell>
              <TableCell>CUP</TableCell>
              <TableCell align="right">AMI</TableCell>
              <TableCell>Rischio</TableCell>
              <TableCell>Entity Resolution</TableCell>
              <TableCell>Disposizione</TableCell>
              <TableCell align="right">Evidenze</TableCell>
              <TableCell>SVI</TableCell>
              <TableCell>Etichetta</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((a) => (
              <AlertRow key={a.id} a={a} label={labels[a.id]} onLabelSaved={onLabelSaved} />
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </div>
  );
}
