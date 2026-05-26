# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Cache-identity pinning gate (Story E.f).

This file's only job is to pin the canonical SHA-256 digest of a
representative fixture recipe. If a code change shifts the canonical
bytes (a pydantic default change, a tweak to ``recipe.canonical``, an
edit to any nested-section default value), this test fails — and the
failure message routes the reviewer through the ceremony documented in
``project-essentials.md`` "Cache identity is the reproducibility
contract — invalidations are ceremonious."

**Why this is its own file.** Putting the pin in a one-test module
makes the gate easy to spot in ``git diff`` and harder to hand-edit
accidentally as part of an unrelated commit. Updating the pinned digest
is a deliberate cache-invalidation event and must follow the
post-production schema-version-bump ceremony (`recipe/loader.py`'s
``SUPPORTED_SCHEMA_VERSIONS``, a documented migration entry, and a
release-notes blast-radius announcement). Until production release the
ceremony is informal — a release-notes mention — but the bump itself
is still a conscious choice, not a silent byte-shift.

**How to update the pin (legitimately).** After a deliberate
cache-invalidating change, regenerate the digest with::

    pyve run python -c "import hashlib; \\
        from datarefinery.recipe.canonical import to_canonical_bytes; \\
        from datarefinery.recipe.loader import load; \\
        from pathlib import Path; \\
        print(hashlib.sha256(to_canonical_bytes(load(Path('<fixture>')))).hexdigest())"

then update ``_PINNED_DIGEST`` below in the same commit that ships the
change. A reviewer signing off on that diff is signing off on the
invalidation.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from datarefinery.recipe.canonical import to_canonical_bytes
from datarefinery.recipe.loader import load

# Representative recipe fixture. Fields are populated across every
# section that contributes to canonical bytes today; defaults that
# could silently shift on a pydantic refactor (Splits.seed, Filters
# stages, etc.) are exercised by leaving them at their defaults
# elsewhere in the test suite.
_FIXTURE_YAML = """\
schema_version: 1
plugin: image_classification
seed: 42
Input:
  sources:
    - name: train
      type: image_folder
      path: /data/train
Output:
  record_schema:
    image:
      dtype: uint8
      shape: [32, 32, 3]
    label:
      dtype: int32
Labels:
  field: label
  source:
    kind: derived
    derivation: parent_directory_name
Splits:
  ratios:
    train: 0.8
    val: 0.1
    test: 0.1
  stratify_by: label
  seed: 7
"""

# Pinned canonical hash for the fixture above. **Do not edit** unless you
# are deliberately invalidating the cache and updating this in the same
# commit — see project-essentials.md "Cache identity is the
# reproducibility contract — invalidations are ceremonious."
_PINNED_DIGEST = "88f2ed7a1266eb9fb736c37c2de16d21765807f6850db50d4804a122051cca7b"

_FAILURE_MESSAGE = """
Canonical hash drift detected.

The pinned digest in tests/unit/test_canonical_hash_pin.py no longer
matches the canonical-bytes hash of the fixture recipe. This means
*every* cached instance built against any recipe that overlaps the
changed default is now stale.

If this drift is intentional — you are knowingly shipping a
cache-invalidating change — follow the ceremony in
docs/specs/project-essentials.md "Cache identity is the reproducibility
contract — invalidations are ceremonious":

    1. Bump `SUPPORTED_SCHEMA_VERSIONS` in src/datarefinery/recipe/loader.py.
    2. Ship a documented migration in `recipe.loader.migrations`
       keyed by (from_version, to_version), or refuse-with-pointer
       if migration is impossible.
    3. Announce the blast radius in CHANGELOG.md and the upgrade-time
       CLI output. Name the change, state that all existing instances
       are stale, document the recompute cost.
    4. Update _PINNED_DIGEST below in the SAME commit. The reviewer
       signing off on that diff is signing off on the invalidation.

If this drift is unintentional — you did not mean to ship a
cache-invalidating change — revert the underlying change rather than
bumping the pin.

Pre-production note: until v1.0.0 the ceremony is informal (a
release-notes mention is sufficient). Post-production it is mandatory.
"""


def test_canonical_hash_is_pinned(tmp_path: Path) -> None:
    fixture_path = tmp_path / "fixture.yaml"
    fixture_path.write_text(_FIXTURE_YAML, encoding="utf-8")
    canonical = to_canonical_bytes(load(fixture_path))
    digest = hashlib.sha256(canonical).hexdigest()
    assert digest == _PINNED_DIGEST, f"{_FAILURE_MESSAGE}\nGot: {digest}"
