import { useEffect, useRef, useState } from "react";
import { Link as RouterLink, useSearchParams } from "react-router-dom";
import {
  Alert as MuiAlert, Box, Button, Checkbox, Chip, CircularProgress, Divider,
  FormControlLabel, Link, List, ListItem, ListItemButton, ListItemIcon, ListItemText,
  Paper, Stack, Switch, TextField, ToggleButton, ToggleButtonGroup, Typography,
} from "@mui/material";
import SearchIcon from "@mui/icons-material/Search";
import {
  decideName, getAlert, getScreening, searchPreview, similarSubjects, startScreening, updateSubject,
  type Alert, type Credibilita, type Screening, type SearchEngineReport, type SearchResult, type SimilarCandidate,
  type SimilarOut, type TipoSoggetto,
} from "../api";
import { checkCf } from "../codiceFiscale";
import RoleChips from "../components/RoleChips";
import SimilarNamesDialog, { type NameChoice } from "../components/SimilarNamesDialog";
import { ESITO } from "../esito";
import { splitPerson } from "../personName";

// Campi del soggetto che la conferma di un nome simile può sostituire.
type NameFields = { denominazione?: string; cognome?: string; nome?: string; cf_piva?: string;
                    data_nascita?: string; luogo_nascita?: string };
// Solo i campi valorizzati: gli altri restano quelli del modulo.
const definedName = (f: NameFields): NameFields =>
  Object.fromEntries(Object.entries(f).filter(([, v]) => v)) as NameFields;

// Colore del chip credibilità testata.
const credColor = (c?: Credibilita | null): "success" | "warning" | "default" =>
  c === "alta" ? "success" : c === "media" ? "warning" : "default";

// Prova end-to-end: soggetto → (web search o URL) → workflow Temporal →
// Entity Resolution → fetch/estrazione/menzione per articolo → FATF → AMI →
// SVI (mock) → alert persistito. Due tipi di soggetto: giuridica / fisica.
export default function ScreeningPage() {
  const [tipo, setTipo] = useState<TipoSoggetto>("persona_giuridica");
  // Modulo vuoto: valori di esempio (CF/P.IVA, CUP) rimasti cambiando solo il nome
  // attribuirebbero lo screening a un altro soggetto del registro.
  const [denominazione, setDenominazione] = useState("");
  const [cognome, setCognome] = useState("");
  const [nome, setNome] = useState("");
  const [dataNascita, setDataNascita] = useState("");
  const [luogoNascita, setLuogoNascita] = useState("");
  const [cfPiva, setCfPiva] = useState("");
  // Qualificatori di ricerca (persona fisica)
  const [azienda, setAzienda] = useState("");
  const [localita, setLocalita] = useState("");
  const [ruolo, setRuolo] = useState("");
  const [cup, setCup] = useState("");
  const [seedUrl, setSeedUrl] = useState("");

  // Web search
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [provider, setProvider] = useState<string>("");
  const [queryUsed, setQueryUsed] = useState<string>("");
  const [engines, setEngines] = useState<SearchEngineReport[]>([]);
  const [note, setNote] = useState<string | null>(null);
  const [removed, setRemoved] = useState(0);
  const [onlyReliable, setOnlyReliable] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Screening | null>(null);
  const [outcome, setOutcome] = useState<Alert | null>(null);   // alert generato dallo screening
  const [error, setError] = useState<string | null>(null);

  // Nomi simili a soggetti noti: dialogo di conferma (promessa risolta dalla scelta).
  const [similar, setSimilar] = useState<SimilarOut | null>(null);
  const answer = useRef<((c: NameChoice) => void) | null>(null);
  const [checkedName, setCheckedName] = useState<string | null>(null);   // nome già verificato
  const [nameNote, setNameNote] = useState<string | null>(null);

  // Precompilazione da un link (es. «Ripeti lo screening» con il nome corretto).
  const [params] = useSearchParams();
  useEffect(() => {
    const t = params.get("tipo");
    if (t !== "persona_fisica" && t !== "persona_giuridica") return;
    setTipo(t);
    setDenominazione(params.get("denominazione") ?? "");
    setCognome(params.get("cognome") ?? "");
    setNome(params.get("nome") ?? "");
    setCfPiva(params.get("cf_piva") ?? "");
    setCup(params.get("cup") ?? "");
  }, [params]);

  const isPerson = tipo === "persona_fisica";
  const hasSubject = isPerson ? Boolean(cognome && nome) : Boolean(denominazione);
  const typedName = isPerson ? `${cognome} ${nome}`.trim() : denominazione.trim();
  // Controllo live CF ↔ dati anagrafici (persona fisica): feedback immediato.
  const cfCheck = isPerson ? checkCf(cfPiva, nome, cognome, dataNascita) : null;

  function onTipoChange(_: unknown, value: TipoSoggetto | null) {
    if (!value) return;
    setTipo(value);
    setResults(null);
    setSelected(new Set());
    setCfPiva("");   // il CF di una persona non vale per un'impresa (e viceversa)
  }

  // Campi condivisi da ricerca e screening. Il RUOLO non è qui: non entra nella
  // ricerca (sarebbe rumore) — viene aggiunto solo al payload di screening, dove
  // serve alla corroborazione a valle.
  const subjectFields = () => ({
    tipo_soggetto: tipo,
    denominazione: isPerson ? undefined : denominazione,
    nome: isPerson ? nome : undefined,
    cognome: isPerson ? cognome : undefined,
    cf_piva: cfPiva || undefined,
    azienda: isPerson && azienda ? azienda : undefined,
    localita: isPerson && localita ? localita : undefined,
  });

  function fieldsOf(c: SimilarCandidate): NameFields {
    const extra = { cf_piva: c.cf_piva ?? undefined, data_nascita: c.data_nascita ?? undefined,
                    luogo_nascita: c.luogo_nascita ?? undefined };
    return isPerson ? { ...splitPerson(c.denominazione), ...extra } : { denominazione: c.denominazione, ...extra };
  }

  function applyFields(f: NameFields) {
    if (f.denominazione !== undefined) setDenominazione(f.denominazione);
    if (f.cognome !== undefined) setCognome(f.cognome);
    if (f.nome !== undefined) setNome(f.nome);
    if (f.cf_piva !== undefined) setCfPiva(f.cf_piva);
    if (f.data_nascita !== undefined) setDataNascita(f.data_nascita);
    if (f.luogo_nascita !== undefined) setLuogoNascita(f.luogo_nascita);
  }

  // Prima di cercare o avviare: il nome è simile a un soggetto noto (registro o screening
  // passati) o è già stato screenato? Chiede conferma una volta per nome. Restituisce i
  // campi da sostituire ({} = nessuno) o null se l'utente annulla.
  async function checkName(): Promise<NameFields | null> {
    if (checkedName === typedName) return {};
    let data: SimilarOut;
    try {
      data = await similarSubjects({ tipo_soggetto: tipo, denominazione: isPerson ? undefined : denominazione,
                                     cognome: isPerson ? cognome : undefined, nome: isPerson ? nome : undefined });
    } catch {
      return {};   // controllo non disponibile: non blocca lo screening
    }
    if (!data.simili.length && !data.alert_esistenti) {
      setCheckedName(typedName);
      return {};
    }
    setSimilar(data);
    const choice = await new Promise<NameChoice>((resolve) => { answer.current = resolve; });
    setSimilar(null);
    if (choice.action === "annulla") return null;
    try {
      if (choice.action === "usa") {
        const f = fieldsOf(choice.c);
        applyFields(f);
        if (choice.c.subject_id) await decideName(choice.c.subject_id, typedName, "stesso");
        setNameNote(`Usato «${choice.c.denominazione}»` + (choice.c.subject_id
          ? `: «${typedName}» è registrato come sua variante.` : "."));
        setCheckedName(isPerson ? `${f.cognome} ${f.nome}`.trim() : f.denominazione ?? typedName);
        return f;
      }
      if (choice.action === "correggi") {
        await updateSubject(choice.c.subject_id!, { denominazione: typedName });
        setNameNote(`Registro corretto: «${choice.c.denominazione}» ora è «${typedName}» (il vecchio nome resta come variante).`);
      } else if (choice.action === "diverso" && choice.c.subject_id) {
        await decideName(choice.c.subject_id, typedName, "diverso");
        setNameNote(`Registrato: «${typedName}» non è «${choice.c.denominazione}».`);
      }
    } catch (e) {
      setError(String(e));
      return null;
    }
    setCheckedName(typedName);
    return {};
  }

  async function search() {
    const over = await checkName();
    if (over === null) return;
    setSearching(true);
    setError(null);
    setResults(null);
    setNote(null);
    setEngines([]);
    setSelected(new Set());
    try {
      const r = await searchPreview({
        ...subjectFields(), ...definedName(over), mode: "targeted",
        // "Escludi bassa credibilità" = scarta solo le testate note come poco
        // affidabili (blog/UGC); mantiene le sconosciute (non ancora a registro).
        min_credibility: onlyReliable ? "sconosciuta" : undefined,
      });
      setProvider(r.provider);
      setResults(r.results);
      setRemoved(r.removed);
      setQueryUsed(r.query);
      setEngines(r.engines ?? []);
      setNote(r.note ?? null);
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
    const over = await checkName();
    if (over === null) return;
    setBusy(true);
    setError(null);
    setResult(null);
    setOutcome(null);
    try {
      const urls = Array.from(selected);
      const s = await startScreening({
        ...subjectFields(),
        data_nascita: isPerson && dataNascita ? dataNascita : undefined,
        luogo_nascita: isPerson && luogoNascita ? luogoNascita : undefined,
        ...definedName(over),
        ruolo: isPerson && ruolo ? ruolo : undefined,   // solo screening (corroborazione)
        cup: cup ? cup.split(",").map((c) => c.trim()) : [],
        // Precedenza: selezionati (web search) → URL singolo → ricerca automatica.
        seed_urls: urls.length > 0 ? urls : undefined,
        seed_url: urls.length === 0 && seedUrl ? seedUrl : undefined,
      });
      setResult(s);
      // Ricerca, articoli e classificazione possono richiedere un paio di minuti.
      let cur = s;
      for (let i = 0; i < 80 && cur.status === "running"; i++) {
        await new Promise((r) => setTimeout(r, 1500));
        cur = await getScreening(s.id);
        setResult(cur);
      }
      if (cur.alert_id) setOutcome(await getAlert(cur.alert_id).catch(() => null));
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
            {isPerson && (
              <TextField label="Luogo di nascita" value={luogoNascita}
                onChange={(e) => setLuogoNascita(e.target.value)} fullWidth
                helperText="Facoltativo: comune/stato, disambigua l'omonimia." />
            )}
          </Stack>

          {cfCheck && !cfCheck.consistent && cfCheck.warnings.length > 0 && (
            <MuiAlert severity="warning" variant="outlined">
              {cfCheck.warnings.map((w, i) => <div key={i}>{w}</div>)}
            </MuiAlert>
          )}

          {isPerson && (
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <TextField label="Azienda" value={azienda}
                onChange={(e) => setAzienda(e.target.value)} fullWidth
                helperText="Qualificatore forte (in AND nella ricerca)." />
              <TextField label="Località" value={localita}
                onChange={(e) => setLocalita(e.target.value)} fullWidth
                helperText="Qualificatore forte (in AND nella ricerca)." />
              <TextField label="Ruolo" value={ruolo}
                onChange={(e) => setRuolo(e.target.value)} fullWidth
                helperText="Soft: non filtra la ricerca, corrobora sugli articoli." />
            </Stack>
          )}

          <TextField label="CUP (separati da virgola)" value={cup}
            onChange={(e) => setCup(e.target.value)} fullWidth
            helperText="Codice interno dell'intervento: usato per la disambiguazione (Entity Resolution), NON nella ricerca web." />

          <Divider textAlign="left">
            <Typography variant="overline" color="text.secondary">Ricerca articoli (web search)</Typography>
          </Divider>

          <Box sx={{ display: "flex", alignItems: "center", gap: 2, flexWrap: "wrap" }}>
            <Button variant="outlined" startIcon={<SearchIcon />} onClick={search}
              disabled={searching || !hasSubject}>
              {searching ? "Ricerca…" : "Cerca articoli"}
            </Button>
            <FormControlLabel
              control={<Switch size="small" checked={onlyReliable}
                onChange={(e) => setOnlyReliable(e.target.checked)} />}
              label="Escludi fonti a bassa credibilità (blog/UGC)"
            />
          </Box>

          {note && <MuiAlert severity="warning" sx={{ py: 0 }}>{note}</MuiAlert>}

          {results && (
            <Paper variant="outlined" sx={{ p: 0 }}>
              <Box sx={{ px: 2, py: 1, display: "flex", alignItems: "center", gap: 1, flexWrap: "wrap" }}>
                <Typography variant="body2" color="text.secondary">
                  {results.length} risultati
                  {removed > 0 && ` · ${removed} rimossi (stessa testata, credibilità, siti che non sono notizie)`}
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
              {engines.length > 0 ? (
                <EngineReports engines={engines} />
              ) : queryUsed && (
                <Typography variant="caption" color="text.secondary" component="div" sx={{ px: 2, pb: 1 }}>
                  query: <code>{queryUsed}</code>
                </Typography>
              )}
              {results.length === 0 ? (
                <Typography variant="body2" color="text.secondary" sx={{ p: 2 }}>
                  Nessun articolo trovato per questa query
                  {onlyReliable && <> (con il filtro credibilità attivo)</>}.
                  {provider === "mock"
                    ? " Con il provider mock i risultati sono di esempio: per risultati reali imposta SEARCH_PROVIDER (es. searxng,gdelt)."
                    : " Qui sopra: cosa ha risposto ogni motore. Prova il nome senza forma societaria o togli il filtro credibilità."}
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
                          primary={
                            <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                              <span>{r.title || r.url}</span>
                              {r.adverse_query && (
                                <Chip size="small" variant="outlined" color="warning" label="termini avversi"
                                  title="Trovato cercando il nome insieme ai termini avversi (indagato, inchiesta, sequestro…)" />
                              )}
                              {r.testata_credibilita && (
                                <Chip size="small" variant="outlined"
                                  label={r.testata_credibilita}
                                  color={credColor(r.testata_credibilita)} />
                              )}
                            </Box>
                          }
                          secondary={
                            <>
                              <Typography variant="caption" color="text.secondary">
                                {[r.domain || r.testata, r.data].filter(Boolean).join(" · ")}
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

      <SimilarNamesDialog typed={typedName} data={similar} mode="screening"
        onChoice={(c) => answer.current?.(c)} />
      {nameNote && <MuiAlert severity="info" sx={{ mt: 2 }} onClose={() => setNameNote(null)}>{nameNote}</MuiAlert>}
      {error && <MuiAlert severity="error" sx={{ mt: 2 }}>{error}</MuiAlert>}
      {result && (
        <MuiAlert severity={result.status === "completed" ? "success" : result.status === "failed" ? "error" : "info"}
          sx={{ mt: 2 }}>
          Screening <code>{result.id}</code> — stato: <strong>{result.status}</strong>
          {result.alert_id && <> · alert generato: <code>{result.alert_id}</code></>}
          {result.status === "running" && !busy && " — ancora in corso: l'esito comparirà nella pagina Alert."}
        </MuiAlert>
      )}
      {outcome && <Outcome a={outcome} />}
    </div>
  );
}

// Esito dello screening: giudizio del sistema, ruoli negli articoli e possibile PEP.
function Outcome({ a }: { a: Alert }) {
  const [esito, color] = ESITO[a.disposition] ?? [a.disposition, "default"];
  const isPerson = a.tipo_soggetto === "persona_fisica";
  // i ruoli sono già mostrati come chip
  const drivers = (a.drivers ?? []).filter((d) => !d.startsWith("Ruoli negli articoli:"));
  return (
    <Paper variant="outlined" sx={{ p: 2, mt: 2 }}>
      <Box sx={{ display: "flex", alignItems: "center", gap: 1, flexWrap: "wrap" }}>
        <Typography variant="subtitle1" sx={{ mr: 0.5 }}>{a.subject}</Typography>
        <Chip size="small" color={color} label={esito} title={a.disposition} />
        <Chip size="small" variant="outlined" label={`AMI ${a.ami_score} · ${a.risk_level}`} />
        <Box sx={{ flex: 1 }} />
        <Button size="small" component={RouterLink} to={`/alerts?caso=${a.id}`}>Apri il caso</Button>
      </Box>
      {isPerson && (
        <Box sx={{ mt: 1 }}>
          <Typography variant="body2" color="text.secondary">
            {a.roles?.length ? "Ruoli negli articoli:" : "Nessun ruolo indicato accanto al nome negli articoli."}
          </Typography>
          <RoleChips roles={a.roles} pep={a.pep} />
        </Box>
      )}
      {drivers.length > 0 && (
        <Box component="ul" sx={{ m: 0, mt: 1, pl: 2.5 }}>
          {drivers.slice(0, 6).map((d) => (
            <li key={d}><Typography variant="body2">{d}</Typography></li>
          ))}
        </Box>
      )}
    </Paper>
  );
}

// Cosa ha fatto ogni motore: risultati trovati (prima di esclusioni e dedup), query
// eseguite, errori e motori che non hanno risposto. Spiega perché i risultati sono pochi.
function EngineReports({ engines }: { engines: SearchEngineReport[] }) {
  return (
    <Box sx={{ px: 2, pb: 1 }}>
      {engines.map((e) => (
        <Typography key={e.provider} variant="caption" color="text.secondary" component="div"
          sx={{ wordBreak: "break-word" }}>
          <strong>{e.provider}</strong>:{" "}
          {e.error ? (
            <Box component="span" sx={{ color: "error.main" }}>errore — {e.error}</Box>
          ) : (
            `${e.count} trovati`
          )}
          {e.queries.length > 0 && (
            <> · {e.queries.length === 1 ? "query" : `${e.queries.length} query`}:{" "}
              {e.queries.map((q, i) => <code key={i} style={{ marginRight: 6 }}>{q}</code>)}</>
          )}
          {!!e.non_disponibili?.length && <> · non hanno risposto: {e.non_disponibili.join(", ")}</>}
        </Typography>
      ))}
    </Box>
  );
}
