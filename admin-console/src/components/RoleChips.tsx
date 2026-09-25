// Ruoli della persona trovati negli articoli e flag PEP (persona politicamente esposta).
// Il PEP è un'indicazione da verificare: per il sindaco dipende dagli abitanti del
// comune, per una carica cessata da quanto tempo è cessata (D.Lgs. 231/2007).
import { Box, Chip, Tooltip } from "@mui/material";
import type { RoleFound } from "../api";

const PEP_HELP = "Possibile persona politicamente esposta (D.Lgs. 231/2007): carica pubblica o politica "
  + "accanto al nome negli articoli. Da verificare (es. sindaco: capoluogo o comune con almeno 15.000 "
  + "abitanti; carica cessata: fino a un anno dalla cessazione).";

export function PepChip({ small = false }: { small?: boolean }) {
  return (
    <Tooltip describeChild title={PEP_HELP}>
      <Chip size="small" color="secondary" label="PEP"
        sx={small ? { ml: 0.75, height: 18, fontSize: 11 } : undefined} />
    </Tooltip>
  );
}

export default function RoleChips({ roles, pep }: { roles?: RoleFound[]; pep?: boolean | null }) {
  if (!roles?.length && !pep) return null;
  return (
    <Box sx={{ display: "flex", gap: 0.5, flexWrap: "wrap", alignItems: "center", mt: 0.5 }}>
      {pep && <PepChip />}
      {(roles ?? []).map((r) => (
        <Chip key={r.ruolo} size="small" variant="outlined"
          color={r.pep ? "secondary" : r.categoria === "politico" ? "info" : "default"}
          label={r.ruolo + (r.articoli && r.articoli > 1 ? ` (${r.articoli})` : "")}
          title={r.pep === "verifica" ? "carica PEP da verificare" : r.pep ? "carica dell'elenco PEP"
            : r.categoria === "politico" ? "ruolo politico (non PEP per legge)" : "ruolo negli articoli"} />
      ))}
    </Box>
  );
}
