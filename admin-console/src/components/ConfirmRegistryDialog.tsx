// Conferma a valle dell'etichettatura: gli articoli del caso, con il giudizio del
// revisore, entrano nello storico verificato del soggetto nel registro. Se il soggetto
// non è nel registro lo si crea — correggendo il nome se l'alert ha un refuso: il nome
// sbagliato diventa una sua variante e l'Entity Resolution lo riconoscerà. Per una
// persona fisica si registrano anche i ruoli trovati negli articoli e il flag PEP.
import { useState } from "react";
import {
  Alert as MuiAlert, Box, Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle,
  FormControlLabel, FormGroup, Radio, RadioGroup, Stack, TextField, Typography,
} from "@mui/material";
import {
  confirmInRegistry, similarSubjects,
  type Alert, type CaseLabelIn, type ConfirmOut, type RelatedOut, type RoleFound, type TipoSoggetto,
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

// Nota accanto al ruolo: perché conta per il flag PEP.
const roleNote = (r: RoleFound) =>
  [r.pep === "si" ? "carica dell'elenco PEP" : r.pep === "verifica" ? "carica PEP da verificare"
    : r.categoria === "politico" ? "ruolo politico, non PEP per legge" : "",
   r.ex ? "cessata" : "",
   r.articoli && r.articoli > 1 ? `in ${r.articoli} articoli` : ""].filter(Boolean).join(" · ");

export default function ConfirmRegistryDialog({ open, a, label, registry, onClose, onDone }: Props) {
  const isPerson = a.tipo_soggetto === "persona_fisica";
  const variant = (a.name_variants ?? [])[0];
  const roles = isPerson ? a.roles ?? [] : [];
  const [target, setTarget] = useState<"registro" | "nuovo">(registry ? "registro" : "nuovo");
  const [existing, setExisting] = useState(registry ? { id: registry.subject_id, name: registry.denominazione } : null);
  const [name, setName] = useState(a.subject);
  const [cf, setCf] = useState(a.cf_piva ?? "");
  // ruoli da registrare (tutti, di norma) e PEP: proposto per una carica certa e in corso
  const [cariche, setCariche] = useState<string[]>(roles.map((r) => r.ruolo));
  const [pep, setPep] = useState(roles.some((r) => r.pep === "si" && !r.ex));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const evidence = (a.evidence ?? []).filter((e) => e.id);
  const ok = evidence.filter((e) => certain(label.evidence_labels[e.id!])).length;
  const toggle = (ruolo: string) =>
    setCariche((xs) => (xs.includes(ruolo) ? xs.filter((x) => x !== ruolo) : [...xs, ruolo]));

  const confirm = async () => {
    setBusy(true);
    setMsg(null);
    const tipo = (a.tipo_soggetto ?? "persona_giuridica") as TipoSoggetto;
    const extra = isPerson ? { cariche, pep: pep || undefined } : {};
    try {
      const body = target === "registro" && existing
        ? { subject_id: existing.id, ...extra }
        : { nuovo: { tipo_soggetto: tipo, denominazione: name.trim(), cf_piva: cf.trim() || undefined, cup: a.cup },
            ...extra };
      onDone(await confirmInRegistry(a.id, body));
    } catch (e) {
      const text = e instanceof Error ? e.message : String(e);
      // Il soggetto è già nel registro (stesso nome o CF/P.IVA): proponi di confermare lì.
      if (text.startsWith("409") && target === "nuovo") {
        const sim = await similarSubjects({ tipo_soggetto: tipo, denominazione: name.trim(),
                                            cf_piva: cf.trim() || undefined }).catch(() => null);
        if (sim?.registro_esatto?.subject_id) {
          setExisting({ id: sim.registro_esatto.subject_id, name: sim.registro_esatto.denominazione });
          setTarget("registro");
          setMsg(`Soggetto già inserito nel registro: «${sim.registro_esatto.denominazione}». `
                 + "Conferma gli articoli su quel soggetto.");
          return;
        }
      }
      setMsg(text.replace(/^\d{3}: /, ""));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth aria-labelledby="conf-title">
      <DialogTitle id="conf-title">Conferma nel registro dei soggetti</DialogTitle>
      <DialogContent>
        {existing && target === "registro" && !msg && (
          <MuiAlert severity="info" sx={{ mb: 1.5 }}>
            Soggetto già inserito nel registro: «{existing.name}». La conferma aggiunge gli articoli
            al suo storico, senza creare un nuovo soggetto.
          </MuiAlert>
        )}
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
                <Typography variant="body2">Aggiungi gli articoli a <strong>{existing.name}</strong></Typography>
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
        {isPerson && (roles.length > 0 || a.pep) && (
          <Box sx={{ mt: 2 }}>
            <Typography variant="subtitle2">Ruoli negli articoli</Typography>
            <Typography variant="caption" color="text.secondary" component="div">
              Quelli spuntati si aggiungono alle cariche del soggetto nel registro.
            </Typography>
            <FormGroup>
              {roles.map((r) => (
                <FormControlLabel key={r.ruolo} control={
                  <Checkbox size="small" checked={cariche.includes(r.ruolo)} onChange={() => toggle(r.ruolo)} />}
                  label={
                    <Typography variant="body2">
                      {r.ruolo}
                      {roleNote(r) && <Typography component="span" variant="caption" color="text.secondary"> — {roleNote(r)}</Typography>}
                    </Typography>} />
              ))}
            </FormGroup>
            <FormControlLabel sx={{ mt: 0.5 }} control={
              <Checkbox size="small" color="secondary" checked={pep} onChange={(e) => setPep(e.target.checked)} />}
              label={<Typography variant="body2"><strong>PEP</strong>: persona politicamente esposta (verificata)</Typography>} />
            <Typography variant="caption" color="text.secondary" component="div">
              D.Lgs. 231/2007: per il sindaco conta il comune (capoluogo o almeno 15.000 abitanti); una
              carica cessata vale per un anno. Il flag nel registro non viene tolto da conferme successive.
            </Typography>
          </Box>
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
