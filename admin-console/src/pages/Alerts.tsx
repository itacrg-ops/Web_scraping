import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert as MuiAlert, Box, Button, Checkbox, Chip, FormControlLabel, IconButton, Paper, Switch, Table,
  TableBody, TableCell, TableContainer, TableHead, TableRow, Tooltip, Typography,
} from "@mui/material";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import {
  downloadDataset, getLabelStats, listAlerts, listMyLabels,
  type Alert, type AlertDeleteResult, type CaseLabelSummary, type LabelStats,
} from "../api";
import CaseDrawer from "../components/CaseDrawer";
import DeleteAlertsDialog from "../components/DeleteAlertsDialog";

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

// Stesso soggetto (stessa regola dell'API, registry_lookup.same_subject): stesso CF/P.IVA
// se entrambi lo hanno — omonimi con CF diversi restano distinti — altrimenti stesso tipo
// e stesso nome normalizzato ("ACME S.r.l." = "Acme srl").
const cleanId = (v?: string | null) => (v ?? "").toUpperCase().replace(/[^A-Z0-9]/g, "");
function sameSubject(a: Alert, b: Alert): boolean {
  const ca = cleanId(a.cf_piva), cb = cleanId(b.cf_piva);
  if (ca && cb) return ca === cb;
  return (a.tipo_soggetto ?? "persona_giuridica") === (b.tipo_soggetto ?? "persona_giuridica")
    && a.subject_key === b.subject_key;
}

type RowProps = {
  a: Alert; label?: CaseLabelSummary; dup: number; selected: boolean;
  onOpen: () => void; onSelect: (on: boolean) => void;
};

function AlertRow({ a, label, dup, selected, onOpen, onSelect }: RowProps) {
  const er = a.entity_resolution;
  const [esito, esitoColor] = ESITO[a.disposition] ?? [a.disposition, "default"];
  const [svi, sviColor] = SVI[a.svi_status ?? ""] ?? ["—", "default"];
  return (
    <TableRow hover onClick={onOpen} selected={selected} sx={{ cursor: "pointer" }}>
      <TableCell padding="checkbox" onClick={(ev) => ev.stopPropagation()}>
        <Checkbox size="small" checked={selected} onChange={(ev) => onSelect(ev.target.checked)}
          inputProps={{ "aria-label": `seleziona ${a.subject}` }} />
      </TableCell>
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
            <Typography variant="body2">
              {a.subject}
              {dup > 1 && (
                <Tooltip describeChild title={`${dup} alert per questo soggetto: possibili duplicati`}>
                  <Chip size="small" color="warning" variant="outlined" label={`×${dup}`}
                    sx={{ ml: 0.75, height: 18, fontSize: 11 }} />
                </Tooltip>
              )}
            </Typography>
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
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [onlyDup, setOnlyDup] = useState(false);
  const [toDelete, setToDelete] = useState<Alert[]>([]);
  const [deleted, setDeleted] = useState<AlertDeleteResult | null>(null);

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

  // Alert dello stesso soggetto (compreso sé stesso): il chip ×N e il filtro dei duplicati.
  const dups = useMemo(() => {
    const m: Record<string, number> = {};
    rows.forEach((a) => { m[a.id] = rows.filter((b) => sameSubject(a, b)).length; });
    return m;
  }, [rows]);
  const dupCount = (a: Alert) => dups[a.id] ?? 1;
  const visible = useMemo(() => (onlyDup
    ? rows.filter((a) => dupCount(a) > 1).sort((x, y) => x.subject_key.localeCompare(y.subject_key))
    : rows), [rows, onlyDup, dups]);   // eslint-disable-line react-hooks/exhaustive-deps
  const nDup = rows.filter((a) => dupCount(a) > 1).length;

  const select = (id: string, on: boolean) => setSelected((prev) => {
    const next = new Set(prev);
    on ? next.add(id) : next.delete(id);
    return next;
  });
  // Per ogni soggetto con più alert ne tiene uno — il più recente già nel dataset
  // (affidabile), altrimenti il più recente etichettato, altrimenti il più recente — e
  // seleziona gli altri. La finestra di conferma mostra cosa si perde.
  const selectDuplicates = () => {
    const rank = (a: Alert) => (labels[a.id]?.affidabile ? 0 : labels[a.id] ? 1 : 2);
    const order = [...rows].sort((x, y) => rank(x) - rank(y));   // stabile: resta dal più recente
    const kept: Alert[] = [];
    const next = new Set<string>();
    order.forEach((a) => (kept.some((k) => sameSubject(a, k)) ? next.add(a.id) : kept.push(a)));
    setSelected(next);
  };
  const allVisibleSelected = visible.length > 0 && visible.every((a) => selected.has(a.id));

  const onDeleted = (res: AlertDeleteResult, ids: string[]) => {
    const gone = new Set(ids);
    setRows((prev) => prev.filter((a) => !gone.has(a.id)));
    setLabels((prev) => Object.fromEntries(Object.entries(prev).filter(([id]) => !gone.has(id))));
    setSelected((prev) => new Set([...prev].filter((id) => !gone.has(id))));
    setToDelete([]);
    setOpen(null);
    setDeleted(res);
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
      {deleted && (
        <MuiAlert severity="success" sx={{ mt: 2 }} onClose={() => setDeleted(null)}>
          {deleted.eliminati === 1 ? "Eliminato 1 caso" : `Eliminati ${deleted.eliminati} casi`}
          {deleted.etichette_eliminate > 0 && ` (con ${deleted.etichette_eliminate} etichett${deleted.etichette_eliminate === 1 ? "a" : "e"})`}.
          {deleted.in_svi.length > 0 && (
            <> Restano aperti in SAS VI, da chiudere là: {deleted.in_svi.map((x) => x.svi_alert_id).join(", ")}.</>
          )}
        </MuiAlert>
      )}
      <Box sx={{ display: "flex", alignItems: "center", gap: 1.5, flexWrap: "wrap", mt: 2 }}>
        <FormControlLabel sx={{ mr: 0 }} label={`Solo soggetti con più alert (${nDup})`}
          control={<Switch size="small" checked={onlyDup}
            onChange={(e) => { setOnlyDup(e.target.checked); setOpen(null); }} />} />
        {nDup > 0 && (
          <Tooltip describeChild title="Per ogni soggetto tiene un alert (quello già nel dataset, altrimenti il più recente) e seleziona gli altri">
            <Button size="small" onClick={selectDuplicates}>Seleziona i duplicati</Button>
          </Tooltip>
        )}
        <Box sx={{ flex: 1 }} />
        {selected.size > 0 && (
          <>
            <Typography variant="body2">{selected.size} selezionat{selected.size === 1 ? "o" : "i"}</Typography>
            <Button size="small" onClick={() => setSelected(new Set())}>Deseleziona</Button>
            <Button size="small" color="error" variant="outlined" startIcon={<DeleteOutlineIcon />}
              onClick={() => setToDelete(rows.filter((a) => selected.has(a.id)))}>
              Elimina…
            </Button>
          </>
        )}
      </Box>
      <TableContainer component={Paper} sx={{ mt: 1 }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell padding="checkbox">
                <Checkbox size="small" checked={allVisibleSelected}
                  indeterminate={!allVisibleSelected && visible.some((a) => selected.has(a.id))}
                  onChange={(e) => setSelected(e.target.checked ? new Set(visible.map((a) => a.id)) : new Set())}
                  inputProps={{ "aria-label": "seleziona tutti" }} />
              </TableCell>
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
            {visible.map((a, i) => (
              <AlertRow key={a.id} a={a} label={labels[a.id]} dup={dupCount(a)} selected={selected.has(a.id)}
                onOpen={() => setOpen(i)} onSelect={(on) => select(a.id, on)} />
            ))}
          </TableBody>
        </Table>
      </TableContainer>
      <CaseDrawer alerts={visible} index={open} onNavigate={setOpen} onSaved={onLabelSaved}
        onDelete={(a) => setToDelete([a])} />
      <DeleteAlertsDialog alerts={toDelete} labels={labels} onClose={() => setToDelete([])}
        onDeleted={onDeleted} />
    </div>
  );
}
