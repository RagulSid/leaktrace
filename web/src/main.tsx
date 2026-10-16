import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./theme.css";
import { api, session, Who } from "./api";
import { Shell } from "./components/Shell";
import { AutoMode } from "./views/AutoMode";
import { HowItWorks } from "./views/HowItWorks";
import { Jobs } from "./views/Jobs";
import { Login } from "./views/Login";
import { Problems } from "./views/Problems";
import { ReportProblem } from "./views/Report";
import { TrackReport } from "./views/Track";
import { WhoDidWhat } from "./views/WhoDidWhat";

const HOME: Record<string, string> = { operator: "/problems", manager: "/problems", authority: "/problems", tech: "/jobs", staff: "/report" };

function useRoute(): string {
  const read = () => window.location.hash.replace(/^#/, "") || "/";
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const on = () => { setRoute(read()); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

function App() {
  const route = useRoute();
  const [who, setWho] = useState<Who | null>(session.who());
  const [paused, setPaused] = useState<boolean | null>(null);
  const staffRole = who && who.role !== "staff" && who.role !== "integration";
  const loadPaused = () => {
    if (!staffRole) return;
    api<any[]>("/policies").then((p) => setPaused(!!p[0]?.policy?.frozen)).catch(() => setPaused(null));
  };
  useEffect(loadPaused, [who]);

  const [, page, arg] = route.split("/");
  const needLogin = ["problems", "jobs", "auto", "who"].includes(page);
  let body;
  if (needLogin && !who) body = <Login onDone={(w) => { setWho(w); window.location.hash = `#${HOME[w.role] || "/report"}`; }} />;
  else if (page === "login") body = <Login onDone={(w) => { setWho(w); window.location.hash = `#${HOME[w.role] || "/report"}`; }} />;
  else if (page === "problems") body = <Problems who={who!} id={arg} />;
  else if (page === "jobs") body = <Jobs who={who!} />;
  else if (page === "auto") body = <AutoMode who={who!} onPaused={loadPaused} />;
  else if (page === "who") body = <WhoDidWhat id={arg} />;
  else if (page === "track") body = <TrackReport code={arg} />;
  else if (page === "how-it-works") body = <HowItWorks />;
  else if (page === "report") body = <ReportProblem />;
  else { window.location.hash = `#${who ? HOME[who.role] || "/report" : "/report"}`; body = null; }

  return (
    <Shell who={who} route={route} paused={paused} onSignOut={() => { session.clear(); setWho(null); window.location.hash = "#/report"; }}>
      {body}
    </Shell>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
