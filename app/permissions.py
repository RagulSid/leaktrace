"""Who may do what. Shared by the API and the CLI so both apply the same rules."""

REPORTERS = ("staff", "operator", "tech", "manager", "authority")
VIEWERS = ("operator", "manager", "authority")
DECIDERS = ("operator", "manager")  # investigate, execute, verify, undo, replan
APPROVERS = ("operator", "manager")  # approve or reject a plan that needs a person's OK
FIELD = ("tech",)  # pick up valve moves and report what happened

# Internal actor role for the engine's own steps (auto mode, the checker). It is not a login role:
# no token can carry it (app/api/auth.py ROLES).
SYSTEM = "system"
