// Cancellazione di alert duplicati o errati: motivo obbligatorio (va nell'audit),
// riepilogo di cosa si perde (etichette, dataset) e di cosa resta in SAS VI.
import { useState } from "react";
import {
  Alert as MuiAlert, Button, Dialog, DialogActions, DialogContent, DialogTitle,
  FormControlLabel, Radio, RadioGroup, TextField, Typography,
} from "@mui/material";
import {
  deleteAlerts, type Alert, type AlertDeleteResult, type CaseLabelSummary, type MotivoCancellazione,
} from "../api";

type Props = {
  alerts: Alert[];                                   // da eliminare (vuoto = chiuso)
  labels: Record<string, CaseLabelSummary>;          // mie etichette, per il riepilogo
  onClose: () => void;
  onDeleted: (res: AlertDeleteResult, ids: string[]) => void;
};

export default function DeleteAlertsDialog({ alerts, labels, onClose, onDeleted }: Props) {
  const [motivo, setMotivo] = useState<MotivoCancellazione | "">("");
  const [nota, setNota] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const n = alerts.length;
  const labeled = alerts.filter((a) => labels[a.id]);
  const reliable = labeled.filter((a) => labels[a.id].affidabile).length;
  const inSvi = alerts.filter((a) => a.svi_status === "published").length;

  const confirm = async () => {
    if (!motivo) return;
    setBusy(true);
    setError(null);
    try {
      const ids = alerts.map((a) => a.id);
      onDeleted(await deleteAlerts(ids, motivo, nota), ids);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={n > 0} onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth
      aria-labelledby="del-title">
      <DialogTitle id="del-title">{n === 1 ? "Eliminare il caso?" : `Eliminare ${n} casi?`}</DialogTitle>
      <DialogContent>
        <Typography variant="body2" gutterBottom>
          {n === 1 ? <>«{alerts[0]?.subject}» verrà eliminato con i suoi articoli.</>
            : <>Verranno eliminati {n} casi con i loro articoli.</>}{" "}
          L'operazione non si annulla e resta nel registro delle attività (audit).
        </Typography>
        {labeled.length > 0 && (
          <MuiAlert severity="warning" sx={{ my: 1 }}>
            {labeled.length === 1 ? "Un caso è etichettato" : `${labeled.length} casi sono etichettati`}
            {reliable > 0 && ` (${reliable} nel dataset come affidabil${reliable === 1 ? "e" : "i"})`}: le
            etichette vengono eliminate con il caso.
          </MuiAlert>
        )}
        {inSvi > 0 && (
          <MuiAlert severity="info" sx={{ my: 1 }}>
            {inSvi === 1 ? "Un caso è pubblicato" : `${inSvi} casi sono pubblicati`} in SAS Visual
            Investigator: lì restano aperti e vanno chiusi da SVI.
          </MuiAlert>
        )}
        <Typography variant="subtitle2" sx={{ mt: 2 }}>Motivo</Typography>
        <RadioGroup value={motivo} onChange={(e) => setMotivo(e.target.value as MotivoCancellazione)}>
          <FormControlLabel value="duplicato" control={<Radio />}
            label="Duplicato: lo stesso soggetto è già stato screenato" />
          <FormControlLabel value="errato" control={<Radio />}
            label="Errato: soggetto sbagliato (refuso, omonimo) o articoli non pertinenti" />
        </RadioGroup>
        <TextField label="Nota (facoltativa)" size="small" fullWidth multiline minRows={2} sx={{ mt: 1 }}
          value={nota} onChange={(e) => setNota(e.target.value)} inputProps={{ maxLength: 500 }} />
        {error && <MuiAlert severity="error" sx={{ mt: 2 }}>{error}</MuiAlert>}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy}>Annulla</Button>
        <Button color="error" variant="contained" onClick={confirm} disabled={busy || !motivo}>
          {n === 1 ? "Elimina il caso" : `Elimina ${n} casi`}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
