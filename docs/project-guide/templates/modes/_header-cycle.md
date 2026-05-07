**Next Action**
Restart the cycle of steps. 

---

## Version Cadence (quick reference)

When bumping the package version for a completed story, follow the **Version Cadence** rule documented at the top of `docs/specs/stories.md`. Quick reference:

- Bugfix or trivial change → **patch**
- Feature or improvement → **minor**
- Breaking change → **major** (post-1.0 only; only via `plan_production_phase`)
- **Phase-bundled releases:** stories within a phase can run unversioned during work; the phase ships a single release/tag at end-of-phase, with bump magnitude determined by the highest-impact change in the bundle.

**Do not extrapolate the bump magnitude from `pyproject.toml`'s current version.** Re-read `docs/specs/stories.md`'s Version Cadence section if unsure.

## Out-of-scope items in stories

When announcing a story (Step 2 in code cycles, or the equivalent gate in other cycle modes), check whether the story or its parent phase plan has an "Out of scope" section. If so, **briefly summarize those items to the developer**. They are a negotiation point — the developer may opt some items back into scope before implementation begins. Do not silently treat them as deferred.

---
