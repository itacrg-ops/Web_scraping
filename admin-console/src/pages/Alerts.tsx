import { useEffect, useState } from "react";
import {
  Alert as MuiAlert, Box, Chip, Collapse, IconButton, Link, Paper, Table, TableBody,
  TableCell, TableContainer, TableHead, TableRow, Typography,
} from "@mui/material";
import KeyboardArrowDownIcon from "@mui/icons-material/KeyboardArrowDown";
import KeyboardArrowUpIcon from "@mui/icons-material/KeyboardArrowUp";
import { listAlerts, type Alert } from "../api";

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
          <Typography variant="body2">
            <strong>{e.testata || "—"}</strong>{e.data ? ` · ${e.data}` : ""}
            {e.url && <> · <Link href={e.url} target="_blank" rel="noreferrer">fonte</Link></>}
          </Typography>
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

function AlertRow({ a }: { a: Alert }) {
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
        <TableCell>{a.svi_alert_id ?? "—"}</TableCell>
      </TableRow>
      <TableRow>
        <TableCell sx={{ py: 0 }} colSpan={10}>
          <Collapse in={open} timeout="auto" unmountOnExit>
            <ResolutionDetail a={a} />
            <EvidenceDetail a={a} />
          </Collapse>
        </TableCell>
      </TableRow>
    </>
  );
}

export default function Alerts() {
  const [rows, setRows] = useState<Alert[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listAlerts().then(setRows).catch((e) => setError(String(e)));
  }, []);

  return (
    <div>
      <Typography variant="h5" gutterBottom>Alert (sintesi)</Typography>
      <Typography variant="body2" color="text.secondary" gutterBottom>
        Vista di monitoraggio. Espandi una riga per le <strong>evidenze ancorate</strong>
        (URL, snippet, hash, timestamp, WARC). La lavorazione investigativa avviene in
        <strong> SAS Visual Investigator</strong>.
      </Typography>
      {error && <MuiAlert severity="error" sx={{ my: 2 }}>{error}</MuiAlert>}
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
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((a) => <AlertRow key={a.id} a={a} />)}
          </TableBody>
        </Table>
      </TableContainer>
    </div>
  );
}
