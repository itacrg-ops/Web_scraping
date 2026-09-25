import { Fragment, useEffect, useRef, useState } from "react";
import {
  Alert as MuiAlert, Box, Button, Checkbox, Chip, FormControlLabel, IconButton, Link, Paper, Stack, Switch,
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow, TextField, ToggleButton,
  ToggleButtonGroup, Typography,
} from "@mui/material";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import SaveOutlinedIcon from "@mui/icons-material/SaveOutlined";
import CloseOutlinedIcon from "@mui/icons-material/CloseOutlined";
import FileUploadOutlinedIcon from "@mui/icons-material/FileUploadOutlined";
import DownloadOutlinedIcon from "@mui/icons-material/DownloadOutlined";
import {
  createSubject, decideName, deleteSubject, importSubjects, listSubjectArticles, listSubjects,
  removeSubjectArticle, similarSubjects, updateSubject,
  type SimilarOut, type Subject, type SubjectArticle, type SubjectImportResult, type TipoSoggetto,
} from "../api";
import { checkCf } from "../codiceFiscale";
import { PepChip } from "../components/RoleChips";
import SimilarNamesDialog, { type NameChoice } from "../components/SimilarNamesDialog";
import { splitPerson } from "../personName";

const P_TEXT: Record<string, string> = { si: "riguarda il soggetto", omonimo: "omonimo", non_citato: "non citato" };

// Notizie confermate dai revisori per il soggetto (storico verificato).
function ConfirmedArticles({ subject, onChanged }: { subject: Subject; onChanged: () => void }) {
  const [items, setItems] = useState<SubjectArticle[] | null>(null);
  const load = () => listSubjectArticles(subject.id).then(setItems).catch(() => setItems([]));
  useEffect(() => { load(); }, [subject.id]);   // eslint-disable-line react-hooks/exhaustive-deps
  if (items === null) return <Typography variant="caption">Caricamento…</Typography>;
  if (!items.length) return <Typography variant="caption" color="text.secondary">Nessuna notizia confermata.</Typography>;
  return (
    <Box>
      {items.map((x) => (
        <Box key={x.id} sx={{ display: "flex", alignItems: "flex-start", gap: 1, py: 0.5, borderBottom: 1, borderColor: "divider" }}>
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography variant="body2" sx={{ wordBreak: "break-word" }}>
              {[x.testata, x.data].filter(Boolean).join(" · ")}{" — "}
              <Link href={x.url} target="_blank" rel="noreferrer">{x.title || x.url}</Link>
            </Typography>
            <Box sx={{ display: "flex", gap: 0.5, flexWrap: "wrap", mt: 0.5, alignItems: "center" }}>
              <Chip size="small" label={P_TEXT[x.pertinenza] ?? x.pertinenza}
                color={x.pertinenza === "si" ? "primary" : "default"} variant="outlined" />
              <Chip size="small" label={x.avversa === "si" ? "avversa" : "non avversa"}
                color={x.avversa === "si" ? "error" : "success"} variant="outlined" />
              {x.categorie.map((c) => <Chip key={c} size="small" label={c} variant="outlined" />)}
              <Typography variant="caption" color="text.secondary">
                confermato{x.confirmed_by_name ? ` da ${x.confirmed_by_name}` : ""}
                {x.confirmed_at ? ` il ${new Date(x.confirmed_at).toLocaleDateString("it-IT")}` : ""}
              </Typography>
            </Box>
          </Box>
          <IconButton size="small" aria-label="rimuovi la conferma" title="Rimuovi dallo storico del soggetto"
            onClick={async () => { await removeSubjectArticle(subject.id, x.id); await load(); onChanged(); }}>
            <DeleteOutlineIcon fontSize="small" />
          </IconButton>
        </Box>
      ))}
    </Box>
  );
}

// pep: si/no; cariche: ruoli negli articoli separati da «;» (come i CUP)
const CSV_TEMPLATE =
  "tipo_soggetto,denominazione,nome,cognome,cf_piva,data_nascita,luogo_nascita,cup,ruolo,pep,cariche\n" +
  "persona_giuridica,Italware S.r.l.,,,12345670159,,,E51B21000000001;B22C21000000002,beneficiario,,\n" +
  "persona_fisica,,Anna,Verdi,VRDNNA85M41H501K,1985-08-01,Roma,,RUP,si,sindaco di Bari;AD di Acme S.p.A.\n";

// Cariche (ruoli negli articoli) scritte in un campo di testo, separate da «;».
const splitRoles = (text: string) => text.split(";").map((c) => c.trim()).filter(Boolean);
// Messaggio dell'API senza il codice HTTP («409: Soggetto già inserito…»).
const apiMessage = (e: unknown) => (e instanceof Error ? e.message : String(e)).replace(/^\d{3}: /, "");

interface EditForm {
  denominazione: string; cf_piva: string; data_nascita: string;
  cup: string; ruolo: string; attivo: boolean; pep: boolean; cariche: string;
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
  const [luogoNascita, setLuogoNascita] = useState("");
  const [cfPiva, setCfPiva] = useState("");
  const [cup, setCup] = useState("");
  const [ruolo, setRuolo] = useState("");
  const [cariche, setCariche] = useState("");
  const [pep, setPep] = useState(false);

  // modifica in linea
  const [editingId, setEditingId] = useState<string | null>(null);
  const [edit, setEdit] = useState<EditForm | null>(null);

  // import
  const [importResult, setImportResult] = useState<SubjectImportResult | null>(null);

  // notizie confermate (riga espansa) e controllo dei nomi simili prima di aggiungere
  const [expanded, setExpanded] = useState<string | null>(null);
  const [similar, setSimilar] = useState<SimilarOut | null>(null);
  const answer = useRef<((c: NameChoice) => void) | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const isPerson = tipo === "persona_fisica";
  const canAdd = isPerson ? Boolean(cognome && nome) : Boolean(denominazione);
  const cfCheck = isPerson ? checkCf(cfPiva, nome, cognome, dataNascita) : null;

  async function reload() {
    try { setRows(await listSubjects()); } catch (e) { setError(String(e)); }
  }
  useEffect(() => { reload(); }, []);

  const typedName = isPerson ? `${cognome} ${nome}`.trim() : denominazione.trim();

  // Prima di aggiungere: lo stesso soggetto (o uno con nome simile) è già noto?
  // Restituisce true se si può procedere con l'aggiunta.
  async function checkName(): Promise<boolean> {
    let data: SimilarOut;
    try {
      data = await similarSubjects({ tipo_soggetto: tipo, denominazione: isPerson ? undefined : denominazione,
                                     cognome: isPerson ? cognome : undefined, nome: isPerson ? nome : undefined,
                                     cf_piva: cfPiva.trim() || undefined,
                                     data_nascita: isPerson && dataNascita ? dataNascita : undefined });
    } catch {
      return true;
    }
    if (!data.simili.length && !data.registro_esatto) return true;
    setSimilar(data);
    const choice = await new Promise<NameChoice>((resolve) => { answer.current = resolve; });
    setSimilar(null);
    if (choice.action === "annulla") return false;
    if (choice.action === "prosegui") return true;
    if (choice.action === "usa") {             // nome di uno screening passato: correggi il modulo
      if (isPerson) {
        const { cognome: c, nome: n } = splitPerson(choice.c.denominazione);
        setCognome(c); setNome(n);
      } else {
        setDenominazione(choice.c.denominazione);
      }
      setInfo(`Nome corretto in «${choice.c.denominazione}»: controlla e aggiungi.`);
      return false;
    }
    if (choice.action === "variante") {
      await decideName(choice.c.subject_id!, typedName, "stesso");
      setInfo(`«${typedName}» registrato come variante di «${choice.c.denominazione}» (nessun nuovo soggetto).`);
      setDenominazione(""); setCognome(""); setNome("");
      await reload();
      return false;
    }
    if (choice.action === "diverso" && choice.c.subject_id) {
      await decideName(choice.c.subject_id, typedName, "diverso");
    }
    return true;
  }

  async function add() {
    setBusy(true); setError(null); setInfo(null);
    try {
      if (!(await checkName())) return;
      await createSubject({
        tipo_soggetto: tipo,
        denominazione: isPerson ? undefined : denominazione,
        nome: isPerson ? nome : undefined,
        cognome: isPerson ? cognome : undefined,
        data_nascita: isPerson && dataNascita ? dataNascita : undefined,
        luogo_nascita: isPerson && luogoNascita ? luogoNascita : undefined,
        cf_piva: cfPiva || undefined,
        cup: cup ? cup.split(",").map((c) => c.trim()).filter(Boolean) : [],
        ruolo: ruolo || undefined,
        pep: isPerson ? pep : undefined,
        cariche: isPerson ? splitRoles(cariche) : undefined,
      });
      setDenominazione(""); setCognome(""); setNome("");
      setDataNascita(""); setLuogoNascita(""); setCfPiva(""); setCup(""); setRuolo("");
      setCariche(""); setPep(false);
      await reload();
    } catch (e) { setError(apiMessage(e)); } finally { setBusy(false); }
  }

  function startEdit(s: Subject) {
    setEditingId(s.id);
    setEdit({
      denominazione: s.denominazione, cf_piva: s.cf_piva ?? "",
      data_nascita: s.data_nascita ?? "", cup: s.cup.join(", "),
      ruolo: s.ruolo ?? "", attivo: s.attivo, pep: !!s.pep, cariche: (s.cariche ?? []).join("; "),
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
        pep: edit.pep,
        cariche: splitRoles(edit.cariche),
      });
      setEditingId(null); setEdit(null);
      await reload();
    } catch (e) { setError(apiMessage(e)); }
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
              <TextField label="Luogo di nascita" value={luogoNascita}
                onChange={(e) => setLuogoNascita(e.target.value)} fullWidth
                helperText="Comune/stato: disambigua l'omonimia." />
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

          {isPerson && (
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems={{ sm: "center" }}>
              <TextField label="Cariche (separate da ;)" value={cariche} onChange={(e) => setCariche(e.target.value)}
                fullWidth helperText="Ruoli negli articoli, es. sindaco di Bari; AD di Acme S.p.A." />
              <FormControlLabel sx={{ whiteSpace: "nowrap" }} label="PEP (verificata)"
                control={<Checkbox color="secondary" checked={pep} onChange={(e) => setPep(e.target.checked)} />} />
            </Stack>
          )}

          {cfCheck && !cfCheck.consistent && cfCheck.warnings.length > 0 && (
            <MuiAlert severity="warning" variant="outlined">
              {cfCheck.warnings.map((w, i) => <div key={i}>{w}</div>)}
            </MuiAlert>
          )}

          <Box>
            <Button variant="contained" onClick={add} disabled={busy || !canAdd}>
              {busy ? "Salvataggio…" : "Aggiungi al registro"}
            </Button>
          </Box>
        </Stack>
      </Paper>

      <SimilarNamesDialog typed={typedName} data={similar} mode="registro" onChoice={(c) => answer.current?.(c)} />
      {info && <MuiAlert severity="info" sx={{ my: 2 }} onClose={() => setInfo(null)}>{info}</MuiAlert>}
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
              <TableCell>Ruolo · cariche</TableCell>
              <TableCell>Notizie</TableCell>
              <TableCell>Attivo</TableCell>
              <TableCell align="right">Azioni</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((s) => {
              const editing = editingId === s.id && edit;
              return (
                <Fragment key={s.id}>
                <TableRow>
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
                        <TextField size="small" variant="standard" value={edit!.ruolo} placeholder="ruolo"
                          onChange={(e) => setE({ ruolo: e.target.value })} inputProps={{ "aria-label": "ruolo" }} />
                        {s.tipo_soggetto === "persona_fisica" && (
                          <>
                            <TextField size="small" variant="standard" fullWidth value={edit!.cariche} sx={{ mt: 0.5 }}
                              onChange={(e) => setE({ cariche: e.target.value })} placeholder="cariche: carica 1; carica 2"
                              inputProps={{ "aria-label": "cariche" }} />
                            <FormControlLabel label={<Typography variant="caption">PEP</Typography>}
                              control={<Checkbox size="small" color="secondary" checked={edit!.pep}
                                onChange={(e) => setE({ pep: e.target.checked })} />} />
                          </>
                        )}
                      </TableCell>
                      <TableCell>{s.articoli_confermati || "—"}</TableCell>
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
                      <TableCell>
                        {s.denominazione}
                        {s.pep && <PepChip small />}
                        {!!s.alias?.length && (
                          <Typography variant="caption" color="text.secondary" component="div"
                            title="Varianti confermate dai revisori: l'Entity Resolution le riconosce come questo soggetto">
                            varianti: {s.alias.join(", ")}
                          </Typography>
                        )}
                        {!!s.distinti?.length && (
                          <Typography variant="caption" color="text.secondary" component="div"
                            title="Nomi simili confermati come altri soggetti: non vengono confusi con questo">
                            diverso da: {s.distinti.join(", ")}
                          </Typography>
                        )}
                      </TableCell>
                      <TableCell>{s.cf_piva ?? "—"}</TableCell>
                      <TableCell>{s.data_nascita ?? "—"}</TableCell>
                      <TableCell>{s.cup.join(", ") || "—"}</TableCell>
                      <TableCell>
                        {s.ruolo ?? (s.cariche?.length ? "" : "—")}
                        {!!s.cariche?.length && (
                          <Typography variant="caption" color="text.secondary" component="div"
                            title="Cariche negli articoli, confermate dai revisori">
                            cariche: {s.cariche.join("; ")}
                          </Typography>
                        )}
                      </TableCell>
                      <TableCell>
                        {s.articoli_confermati ? (
                          <Button size="small" sx={{ whiteSpace: "nowrap" }}
                            onClick={() => setExpanded(expanded === s.id ? null : s.id)}>
                            {s.articoli_confermati} confermat{s.articoli_confermati === 1 ? "a" : "e"}
                          </Button>
                        ) : "—"}
                      </TableCell>
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
                {expanded === s.id && (
                  <TableRow>
                    <TableCell colSpan={9} sx={{ bgcolor: "action.hover" }}>
                      <Typography variant="subtitle2" gutterBottom>Notizie confermate dai revisori</Typography>
                      <ConfirmedArticles subject={s} onChanged={reload} />
                    </TableCell>
                  </TableRow>
                )}
                </Fragment>
              );
            })}
            {rows.length === 0 && (
              <TableRow><TableCell colSpan={9}>
                <Typography variant="body2" color="text.secondary" sx={{ p: 1 }}>Registro vuoto.</Typography>
              </TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>
    </div>
  );
}
