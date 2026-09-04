import { AppBar, Box, Button, Chip, Container, Toolbar, Typography } from "@mui/material";
import { Link as RouterLink, Navigate, Route, Routes } from "react-router-dom";
import { useCurrentUser } from "./auth";
import Sources from "./pages/Sources";
import Alerts from "./pages/Alerts";
import Observability from "./pages/Observability";
import ScreeningPage from "./pages/Screening";

const NAV = [
  { to: "/sources", label: "Fonti" },
  { to: "/screening", label: "Screening" },
  { to: "/alerts", label: "Alert" },
  { to: "/observability", label: "Observability" },
];

export default function App() {
  const user = useCurrentUser();
  return (
    <Box sx={{ display: "flex", flexDirection: "column", minHeight: "100vh" }}>
      <AppBar position="static">
        <Toolbar>
          <Typography variant="h6" sx={{ mr: 3 }}>Adverse Media · Admin</Typography>
          {NAV.map((n) => (
            <Button key={n.to} color="inherit" component={RouterLink} to={n.to}>
              {n.label}
            </Button>
          ))}
          <Box sx={{ flexGrow: 1 }} />
          <Chip label={`${user.name} · ${user.roles.join(",")}`} color="default" size="small" />
        </Toolbar>
      </AppBar>
      <Container sx={{ py: 3, flexGrow: 1 }}>
        <Routes>
          <Route path="/" element={<Navigate to="/sources" replace />} />
          <Route path="/sources" element={<Sources />} />
          <Route path="/screening" element={<ScreeningPage />} />
          <Route path="/alerts" element={<Alerts />} />
          <Route path="/observability" element={<Observability />} />
        </Routes>
      </Container>
    </Box>
  );
}
