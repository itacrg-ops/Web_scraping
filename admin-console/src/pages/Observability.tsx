import { Box, Card, CardContent, Link, Typography } from "@mui/material";

// Observability di piattaforma: viste di dominio + pannelli embeddati
// (Grafana / Azure Monitor). Scaffold: placeholder con i KPI previsti.
const KPI = [
  { label: "Profondità code", hint: "task queue Temporal per tipo di worker" },
  { label: "Throughput per fonte", hint: "documenti/ora per dominio" },
  { label: "Tasso errori scraping", hint: "per dominio, con drift di layout" },
  { label: "Uso/costo Foundry", hint: "TPM/RPM, 429, costo per CUP" },
  { label: "Latenza SAS", hint: "score_data (MCP) e pubblicazioni SVI" },
  { label: "Drift / bias", hint: "FP per categoria a rischio" },
];

export default function Observability() {
  return (
    <div>
      <Typography variant="h5" gutterBottom>Observability</Typography>
      <Typography variant="body2" color="text.secondary" gutterBottom>
        In produzione i pannelli sono alimentati da OpenTelemetry →{" "}
        <Link href="#">Azure Monitor / Grafana</Link>. Qui i KPI previsti.
      </Typography>
      <Box sx={{ display: "flex", flexWrap: "wrap", gap: 2, mt: 1 }}>
        {KPI.map((k) => (
          <Card key={k.label} variant="outlined" sx={{ flex: "1 1 260px", minWidth: 240 }}>
            <CardContent>
              <Typography variant="subtitle1">{k.label}</Typography>
              <Typography variant="body2" color="text.secondary">{k.hint}</Typography>
              <Typography variant="h4" sx={{ mt: 1 }}>—</Typography>
            </CardContent>
          </Card>
        ))}
      </Box>
    </div>
  );
}
