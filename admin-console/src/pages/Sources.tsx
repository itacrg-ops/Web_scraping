import { useEffect, useState } from "react";
import {
  Alert as MuiAlert, Box, Chip, Paper, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, Typography,
} from "@mui/material";
import {
  getSearchProviders, listSources,
  type SearchProvidersStatus, type Source,
} from "../api";

const credColor = (c: string) =>
  c === "alta" ? "success" : c === "media" ? "warning" : "default";

export default function Sources() {
  const [rows, setRows] = useState<Source[]>([]);
  const [providers, setProviders] = useState<SearchProvidersStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [provError, setProvError] = useState<string | null>(null);

  useEffect(() => {
    listSources().then(setRows).catch((e) => setError(String(e)));
    getSearchProviders().then(setProviders).catch((e) => setProvError(String(e)));
  }, []);

  return (
    <div>
      {/* --- Motori di ricerca web: come vengono SCOPERTI gli articoli --- */}
      <Typography variant="h5" gutterBottom>Motori di ricerca web</Typography>
      <Typography variant="body2" color="text.secondary" gutterBottom>
        Come vengono <strong>scoperti</strong> gli articoli. Gli attivi derivano da
        <code> SEARCH_PROVIDER</code> nel <code>.env</code>; con più motori attivi è
        in funzione il <strong>fan-out</strong> (ricerca parallela, merge per URL e
        boost di corroborazione).
        {providers?.fan_out && (
          <Chip size="small" color="info" label="fan-out attivo" sx={{ ml: 1 }} />
        )}
      </Typography>
      {provError && (
        <MuiAlert severity="warning" sx={{ my: 2 }}>
          Stato motori non disponibile (search-gateway non raggiungibile): {provError}
        </MuiAlert>
      )}
      <TableContainer component={Paper} sx={{ mt: 2 }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Motore</TableCell>
              <TableCell>Tipo</TableCell>
              <TableCell>Accesso</TableCell>
              <TableCell>Stato</TableCell>
              <TableCell>Note</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {(providers?.providers ?? []).map((p) => (
              <TableRow key={p.id}>
                <TableCell>{p.nome}</TableCell>
                <TableCell>{p.tipo}</TableCell>
                <TableCell>{p.keyless ? "keyless" : "a chiave"}</TableCell>
                <TableCell>
                  {p.attivo ? (
                    <Chip size="small" color="success" label="attivo" />
                  ) : !p.configurato ? (
                    <Chip size="small" color="warning" label="non configurato" />
                  ) : (
                    <Chip size="small" label="disponibile" />
                  )}
                </TableCell>
                <TableCell>
                  <Typography variant="caption" color="text.secondary">{p.note}</Typography>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>

      {/* --- Catalogo fonti / feed dati (dichiarativo) --- */}
      <Box sx={{ mt: 5 }}>
        <Typography variant="h5" gutterBottom>Catalogo fonti / feed dati</Typography>
        <Typography variant="body2" color="text.secondary" gutterBottom>
          Elenco <strong>dichiarativo</strong> dei feed previsti (governa credibilità,
          rischio legale e politeness per dominio, §5.1). Nota: questi feed
          <strong> non sono ancora interrogati</strong> dalla pipeline runtime — la
          discovery degli articoli avviene tramite i motori qui sopra. Il registro
          resta il riferimento di governance per l'onboarding delle fonti.
        </Typography>
        {error && <MuiAlert severity="error" sx={{ my: 2 }}>{error}</MuiAlert>}
        <TableContainer component={Paper} sx={{ mt: 2 }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Nome</TableCell>
                <TableCell>Tipo</TableCell>
                <TableCell>Credibilità</TableCell>
                <TableCell>Rischio legale</TableCell>
                <TableCell align="right">Crawl delay (s)</TableCell>
                <TableCell>robots.txt</TableCell>
                <TableCell>Stato</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((s) => (
                <TableRow key={s.id}>
                  <TableCell>{s.nome}</TableCell>
                  <TableCell>{s.tipo}</TableCell>
                  <TableCell><Chip size="small" label={s.credibilita} color={credColor(s.credibilita)} /></TableCell>
                  <TableCell>{s.rischio_legale}</TableCell>
                  <TableCell align="right">{s.crawl_delay_s}</TableCell>
                  <TableCell>{s.respect_robots ? "rispettato" : "—"}</TableCell>
                  <TableCell>{s.attiva ? "attiva" : "sospesa"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </Box>
    </div>
  );
}
