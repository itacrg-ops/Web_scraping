// Nome simile a soggetti già noti (registro o screening passati): «Stropp» / «Stroppa»
// è un refuso o un'altra persona? La decisione del revisore resta nel registro e
// migliora l'Entity Resolution (variante dello stesso soggetto / soggetto diverso).
import {
  Alert as MuiAlert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, Paper,
  Typography,
} from "@mui/material";
import type { SimilarCandidate, SimilarOut } from "../api";

export type NameChoice =
  | { action: "usa"; c: SimilarCandidate }        // è lui: usa il nome (e i dati) del candidato
  | { action: "correggi"; c: SimilarCandidate }   // è lui, ma il registro ha il nome sbagliato
  | { action: "variante"; c: SimilarCandidate }   // (registro) il nome inserito è una sua variante
  | { action: "diverso"; c: SimilarCandidate }    // è un altro soggetto
  | { action: "prosegui" }                        // continua con il nome inserito
  | { action: "annulla" };

// Un omonimo si distingue con un identificativo diverso da quello del soggetto già
// inserito: CF/P.IVA o, per una persona, data di nascita.
function homonymHint(c: SimilarCandidate) {
  const pf = c.tipo_soggetto === "persona_fisica";
  const ids = pf ? "il codice fiscale o la data di nascita" : "il CF/P.IVA";
  return c.cf_piva || (pf && c.data_nascita)
    ? `Se è un omonimo, indica ${ids} per distinguerlo.`
    : `Se è un omonimo, aggiungi prima ${ids} a «${c.denominazione}», poi indica i suoi.`;
}

type Props = {
  typed: string;
  data: SimilarOut | null;              // null = chiuso
  mode: "screening" | "registro";       // prima di uno screening o di aggiungere al registro
  onChoice: (c: NameChoice) => void;
};

export default function SimilarNamesDialog({ typed, data, mode, onChoice }: Props) {
  const exact = data?.registro_esatto;
  // Aggiunta al registro di un soggetto che c'è già (stesso nome o CF/P.IVA): l'API la
  // rifiuterebbe, quindi niente «Aggiungi comunque».
  const already = mode === "registro" && !!exact;
  const simili = already ? [] : data?.simili ?? [];
  return (
    <Dialog open={!!data} onClose={() => onChoice({ action: "annulla" })} maxWidth="sm" fullWidth
      aria-labelledby="sim-title">
      <DialogTitle id="sim-title">
        {already ? "Soggetto già inserito" : simili.length ? "Nome simile a soggetti già noti" : "Soggetto già presente"}
      </DialogTitle>
      <DialogContent>
        {mode === "screening" && !!data?.alert_esistenti && (
          <MuiAlert severity="info" sx={{ mb: 1.5 }}>
            «{typed}» ha già {data.alert_esistenti === 1 ? "un alert" : `${data.alert_esistenti} alert`}: un
            nuovo screening crea un altro caso dello stesso soggetto (duplicato nel dataset).
          </MuiAlert>
        )}
        {already && exact && (
          <MuiAlert severity="warning" sx={{ mb: 1.5 }}>
            Soggetto già inserito nel registro: «{exact.denominazione}»
            {exact.cf_piva && ` (CF/P.IVA ${exact.cf_piva})`}
            {exact.denominazione !== typed && `: «${typed}» è lo stesso soggetto`}. Per cambiarne i dati usa
            la modifica nella tabella. {homonymHint(exact)}
          </MuiAlert>
        )}
        {simili.length > 0 && (
          <Typography variant="body2" gutterBottom>
            «<strong>{typed}</strong>» è simile a {simili.length === 1 ? "questo soggetto" : "questi soggetti"}.
            È la stessa persona o impresa (il nome ha un refuso) o un'altra?
          </Typography>
        )}
        {simili.map((c) => (
          <Paper key={`${c.fonte}-${c.subject_id ?? c.denominazione}`} variant="outlined" sx={{ p: 1.5, mt: 1 }}>
            <Box sx={{ display: "flex", alignItems: "center", gap: 1, flexWrap: "wrap" }}>
              <Typography variant="body2"><strong>{c.denominazione}</strong></Typography>
              <Chip size="small" variant="outlined" label={`somiglianza ${Math.round(c.score * 100)}%`} />
              <Chip size="small" color={c.fonte === "registro" ? "primary" : "default"} variant="outlined"
                label={c.fonte === "registro" ? "nel registro" : "già screenato"} />
              {c.alert > 0 && <Chip size="small" variant="outlined" label={c.alert === 1 ? "1 alert" : `${c.alert} alert`} />}
            </Box>
            {(c.cf_piva || c.data_nascita || c.luogo_nascita) && (
              <Typography variant="caption" color="text.secondary" component="div">
                {[c.cf_piva && `CF/P.IVA ${c.cf_piva}`, c.data_nascita && `nato/a il ${c.data_nascita}`,
                  c.luogo_nascita].filter(Boolean).join(" · ")}
              </Typography>
            )}
            {c.score >= 1 ? (
              // stesso nome ma identificativo diverso (solo nel registro): un omonimo
              <Typography variant="caption" color="warning.main" component="div" sx={{ mt: 0.5 }}>
                Stesso nome, {c.tipo_soggetto === "persona_fisica" ? "codice fiscale o data di nascita diversi"
                  : "CF/P.IVA diverso"}: è un omonimo? Se sì, aggiungilo.
              </Typography>
            ) : (
              <Box sx={{ display: "flex", gap: 1, mt: 1, flexWrap: "wrap" }}>
                {mode === "registro" && c.fonte === "registro" ? (
                  <Button size="small" variant="outlined" onClick={() => onChoice({ action: "variante", c })}>
                    È lo stesso: registra «{typed}» come sua variante
                  </Button>
                ) : (
                  <Button size="small" variant="outlined" onClick={() => onChoice({ action: "usa", c })}>
                    È lo stesso: usa «{c.denominazione}»
                  </Button>
                )}
                {mode === "screening" && c.fonte === "registro" && (
                  <Button size="small" onClick={() => onChoice({ action: "correggi", c })}
                    title={`Il registro ha il nome sbagliato: diventa «${typed}» (il vecchio nome resta come variante)`}>
                    È lo stesso: correggi il registro
                  </Button>
                )}
                <Button size="small" onClick={() => onChoice({ action: "diverso", c })}>È un altro soggetto</Button>
              </Box>
            )}
          </Paper>
        ))}
      </DialogContent>
      <DialogActions>
        <Button onClick={() => onChoice({ action: "annulla" })}>{already ? "Chiudi" : "Annulla"}</Button>
        {!already && (
          <Button variant="contained" onClick={() => onChoice({ action: "prosegui" })}>
            {mode === "registro" ? "Aggiungi comunque" : `Prosegui con «${typed}»`}
          </Button>
        )}
      </DialogActions>
    </Dialog>
  );
}
