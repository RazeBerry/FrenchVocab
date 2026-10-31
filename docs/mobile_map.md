# Mobile: private web interface

Router: routes an intent to the document or code that owns it. It carries no
invariants; if a rule is written here, move it to its owner.

## Routes

| To | Read |
|---|---|
| Change an API route, mobile service, journal or library read model | `docs/mobile_server.md` (Server) |
| Decide what the phone should do, or whether it should do it | `docs/mobile_server.md` (Product philosophy) |
| Change the shell, capture slip, theme, tokens, icons or caching | `docs/mobile_frontend.md` |
| Change the glossary (Library view) | `docs/mobile_glossary.md` |
| Write, retry or replay a phone save | `docs/persistence.md` |
| Deploy or reach the phone | `docs/MOBILE.md`, `docs/operations.md` |

## Where the code lives
- `vocab_builder/mobile/` contains the optional FastAPI web interface, headless mobile use-case adapters, durable request state, and its no-build static front end.
