// Rivalutazione del dataset on demand: ripassa i casi etichettati nella versione attuale
// del sistema (articoli già salvati, nessuna nuova ricerca) e confronta gli errori prima
// e dopo. Stesso report di scripts/evaluate_labels.py, calcolato dall'API; riservato ai
// ruoli dell'export del dataset (contiene i nomi dei soggetti).
import { useCallback, useEffect, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import {
  Accordion, AccordionDetails, AccordionSummary, Alert as MuiAlert, Box, Button, Card, CardContent, Chip,
  FormControlLabel, LinearProgress, Link, List, ListItemButton, ListItemText, Switch, Table, TableBody,
  TableCell, TableHead, TableRow, Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import {
  getReplay, listReplays, startReplay,
  type EsitoCambiato, type EsitoValutato, type EvalReport, type Rate, type ReplayRun,
} from "../api";

const ESITO: Record<EsitoValutato, string> = { ESCALATION: "Escalation", CHIUSURA: "Chiusura", ALTRO: "Non deciso" };
const STATO: Record<ReplayRun["status"], [string, "info" | "success" | "error"]> = {
  running: ["in corso", "info"], completed: ["completata", "success"], failed: ["fallita", "error"],
};
const pct = (r?: number | null) => (r == null ? "n/d" : `${Math.round(r * 100)}%`);
const when = (iso: string) => new Date(iso).toLocaleString("it-IT", { dateStyle: "short", timeStyle: "short" });

// Misure del confronto: «meglio» se sale (accordo, precisione, richiamo) o se scende (errori).
type Measure = { group?: string; label: string; get: (r: EvalReport) => Rate | number; better: "up" | "down" };
const MEASURES: Measure[] = [
  { group: "Esito del caso", label: "accordo con i revisori", get: (r) => r.esito.accordo, better: "up" },
  { label: "falsi negativi (da escalation, chiusi)", get: (r) => r.esito.falsi_negativi, better: "down" },
  { label: "falsi positivi (da chiudere, in escalation)", get: (r) => r.esito.falsi_positivi, better: "down" },
  { label: "non decisi (esito incompleto)", get: (r) => r.esito.non_decisi_dal_sistema, better: "down" },
  { group: "Riconoscimento del soggetto (articoli)", label: "precisione", get: (r) => r.menzione.precisione,
    better: "up" },
  { label: "richiamo", get: (r) => r.menzione.richiamo, better: "up" },
  { group: "Categorie FATF", label: "precisione", get: (r) => r.categorie.micro.precisione, better: "up" },
  { label: "richiamo", get: (r) => r.categorie.micro.richiamo, better: "up" },
];

const valueOf = (v: Rate | number) => (typeof v === "number" ? v : v.rate);
const show = (v: Rate | number) =>
  typeof v === "number" ? String(v) : v.rate == null ? "n/d" : `${pct(v.rate)} (${v.k}/${v.n})`;

function trend(m: Measure, before: EvalReport, after: EvalReport): "success.main" | "error.main" | undefined {
  const b = valueOf(m.get(before));
  const a = valueOf(m.get(after));
  if (a == null || b == null || a === b) return undefined;
  return (a > b) === (m.better === "up") ? "success.main" : "error.main";
}

function caseLink(id: string | null | undefined, subject: string) {
  return id ? <Link component={RouterLink} to={`/alerts?caso=${id}`}>{subject}</Link> : <>{subject}</>;
}

function Changes({ title, items, color }: { title: string; items: EsitoCambiato[]; color?: string }) {
  if (!items.length) return null;
  return (
    <Box sx={{ mt: 1.5 }}>
      <Typography variant="subtitle2" color={color}>{title} ({items.length})</Typography>
      <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
        {items.map((c) => (
          <li key={`${c.alert_id}-${c.revisore}`}>
            <Typography variant="body2">
              {caseLink(c.alert_id, c.subject)}: {ESITO[c.prima]} → <strong>{ESITO[c.dopo]}</strong>
              {" "}(revisore: {ESITO[c.revisore]})
            </Typography>
            {c.motivo && <Typography variant="caption" color="text.secondary" component="div">{c.motivo}</Typography>}
          </li>
        ))}
      </Box>
    </Box>
  );
}

function Report({ run }: { run: ReplayRun }) {
  const rep = run.report!;
  const { prima: before, dopo: after } = rep;
  const count = (s: string) => rep.rivalutazione[s] ?? 0;
  const mins = run.finished_at
    ? Math.max(1, Math.round((+new Date(run.finished_at) - +new Date(run.created_at)) / 60000)) : null;
  const fn = after.esito.errori.filter((e) => e.sistema === "CHIUSURA");
  const fp = after.esito.errori.filter((e) => e.sistema === "ESCALATION");
  const cats = Array.from(new Set([...Object.keys(before.categorie.per_categoria),
                                   ...Object.keys(after.categorie.per_categoria)])).sort()
    .map((c) => ({ c, b: before.categorie.per_categoria[c], a: after.categorie.per_categoria[c] }))
    .filter(({ b, a }) => (b?.fp ?? 0) !== (a?.fp ?? 0) || (b?.fn ?? 0) !== (a?.fn ?? 0));
  if (after.casi === 0) {
    return (
      <MuiAlert severity="info" sx={{ mt: 2 }}>
        Rivalutazione del {when(run.created_at)}: nessun caso etichettato da rivalutare
        {run.solo_affidabili && " tra quelli affidabili (puoi includere i casi in bozza)"}.
      </MuiAlert>
    );
  }
  const download = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(rep, null, 2)], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `rivalutazione-${run.created_at.slice(0, 10)}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };
  return (
    <Box sx={{ mt: 2 }} aria-label="Report della rivalutazione" role="region">
      <Box sx={{ display: "flex", alignItems: "baseline", gap: 1, flexWrap: "wrap" }}>
        <Typography variant="subtitle1">Report del {when(run.created_at)}</Typography>
        <Typography variant="body2" color="text.secondary">
          {run.started_by_name && `avviata da ${run.started_by_name}`}{mins && ` · ${mins} min`}
          {!run.solo_affidabili && " · anche le bozze"}
        </Typography>
        <Box sx={{ flex: 1 }} />
        <Button size="small" onClick={download} title="Contiene i nomi dei soggetti: stesse cautele dell'export">
          Scarica JSON
        </Button>
      </Box>
      <Typography variant="body2" sx={{ mt: 0.5 }}>
        {count("ok")} casi rivalutati
        {count("non_rivalutabile") > 0 && ` · ${count("non_rivalutabile")} senza articoli salvati (invariati)`}
        {count("errore") > 0 && ` · ${count("errore")} in errore (invariati)`}
      </Typography>
      {after.casi < 30 && (
        <MuiAlert severity="info" sx={{ mt: 1 }}>
          Campione piccolo ({after.casi} casi): le percentuali sono solo indicative; conta soprattutto quali casi
          cambiano.
        </MuiAlert>
      )}

      <Table size="small" sx={{ mt: 1.5, tableLayout: "fixed" }} aria-label="Prima e dopo">
        <TableHead>
          <TableRow>
            <TableCell sx={{ width: "50%" }}>Misura</TableCell>
            <TableCell>Prima</TableCell>
            <TableCell>Dopo</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {MEASURES.map((m) => [
            m.group && (
              <TableRow key={`${m.group}-g`}>
                <TableCell colSpan={3} sx={{ fontWeight: 600, bgcolor: "action.hover" }}>{m.group}</TableCell>
              </TableRow>
            ),
            <TableRow key={`${m.group ?? ""}${m.label}`}>
              <TableCell>{m.label}</TableCell>
              <TableCell>{show(m.get(before))}</TableCell>
              <TableCell sx={{ color: trend(m, before, after), fontWeight: trend(m, before, after) ? 600 : undefined }}>
                {show(m.get(after))}
              </TableCell>
            </TableRow>,
          ])}
        </TableBody>
      </Table>

      <Changes title="Ora corretti" items={rep.cambiamenti.corretti} color="success.main" />
      <Changes title="Ora sbagliati" items={rep.cambiamenti.peggiorati} color="error.main" />
      <Changes title="Altri cambiamenti di esito" items={rep.cambiamenti.altri} />
      {!rep.cambiamenti.corretti.length && !rep.cambiamenti.peggiorati.length && !rep.cambiamenti.altri.length && (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>
          Nessun caso ha cambiato esito.
        </Typography>
      )}

      <Accordion disableGutters variant="outlined" sx={{ mt: 2 }}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography variant="subtitle2">
            Errori di esito con la versione attuale: {fn.length} falsi negativi, {fp.length} falsi positivi
          </Typography>
        </AccordionSummary>
        <AccordionDetails>
          {[["Falsi negativi (il revisore dice escalation)", fn], ["Falsi positivi (il revisore dice chiusura)", fp]]
            .map(([title, list]) => (list as typeof fn).length > 0 && (
              <Box key={title as string} sx={{ mb: 1 }}>
                <Typography variant="body2" sx={{ fontWeight: 600 }}>{title as string}</Typography>
                <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
                  {(list as typeof fn).map((e) => (
                    <li key={`${e.alert_id}-${e.revisore}`}>
                      <Typography variant="body2">
                        {caseLink(e.alert_id, e.subject)}
                        <Typography component="span" variant="caption" color="text.secondary">
                          {" "}· ruolo per il revisore: {e.ruolo ?? "—"} · categorie: {e.categorie.join(", ") || "—"}
                        </Typography>
                      </Typography>
                    </li>
                  ))}
                </Box>
              </Box>
            ))}
          {!fn.length && !fp.length && <Typography variant="body2">Nessuno.</Typography>}
        </AccordionDetails>
      </Accordion>

      <Accordion disableGutters variant="outlined">
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography variant="subtitle2">
            Riconoscimento del soggetto: {after.menzione.errori.length} articoli sbagliati
            {cats.length > 0 && ` · ${cats.length} categorie cambiate`}
          </Typography>
        </AccordionSummary>
        <AccordionDetails>
          <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
            {after.menzione.errori.slice(0, 20).map((e, i) => (
              <li key={i}>
                <Typography variant="body2" sx={{ wordBreak: "break-word" }}>
                  {caseLink(e.alert_id, e.subject)}: per il sistema {e.sistema ? "citato" : "non citato"}, per il
                  revisore {e.revisore === "si" ? "citato" : e.revisore.replace("_", " ")}
                  {e.url && <> · <Link href={e.url} target="_blank" rel="noreferrer">articolo</Link></>}
                </Typography>
              </li>
            ))}
          </Box>
          {after.menzione.errori.length > 20 && (
            <Typography variant="caption" color="text.secondary">
              … e altri {after.menzione.errori.length - 20} (tutti nel JSON)
            </Typography>
          )}
          {cats.length > 0 && (
            <>
              <Typography variant="body2" sx={{ fontWeight: 600, mt: 1 }}>Categorie cambiate (prima → dopo)</Typography>
              {cats.map(({ c, b, a }) => (
                <Typography key={c} variant="body2">
                  {c}: falsi positivi {b?.fp ?? 0} → {a?.fp ?? 0} · mancate {b?.fn ?? 0} → {a?.fn ?? 0}
                </Typography>
              ))}
            </>
          )}
        </AccordionDetails>
      </Accordion>
    </Box>
  );
}

function RunLine({ run }: { run: ReplayRun }) {
  const s = run.sintesi;
  if (run.status === "running") return <>in corso: {run.done} di {run.total || "?"} casi</>;
  if (run.status === "failed") return <>{run.error ?? "fallita"}</>;
  if (!s) return <>completata</>;
  return (
    <>
      {s.casi} casi · esito giusto {pct(s.accordo[0])} → {pct(s.accordo[1])} · {s.corretti} corretti,
      {" "}{s.peggiorati} peggiorati{!run.solo_affidabili && " · anche le bozze"}
    </>
  );
}

export default function ReplayPanel() {
  const [runs, setRuns] = useState<ReplayRun[] | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [drafts, setDrafts] = useState(false);
  const [starting, setStarting] = useState(false);
  const [running, setRunning] = useState<ReplayRun | null>(null);
  const [selected, setSelected] = useState<ReplayRun | null>(null);

  const open = useCallback((id: string) => {
    getReplay(id).then(setSelected).catch((e) => setError(String(e)));
  }, []);

  const refresh = useCallback(async (select?: string) => {
    try {
      const list = await listReplays();
      setRuns(list);
      setRunning(list.find((r) => r.status === "running") ?? null);
      const target = select ?? list.find((r) => r.status === "completed")?.id;
      if (target) open(target);
    } catch (e) {
      if (String(e).startsWith("Error: 403")) setForbidden(true);
      else setError(String(e));
    }
  }, [open]);

  useEffect(() => { refresh(); }, [refresh]);

  // Avanzamento della rivalutazione in corso; alla fine, il suo report.
  useEffect(() => {
    if (!running) return;
    const t = setInterval(async () => {
      const r = await getReplay(running.id).catch(() => null);
      if (!r) return;
      if (r.status === "running") {
        setRunning(r);
      } else {
        setRunning(null);
        refresh(r.id);
      }
    }, 3000);
    return () => clearInterval(t);
  }, [running?.id, refresh]);   // eslint-disable-line react-hooks/exhaustive-deps

  const start = async () => {
    setStarting(true);
    setError(null);
    try {
      const run = await startReplay(!drafts);
      setRunning(run);
      setRuns((rs) => [run, ...(rs ?? [])]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setStarting(false);
    }
  };

  const pctDone = running && running.total ? Math.round((running.done / running.total) * 100) : 0;
  return (
    <Card variant="outlined" sx={{ mb: 3 }}>
      <CardContent>
        <Typography variant="h6">Rivalutazione del dataset</Typography>
        <Typography variant="body2" color="text.secondary">
          Ripassa i casi etichettati nella versione attuale del sistema — sugli articoli già salvati, senza nuove
          ricerche — e confronta gli errori con quelli di allora: l'effetto di ogni modifica sugli stessi casi.
          Classifica ogni caso con l'LLM (qualche minuto per decine di casi).
        </Typography>
        {forbidden ? (
          <MuiAlert severity="info" sx={{ mt: 1.5 }}>
            La rivalutazione e il suo report (con i nomi dei soggetti) sono riservati ai ruoli abilitati all'export
            del dataset (DATASET_EXPORT_ROLES).
          </MuiAlert>
        ) : (
          <>
            <Box sx={{ display: "flex", alignItems: "center", gap: 2, flexWrap: "wrap", mt: 1.5 }}>
              <Button variant="contained" onClick={start} disabled={starting || !!running || runs === null}>
                {running ? "Rivalutazione in corso…" : "Avvia rivalutazione"}
              </Button>
              <FormControlLabel label="Includi i casi in bozza" control={
                <Switch size="small" checked={drafts} onChange={(e) => setDrafts(e.target.checked)}
                  disabled={!!running} />
              } />
            </Box>
            {running && (
              <Box sx={{ mt: 1.5 }} aria-live="polite">
                <LinearProgress variant={running.total ? "determinate" : "indeterminate"} value={pctDone}
                  aria-label="Avanzamento della rivalutazione" />
                <Typography variant="caption" color="text.secondary">
                  {running.total ? `${running.done} di ${running.total} casi` : "Preparazione dei casi…"}
                  {running.started_by_name && ` · avviata da ${running.started_by_name}`} alle{" "}
                  {new Date(running.created_at).toLocaleTimeString("it-IT", { timeStyle: "short" })}
                </Typography>
              </Box>
            )}
            {error && <MuiAlert severity="error" sx={{ mt: 1.5 }}>{error}</MuiAlert>}
            {runs && runs.length > 0 && (
              <List dense sx={{ mt: 1 }} aria-label="Rivalutazioni">
                {runs.map((r) => (
                  <ListItemButton key={r.id} selected={selected?.id === r.id} disabled={r.status !== "completed"}
                    onClick={() => open(r.id)} sx={{ borderRadius: 1, alignItems: "flex-start" }}>
                    <ListItemText
                      primary={
                        <Box sx={{ display: "flex", alignItems: "center", gap: 1, flexWrap: "wrap" }}>
                          <span>{when(r.created_at)}{r.started_by_name && ` · ${r.started_by_name}`}</span>
                          <Chip size="small" label={STATO[r.status][0]} color={STATO[r.status][1]} variant="outlined" />
                        </Box>
                      }
                      secondary={<RunLine run={r} />}
                      secondaryTypographyProps={{ sx: { wordBreak: "break-word" } }} />
                  </ListItemButton>
                ))}
              </List>
            )}
            {runs && runs.length === 0 && !running && (
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>
                Nessuna rivalutazione ancora.
              </Typography>
            )}
            {selected?.report && <Report run={selected} />}
          </>
        )}
      </CardContent>
    </Card>
  );
}
