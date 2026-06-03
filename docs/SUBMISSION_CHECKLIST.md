# Sudo Canary — Submission Checklist
## Final Status — 1 June 2026

All submission requirements met. Epoch 1 complete.

| Requirement | Status |
|---|---|
| Primary language: Python | ✅ |
| Frontend: PySide6 | ✅ |
| Database: SQLite (SQLCipher AES-256) | ✅ |
| Hosting: On-premise | ✅ |
| Version control: GitHub | ✅ |
| No external integrations at runtime | ✅ |
| MFA (TOTP via pyotp) | ✅ |
| Role-based access control | ✅ |
| Data encryption at rest | ✅ |
| Audit logging (append-only, seq integrity) | ✅ |
| DPPA 2019 alignment | ✅ |
| Offline mode | ✅ |
| Configurable data retention (min 365 days) | ✅ |
| Data notice at first login (DPPA S.13) | ✅ |
| Failed login attempt logging (DPPA S.23) | ✅ |

## Notes

**TLS:** Not applicable — local desktop application, no network transit surface.

**Penetration testing:** Not completed — prototype submission. Recommended before production deployment.

**Concurrent users:** 10–20 (SQLite). Scales to 100+ in Epoch 2 (PostgreSQL migration path documented).

**Mobile:** Not supported in Epoch 1. Web interface planned for Epoch 3.

**Offline mode:** Full offline operation. OSM tile cache downloaded before deployment. No internet required at runtime.

## Build Summary

| Day | Deliverable |
|---|---|
| 1 | Full SDK as Python Protocols |
| 2 | Auth, SQLCipher database, session management |
| 3 | Tasks, audit trail, navigation |
| 4 | Forms, documents, workflows scaffold |
| 5 | QR check-in, member directory, RoomAPI |
| 6 | Canary engine, workflow advancement, live dashboard |
| 7 | RoadWorks Tool package |
| 8 | Offline tile server, Leaflet map panel |
| 9 | Live map updates, QWebChannel, section detail panel |
| 10 | Materials divergence, QA trail, 5-room seed data, reports scaffold |
| 11 | Configurable retention, full PDF reports, CSV export |
| 12 | Dual theme system, icon sidebar, KPI cards, submission packaging |

## Repository

https://github.com/Kjeilor/SudoCanary

Tag: `v1.0.0-epoch1`

## Submission Commands

```bash
python3 scripts/seed_dev.py --reset
PYTHONPATH=. python3 app/main.py

git add -A
git commit -m "Epoch 1 complete — Ministry of ICT showcase submission"
git tag v1.0.0-epoch1
git push origin main --tags
```