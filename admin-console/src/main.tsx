import React from "react";
import ReactDOM from "react-dom/client";
import { CssBaseline, ThemeProvider, createTheme } from "@mui/material";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { AUTH_ENABLED, loginRequest, msalInstance } from "./auth";

const theme = createTheme({ palette: { mode: "light" } });

function render() {
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </ThemeProvider>
    </React.StrictMode>,
  );
}

// Bootstrap MSAL solo in modalità "entra": inizializza, raccoglie l'eventuale
// risposta di redirect e — se non c'è una sessione — manda al login. In dev
// (auth disabilitata) si renderizza direttamente, senza dipendere da Entra.
async function bootstrap() {
  if (AUTH_ENABLED && msalInstance) {
    await msalInstance.initialize();
    const result = await msalInstance.handleRedirectPromise();
    if (result?.account) {
      msalInstance.setActiveAccount(result.account);
    } else if (!msalInstance.getActiveAccount()) {
      const accounts = msalInstance.getAllAccounts();
      if (accounts.length > 0) msalInstance.setActiveAccount(accounts[0]);
    }
    if (!msalInstance.getActiveAccount()) {
      // Nessuna sessione: redirect a Entra. Al ritorno handleRedirectPromise
      // risolve e l'account viene impostato sopra.
      await msalInstance.loginRedirect(loginRequest);
      return;
    }
  }
  render();
}

void bootstrap();
