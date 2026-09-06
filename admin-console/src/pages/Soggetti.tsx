import { useEffect, useState } from "react";
import {
  Alert as MuiAlert, Box, Button, Chip, IconButton, Paper, Stack, Table, TableBody,
  TableCell, TableContainer, TableHead, TableRow, TextField, ToggleButton,
  ToggleButtonGroup, Typography,
} from "@mui/material";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import {
  createSubject, deleteSubject, listSubjects, type Subject, type TipoSoggetto,
} from "../api";

// Registro dei soggetti noti (anti-omonimia, §8): beneficiari/attuatori e
// relativi UBO/RUP/rappresentanti. In produzione sincronizzato da
// ReGiS/OpenCoesione/InfoCamere; qui gestibile a mano per il pilota.
export default function Soggetti() {
  const [rows, setRows] = useState<Subject[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [tipo, setTipo] = useState<TipoSoggetto>("persona_giuridica");
  const [denominazione, setDenominazione] = useState("");
  const [cognome, setCognome] = useState("");
  const [nome, setNome] = useState("");
  const [dataNascita, setDataNascita] = useState("");
  const [cfPiva, setCfPiva] = useState("");
  const [cup, setCup] = useState("");
  const [ruolo, setRuolo] = useState("");

  const isPerson = tipo === "persona_fisica";
  const canAdd = isPerson ? Boolean(cognome && nome) : Boolean(denominazione);

  async function reload() {
    try {
      setRows(await listSubjects());
    } catch (e) {
      setError(String(e));
    }
  }
  useEffect(() => { reload(); }, []);

  async function add() {
    setBusy(true);
    setError(null);
    try {
      await createSubject({
        tipo_soggetto: tipo,
        denominazione: isPerson ? undefined : denominazione,
        nome: isPerson ? nome : undefined,
        cognome: isPerson ? cognome : undefined,
        data_nascita: isPerson && dataNascita ? dataNascita : undefined,
        cf_piva: cfPiva || undefined,
        cup: cup ? cup.split(",").map((c) => c.trim()).filter(Boolean) : [],
        ruolo: ruolo || undefined,
      });
      setDenominazione(""); setCognome(""); setNome("");
      setDataNascita(""); setCfPiva(""); setCup(""); setRuolo("");
      await reload();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string, label: string) {
    if (!window.confirm(`Rimuovere "${label}" dal registro?`)) return;
    setError(null);
    try {
      await deleteSubject(id);
      await reload();
    } catch (e) {
      setError(String(e));
    }
  }

  return (
    <div>
      <Typography variant="h5" gutterBottom>Soggetti (registro anti-omonimia)</Typography>
      <Typography variant="body2" color="text.secondary" gutterBottom>
        Registro dei soggetti noti su cui l'<strong>Entity Resolution</strong> disambigua prima
        del giudizio (§8). In produzione è sincronizzato da ReGiS/OpenCoesione/InfoCamere; qui
        puoi aggiungere un beneficiario con il suo <strong>CF/P.IVA</strong> per ottenere un match
        deterministico allo screening.
      </Typography>

      <Paper sx={{ p: 3, mt: 2, maxWidth: 760 }}>
        <Stack spacing={2}>
          <ToggleButtonGroup exclusive size="small" color="primary" value={tipo}
            onChange={(_, v: TipoSoggetto | null) => v && setTipo(v)}>
            <ToggleButton value="persona_giuridica">Persona giuridica</ToggleButton>
            <ToggleButton value="persona_fisica">Persona fisica</ToggleButton>
          </ToggleButtonGroup>

          {isPerson ? (
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <TextField label="Cognome" value={cognome} onChange={(e) => setCognome(e.target.value)} fullWidth required />
              <TextField label="Nome" value={nome} onChange={(e) => setNome(e.target.value)} fullWidth required />
              <TextField label="Data di nascita" type="date" value={dataNascita}
                onChange={(e) => setDataNascita(e.target.value)} fullWidth InputLabelProps={{ shrink: true }} />
            </Stack>
          ) : (
            <TextField label="Denominazione" value={denominazione}
              onChange={(e) => setDenominazione(e.target.value)} fullWidth required />
          )}

          <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
            <TextField label={isPerson ? "Codice Fiscale (16)" : "CF / P.IVA"} value={cfPiva}
              onChange={(e) => setCfPiva(e.target.value)} fullWidth
              helperText="Identificatore forte: abilita il match deterministico." />
            <TextField label="CUP (separati da virgola)" value={cup}
              onChange={(e) => setCup(e.target.value)} fullWidth />
            <TextField label="Ruolo" value={ruolo} onChange={(e) => setRuolo(e.target.value)} fullWidth
              helperText="es. beneficiario, RUP, legale rappresentante" />
          </Stack>

          <Box>
            <Button variant="contained" onClick={add} disabled={busy || !canAdd}>
              {busy ? "Salvataggio…" : "Aggiungi al registro"}
            </Button>
          </Box>
        </Stack>
      </Paper>

      {error && <MuiAlert severity="error" sx={{ my: 2 }}>{error}</MuiAlert>}

      <TableContainer component={Paper} sx={{ mt: 2 }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Tipo</TableCell>
              <TableCell>Denominazione</TableCell>
              <TableCell>CF/P.IVA</TableCell>
              <TableCell>Data nascita</TableCell>
              <TableCell>CUP</TableCell>
              <TableCell>Ruolo</TableCell>
              <TableCell align="right">Azioni</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((s) => (
              <TableRow key={s.id}>
                <TableCell>
                  <Chip size="small" variant="outlined"
                    label={s.tipo_soggetto === "persona_fisica" ? "PF" : "PG"}
                    color={s.tipo_soggetto === "persona_fisica" ? "info" : "default"} />
                </TableCell>
                <TableCell>{s.denominazione}</TableCell>
                <TableCell>{s.cf_piva ?? "—"}</TableCell>
                <TableCell>{s.data_nascita ?? "—"}</TableCell>
                <TableCell>{s.cup.join(", ") || "—"}</TableCell>
                <TableCell>{s.ruolo ?? "—"}</TableCell>
                <TableCell align="right">
                  <IconButton size="small" aria-label="elimina"
                    onClick={() => remove(s.id, s.denominazione)}>
                    <DeleteOutlineIcon fontSize="small" />
                  </IconButton>
                </TableCell>
              </TableRow>
            ))}
            {rows.length === 0 && (
              <TableRow><TableCell colSpan={7}>
                <Typography variant="body2" color="text.secondary" sx={{ p: 1 }}>
                  Registro vuoto.
                </Typography>
              </TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>
    </div>
  );
}
