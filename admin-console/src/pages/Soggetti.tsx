import { useEffect, useState } from "react";
import {
  Alert as MuiAlert, Box, Button, Chip, IconButton, Paper, Stack, Switch, Table, TableBody,
  TableCell, TableContainer, TableHead, TableRow, TextField, ToggleButton,
  ToggleButtonGroup, Typography,
} from "@mui/material";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import SaveOutlinedIcon from "@mui/icons-material/SaveOutlined";
import CloseOutlinedIcon from "@mui/icons-material/CloseOutlined";
import FileUploadOutlinedIcon from "@mui/icons-material/FileUploadOutlined";
import DownloadOutlinedIcon from "@mui/icons-material/DownloadOutlined";
import {
  createSubject, deleteSubject, importSubjects, listSubjects, updateSubject,
  type Subject, type SubjectImportResult, type TipoSoggetto,
} from "../api";

const CSV_TEMPLATE =
  "tipo_soggetto,denominazione,nome,cognome,cf_piva,data_nascita,cup,ruolo\n" +
  "persona_giuridica,Italware S.r.l.,,,12345670159,,E51B21000000001;B22C21000000002,beneficiario\n" +
  "persona_fisica,,Anna,Verdi,VRDNNA85M41H501K,1985-08-01,,RUP\n";

interface EditForm {
  denominazione: string; cf_piva: string; data_nascita: string;
  cup: string; ruolo: string; attivo: boolean;
}

export default function Soggetti() {
  const [rows, setRows] = useState<Subject[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // form "aggiungi"
  const [tipo, setTipo] = useState<TipoSoggetto>("persona_giuridica");
  const [denominazione, setDenominazione] = useState("");
  const [cognome, setCognome] = useState("");
  const [nome, setNome] = useState("");
  const [dataNascita, setDataNascita] = useState("");
  const [cfPiva, setCfPiva] = useState("");
  const [cup, setCup] = useState("");
  const [ruolo, setRuolo] = useState("");

  // modifica in linea
  const [editingId, setEditingId] = useState<string | null>(null);
  const [edit, setEdit] = useState<EditForm | null>(null);

  // import
  const [importResult, setImportResult] = useState<SubjectImportResult | null>(null);

  const isPerson = tipo === "persona_fisica";
  const canAdd = isPerson ? Boolean(cognome && nome) : Boolean(denominazione);

  async function reload() {
    try { setRows(await listSubjects()); } catch (e) { setError(String(e)); }
  }
  useEffect(() => { reload(); }, []);

  async function add() {
    setBusy(true); setError(null);
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
    } catch (e) { setError(String(e)); } finally { setBusy(false); }
  }

  function startEdit(s: Subject) {
    setEditingId(s.id);
    setEdit({
      denominazione: s.denominazione, cf_piva: s.cf_piva ?? "",
      data_nascita: s.data_nascita ?? "", cup: s.cup.join(", "),
      ruolo: s.ruolo ?? "", attivo: s.attivo,
    });
  }

  async function saveEdit() {
    if (!editingId || !edit) return;
    if (!edit.denominazione.trim()) { setError("La denominazione non può essere vuota"); return; }
    setError(null);
    try {
      await updateSubject(editingId, {
        denominazione: edit.denominazione.trim(),
        cf_piva: edit.cf_piva,
        data_nascita: edit.data_nascita,
        cup: edit.cup ? edit.cup.split(",").map((c) => c.trim()).filter(Boolean) : [],
        ruolo: edit.ruolo,
        attivo: edit.attivo,
      });
      setEditingId(null); setEdit(null);
      await reload();
    } catch (e) { setError(String(e)); }
  }

  async function remove(id: string, label: string) {
    if (!window.confirm(`Rimuovere "${label}" dal registro?`)) return;
    setError(null);
    try { await deleteSubject(id); await reload(); } catch (e) { setError(String(e)); }
  }

  async function onImportFile(file: File) {
    setError(null); setImportResult(null);
    try {
      const text = await file.text();
      const res = await importSubjects(text);
      setImportResult(res);
      await reload();
    } catch (e) { setError(String(e)); }
  }

  function downloadTemplate() {
    const blob = new Blob([CSV_TEMPLATE], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "soggetti_template.csv"; a.click();
    URL.revokeObjectURL(url);
  }

  const setE = (patch: Partial<EditForm>) => setEdit((p) => (p ? { ...p, ...patch } : p));

  return (
    <div>
      <Typography variant="h5" gutterBottom>Soggetti (registro anti-omonimia)</Typography>
      <Typography variant="body2" color="text.secondary" gutterBottom>
        Registro dei soggetti noti su cui l'<strong>Entity Resolution</strong> disambigua prima
        del giudizio (§8). In produzione sincronizzato da ReGiS/OpenCoesione/InfoCamere; qui puoi
        aggiungere/modificare/importare. Un <strong>CF/P.IVA</strong> a registro abilita il match
        deterministico.
      </Typography>

      <Paper sx={{ p: 3, mt: 2, maxWidth: 820 }}>
        <Stack spacing={2}>
          <Box sx={{ display: "flex", alignItems: "center", gap: 2, flexWrap: "wrap" }}>
            <ToggleButtonGroup exclusive size="small" color="primary" value={tipo}
              onChange={(_, v: TipoSoggetto | null) => v && setTipo(v)}>
              <ToggleButton value="persona_giuridica">Persona giuridica</ToggleButton>
              <ToggleButton value="persona_fisica">Persona fisica</ToggleButton>
            </ToggleButtonGroup>
            <Box sx={{ flexGrow: 1 }} />
            <Button component="label" size="small" variant="outlined" startIcon={<FileUploadOutlinedIcon />}>
              Importa CSV
              <input hidden type="file" accept=".csv,text/csv"
                onChange={(e) => { const f = e.target.files?.[0]; if (f) onImportFile(f); e.target.value = ""; }} />
            </Button>
            <Button size="small" startIcon={<DownloadOutlinedIcon />} onClick={downloadTemplate}>
              Template
            </Button>
          </Box>

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
      {importResult && (
        <MuiAlert severity={importResult.errors.length ? "warning" : "success"} sx={{ my: 2 }}
          onClose={() => setImportResult(null)}>
          Import: {importResult.created} creati, {importResult.updated} aggiornati
          {importResult.errors.length > 0 && (
            <>, {importResult.errors.length} righe con errori:
              <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                {importResult.errors.slice(0, 5).map((er, i) => (
                  <li key={i}><Typography variant="caption">{er}</Typography></li>
                ))}
              </ul>
            </>
          )}
        </MuiAlert>
      )}

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
              <TableCell>Attivo</TableCell>
              <TableCell align="right">Azioni</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((s) => {
              const editing = editingId === s.id && edit;
              return (
                <TableRow key={s.id}>
                  <TableCell>
                    <Chip size="small" variant="outlined"
                      label={s.tipo_soggetto === "persona_fisica" ? "PF" : "PG"}
                      color={s.tipo_soggetto === "persona_fisica" ? "info" : "default"} />
                  </TableCell>
                  {editing ? (
                    <>
                      <TableCell>
                        <TextField size="small" variant="standard" fullWidth value={edit!.denominazione}
                          onChange={(e) => setE({ denominazione: e.target.value })} />
                      </TableCell>
                      <TableCell>
                        <TextField size="small" variant="standard" value={edit!.cf_piva}
                          onChange={(e) => setE({ cf_piva: e.target.value })} />
                      </TableCell>
                      <TableCell>
                        <TextField size="small" variant="standard" type="date" value={edit!.data_nascita}
                          onChange={(e) => setE({ data_nascita: e.target.value })}
                          InputLabelProps={{ shrink: true }} />
                      </TableCell>
                      <TableCell>
                        <TextField size="small" variant="standard" value={edit!.cup}
                          onChange={(e) => setE({ cup: e.target.value })} placeholder="CUP1, CUP2" />
                      </TableCell>
                      <TableCell>
                        <TextField size="small" variant="standard" value={edit!.ruolo}
                          onChange={(e) => setE({ ruolo: e.target.value })} />
                      </TableCell>
                      <TableCell>
                        <Switch size="small" checked={edit!.attivo}
                          onChange={(e) => setE({ attivo: e.target.checked })} />
                      </TableCell>
                      <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>
                        <IconButton size="small" aria-label="salva" color="primary" onClick={saveEdit}>
                          <SaveOutlinedIcon fontSize="small" />
                        </IconButton>
                        <IconButton size="small" aria-label="annulla"
                          onClick={() => { setEditingId(null); setEdit(null); }}>
                          <CloseOutlinedIcon fontSize="small" />
                        </IconButton>
                      </TableCell>
                    </>
                  ) : (
                    <>
                      <TableCell>{s.denominazione}</TableCell>
                      <TableCell>{s.cf_piva ?? "—"}</TableCell>
                      <TableCell>{s.data_nascita ?? "—"}</TableCell>
                      <TableCell>{s.cup.join(", ") || "—"}</TableCell>
                      <TableCell>{s.ruolo ?? "—"}</TableCell>
                      <TableCell>
                        <Chip size="small" label={s.attivo ? "sì" : "no"}
                          color={s.attivo ? "success" : "default"} variant="outlined" />
                      </TableCell>
                      <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>
                        <IconButton size="small" aria-label="modifica" onClick={() => startEdit(s)}>
                          <EditOutlinedIcon fontSize="small" />
                        </IconButton>
                        <IconButton size="small" aria-label="elimina" onClick={() => remove(s.id, s.denominazione)}>
                          <DeleteOutlineIcon fontSize="small" />
                        </IconButton>
                      </TableCell>
                    </>
                  )}
                </TableRow>
              );
            })}
            {rows.length === 0 && (
              <TableRow><TableCell colSpan={8}>
                <Typography variant="body2" color="text.secondary" sx={{ p: 1 }}>Registro vuoto.</Typography>
              </TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>
    </div>
  );
}
