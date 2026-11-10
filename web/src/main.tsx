import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";
import "./looks/gold-wood.css";
import "./looks/dark-dungeon.css";
import { applyLook, readLook } from "./looks/looks";
import { watchForNewBuild } from "./staleBuild";
import { takeTokenFromUrl } from "./token";

// A page open since before a deploy reloads for the new build when it can't load a screen's code.
watchForNewBuild();

// look.js set the look before the first paint; this sets it again, in case look.js could not run.
applyLook(readLook());

// Before anything calls the API: the printed link's #token= goes to the server, which keeps it in an HttpOnly cookie.
void takeTokenFromUrl().then(() =>
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  ),
);
