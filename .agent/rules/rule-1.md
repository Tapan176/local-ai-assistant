---
trigger: always_on
---

# TAPAN_AI – Project Instructions

## 1. Workspace & Paths
- Project root is: **J:\**
- ALL code must remain inside:
  - J:\src\
  - J:\data\
  - J:\tests\
  - J:\experiments\
  - J:\backup\
- Never create files outside these folders.
- Use **relative imports only** (no C:\Users, no absolute paths).

## 2. Technology Rules
- Language: Python
- Database: SQLite only
- No internet/API calls in core logic
- Design must be OS-independent (Windows now → Linux later)
- Avoid Windows-specific features (registry, PowerShell scripts).

## 3. Code Organization
- Application code → src/
- User data → data/
- Tests → tests/
- Throwaway demos → experiments/
- Backups → backup/

## 4. Finance Safety
- Always confirm before saving expenses
- Amount must be positive
- INR formatting required
- Logs must be written to: data/activity.log

## 5. Language & Persona
- Assistant replies: English 70% + Hindi 30% (Hinglish buddy tone)
- Code & comments: clear professional English

## 6. Writing Behavior
- Prefer returning **patch/diff** instead of directly creating many files.
- Ask before generating files outside allowed folders.
- Keep changes minimal and modular.

## 7. Testing
- New features must include tests in J:\tests
- Existing finance & parser behavior must not break.

## 8. Privacy
- All personal data stays local in J:\data
- No telemetry or external sharing.

If any request conflicts with these rules, ask for clarification first.
