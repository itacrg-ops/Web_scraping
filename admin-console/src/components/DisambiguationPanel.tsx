// Caso «Da disambiguare»: l'Entity Resolution non ha stabilito CHI è il soggetto e il
// sistema non ha valutato le notizie (anti-omonimia: nessun giudizio senza identità).
// Qui decide il revisore: è uno dei soggetti del registro proposti (lo screening si
// ripete con quell'identità, registrata come «scelta del revisore»), è un altro
// soggetto (non viene più proposto), oppure non è nel registro e va inserito.
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Alert as MuiAlert, Box, Button, Paper, Typography } from "@mui/material";
import { createSubject, decideName, similarSubjects, type Alert, type ErSubject } from "../api";
import { splitPerson } from "../personName";

// Avviso generico dell'ER (già detto dalla spiegazione): non ripeterlo.
const GENERIC = /^Disambiguazione non conclusiva/;

function explanation(a: Alert, candidates: number): string {
  const er = a.entity_resolution;
  if (er?.method === "incoerenza_CF_dati_anagrafici") {
    return "Il codice fiscale indicato non corrisponde a nome, cognome o data di nascita: correggi i dati "
      + "e ripeti lo screening.";
  }
  if (candidates > 1) {
    return `Più soggetti del registro hanno un nome simile a «${a.subject}»: senza un'identità certa il `
      + "sistema non valuta le notizie. Indica quale è, oppure che è un altro soggetto.";
  }
  if (candidates === 1) {
    return `«${a.subject}» potrebbe essere un soggetto del registro, ma i dati non bastano a stabilirlo `
      + "(omonimia). Indica se è lui.";
  }
  return `«${a.subject}» non è nel registro dei soggetti noti: senza un'identità certa il sistema non valuta `
    + "le notizie (un nome può appartenere a più persone o imprese). Se è il soggetto che intendi, "
    + "inseriscilo nel registro e ripeti lo screening.";
}

function Candidate({ c, busy, onItIs, onOther }: {
  c: ErSubject; busy: boolean; onItIs: () => void; onOther: () => void;
}) {
  const person = c.tipo === "persona_fisica";
  const born = [c.data_nascita && `nato/a il ${c.data_nascita}`, c.luogo_nascita && `a ${c.luogo_nascita}`]
    .filter(Boolean).join(" ");
  const data = [
    c.cf_piva ? `${person ? "CF" : "CF/P.IVA"} ${c.cf_piva}` : `senza ${person ? "codice fiscale" : "CF/P.IVA"}`,
    born, c.ruolo, c.cup?.length ? `CUP ${c.cup.join(", ")}` : "",
  ].filter(Boolean).join(" · ");
  return (
    <Paper variant="outlined" sx={{ p: 1.25, mt: 1 }} role="group" aria-label={`Candidato ${c.denominazione}`}>
      <Typography variant="body2">
        <strong>{c.denominazione}</strong>
        {typeof c.score === "number" && (
          <Typography component="span" variant="caption" color="text.secondary">
            {" "}· nome simile al {Math.round(c.score * 100)}%
          </Typography>
        )}
      </Typography>
      <Typography variant="caption" color="text.secondary" component="div">{data}</Typography>
      <Box sx={{ display: "flex", gap: 1, mt: 0.75, flexWrap: "wrap" }}>
        <Button size="small" variant="contained" disabled={busy} onClick={onItIs}>È lui: ripeti lo screening</Button>
        <Button size="small" disabled={busy} onClick={onOther}>È un altro soggetto</Button>
      </Box>
    </Paper>
  );
}

export default function DisambiguationPanel({ a }: { a: Alert }) {
  const navigate = useNavigate();
  const er = a.entity_resolution;
  const [busy, setBusy] = useState(false);
  const [others, setOthers] = useState<string[]>([]);   // dichiarati «altro soggetto»
  const [error, setError] = useState<string | null>(null);
  const isPerson = a.tipo_soggetto === "persona_fisica";
  const all = er?.candidates ?? [];
  const candidates = all.filter((c) => !others.includes(c.id));
  const warnings = (er?.warnings ?? []).filter((w) => !GENERIC.test(w));
  const canAdd = candidates.length === 0 && er?.method !== "incoerenza_CF_dati_anagrafici";

  // Screening dello stesso nome, con l'identità indicata (se c'è).
  const rescreen = (subject?: { id: string; denominazione: string }) => {
    const q = new URLSearchParams({ tipo: isPerson ? "persona_fisica" : "persona_giuridica" });
    if (isPerson) {
      const { cognome, nome } = splitPerson(a.subject);
      q.set("cognome", cognome);
      q.set("nome", nome);
    } else {
      q.set("denominazione", a.subject);
    }
    if (a.cup.length) q.set("cup", a.cup.join(","));
    if (subject) {
      q.set("subject_id", subject.id);
      q.set("soggetto", subject.denominazione);
    }
    navigate(`/screening?${q}`);
  };

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  // È lui: il nome del caso diventa una sua variante confermata (se è diverso da quello
  // del registro), poi lo screening si ripete con la sua identità.
  const itIs = (c: ErSubject) => run(async () => {
    try {
      await decideName(c.id, a.subject, "stesso");
    } catch (e) {
      if (!String(e).includes("è già il nome")) throw e;
    }
    rescreen(c);
  });

  const other = (c: ErSubject) => run(async () => {
    await decideName(c.id, a.subject, "diverso");
    setOthers((o) => [...o, c.id]);
  });

  // Non è nel registro: lo inserisce con i dati del caso (CF/P.IVA e CUP indicati allo
  // screening; gli altri dati si completano dalla pagina Soggetti) e ripete lo screening.
  // Un CF/P.IVA che l'ER ha trovato su un ALTRO soggetto (conflitto) non è il suo.
  const cfOfOther = (er?.method ?? "").startsWith("conflitto_CF");
  const addAndRescreen = () => run(async () => {
    const base = { tipo_soggetto: isPerson ? "persona_fisica" as const : "persona_giuridica" as const,
                   cf_piva: (!cfOfOther && a.cf_piva) || undefined, cup: a.cup };
    const name = isPerson ? splitPerson(a.subject) : { denominazione: a.subject };
    try {
      const s = await createSubject({ ...base, ...name });
      rescreen({ id: s.id, denominazione: s.denominazione });
    } catch (e) {
      // già inserito nel frattempo (stesso nome, o stesso CF/P.IVA): è lui, per la stessa
      // regola dell'API che rifiuta il doppione
      if (!String(e).includes("409")) throw e;
      const same = (await similarSubjects({ tipo_soggetto: base.tipo_soggetto, ...name,
                                            cf_piva: base.cf_piva })).registro_esatto;
      if (!same?.subject_id) throw e;
      rescreen({ id: same.subject_id, denominazione: same.denominazione });
    }
  });

  return (
    <MuiAlert severity="info" sx={{ mb: 2 }} aria-label="Da disambiguare">
      <Typography variant="subtitle2">Da disambiguare: chi è il soggetto?</Typography>
      <Typography variant="body2">{explanation(a, candidates.length)}</Typography>
      {warnings.length > 0 && (
        <Box component="ul" sx={{ m: 0, mt: 0.5, pl: 2.5 }}>
          {warnings.map((w) => (
            <li key={w}><Typography variant="caption" color="text.secondary">{w}</Typography></li>
          ))}
        </Box>
      )}
      {candidates.map((c) => (
        <Candidate key={c.id} c={c} busy={busy} onItIs={() => itIs(c)} onOther={() => other(c)} />
      ))}
      {others.length > 0 && (
        <Typography variant="caption" component="div" sx={{ mt: 1 }}>
          Registrato: «{a.subject}» non è {all.filter((c) => others.includes(c.id))
            .map((c) => `«${c.denominazione}»`).join(", ")} (non verrà più proposto).
        </Typography>
      )}
      <Box sx={{ display: "flex", gap: 1, mt: 1.25, flexWrap: "wrap" }}>
        {canAdd && (
          <Button size="small" variant="contained" disabled={busy} onClick={addAndRescreen}>
            Inserisci nel registro e ripeti lo screening
          </Button>
        )}
        <Button size="small" disabled={busy} onClick={() => rescreen()}
          title="Apre lo screening con lo stesso nome, per correggere o aggiungere i dati (CF, data di nascita)">
          Ripeti lo screening
        </Button>
      </Box>
      {error && <MuiAlert severity="error" sx={{ mt: 1 }}>{error}</MuiAlert>}
    </MuiAlert>
  );
}
