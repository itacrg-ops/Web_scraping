// Corpo della scheda del caso (nel pannello laterale): esito del sistema, articoli con
// le loro etichette e giudizio sul caso, con il salvataggio in un piè di pagina fisso.
// Sta in un pannello largo quanto lo SCHERMO (non quanto la tabella): niente scroll
// orizzontale. L'esito del sistema è chiuso di default e la predizione per articolo
// non è mostrata, per non influenzare il giudizio (il confronto lo fa
// scripts/evaluate_labels.py).
// Un caso "affidabile" richiede un giudizio completo e certo: la scheda lo verifica
// prima di salvare, evidenzia cosa manca (per numero di articolo) e porta al primo punto.
// Mostra anche gli altri casi dello stesso soggetto (già nel dataset?), i giudizi che il
// revisore ha già dato sugli stessi articoli, un possibile refuso nel nome e la conferma
// degli articoli nel registro del soggetto.
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Accordion, AccordionDetails, AccordionSummary, Alert as MuiAlert, Autocomplete, Box, Button,
  Checkbox, Chip, FormControl, FormControlLabel, FormHelperText, InputLabel, Link, MenuItem, Paper,
  Select, TextField, ToggleButton, ToggleButtonGroup, Tooltip, Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import {
  FATF_CATEGORIES, getLabel, getRelated, saveLabel,
  type Alert, type Avversa, type CaseLabelIn, type CaseLabelSummary, type ConfirmOut, type DispositionAttesa,
  type EvidenceItem, type EvidenceLabel, type Pertinenza, type PriorJudgment, type RegistryArticle,
  type RelatedOut, type Ruolo,
} from "../api";
import { asSubjectName, splitPerson } from "../personName";
import ConfirmRegistryDialog from "./ConfirmRegistryDialog";

type Ev = EvidenceItem & { id: string };
type Question = "pertinenza" | "avversa";
type Gap = { q: Question; incerto: boolean };

// [valore, etichetta, significato]: il significato va nella legenda e nel tooltip.
const PERTINENZA: [Pertinenza, string, string][] = [
  ["si", "Sì", "parla proprio di questo soggetto"],
  ["omonimo", "Omonimo", "parla di un'altra persona o azienda con lo stesso nome"],
  ["non_citato", "Non citato", "il soggetto non è nominato"],
  ["incerto", "Incerto", "non si può stabilire (il caso resta una bozza)"],
];
const AVVERSA: [Avversa, string, string][] = [
  ["si", "Sì", "attribuisce al soggetto reati, indagini, accuse, condanne, sanzioni o legami con ambienti criminali"],
  ["no", "No", "il soggetto è vittima, testimone o parte lesa, o è solo citato; anche se l'articolo non lo riguarda"],
  ["incerto", "Incerto", "non si può stabilire (il caso resta una bozza)"],
];
const DOMANDA: Record<Question, string> = { pertinenza: "riguarda il soggetto?", avversa: "notizia avversa?" };
const NON_LO_RIGUARDA: Pertinenza[] = ["omonimo", "non_citato"];
const RUOLI: [Ruolo, string][] = [
  ["autore_indagato", "Autore / indagato"], ["vittima", "Vittima"],
  ["menzionato", "Solo menzionato"], ["non_determinabile", "Non determinabile"],
];
const ESITI: [DispositionAttesa, string][] = [
  ["ESCALATION_I_LIVELLO", "Escalation (I livello)"], ["AUTO_CHIUSO", "Chiusura"],
];

const P_TEXT: Record<string, string> = { si: "riguarda il soggetto", omonimo: "omonimo", non_citato: "non citato",
                                         incerto: "incerto" };
const A_TEXT: Record<string, string> = { si: "avversa", no: "non avversa", incerto: "incerto" };
const judgment = (p?: string | null, v?: string | null) =>
  [p && P_TEXT[p], v && A_TEXT[v]].filter(Boolean).join(" · ");
const day = (iso: string) => new Date(iso).toLocaleDateString("it-IT");

const EMPTY: CaseLabelIn = {
  evidence_labels: {}, categorie_corrette: [], ruolo: null, disposition_attesa: null,
  affidabile: false, note: "",
};

// Domande di un articolo senza risposta certa: in un caso affidabile servono entrambe e
// «Incerto» non basta (stessa regola dell'API, CaseLabelIn.missing_for_reliable).
function articleGaps(v?: EvidenceLabel): Gap[] {
  return (["pertinenza", "avversa"] as const)
    .filter((q) => !v?.[q] || v[q] === "incerto")
    .map((q) => ({ q, incerto: v?.[q] === "incerto" }));
}

// Nel riepilogo: "notizia avversa?", "riguarda il soggetto? «Incerto»".
const gapText = (gaps: Gap[]) => gaps.map((g) => DOMANDA[g.q] + (g.incerto ? " «Incerto»" : "")).join(", ");

// Sull'articolo: cosa manca e, per le risposte «Incerto», perché non bastano.
function gapCaption(gaps: Gap[]): string {
  const missing = gaps.filter((g) => !g.incerto).map((g) => DOMANDA[g.q]);
  const uncertain = gaps.filter((g) => g.incerto).map((g) => DOMANDA[g.q]);
  return [
    missing.length ? `Manca: ${missing.join(", ")}` : "",
    uncertain.length ? `«Incerto» non basta per un caso affidabile: ${uncertain.join(", ")}` : "",
  ].filter(Boolean).join(" · ");
}

// Combinazioni sospette, non bloccanti: tengono coerente il dataset.
function consistencyHints(label: CaseLabelIn, evidence: Ev[]): string[] {
  const labels = evidence.map((e) => label.evidence_labels[e.id] ?? {});
  const hints: string[] = [];
  if (label.disposition_attesa === "ESCALATION_I_LIVELLO") {
    if (label.ruolo === "vittima" || label.ruolo === "menzionato") {
      hints.push("Soggetto vittima o solo citato, ma esito «Escalation»: di norma queste notizie non sono "
        + "avverse per il soggetto. Se l'escalation è voluta (es. rischio di infiltrazione), spiegalo nelle note.");
    } else if (labels.length > 0 && labels.every((v) => v.avversa && v.avversa !== "si")) {
      hints.push("Esito «Escalation» ma nessun articolo è una notizia avversa: se ti basi su notizie che il "
        + "sistema non ha trovato, indicalo nelle note.");
    }
  }
  const n = labels.findIndex((v) => v.pertinenza === "si" && v.avversa === "si");
  if (label.disposition_attesa === "AUTO_CHIUSO" && n >= 0) {
    hints.push(`Esito «Chiusura» ma l'articolo ${n + 1} riguarda il soggetto ed è una notizia avversa: `
      + "verifica l'esito.");
  }
  return hints;
}

// Esito del sistema: chiuso di default (aprilo dopo aver giudicato).
function SystemOutcome({ a }: { a: Alert }) {
  const er = a.entity_resolution;
  return (
    <Accordion disableGutters variant="outlined" sx={{ mb: 2 }}>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Box>
          <Typography variant="subtitle2">Esito del sistema</Typography>
          <Typography variant="caption" color="text.secondary">
            AMI, categorie, motivazione, Entity Resolution — aprilo dopo aver giudicato, per non
            farti influenzare
          </Typography>
        </Box>
      </AccordionSummary>
      <AccordionDetails>
        <Typography variant="body2" gutterBottom>
          AMI <strong>{a.ami_score}</strong> · rischio {a.risk_level} · esito <strong>{a.disposition}</strong>
          {a.classification?.method && <> · classificazione: {String(a.classification.method)}</>}
        </Typography>
        {(a.fatf_categories ?? []).length > 0 && (
          <Box sx={{ display: "flex", gap: 0.5, flexWrap: "wrap", mb: 1 }}>
            {(a.fatf_categories ?? []).map((c) => (
              <Chip key={c} size="small" label={c} color="warning" variant="outlined" />
            ))}
          </Box>
        )}
        <ul style={{ margin: 0, paddingLeft: 18 }}>
          {(a.drivers ?? []).map((d, i) => (
            <li key={i}><Typography variant="caption" color="text.secondary">{d}</Typography></li>
          ))}
        </ul>
        {er && (
          <Typography variant="caption" color="text.secondary" component="div" sx={{ mt: 1 }}>
            Entity Resolution: {er.status} · {er.method} ({er.confidence.toFixed(2)})
            {(er.warnings ?? []).length > 0 && <> — {(er.warnings ?? []).join(" · ")}</>}
          </Typography>
        )}
        {a.svi_status === "failed" && a.svi_error && (
          <Typography variant="caption" color="error" component="div" sx={{ mt: 1 }}>
            Pubblicazione SVI fallita: {a.svi_error}
          </Typography>
        )}
      </AccordionDetails>
    </Accordion>
  );
}

// Come rispondere: lo stesso testo dei tooltip, sempre visibile sopra gli articoli.
function Legend() {
  const line = (options: [string, string, string][]) =>
    options.filter(([v]) => v !== "incerto").map(([, t, d]) => `${t}: ${d}`).join(" · ");
  return (
    <Box sx={{ bgcolor: "action.hover", borderRadius: 1, px: 1.5, py: 1, mb: 1.5 }}>
      <Typography variant="caption" component="div">
        <strong>Riguarda il soggetto?</strong> {line(PERTINENZA)}.
      </Typography>
      <Typography variant="caption" component="div" sx={{ mt: 0.5 }}>
        <strong>Notizia avversa per il soggetto?</strong> {line(AVVERSA)}. Con «Omonimo» o «Non
        citato» si imposta da sé su «No».
      </Typography>
      <Typography variant="caption" component="div" color="text.secondary" sx={{ mt: 0.5 }}>
        «Incerto» se non si può stabilire: il caso resta una bozza, fuori dal dataset.
      </Typography>
    </Box>
  );
}

// Una domanda a risposta singola. Come i radio: la risposta si cambia ma non si toglie
// (un secondo clic sulla stessa, anche su un «No» impostato da sé, non la cancella).
function Choice<T extends string>({ label, options, value, missing, onChange }: {
  label: string; options: [T, string, string][]; value: T | null; missing: boolean;
  onChange: (v: T) => void;
}) {
  return (
    <Box>
      <Typography variant="caption" component="div" color={missing ? "error" : "text.secondary"}>
        {label}
      </Typography>
      <ToggleButtonGroup size="small" exclusive color="primary" value={value} aria-label={label}
        onChange={(_, v: T | null) => { if (v !== null) onChange(v); }}>
        {options.map(([v, t, d]) => (
          <Tooltip key={v} title={`${t}: ${d}`} describeChild enterDelay={500} disableInteractive>
            <ToggleButton value={v}>{t}</ToggleButton>
          </Tooltip>
        ))}
      </ToggleButtonGroup>
    </Box>
  );
}

type ArticleProps = {
  n: number;
  e: Ev;
  value?: EvidenceLabel;
  gaps?: Gap[];     // cosa manca per un caso affidabile (dopo un salvataggio bloccato)
  prior?: PriorJudgment;        // mio giudizio sullo stesso articolo in un altro caso
  registry?: RegistryArticle;   // già confermato nel registro del soggetto
  onPertinenza: (v: Pertinenza) => void;
  onAvversa: (v: Avversa) => void;
  onReuse: () => void;
  boxRef: (el: HTMLDivElement | null) => void;
};

// Un articolo: contenuto (per giudicare senza aprire la pagina) + le due domande.
function Article({ n, e, value, gaps, prior, registry, onPertinenza, onAvversa, onReuse, boxRef }: ArticleProps) {
  const same = (x?: { pertinenza?: string | null; avversa?: string | null }) =>
    !!x && x.pertinenza === value?.pertinenza && x.avversa === value?.avversa;
  const answered = !!value?.pertinenza && !!value?.avversa;
  const missing = (q: Question) => !!gaps?.some((g) => g.q === q);
  return (
    <Paper ref={boxRef} variant="outlined" role="group" aria-label={`Articolo ${n}`}
      sx={{ p: 1.5, mb: 1.5, scrollMarginTop: 8,
            ...(gaps?.length ? { borderColor: "error.main", boxShadow: (t) => `inset 0 0 0 1px ${t.palette.error.main}` } : {}) }}>
      <Box sx={{ display: "flex", alignItems: "center", gap: 1, flexWrap: "wrap" }}>
        <Typography variant="body2">
          <strong>Articolo {n}</strong> · {e.testata || "—"}{e.data ? ` · ${e.data}` : ""}
        </Typography>
        {e.url && <Link variant="body2" href={e.url} target="_blank" rel="noreferrer">apri articolo</Link>}
        {e.fonte_credibilita && (
          <Chip size="small" variant="outlined" label={`credibilità: ${e.fonte_credibilita}`} />
        )}
      </Box>
      {e.title && <Typography variant="body2" sx={{ mt: 0.5 }}>{e.title}</Typography>}
      {e.snippet && (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, fontStyle: "italic" }}>
          “{e.snippet}”
        </Typography>
      )}
      <Box sx={{ display: "flex", gap: 2, rowGap: 1, flexWrap: "wrap", mt: 1 }}>
        <Choice label="Riguarda il soggetto?" options={PERTINENZA} value={value?.pertinenza ?? null}
          missing={missing("pertinenza")} onChange={onPertinenza} />
        <Choice label="Notizia avversa per il soggetto?" options={AVVERSA} value={value?.avversa ?? null}
          missing={missing("avversa")} onChange={onAvversa} />
      </Box>
      {!!gaps?.length && (
        <Typography variant="caption" color="error" component="div" sx={{ mt: 0.5, fontWeight: 500 }}>
          {gapCaption(gaps)}
        </Typography>
      )}
      {prior && (
        <Box sx={{ display: "flex", alignItems: "center", gap: 1, mt: 0.5, flexWrap: "wrap" }}>
          <Typography variant="caption" color="text.secondary">
            Già giudicato da te il {day(prior.created_at)}: {judgment(prior.pertinenza, prior.avversa)}
          </Typography>
          {!same(prior) && <Button size="small" sx={{ py: 0 }} onClick={onReuse}>Usa lo stesso giudizio</Button>}
        </Box>
      )}
      {registry && answered && (
        // dopo aver risposto (etichettatura cieca): confronto con lo storico del soggetto
        <Typography variant="caption" component="div" sx={{ mt: 0.5 }}
          color={same(registry) ? "success.main" : "warning.main"}>
          Nel registro del soggetto: {judgment(registry.pertinenza, registry.avversa)}
          {registry.confirmed_by_name && ` (confermato da ${registry.confirmed_by_name})`}
          {!same(registry) && " — diverso dal tuo giudizio"}
        </Typography>
      )}
      <Typography variant="caption" color="text.secondary" component="div"
        sx={{ mt: 1, wordBreak: "break-all" }} title={e.content_hash ?? undefined}>
        hash {(e.content_hash ?? "—").slice(0, 12)}… · fetch {e.fetch_ts || "—"}
        {e.warc_key && <> · WARC {e.warc_key}</>}
      </Typography>
    </Paper>
  );
}

// Altri casi dello stesso soggetto e loro presenza nel dataset: casi dello stesso
// soggetto non sono indipendenti (conviene tenerne uno) e i duplicati si possono eliminare.
function RelatedCases({ rel, onOpen, isListed }: {
  rel: RelatedOut; onOpen?: (id: string) => void; isListed?: (id: string) => boolean;
}) {
  const cases = rel.stesso_soggetto;
  if (!cases.length) return null;
  const inDataset = cases.filter((c) => c.affidabili > 0).length;
  return (
    <MuiAlert severity="info" sx={{ mb: 2 }}>
      <Typography variant="body2">
        <strong>Stesso soggetto in {cases.length === 1 ? "un altro caso" : `altri ${cases.length} casi`}</strong>
        {inDataset > 0 && <> · {inDataset === 1 ? "uno è già" : `${inDataset} sono già`} nel dataset</>}.
        Casi dello stesso soggetto non sono indipendenti: tienine uno nel dataset, gli altri eliminali
        come duplicati.
      </Typography>
      {cases.slice(0, 5).map((c) => (
        <Box key={c.id} sx={{ display: "flex", alignItems: "center", gap: 1, mt: 0.5, flexWrap: "wrap" }}>
          <Typography variant="caption">
            {day(c.created_at)} · {c.subject} · esito {c.disposition}
            {" · "}{c.affidabili > 0 ? "nel dataset (affidabile)" : c.etichette > 0 ? "etichettato (bozza)" : "non etichettato"}
            {c.mia && ` · tua etichetta: ${c.mia}`}
          </Typography>
          {onOpen && isListed?.(c.id) && (
            <Button size="small" sx={{ py: 0 }} onClick={() => onOpen(c.id)}>apri</Button>
          )}
        </Box>
      ))}
    </MuiAlert>
  );
}

type Props = {
  a: Alert;
  onSaved: (s: CaseLabelSummary) => void;
  onDirtyChange: (dirty: boolean) => void;
  onNext?: () => void;   // assente sull'ultimo caso
  onClose: () => void;
  onOpenCase?: (id: string) => void;       // apre un altro caso della lista
  isListed?: (id: string) => boolean;
};

export default function CaseLabelPanel({ a, onSaved, onDirtyChange, onNext, onClose, onOpenCase, isListed }: Props) {
  const navigate = useNavigate();
  const [related, setRelated] = useState<RelatedOut | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmed, setConfirmed] = useState<ConfirmOut | null>(null);
  const [label, setLabel] = useState<CaseLabelIn>(EMPTY);
  const [saved, setSaved] = useState(JSON.stringify(EMPTY));   // ultimo stato salvato/caricato
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [checked, setChecked] = useState(false);   // un salvataggio "affidabile" è stato bloccato
  const articleEls = useRef<Record<string, HTMLDivElement | null>>({});
  const caseEl = useRef<HTMLDivElement>(null);
  const autoNo = useRef(new Set<string>());   // articoli con «avversa = No» impostato da sé
  const evidence = (a.evidence ?? []).filter((e): e is Ev => !!e.id);
  const dirty = JSON.stringify(label) !== saved;

  // Cosa manca perché il caso sia affidabile, nell'ordine in cui appare nella scheda.
  const incomplete = evidence
    .map((e, i) => ({ id: e.id, n: i + 1, gaps: articleGaps(label.evidence_labels[e.id]) }))
    .filter((x) => x.gaps.length > 0);
  const missingRuolo = !label.ruolo;
  const missingEsito = !label.disposition_attesa;
  const complete = incomplete.length === 0 && !missingRuolo && !missingEsito;
  const showGaps = checked && label.affidabile && !complete;
  const answered = evidence.filter((e) => {
    const v = label.evidence_labels[e.id];
    return v?.pertinenza && v?.avversa;
  }).length;
  const uncertain = evidence.filter((e) => {
    const v = label.evidence_labels[e.id];
    return v?.pertinenza === "incerto" || v?.avversa === "incerto";
  }).length;
  const hints = consistencyHints(label, evidence);

  useEffect(() => onDirtyChange(dirty), [dirty, onDirtyChange]);

  useEffect(() => {
    getRelated(a.id).then(setRelated).catch(() => setRelated(null));
  }, [a.id]);

  useEffect(() => {
    getLabel(a.id)
      .then((l) => {
        if (!l) return;
        const loaded: CaseLabelIn = {
          evidence_labels: l.evidence_labels ?? {}, categorie_corrette: l.categorie_corrette ?? [],
          ruolo: l.ruolo ?? null, disposition_attesa: l.disposition_attesa ?? null,
          affidabile: l.affidabile, note: l.note ?? "",
        };
        setLabel(loaded);
        setSaved(JSON.stringify(loaded));
      })
      .catch((e) => setMsg({ ok: false, text: String(e) }));
  }, [a.id]);

  const setEvidence = (id: string, patch: Partial<EvidenceLabel>) =>
    setLabel((l) => ({
      ...l, evidence_labels: { ...l.evidence_labels, [id]: { ...l.evidence_labels[id], ...patch } },
    }));

  // Un articolo su un omonimo (o che non cita il soggetto) non è avverso per il soggetto:
  // «No» da sé, se non già risposto; tolto di nuovo se la pertinenza torna «Sì» / «Incerto».
  const setPertinenza = (id: string, v: Pertinenza) => {
    const patch: Partial<EvidenceLabel> = { pertinenza: v };
    if (NON_LO_RIGUARDA.includes(v)) {
      if (!label.evidence_labels[id]?.avversa) {
        patch.avversa = "no";
        autoNo.current.add(id);
      }
    } else if (autoNo.current.delete(id)) {
      patch.avversa = null;
    }
    setEvidence(id, patch);
  };
  const setAvversa = (id: string, v: Avversa) => {
    autoNo.current.delete(id);
    setEvidence(id, { avversa: v });
  };

  // Mio giudizio già dato sullo stesso articolo in un altro caso: lo riusa.
  const reuse = (id: string, p: PriorJudgment) => {
    autoNo.current.delete(id);
    setEvidence(id, { pertinenza: p.pertinenza ?? null, avversa: p.avversa ?? null });
  };

  // Possibile refuso nel nome: ripeti lo screening con il nome trovato negli articoli.
  const variant = (a.name_variants ?? [])[0];
  const isPerson = a.tipo_soggetto === "persona_fisica";
  const rescreen = () => {
    const fixed = asSubjectName(variant!, a.subject, isPerson);
    const q = new URLSearchParams({ tipo: isPerson ? "persona_fisica" : "persona_giuridica" });
    if (isPerson) {
      const { cognome, nome } = splitPerson(fixed);
      q.set("cognome", cognome);
      q.set("nome", nome);
    } else {
      q.set("denominazione", fixed);
    }
    if (a.cup.length) q.set("cup", a.cup.join(","));
    navigate(`/screening?${q}`);
  };
  const otherReliable = !!related?.stesso_soggetto.some((c) => c.affidabili > 0);
  const confirmable = evidence.some((e) => {
    const v = label.evidence_labels[e.id];
    return v?.pertinenza && v.pertinenza !== "incerto" && v?.avversa && v.avversa !== "incerto";
  });

  const save = async (andThen?: () => void) => {
    setMsg(null);
    if (label.affidabile && !complete) {
      // Blocca prima dell'API: evidenzia cosa manca e porta al primo punto da completare.
      setChecked(true);
      const first = incomplete.length ? articleEls.current[incomplete[0].id] : caseEl.current;
      first?.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    setSaving(true);
    try {
      const res = await saveLabel(a.id, { ...label, note: label.note || null });
      setSaved(JSON.stringify(label));
      onDirtyChange(false);
      onSaved({ alert_id: a.id, affidabile: res.affidabile, updated_at: res.updated_at });
      if (andThen) {
        andThen();
      } else {
        setMsg({
          ok: true,
          text: res.affidabile ? "Salvato: caso incluso nel dataset." : "Salvato come bozza (non incluso nel dataset).",
        });
      }
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      setSaving(false);
    }
  };

  // Riepilogo di cosa manca: per numero di articolo (tutti i dettagli se sono pochi).
  const todo = [
    ...(incomplete.length <= 3
      ? incomplete.map((x) => `articolo ${x.n} (${gapText(x.gaps)})`)
      : [`articoli ${incomplete.map((x) => x.n).join(", ")}`]),
    ...(missingRuolo ? ["ruolo del soggetto"] : []),
    ...(missingEsito ? ["esito corretto"] : []),
  ];

  return (
    <>
      <Box sx={{ flex: 1, overflowY: "auto", px: 2, py: 2 }}>
        {variant && (
          <MuiAlert severity="warning" sx={{ mb: 2 }} action={
            <Button size="small" color="inherit" onClick={rescreen}>Ripeti lo screening</Button>}>
            Il nome «{a.subject}» non compare negli articoli, che citano invece
            {" "}{(a.name_variants ?? []).map((v) => `«${v}»`).join(", ")}: se è un refuso, ripeti lo
            screening con il nome corretto (ed elimina questo caso come errato).
          </MuiAlert>
        )}
        {related && <RelatedCases rel={related} onOpen={onOpenCase} isListed={isListed} />}
        {related?.registro && (
          <Typography variant="caption" color="text.secondary" component="div" sx={{ mb: 1 }}>
            Nel registro: <strong>{related.registro.denominazione}</strong>
            {Object.keys(related.registro.articoli).length > 0 &&
              ` · ${Object.keys(related.registro.articoli).length} di questi articoli già confermati`}
          </Typography>
        )}
        <SystemOutcome a={a} />

        <Typography variant="subtitle2" gutterBottom>Articoli ({evidence.length})</Typography>
        {evidence.length === 0 ? (
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Nessun articolo analizzato (ricerca vuota, fonti non accessibili o Entity Resolution non
            superata). Se sai che esistono notizie avverse su questo soggetto, indica «Escalation»
            come esito corretto: serve a misurare i falsi negativi.
          </Typography>
        ) : (
          <>
            <Legend />
            {evidence.map((e, i) => (
              <Article key={e.id} n={i + 1} e={e} value={label.evidence_labels[e.id]}
                gaps={showGaps ? articleGaps(label.evidence_labels[e.id]) : undefined}
                prior={related?.giudizi_precedenti[e.id]?.[0]} registry={related?.registro?.articoli[e.id]}
                onPertinenza={(v) => setPertinenza(e.id, v)} onAvversa={(v) => setAvversa(e.id, v)}
                onReuse={() => reuse(e.id, related!.giudizi_precedenti[e.id][0])}
                boxRef={(el) => { articleEls.current[e.id] = el; }} />
            ))}
          </>
        )}

        <Typography variant="subtitle2" sx={{ mt: 2, mb: 1.5 }}>Giudizio sul caso</Typography>
        <Autocomplete multiple size="small" options={FATF_CATEGORIES} value={label.categorie_corrette}
          onChange={(_, v) => setLabel((l) => ({ ...l, categorie_corrette: v }))}
          renderInput={(params) => <TextField {...params} label="Categorie FATF corrette (vuoto = nessuna)" />} />
        <Box ref={caseEl} sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" }, gap: 2, mt: 2 }}>
          <FormControl size="small" fullWidth error={showGaps && missingRuolo}>
            <InputLabel id={`ruolo-${a.id}`}>Ruolo del soggetto</InputLabel>
            <Select labelId={`ruolo-${a.id}`} label="Ruolo del soggetto" value={label.ruolo ?? ""}
              onChange={(ev) => setLabel((l) => ({ ...l, ruolo: (ev.target.value || null) as Ruolo | null }))}>
              <MenuItem value=""><em>—</em></MenuItem>
              {RUOLI.map(([v, t]) => <MenuItem key={v} value={v}>{t}</MenuItem>)}
            </Select>
            {showGaps && missingRuolo && <FormHelperText>Serve per un caso affidabile</FormHelperText>}
          </FormControl>
          <FormControl size="small" fullWidth error={showGaps && missingEsito}>
            <InputLabel id={`esito-${a.id}`}>Esito corretto</InputLabel>
            <Select labelId={`esito-${a.id}`} label="Esito corretto" value={label.disposition_attesa ?? ""}
              onChange={(ev) => setLabel((l) => ({
                ...l, disposition_attesa: (ev.target.value || null) as DispositionAttesa | null,
              }))}>
              <MenuItem value=""><em>—</em></MenuItem>
              {ESITI.map(([v, t]) => <MenuItem key={v} value={v}>{t}</MenuItem>)}
            </Select>
            {showGaps && missingEsito && <FormHelperText>Serve per un caso affidabile</FormHelperText>}
          </FormControl>
        </Box>
        {hints.map((h) => <MuiAlert key={h} severity="info" sx={{ mt: 2 }}>{h}</MuiAlert>)}
        <TextField size="small" fullWidth multiline minRows={2} label="Note" sx={{ mt: 2 }}
          value={label.note ?? ""} onChange={(ev) => setLabel((l) => ({ ...l, note: ev.target.value }))} />
      </Box>

      <Box sx={{ borderTop: 1, borderColor: "divider", px: 2, py: 1.5, bgcolor: "background.paper" }}>
        {msg && <MuiAlert severity={msg.ok ? "success" : "error"} sx={{ mb: 1 }}>{msg.text}</MuiAlert>}
        {confirmed && (
          <MuiAlert severity="success" sx={{ mb: 1 }} onClose={() => setConfirmed(null)}>
            {confirmed.nuovo_soggetto ? "Soggetto inserito nel registro" : "Soggetto già inserito nel registro"}:
            {" "}«{confirmed.subject.denominazione}» — {confirmed.confermati === 1 ? "1 articolo confermato"
              : `${confirmed.confermati} articoli confermati`}
            {confirmed.alias_aggiunto && `; «${confirmed.alias_aggiunto}» registrato come sua variante`}.
          </MuiAlert>
        )}
        {label.affidabile && otherReliable && (
          <Typography variant="caption" color="warning.main" component="div">
            Il dataset ha già un caso affidabile di questo soggetto: due casi dello stesso soggetto
            non sono indipendenti.
          </Typography>
        )}
        {showGaps && (
          <MuiAlert severity="error" sx={{ mb: 1 }}>
            Per includere il caso nel dataset completa: {todo.join("; ")} (in rosso nella scheda). Oppure
            togli la spunta «Caso affidabile» per salvarlo come bozza.
          </MuiAlert>
        )}
        {evidence.length > 0 && (
          <Typography variant="caption" component="div" aria-live="polite"
            color={answered === evidence.length && !uncertain ? "success.main" : "text.secondary"}>
            Articoli completi: {answered} di {evidence.length}
            {uncertain > 0 && ` · ${uncertain} con «Incerto»`}
          </Typography>
        )}
        <Box sx={{ display: "flex", alignItems: "center", columnGap: 1, flexWrap: "wrap" }}>
          <FormControlLabel label="Caso affidabile (includi nel dataset)" sx={{ mr: 0 }} control={
            <Checkbox checked={label.affidabile}
              onChange={(ev) => setLabel((l) => ({ ...l, affidabile: ev.target.checked }))} />
          } />
          <Box sx={{ display: "flex", gap: 1, ml: "auto" }}>
            <Button size="small" onClick={() => setConfirmOpen(true)} disabled={saving || dirty || !confirmable}
              title={dirty ? "Salva prima l'etichetta" : !confirmable ? "Serve almeno un articolo con giudizio certo" : undefined}>
              Conferma nel registro…
            </Button>
            <Button variant="outlined" size="small" onClick={() => save()} disabled={saving}>Salva</Button>
            <Button variant="contained" size="small" disabled={saving}
              onClick={() => save(onNext ?? onClose)}>
              {onNext ? "Salva e successivo" : "Salva e chiudi"}
            </Button>
          </Box>
        </Box>
      </Box>
      {confirmOpen && (
        <ConfirmRegistryDialog open a={a} label={label} registry={related?.registro ?? null}
          onClose={() => setConfirmOpen(false)}
          onDone={(res) => {
            setConfirmOpen(false);
            setConfirmed(res);
            getRelated(a.id).then(setRelated).catch(() => undefined);
          }} />
      )}
    </>
  );
}
