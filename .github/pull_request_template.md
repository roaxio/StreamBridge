## Summary
<!-- What and why. -->
Closes #

## Area
- [ ] Core (urls / engine / jitter / reconnect / session / settings)
- [ ] Windows  - [ ] Linux  - [ ] macOS
- [ ] GUI / CLI
- [ ] Packaging / CI / docs

## Invariants kept
- [ ] Low latency path unchanged (no extra buffering or scaling in Auto mode), or explained below
- [ ] Nothing is downloaded or installed without asking

## Verification
- [ ] `ruff check .`
- [ ] `pytest`
- [ ] Manual device test on: <!-- OS, apps used -->

## Hygiene
- [ ] No passwords, tokens, real credentialed URLs or personal paths committed
