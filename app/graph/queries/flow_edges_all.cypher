// Every flow link with what the what-if needs: capacities, the controlling valve, and the demand of the
// node it feeds when that node is a consumer (used to cap consumer inflow at required_flow).
MATCH ()-[r:FLOWS_TO]->(b)
RETURN r.id AS id, r.cap_base AS cap_base, r.open_cap AS open_cap, r.valve_id AS valve_id,
       CASE WHEN 'Consumer' IN labels(b) THEN b.required_flow END AS demand
