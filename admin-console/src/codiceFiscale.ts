// Controllo di coerenza tra Codice Fiscale e dati anagrafici (persona fisica).
// Il CF codifica cognome, nome e data di nascita: qui li ricalcoliamo e li
// confrontiamo per un feedback IMMEDIATO in console. La verifica autoritativa
// resta lato server (Entity Resolution). Speculare a services/entity-resolution/
// app/codice_fiscale.py.

const VOWELS = new Set(["A", "E", "I", "O", "U"]);
const MONTHS: Record<string, number> = {
  A: 1, B: 2, C: 3, D: 4, E: 5, H: 6, L: 7, M: 8, P: 9, R: 10, S: 11, T: 12,
};

function letters(s: string): string {
  return (s || "").toUpperCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[^A-Z]/g, "");
}
function consonants(s: string): string[] {
  return [...s].filter((c) => !VOWELS.has(c));
}

export function surnameCode(cognome: string): string {
  const s = letters(cognome);
  const picked = [...consonants(s), ...[...s].filter((c) => VOWELS.has(c))];
  return picked.concat(["X", "X", "X"]).slice(0, 3).join("");
}

export function nameCode(nome: string): string {
  const s = letters(nome);
  const cons = consonants(s);
  const picked = cons.length >= 4 ? [cons[0], cons[2], cons[3]] : [...cons, ...[...s].filter((c) => VOWELS.has(c))];
  return picked.concat(["X", "X", "X"]).slice(0, 3).join("");
}

export interface CfCheck {
  valid: boolean;       // il CF ha 16 caratteri
  consistent: boolean;  // i dati anagrafici inseriti combaciano col CF
  warnings: string[];
}

export function checkCf(cf: string, nome?: string, cognome?: string, dataNascita?: string): CfCheck {
  const c = (cf || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
  if (c.length !== 16) {
    // CF incompleto/errato: nessun avviso "live" (la validazione formale è del
    // server); il controllo di coerenza scatta solo sul CF completo a 16 caratteri.
    return { valid: false, consistent: false, warnings: [] };
  }
  const warnings: string[] = [];
  let consistent = true;

  if (cognome && cognome.trim()) {
    const exp = surnameCode(cognome);
    if (exp !== c.slice(0, 3)) {
      consistent = false;
      warnings.push(`Il cognome «${cognome}» non corrisponde al CF (CF: ${c.slice(0, 3)}, atteso: ${exp}).`);
    }
  }
  if (nome && nome.trim()) {
    const exp = nameCode(nome);
    if (exp !== c.slice(3, 6)) {
      consistent = false;
      warnings.push(`Il nome «${nome}» non corrisponde al CF (CF: ${c.slice(3, 6)}, atteso: ${exp}).`);
    }
  }
  if (dataNascita && dataNascita.trim()) {
    const [yyyy, mm, dd] = dataNascita.split("-").map((x) => parseInt(x, 10));
    const cfYear = c.slice(6, 8);
    const cfMonth = MONTHS[c[8]];
    let cfDay = parseInt(c.slice(9, 11), 10);
    if (cfDay > 40) cfDay -= 40;
    if (!isNaN(yyyy) && yyyy % 100 !== parseInt(cfYear, 10)) {
      consistent = false;
      warnings.push(`Anno di nascita incoerente col CF (CF: ..${cfYear}, inserito: ${yyyy}).`);
    } else if (cfMonth !== mm) {
      consistent = false;
      warnings.push(`Mese di nascita incoerente col CF (CF: ${cfMonth}, inserito: ${mm}).`);
    } else if (cfDay !== dd) {
      consistent = false;
      warnings.push(`Giorno di nascita incoerente col CF (CF: ${cfDay}, inserito: ${dd}).`);
    }
  }
  return { valid: true, consistent, warnings };
}
