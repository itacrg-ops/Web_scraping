import { useEffect, useState } from "react";
import {
  Alert as MuiAlert, Chip, Paper, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, Typography,
} from "@mui/material";
import { listAlerts, type Alert } from "../api";

export default function Alerts() {
  const [rows, setRows] = useState<Alert[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listAlerts().then(setRows).catch((e) => setError(String(e)));
  }, []);

  return (
    <div>
      <Typography variant="h5" gutterBottom>Alert (sintesi)</Typography>
      <Typography variant="body2" color="text.secondary" gutterBottom>
        Vista di monitoraggio. La lavorazione investigativa (triage, dossier,
        network analysis, disposizione) avviene in <strong>SAS Visual Investigator</strong>.
      </Typography>
      {error && <MuiAlert severity="error" sx={{ my: 2 }}>{error}</MuiAlert>}
      <TableContainer component={Paper} sx={{ mt: 2 }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Soggetto</TableCell>
              <TableCell>CF/P.IVA</TableCell>
              <TableCell>CUP</TableCell>
              <TableCell align="right">AMI</TableCell>
              <TableCell>Rischio</TableCell>
              <TableCell>Entity Resolution</TableCell>
              <TableCell>Disposizione</TableCell>
              <TableCell>SVI</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((a) => (
              <TableRow key={a.id}>
                <TableCell>{a.subject}</TableCell>
                <TableCell>{a.cf_piva ?? "—"}</TableCell>
                <TableCell>{a.cup.join(", ")}</TableCell>
                <TableCell align="right">{a.ami_score}</TableCell>
                <TableCell>
                  <Chip size="small" label={a.risk_level}
                    color={a.risk_level === "ALTO" ? "error" : "warning"} />
                </TableCell>
                <TableCell>
                  {a.entity_resolution
                    ? `${a.entity_resolution.method} (${a.entity_resolution.confidence.toFixed(2)})`
                    : "—"}
                </TableCell>
                <TableCell>{a.disposition}</TableCell>
                <TableCell>{a.svi_alert_id ?? "—"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </div>
  );
}
