import { useState } from "react";
import {
  Alert as MuiAlert, Box, Button, Paper, Stack, TextField,
  ToggleButton, ToggleButtonGroup, Typography,
} from "@mui/material";
import {
  getScreening, startScreening, type Screening, type TipoSoggetto,
} from "../api";

// Pagina di prova del walking skeleton end-to-end:
// avvia uno screening → workflow Temporal → pipeline → alert persistito.
// Supporta due tipi di soggetto: persona giuridica (denominazione) e
// persona fisica (nome + cognome, con CF/data di nascita per l'anti-omonimia).
export default function ScreeningPage() {
  const [tipo, setTipo] = useState<TipoSoggetto>("persona_giuridica");
  // Persona giuridica
  const [denominazione, setDenominazione] = useState("ACME Costruzioni S.r.l.");
  // Persona fisica
  const [cognome, setCognome] = useState("Rossi");
  const [nome, setNome] = useState("Mario");
  const [dataNascita, setDataNascita] = useState("");
  // Comuni
  const [cfPiva, setCfPiva] = useState("00743110157");
  const [cup, setCup] = useState("E51B21000000001");
  const [seedUrl, setSeedUrl] = useState("https://example.com");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Screening | null>(null);
  const [error, setError] = useState<string | null>(null);

  const isPerson = tipo === "persona_fisica";
  const canSubmit = isPerson ? Boolean(cognome && nome) : Boolean(denominazione);

  function onTipoChange(_: unknown, value: TipoSoggetto | null) {
    if (!value) return;
    setTipo(value);
    // Preset coerenti col registro seed (match deterministico via CF/P.IVA).
    if (value === "persona_fisica") {
      setCfPiva("RSSMRA75C15H501P");
    } else {
      setCfPiva("00743110157");
    }
  }

  async function submit() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const s = await startScreening({
        tipo_soggetto: tipo,
        denominazione: isPerson ? undefined : denominazione,
        nome: isPerson ? nome : undefined,
        cognome: isPerson ? cognome : undefined,
        data_nascita: isPerson && dataNascita ? dataNascita : undefined,
        cf_piva: cfPiva || undefined,
        cup: cup ? cup.split(",").map((c) => c.trim()) : [],
        seed_url: seedUrl || undefined,
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
        Avvia il workflow Temporal: Entity Resolution (anti-omonimia) → fetch →
        estrazione → classificazione FATF (Foundry) → AMI → pubblicazione in SVI
        (mock) → alert persistito. L'esito appare nella pagina <strong>Alert</strong>.
      </Typography>

      <Paper sx={{ p: 3, mt: 2, maxWidth: 560 }}>
        <Stack spacing={2}>
          <ToggleButtonGroup
            exclusive size="small" color="primary"
            value={tipo} onChange={onTipoChange} aria-label="tipo di soggetto"
          >
            <ToggleButton value="persona_giuridica">Persona giuridica</ToggleButton>
            <ToggleButton value="persona_fisica">Persona fisica</ToggleButton>
          </ToggleButtonGroup>

          {isPerson ? (
            <>
              <TextField label="Cognome" value={cognome}
                onChange={(e) => setCognome(e.target.value)} fullWidth required />
              <TextField label="Nome" value={nome}
                onChange={(e) => setNome(e.target.value)} fullWidth required />
              <TextField label="Codice Fiscale (16)" value={cfPiva}
                onChange={(e) => setCfPiva(e.target.value)} fullWidth
                helperText="Identificatore forte: consente il match deterministico ed evita l'omonimia." />
              <TextField label="Data di nascita" type="date" value={dataNascita}
                onChange={(e) => setDataNascita(e.target.value)} fullWidth
                InputLabelProps={{ shrink: true }}
                helperText="Facoltativa: disambigua i casi di omonimia quando manca il CF." />
            </>
          ) : (
            <>
              <TextField label="Denominazione" value={denominazione}
                onChange={(e) => setDenominazione(e.target.value)} fullWidth required />
              <TextField label="CF / P.IVA" value={cfPiva}
                onChange={(e) => setCfPiva(e.target.value)} fullWidth />
            </>
          )}

          <TextField label="CUP (separati da virgola)" value={cup}
            onChange={(e) => setCup(e.target.value)} fullWidth />
          <TextField label="URL sorgente (seed)" value={seedUrl}
            onChange={(e) => setSeedUrl(e.target.value)} fullWidth
            helperText="Fetch conforme (robots.txt). Per un alert ALTO usa un articolo con contenuti adverse che consenta lo scraping." />
          <Box>
            <Button variant="contained" onClick={submit} disabled={busy || !canSubmit}>
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
