// Nomi di persona: il sistema scrive "Cognome Nome", gli articoli di solito "Nome Cognome".

// Separa cognome e nome. `knownNome` (il nome di battesimo già noto) decide l'ordine
// quando il testo viene da un articolo ("Andrea Stroppa"); altrimenti "Cognome Nome".
export function splitPerson(name: string, knownNome?: string): { cognome: string; nome: string } {
  const toks = name.trim().split(/\s+/).filter(Boolean);
  if (toks.length < 2) return { cognome: toks.join(" "), nome: "" };
  if (knownNome) {
    const i = toks.findIndex((t) => t.toLowerCase() === knownNome.trim().toLowerCase());
    if (i === 0) return { nome: toks[0], cognome: toks.slice(1).join(" ") };
    if (i === toks.length - 1) return { nome: toks[i], cognome: toks.slice(0, i).join(" ") };
  }
  return { cognome: toks[0], nome: toks.slice(1).join(" ") };
}

// Una variante trovata negli articoli, riscritta nel formato del sistema ("Cognome Nome").
export function asSubjectName(variant: string, subject: string, isPerson: boolean): string {
  if (!isPerson) return variant;
  const known = splitPerson(subject).nome;
  const { cognome, nome } = splitPerson(variant, known);
  return [cognome, nome].filter(Boolean).join(" ");
}
