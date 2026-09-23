// Corpo della scheda del caso (nel pannello laterale): esito del sistema, articoli con
// le loro etichette e giudizio sul caso, con il salvataggio in un piè di pagina fisso.
// Sta in un pannello largo quanto lo SCHERMO (non quanto la tabella): niente scroll
// orizzontale. L'esito del sistema è chiuso di default e la predizione per articolo
// non è mostrata, per non influenzare il giudizio (il confronto lo fa
// scripts/evaluate_labels.py).
import { useEffect, useState } from "react";
import {
  Accordion, AccordionDetails, AccordionSummary, Alert as MuiAlert, Autocomplete, Box, Button,
  Checkbox, Chip, FormControl, FormControlLabel, InputLabel, Link, MenuItem, Paper, Select,
  TextField, ToggleButton, ToggleButtonGroup, Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import {
  FATF_CATEGORIES, getLabel, saveLabel,
  type Alert, type Avversa, type CaseLabelIn, type CaseLabelSummary, type DispositionAttesa,
  type EvidenceItem, type EvidenceLabel, type Pertinenza, type Ruolo,
} from "../api";

const PERTINENZA: [Pertinenza, string][] = [
  ["si", "Sì"], ["omonimo", "Omonimo"], ["non_citato", "Non citato"], ["incerto", "Incerto"],
];
const AVVERSA: [Avversa, string][] = [["si", "Sì"], ["no", "No"], ["incerto", "Incerto"]];
const RUOLI: [Ruolo, string][] = [
  ["autore_indagato", "Autore / indagato"], ["vittima", "Vittima"],
  ["menzionato", "Solo menzionato"], ["non_determinabile", "Non determinabile"],
];
const ESITI: [DispositionAttesa, string][] = [
  ["ESCALATION_I_LIVELLO", "Escalation (I livello)"], ["AUTO_CHIUSO", "Chiusura"],
];

const EMPTY: CaseLabelIn = {
  evidence_labels: {}, categorie_corrette: [], ruolo: null, disposition_attesa: null,
  affidabile: false, note: "",
};

// Esito del sistema: chiuso di default (aprilo dopo aver giudicato).
function SystemOutcome({ a }: { a: Alert }) {
  const er = a.entity_resolution;
  return (
    <Accordion disableGutters variant="outlined" sx={{ mb: 2 }}>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Box>
          <Typography variant="subtitle2">Esito del sistema</Typography>
          <Typography variant="caption" color="text.secondary">
            AMI, categorie, motivazione, Entity Resolution — aprilo dopo aver giudicato, per non
            farti influenzare
          </Typography>
        </Box>
      </AccordionSummary>
      <AccordionDetails>
        <Typography variant="body2" gutterBottom>
          AMI <strong>{a.ami_score}</strong> · rischio {a.risk_level} · esito <strong>{a.disposition}</strong>
          {a.classification?.method && <> · classificazione: {String(a.classification.method)}</>}
        </Typography>
        {(a.fatf_categories ?? []).length > 0 && (
          <Box sx={{ display: "flex", gap: 0.5, flexWrap: "wrap", mb: 1 }}>
            {(a.fatf_categories ?? []).map((c) => (
              <Chip key={c} size="small" label={c} color="warning" variant="outlined" />
            ))}
          </Box>
        )}
        <ul style={{ margin: 0, paddingLeft: 18 }}>
          {(a.drivers ?? []).map((d, i) => (
            <li key={i}><Typography variant="caption" color="text.secondary">{d}</Typography></li>
          ))}
        </ul>
        {er && (
          <Typography variant="caption" color="text.secondary" component="div" sx={{ mt: 1 }}>
            Entity Resolution: {er.status} · {er.method} ({er.confidence.toFixed(2)})
            {(er.warnings ?? []).length > 0 && <> — {(er.warnings ?? []).join(" · ")}</>}
          </Typography>
        )}
        {a.svi_status === "failed" && a.svi_error && (
          <Typography variant="caption" color="error" component="div" sx={{ mt: 1 }}>
            Pubblicazione SVI fallita: {a.svi_error}
          </Typography>
        )}
      </AccordionDetails>
    </Accordion>
  );
}

type ArticleProps = {
  e: EvidenceItem & { id: string };
  value?: EvidenceLabel;
  onChange: (patch: Partial<EvidenceLabel>) => void;
};

// Un articolo: contenuto (per giudicare senza aprire la pagina) + le due domande.
function Article({ e, value, onChange }: ArticleProps) {
  return (
    <Paper variant="outlined" sx={{ p: 1.5, mb: 1.5 }}>
      <Box sx={{ display: "flex", alignItems: "center", gap: 1, flexWrap: "wrap" }}>
        <Typography variant="body2">
          <strong>{e.testata || "—"}</strong>{e.data ? ` · ${e.data}` : ""}
        </Typography>
        {e.url && <Link variant="body2" href={e.url} target="_blank" rel="noreferrer">apri articolo</Link>}
        {e.fonte_credibilita && (
          <Chip size="small" variant="outlined" label={`credibilità: ${e.fonte_credibilita}`} />
        )}
      </Box>
      {e.title && <Typography variant="body2" sx={{ mt: 0.5 }}>{e.title}</Typography>}
      {e.snippet && (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, fontStyle: "italic" }}>
          “{e.snippet}”
        </Typography>
      )}
      <Box sx={{ display: "flex", gap: 2, rowGap: 1, flexWrap: "wrap", mt: 1 }}>
        <Box>
          <Typography variant="caption" color="text.secondary" component="div">Riguarda il soggetto?</Typography>
          <ToggleButtonGroup size="small" exclusive color="primary" value={value?.pertinenza ?? null}
            onChange={(_, v: Pertinenza | null) => onChange({ pertinenza: v })}>
            {PERTINENZA.map(([v, t]) => <ToggleButton key={v} value={v}>{t}</ToggleButton>)}
          </ToggleButtonGroup>
        </Box>
        <Box>
          <Typography variant="caption" color="text.secondary" component="div">
            Notizia avversa per il soggetto?
          </Typography>
          <ToggleButtonGroup size="small" exclusive color="primary" value={value?.avversa ?? null}
            onChange={(_, v: Avversa | null) => onChange({ avversa: v })}>
            {AVVERSA.map(([v, t]) => <ToggleButton key={v} value={v}>{t}</ToggleButton>)}
          </ToggleButtonGroup>
        </Box>
      </Box>
      <Typography variant="caption" color="text.secondary" component="div"
        sx={{ mt: 1, wordBreak: "break-all" }} title={e.content_hash ?? undefined}>
        hash {(e.content_hash ?? "—").slice(0, 12)}… · fetch {e.fetch_ts || "—"}
        {e.warc_key && <> · WARC {e.warc_key}</>}
      </Typography>
    </Paper>
  );
}

type Props = {
  a: Alert;
  onSaved: (s: CaseLabelSummary) => void;
  onDirtyChange: (dirty: boolean) => void;
  onNext?: () => void;   // assente sull'ultimo caso
  onClose: () => void;
};

export default function CaseLabelPanel({ a, onSaved, onDirtyChange, onNext, onClose }: Props) {
  const [label, setLabel] = useState<CaseLabelIn>(EMPTY);
  const [saved, setSaved] = useState(JSON.stringify(EMPTY));   // ultimo stato salvato/caricato
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const evidence = (a.evidence ?? []).filter((e): e is EvidenceItem & { id: string } => !!e.id);
  const dirty = JSON.stringify(label) !== saved;

  useEffect(() => onDirtyChange(dirty), [dirty, onDirtyChange]);

  useEffect(() => {
    getLabel(a.id)
      .then((l) => {
        if (!l) return;
        const loaded: CaseLabelIn = {
          evidence_labels: l.evidence_labels ?? {}, categorie_corrette: l.categorie_corrette ?? [],
          ruolo: l.ruolo ?? null, disposition_attesa: l.disposition_attesa ?? null,
          affidabile: l.affidabile, note: l.note ?? "",
        };
        setLabel(loaded);
        setSaved(JSON.stringify(loaded));
      })
      .catch((e) => setMsg({ ok: false, text: String(e) }));
  }, [a.id]);

  const setEvidence = (id: string, patch: Partial<EvidenceLabel>) =>
    setLabel((l) => ({
      ...l, evidence_labels: { ...l.evidence_labels, [id]: { ...l.evidence_labels[id], ...patch } },
    }));

  const save = async (andThen?: () => void) => {
    setSaving(true);
    setMsg(null);
    try {
      const res = await saveLabel(a.id, { ...label, note: label.note || null });
      setSaved(JSON.stringify(label));
      onDirtyChange(false);
      onSaved({ alert_id: a.id, affidabile: res.affidabile, updated_at: res.updated_at });
      if (andThen) {
        andThen();
      } else {
        setMsg({
          ok: true,
          text: res.affidabile ? "Salvato: caso incluso nel dataset." : "Salvato come bozza (non incluso nel dataset).",
        });
      }
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <Box sx={{ flex: 1, overflowY: "auto", px: 2, py: 2 }}>
        <SystemOutcome a={a} />

        <Typography variant="subtitle2" gutterBottom>Articoli ({evidence.length})</Typography>
        {evidence.length === 0 ? (
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Nessun articolo analizzato (ricerca vuota, fonti non accessibili o Entity Resolution non
            superata). Se sai che esistono notizie avverse su questo soggetto, indica «Escalation»
            come esito corretto: serve a misurare i falsi negativi.
          </Typography>
        ) : evidence.map((e) => (
          <Article key={e.id} e={e} value={label.evidence_labels[e.id]}
            onChange={(patch) => setEvidence(e.id, patch)} />
        ))}

        <Typography variant="subtitle2" sx={{ mt: 2, mb: 1.5 }}>Giudizio sul caso</Typography>
        <Autocomplete multiple size="small" options={FATF_CATEGORIES} value={label.categorie_corrette}
          onChange={(_, v) => setLabel((l) => ({ ...l, categorie_corrette: v }))}
          renderInput={(params) => <TextField {...params} label="Categorie FATF corrette (vuoto = nessuna)" />} />
        <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" }, gap: 2, mt: 2 }}>
          <FormControl size="small" fullWidth>
            <InputLabel id={`ruolo-${a.id}`}>Ruolo del soggetto</InputLabel>
            <Select labelId={`ruolo-${a.id}`} label="Ruolo del soggetto" value={label.ruolo ?? ""}
              onChange={(ev) => setLabel((l) => ({ ...l, ruolo: (ev.target.value || null) as Ruolo | null }))}>
              <MenuItem value=""><em>—</em></MenuItem>
              {RUOLI.map(([v, t]) => <MenuItem key={v} value={v}>{t}</MenuItem>)}
            </Select>
          </FormControl>
          <FormControl size="small" fullWidth>
            <InputLabel id={`esito-${a.id}`}>Esito corretto</InputLabel>
            <Select labelId={`esito-${a.id}`} label="Esito corretto" value={label.disposition_attesa ?? ""}
              onChange={(ev) => setLabel((l) => ({
                ...l, disposition_attesa: (ev.target.value || null) as DispositionAttesa | null,
              }))}>
              <MenuItem value=""><em>—</em></MenuItem>
              {ESITI.map(([v, t]) => <MenuItem key={v} value={v}>{t}</MenuItem>)}
            </Select>
          </FormControl>
        </Box>
        <TextField size="small" fullWidth multiline minRows={2} label="Note" sx={{ mt: 2 }}
          value={label.note ?? ""} onChange={(ev) => setLabel((l) => ({ ...l, note: ev.target.value }))} />
      </Box>

      <Box sx={{ borderTop: 1, borderColor: "divider", px: 2, py: 1.5, bgcolor: "background.paper" }}>
        {msg && <MuiAlert severity={msg.ok ? "success" : "error"} sx={{ mb: 1 }}>{msg.text}</MuiAlert>}
        <Box sx={{ display: "flex", alignItems: "center", gap: 1, flexWrap: "wrap" }}>
          <FormControlLabel label="Caso affidabile (includi nel dataset)" control={
            <Checkbox checked={label.affidabile}
              onChange={(ev) => setLabel((l) => ({ ...l, affidabile: ev.target.checked }))} />
          } />
          <Box sx={{ flex: 1 }} />
          <Button variant="outlined" size="small" onClick={() => save()} disabled={saving}>Salva</Button>
          <Button variant="contained" size="small" disabled={saving}
            onClick={() => save(onNext ?? onClose)}>
            {onNext ? "Salva e successivo" : "Salva e chiudi"}
          </Button>
        </Box>
      </Box>
    </>
  );
}
