// Etichettatura del caso per il dataset di valutazione: il revisore giudica ogni
// articolo (riguarda davvero il soggetto? è avverso?) e il caso nel suo insieme.
// La predizione del sistema per articolo NON è mostrata qui, per non influenzare il
// giudizio: il confronto sistema/revisore lo fa scripts/evaluate_labels.py.
import { useEffect, useState } from "react";
import {
  Alert as MuiAlert, Autocomplete, Box, Button, Checkbox, Divider, FormControl,
  FormControlLabel, InputLabel, MenuItem, Paper, Select, TextField, ToggleButton,
  ToggleButtonGroup, Typography,
} from "@mui/material";
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

type Props = { a: Alert; onSaved: (s: CaseLabelSummary) => void };

export default function CaseLabelPanel({ a, onSaved }: Props) {
  const [label, setLabel] = useState<CaseLabelIn>(EMPTY);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const evidence = (a.evidence ?? []).filter((e): e is EvidenceItem & { id: string } => !!e.id);

  useEffect(() => {
    getLabel(a.id)
      .then((l) => {
        if (l) {
          setLabel({
            evidence_labels: l.evidence_labels ?? {}, categorie_corrette: l.categorie_corrette ?? [],
            ruolo: l.ruolo ?? null, disposition_attesa: l.disposition_attesa ?? null,
            affidabile: l.affidabile, note: l.note ?? "",
          });
        }
      })
      .catch((e) => setMsg({ ok: false, text: String(e) }));
  }, [a.id]);

  const setEvidence = (id: string, patch: Partial<EvidenceLabel>) =>
    setLabel((l) => ({
      ...l, evidence_labels: { ...l.evidence_labels, [id]: { ...l.evidence_labels[id], ...patch } },
    }));

  const save = async () => {
    setSaving(true);
    setMsg(null);
    try {
      const saved = await saveLabel(a.id, { ...label, note: label.note || null });
      setMsg({
        ok: true,
        text: saved.affidabile ? "Salvato: caso incluso nel dataset." : "Salvato come bozza (non incluso nel dataset).",
      });
      onSaved({ alert_id: a.id, affidabile: saved.affidabile, updated_at: saved.updated_at });
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Box component="section" aria-label={`Etichetta del caso ${a.subject}`} sx={{ p: 2 }}>
      <Divider sx={{ mb: 2 }} />
      <Typography variant="subtitle2">Etichetta del caso — dataset di valutazione</Typography>
      <Typography variant="caption" color="text.secondary" component="p" sx={{ mb: 1 }}>
        Giudica ogni articolo e il caso nel suo insieme. Marca <strong>affidabile</strong> solo i
        casi di cui sei certo: formano il dataset con cui si misurano gli errori del sistema.
        Etichetta anche casi chiusi o incompleti, non solo le escalation.
      </Typography>

      {evidence.length === 0 ? (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          Nessun articolo analizzato. Se sai che esistono notizie avverse su questo soggetto,
          indica «Escalation» come esito corretto: serve a misurare i falsi negativi.
        </Typography>
      ) : evidence.map((e) => (
        <Paper key={e.id} variant="outlined" sx={{ p: 1, mb: 1 }}>
          <Typography variant="body2">
            <strong>{e.testata || "—"}</strong>{e.title ? ` · ${e.title}` : ""}
          </Typography>
          <Box sx={{ display: "flex", gap: 2, flexWrap: "wrap", mt: 0.5 }}>
            <Box>
              <Typography variant="caption" color="text.secondary" component="div">
                Riguarda il soggetto?
              </Typography>
              <ToggleButtonGroup size="small" exclusive color="primary"
                value={label.evidence_labels[e.id]?.pertinenza ?? null}
                onChange={(_, v: Pertinenza | null) => setEvidence(e.id, { pertinenza: v })}>
                {PERTINENZA.map(([v, t]) => <ToggleButton key={v} value={v}>{t}</ToggleButton>)}
              </ToggleButtonGroup>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary" component="div">
                Notizia avversa per il soggetto?
              </Typography>
              <ToggleButtonGroup size="small" exclusive color="primary"
                value={label.evidence_labels[e.id]?.avversa ?? null}
                onChange={(_, v: Avversa | null) => setEvidence(e.id, { avversa: v })}>
                {AVVERSA.map(([v, t]) => <ToggleButton key={v} value={v}>{t}</ToggleButton>)}
              </ToggleButtonGroup>
            </Box>
          </Box>
        </Paper>
      ))}

      <Box sx={{ display: "flex", gap: 2, flexWrap: "wrap", mt: 1.5 }}>
        <Autocomplete multiple size="small" sx={{ flex: "1 1 320px" }} options={FATF_CATEGORIES}
          value={label.categorie_corrette}
          onChange={(_, v) => setLabel((l) => ({ ...l, categorie_corrette: v }))}
          renderInput={(params) => <TextField {...params} label="Categorie FATF corrette (vuoto = nessuna)" />} />
        <FormControl size="small" sx={{ minWidth: 200 }}>
          <InputLabel id={`ruolo-${a.id}`}>Ruolo del soggetto</InputLabel>
          <Select labelId={`ruolo-${a.id}`} label="Ruolo del soggetto" value={label.ruolo ?? ""}
            onChange={(ev) => setLabel((l) => ({ ...l, ruolo: (ev.target.value || null) as Ruolo | null }))}>
            <MenuItem value=""><em>—</em></MenuItem>
            {RUOLI.map(([v, t]) => <MenuItem key={v} value={v}>{t}</MenuItem>)}
          </Select>
        </FormControl>
        <FormControl size="small" sx={{ minWidth: 200 }}>
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

      <TextField size="small" fullWidth multiline minRows={1} label="Note" sx={{ mt: 2 }}
        value={label.note ?? ""} onChange={(ev) => setLabel((l) => ({ ...l, note: ev.target.value }))} />

      <Box sx={{ display: "flex", alignItems: "center", gap: 2, mt: 1, flexWrap: "wrap" }}>
        <FormControlLabel label="Caso affidabile (includi nel dataset)" control={
          <Checkbox checked={label.affidabile}
            onChange={(ev) => setLabel((l) => ({ ...l, affidabile: ev.target.checked }))} />
        } />
        <Button variant="contained" size="small" onClick={save} disabled={saving}>Salva etichetta</Button>
      </Box>
      {msg && <MuiAlert severity={msg.ok ? "success" : "error"} sx={{ mt: 1 }}>{msg.text}</MuiAlert>}
    </Box>
  );
}
