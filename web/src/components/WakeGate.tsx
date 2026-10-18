import { ReactNode, useEffect, useState } from "react";
import { ApiError } from "../api";
import { copy } from "../copy";
import { DownDetails } from "./ui";

const EVERY_MS = 3000;
const GIVE_UP_MS = 180000;

/** Before the first screen loads, ask /health. While FalkorDB is starting or the practice data is being seeded
 * (after a sleep, a restart or a reset), show "waking up" and ask again every few seconds. */
export function WakeGate({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [waited, setWaited] = useState(0);
  const [last, setLast] = useState<unknown>(null);
  useEffect(() => {
    let live = true;
    const t0 = Date.now();
    async function check() {
      try {
        const r = await fetch("/health");
        if (r.ok) { if (live) setReady(true); return; }
        const body = await r.json().catch(() => null);
        // The server answers but FalkorDB does not: in the container FalkorDB starts first, so this is not a
        // wake-up. Show the screens, which say plainly that the map can't be reached.
        if (body && body.falkordb_reachable === false) { if (live) setReady(true); return; }
        if (live) setLast(new ApiError(503, "waking", body));
      } catch { if (live) setLast(new ApiError(503, "unreachable", null)); }
      if (!live) return;
      setWaited(Date.now() - t0);
      if (Date.now() - t0 < GIVE_UP_MS) setTimeout(check, EVERY_MS);
    }
    check();
    return () => { live = false; };
  }, []);
  if (ready) return <>{children}</>;
  if (!last) return null;
  const W = copy.wake;
  return (
    <div className="page-narrow">
      <div className="card stack" role="status" aria-live="polite">
        <h1>{W.title}</h1>
        <p className="muted">{W.text}</p>
        {waited >= GIVE_UP_MS ? <div className="error" role="alert">{W.gaveUp}<DownDetails error={last} /></div>
          : waited > 15000 ? <span className="small muted">{W.still}</span> : null}
      </div>
    </div>
  );
}
