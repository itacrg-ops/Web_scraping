import { useState } from "react";
import {
  Alert as MuiAlert, Box, Button, Checkbox, Chip, CircularProgress, Divider,
  Link, List, ListItem, ListItemButton, ListItemIcon, ListItemText, Paper, Stack,
  TextField, ToggleButton, ToggleButtonGroup, Typography,
} from "@mui/material";
import SearchIcon from "@mui/icons-material/Search";
import {
  getScreening, searchPreview, startScreening,
  type Screening, type SearchResult, type TipoSoggetto,
} from "../api";

// Prova end-to-end: soggetto → (web search o URL) → workflow Temporal →
// Entity Resolution → fetch/estrazione/menzione per articolo → FATF → AMI →
// SVI (mock) → alert persistito. Due tipi di soggetto: giuridica / fisica.
export default function ScreeningPage() {
  const [tipo, setTipo] = useState<TipoSoggetto>("persona_giuridica");
  const [denominazione, setDenominazione] = useState("ACME Costruzioni S.r.l.");
  const [cognome, setCognome] = useState("Rossi");
  const [nome, setNome] = useState("Mario");
  const [dataNascita, setDataNascita] = useState("");
  const [cfPiva, setCfPiva] = useState("00743110157");
  const [cup, setCup] = useState("E51B21000000001");
  const [seedUrl, setSeedUrl] = useState("");

  // Web search
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [provider, setProvider] = useState<string>("");
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Screening | null>(null);
  const [error, setError] = useState<string | null>(null);

  const isPerson = tipo === "persona_fisica";
  const hasSubject = isPerson ? Boolean(cognome && nome) : Boolean(denominazione);

  function onTipoChange(_: unknown, value: TipoSoggetto | null) {
    if (!value) return;
    setTipo(value);
    setResults(null);
    setSelected(new Set());
    setCfPiva(value === "persona_fisica" ? "RSSMRA75C15H501P" : "00743110157");
  }

  const subjectFields = () => ({
    tipo_soggetto: tipo,
    denominazione: isPerson ? undefined : denominazione,
    nome: isPerson ? nome : undefined,
    cognome: isPerson ? cognome : undefined,
    cf_piva: cfPiva || undefined,
  });

  async function search() {
    setSearching(true);
    setError(null);
    setResults(null);
    setSelected(new Set());
    try {
      const r = await searchPreview({ ...subjectFields(), mode: "targeted" });
      setProvider(r.provider);
      setResults(r.results);
    } catch (e) {
      setError(String(e));
    } finally {
      setSearching(false);
    }
  }

  function toggle(url: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(url) ? next.delete(url) : next.add(url);
      return next;
    });
  }

  async function submit() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const urls = Array.from(selected);
      const s = await startScreening({
        ...subjectFields(),
        data_nascita: isPerson && dataNascita ? dataNascita : undefined,
        cup: cup ? cup.split(",").map((c) => c.trim()) : [],
        // Precedenza: selezionati (web search) → URL singolo → ricerca automatica.
        seed_urls: urls.length > 0 ? urls : undefined,
        seed_url: urls.length === 0 && seedUrl ? seedUrl : undefined,
      });
      setResult(s);
      for (let i = 0; i < 12; i++) {
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

  const submitLabel = busy
    ? "In corso…"
    : selected.size > 0
    ? `Avvia screening (${selected.size} selezionati)`
    : seedUrl
    ? "Avvia screening (URL singolo)"
    : "Avvia screening (ricerca automatica)";

  return (
    <div>
      <Typography variant="h5" gutterBottom>Nuovo screening (prova end-to-end)</Typography>
      <Typography variant="body2" color="text.secondary" gutterBottom>
        Indica il soggetto, poi <strong>cerca gli articoli sul web</strong> e seleziona quelli da
        analizzare — oppure lascia fare la ricerca automatica al workflow. L'esito appare nella
        pagina <strong>Alert</strong>.
      </Typography>

      <Paper sx={{ p: 3, mt: 2, maxWidth: 720 }}>
        <Stack spacing={2}>
          <ToggleButtonGroup
            exclusive size="small" color="primary"
            value={tipo} onChange={onTipoChange} aria-label="tipo di soggetto"
          >
            <ToggleButton value="persona_giuridica">Persona giuridica</ToggleButton>
            <ToggleButton value="persona_fisica">Persona fisica</ToggleButton>
          </ToggleButtonGroup>

          {isPerson ? (
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <TextField label="Cognome" value={cognome}
                onChange={(e) => setCognome(e.target.value)} fullWidth required />
              <TextField label="Nome" value={nome}
                onChange={(e) => setNome(e.target.value)} fullWidth required />
            </Stack>
          ) : (
            <TextField label="Denominazione" value={denominazione}
              onChange={(e) => setDenominazione(e.target.value)} fullWidth required />
          )}

          <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
            <TextField label={isPerson ? "Codice Fiscale (16)" : "CF / P.IVA"} value={cfPiva}
              onChange={(e) => setCfPiva(e.target.value)} fullWidth
              helperText={isPerson ? "Identificatore forte (anti-omonimia)." : undefined} />
            {isPerson && (
              <TextField label="Data di nascita" type="date" value={dataNascita}
                onChange={(e) => setDataNascita(e.target.value)} fullWidth
                InputLabelProps={{ shrink: true }}
                helperText="Facoltativa: disambigua l'omonimia." />
            )}
          </Stack>

          <TextField label="CUP (separati da virgola)" value={cup}
            onChange={(e) => setCup(e.target.value)} fullWidth />

          <Divider textAlign="left">
            <Typography variant="overline" color="text.secondary">Ricerca articoli (web search)</Typography>
          </Divider>

          <Box>
            <Button variant="outlined" startIcon={<SearchIcon />} onClick={search}
              disabled={searching || !hasSubject}>
              {searching ? "Ricerca…" : "Cerca articoli"}
            </Button>
          </Box>

          {results && (
            <Paper variant="outlined" sx={{ p: 0 }}>
              <Box sx={{ px: 2, py: 1, display: "flex", alignItems: "center", gap: 1 }}>
                <Typography variant="body2" color="text.secondary">
                  {results.length} risultati
                </Typography>
                <Chip size="small" label={`provider: ${provider}`} />
                {results.length > 0 && (
                  <Button size="small" onClick={() =>
                    setSelected(selected.size === results.length
                      ? new Set()
                      : new Set(results.map((r) => r.url)))}>
                    {selected.size === results.length ? "Deseleziona tutti" : "Seleziona tutti"}
                  </Button>
                )}
              </Box>
              <Divider />
              {results.length === 0 ? (
                <Typography variant="body2" color="text.secondary" sx={{ p: 2 }}>
                  Nessun articolo trovato. Con il provider <code>mock</code> i risultati sono di
                  esempio; per risultati reali imposta <code>SEARCH_PROVIDER=gdelt</code>.
                </Typography>
              ) : (
                <List dense sx={{ maxHeight: 320, overflow: "auto" }}>
                  {results.map((r) => (
                    <ListItem key={r.url} disablePadding>
                      <ListItemButton onClick={() => toggle(r.url)} dense>
                        <ListItemIcon sx={{ minWidth: 36 }}>
                          <Checkbox edge="start" size="small" tabIndex={-1} disableRipple
                            checked={selected.has(r.url)} />
                        </ListItemIcon>
                        <ListItemText
                          primary={r.title || r.url}
                          secondary={
                            <>
                              <Typography variant="caption" color="text.secondary">
                                {[r.testata, r.data].filter(Boolean).join(" · ")}
                              </Typography>
                              {r.snippet && (
                                <Typography variant="caption" display="block" color="text.secondary"
                                  sx={{ fontStyle: "italic" }}>
                                  “{r.snippet}”
                                </Typography>
                              )}
                              <Link href={r.url} target="_blank" rel="noreferrer"
                                variant="caption" onClick={(e) => e.stopPropagation()}>
                                {r.url}
                              </Link>
                            </>
                          }
                        />
                      </ListItemButton>
                    </ListItem>
                  ))}
                </List>
              )}
            </Paper>
          )}

          <TextField label="URL singolo (override manuale, opzionale)" value={seedUrl}
            onChange={(e) => setSeedUrl(e.target.value)} fullWidth
            helperText="Se valorizzato e senza selezioni, screena solo questo URL (fetch conforme robots.txt)." />

          <Box>
            <Button variant="contained" onClick={submit} disabled={busy || !hasSubject}>
              {busy ? <><CircularProgress size={16} sx={{ mr: 1 }} />In corso…</> : submitLabel}
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
