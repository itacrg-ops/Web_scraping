import { useState } from "react";
import {
  Alert as MuiAlert, Box, Button, Paper, Stack, TextField, Typography,
} from "@mui/material";
import { getScreening, startScreening, type Screening } from "../api";

// Pagina di prova del walking skeleton end-to-end:
// avvia uno screening → workflow Temporal → pipeline → alert persistito.
export default function ScreeningPage() {
  const [denominazione, setDenominazione] = useState("ACME Costruzioni S.r.l.");
  const [cfPiva, setCfPiva] = useState("00743110157");
  const [cup, setCup] = useState("E51B21000000001");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Screening | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const s = await startScreening({
        denominazione,
        cf_piva: cfPiva || undefined,
        cup: cup ? cup.split(",").map((c) => c.trim()) : [],
      });
      setResult(s);
      // Polling breve dello stato (il worker completa la pipeline in modo asincrono).
      for (let i = 0; i < 10; i++) {
        await new Promise((r) => setTimeout(r, 1000));
        const cur = await getScreening(s.id);
        setResult(cur);
        if (cur.status !== "running") break;
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <Typography variant="h5" gutterBottom>Nuovo screening (prova end-to-end)</Typography>
      <Typography variant="body2" color="text.secondary" gutterBottom>
        Avvia il workflow Temporal: fetch → estrazione → classificazione FATF
        (Foundry) → AMI → pubblicazione in SVI (mock) → alert persistito. L'esito
        appare nella pagina <strong>Alert</strong>.
      </Typography>

      <Paper sx={{ p: 3, mt: 2, maxWidth: 560 }}>
        <Stack spacing={2}>
          <TextField label="Denominazione" value={denominazione}
            onChange={(e) => setDenominazione(e.target.value)} fullWidth />
          <TextField label="CF / P.IVA" value={cfPiva}
            onChange={(e) => setCfPiva(e.target.value)} fullWidth />
          <TextField label="CUP (separati da virgola)" value={cup}
            onChange={(e) => setCup(e.target.value)} fullWidth />
          <Box>
            <Button variant="contained" onClick={submit} disabled={busy || !denominazione}>
              {busy ? "In corso…" : "Avvia screening"}
            </Button>
          </Box>
        </Stack>
      </Paper>

      {error && <MuiAlert severity="error" sx={{ mt: 2 }}>{error}</MuiAlert>}
      {result && (
        <MuiAlert severity={result.status === "completed" ? "success" : "info"} sx={{ mt: 2 }}>
          Screening <code>{result.id}</code> — stato: <strong>{result.status}</strong>
          {result.alert_id && <> · alert generato: <code>{result.alert_id}</code></>}
        </MuiAlert>
      )}
    </div>
  );
}
