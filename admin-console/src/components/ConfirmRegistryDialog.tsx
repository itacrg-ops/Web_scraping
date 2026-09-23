// Conferma a valle dell'etichettatura: gli articoli del caso, con il giudizio del
// revisore, entrano nello storico verificato del soggetto nel registro. Se il soggetto
// non è nel registro lo si crea — correggendo il nome se l'alert ha un refuso: il nome
// sbagliato diventa una sua variante e l'Entity Resolution lo riconoscerà.
import { useState } from "react";
import {
  Alert as MuiAlert, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle,
  FormControlLabel, Radio, RadioGroup, Stack, TextField, Typography,
} from "@mui/material";
import {
  confirmInRegistry, similarSubjects,
  type Alert, type CaseLabelIn, type ConfirmOut, type RelatedOut, type TipoSoggetto,
} from "../api";
import { asSubjectName } from "../personName";

type Props = {
  open: boolean;
  a: Alert;
  label: CaseLabelIn;                    // etichetta salvata del revisore
  registry: RelatedOut["registro"];      // soggetto del registro già collegato, se c'è
  onClose: () => void;
  onDone: (res: ConfirmOut) => void;
};

const COME: Record<string, string> = {
  entity_resolution: "identità risolta dall'Entity Resolution", cf_piva: "stesso CF/P.IVA",
  nome: "stesso nome", alias: "variante del nome già confermata",
};
const certain = (v?: { pertinenza?: string | null; avversa?: string | null }) =>
  !!v?.pertinenza && v.pertinenza !== "incerto" && !!v?.avversa && v.avversa !== "incerto";

export default function ConfirmRegistryDialog({ open, a, label, registry, onClose, onDone }: Props) {
  const isPerson = a.tipo_soggetto === "persona_fisica";
  const variant = (a.name_variants ?? [])[0];
  const [target, setTarget] = useState<"registro" | "nuovo">(registry ? "registro" : "nuovo");
  const [existing, setExisting] = useState(registry ? { id: registry.subject_id, name: registry.denominazione } : null);
  const [name, setName] = useState(a.subject);
  const [cf, setCf] = useState(a.cf_piva ?? "");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const evidence = (a.evidence ?? []).filter((e) => e.id);
  const ok = evidence.filter((e) => certain(label.evidence_labels[e.id!])).length;

  const confirm = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const body = target === "registro" && existing
        ? { subject_id: existing.id }
        : { nuovo: { tipo_soggetto: (a.tipo_soggetto ?? "persona_giuridica") as TipoSoggetto,
                     denominazione: name.trim(), cf_piva: cf.trim() || undefined, cup: a.cup } };
      onDone(await confirmInRegistry(a.id, body));
    } catch (e) {
      const text = e instanceof Error ? e.message : String(e);
      // Il nome scelto è già nel registro: proponi di confermare su quel soggetto.
      if (text.startsWith("409") && target === "nuovo") {
        const sim = await similarSubjects({ tipo_soggetto: (a.tipo_soggetto ?? "persona_giuridica") as TipoSoggetto,
                                            denominazione: name.trim() }).catch(() => null);
        if (sim?.registro_esatto?.subject_id) {
          setExisting({ id: sim.registro_esatto.subject_id, name: sim.registro_esatto.denominazione });
          setTarget("registro");
          setMsg(`«${sim.registro_esatto.denominazione}» è già nel registro: conferma su quel soggetto.`);
          return;
        }
      }
      setMsg(text);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth aria-labelledby="conf-title">
      <DialogTitle id="conf-title">Conferma nel registro dei soggetti</DialogTitle>
      <DialogContent>
        <Typography variant="body2" gutterBottom>
          Gli articoli con giudizio certo ({ok} su {evidence.length}) entrano nello storico verificato
          del soggetto, con il tuo giudizio sul caso
          {label.categorie_corrette.length > 0 && <> ({label.categorie_corrette.join(", ")})</>}.
          {ok < evidence.length && " Gli altri (senza risposta o «Incerto») vengono saltati."}
        </Typography>
        <RadioGroup value={target} onChange={(e) => setTarget(e.target.value as "registro" | "nuovo")}>
          {existing && (
            <FormControlLabel value="registro" control={<Radio />} label={
              <Box>
                <Typography variant="body2">Soggetto del registro: <strong>{existing.name}</strong></Typography>
                {registry && existing.id === registry.subject_id && (
                  <Typography variant="caption" color="text.secondary">trovato per {COME[registry.come]}</Typography>
                )}
              </Box>} />
          )}
          <FormControlLabel value="nuovo" control={<Radio />} label={
            <Typography variant="body2">{existing ? "Un altro soggetto: aggiungilo al registro" : "Aggiungi il soggetto al registro"}</Typography>} />
        </RadioGroup>
        {target === "nuovo" && (
          <Stack spacing={1.5} sx={{ mt: 1, pl: 4 }}>
            {variant && (
              <MuiAlert severity="warning" action={
                <Button size="small" onClick={() => setName(asSubjectName(variant, a.subject, isPerson))}>Usa</Button>}>
                Gli articoli citano «{variant}»: se «{a.subject}» è un refuso, usa il nome corretto.
              </MuiAlert>
            )}
            <TextField size="small" label={isPerson ? "Cognome Nome" : "Denominazione"} value={name}
              onChange={(e) => setName(e.target.value)}
              helperText={name.trim() && name.trim() !== a.subject
                ? `«${a.subject}» verrà registrato come variante di questo nome` : undefined} />
            <TextField size="small" label={isPerson ? "Codice Fiscale" : "CF / P.IVA"} value={cf}
              onChange={(e) => setCf(e.target.value)} />
          </Stack>
        )}
        {msg && <MuiAlert severity="warning" sx={{ mt: 2 }}>{msg}</MuiAlert>}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy}>Annulla</Button>
        <Button variant="contained" onClick={confirm}
          disabled={busy || ok === 0 || (target === "nuovo" ? !name.trim() : !existing)}>
          Conferma {ok === 1 ? "1 articolo" : `${ok} articoli`}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
