import { useEffect, useState } from "react";
import {
  Alert as MuiAlert, Chip, Paper, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, Typography,
} from "@mui/material";
import { listSources, type Source } from "../api";

const credColor = (c: string) =>
  c === "alta" ? "success" : c === "media" ? "warning" : "default";

export default function Sources() {
  const [rows, setRows] = useState<Source[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listSources().then(setRows).catch((e) => setError(String(e)));
  }, []);

  return (
    <div>
      <Typography variant="h5" gutterBottom>Registro fonti</Typography>
      <Typography variant="body2" color="text.secondary" gutterBottom>
        Credibilità, rischio legale e politeness per dominio (§5.1). La modifica
        scrive sull'API, che applica validazione e audit.
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
    </div>
  );
}
