import { ReactNode } from "react";
import { Who } from "../api";
import { copy } from "../copy";
import { Badge } from "./ui";

const NAV: Record<string, [string, string][]> = {
  public: [["#/report", copy.nav.report], ["#/track", copy.nav.track]],
  staff: [["#/report", copy.nav.report], ["#/track", copy.nav.track]],
  operator: [["#/problems", copy.nav.problems], ["#/who", copy.nav.who]],
  manager: [["#/problems", copy.nav.problems], ["#/auto", copy.nav.auto], ["#/who", copy.nav.who]],
  authority: [["#/problems", copy.nav.problems], ["#/auto", copy.nav.auto], ["#/who", copy.nav.who]],
  tech: [["#/jobs", copy.nav.jobs]],
  integration: [],
};

export function Shell({ who, route, paused, onSignOut, children }: {
  who: Who | null; route: string; paused?: boolean | null; onSignOut: () => void; children: ReactNode;
}) {
  const links = NAV[who ? who.role : "public"] || [];
  const staff = !!who && who.role !== "staff";
  return (
    <>
      <header className="topbar">
        <a className="brand" href={who ? links[0]?.[0] || "#/report" : "#/report"}>
          <span className="brand-dot" aria-hidden="true" />{copy.app.name}
        </a>
        <span className="muted small site">{copy.app.site}</span>
        <nav className="nav" aria-label={copy.app.mainNav}>
          {links.map(([href, label]) => (
            <a key={href} href={href} className={route.startsWith(href.slice(1)) ? "on" : ""}>{label}</a>
          ))}
          <a href="#/how-it-works" className={route.startsWith("/how-it-works") ? "on" : ""}>{copy.nav.howItWorks}</a>
        </nav>
        <span className="grow" />
        <span className="row">
          <Badge kind="accent">{copy.app.practiceMode}</Badge>
          {staff && <Badge>{copy.app.practiceData}</Badge>}
          {staff && paused !== undefined && paused !== null && (
            <Badge kind={paused ? "ok-needed" : "good"}>{paused ? copy.app.autoPaused : copy.app.autoOn}</Badge>
          )}
          {who ? (
            <>
              <Badge>{copy.roles[who.role as keyof typeof copy.roles] || who.role}</Badge>
              <button className="btn link" onClick={onSignOut}>{copy.app.signOut}</button>
            </>
          ) : (
            <a href="#/login" className="small">{copy.app.signIn}</a>
          )}
        </span>
      </header>
      {!staff && <div className="practice-banner">{copy.app.practiceBuild}</div>}
      {staff && paused && <div className="practice-banner" role="status">{copy.app.pausedBar}</div>}
      <main>{children}</main>
      <footer className="footer"><a href="#/how-it-works">{copy.app.howItWorks}</a></footer>
    </>
  );
}
