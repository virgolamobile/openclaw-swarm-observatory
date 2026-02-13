# Licensing and Release Guidelines

## 1. Project license intent

This project is released for public showcase and personal branding,
while disallowing unapproved commercial use.

## 2. Chosen license

**PolyForm Noncommercial 1.0.0**

Effects in practice:
- Public sharing is allowed under license terms
- Commercial use is not allowed without separate permission

## 3. Dependency licensing posture

Current dependency families are mostly permissive (MIT/BSD/ISC), with MPL-2.0 in transitive set.
This is generally compatible with non-commercial project licensing, but always review full legal terms before distribution.

Vendored frontend libraries are shipped under `static/vendor/` and remain governed by their own licenses.
Project maintainers must keep their notices and license texts in the repository.

## 4. Third-party compliance checklist

Before publishing:
- Keep dependency notices/attributions where required
- Review bundled assets and CDN-sourced artifacts before vendoring
- Confirm no proprietary credentials or private logs are included

Mandatory artifacts:
- `THIRD_PARTY_NOTICES.md`
- `static/vendor/licenses/*`

## 5. Repository publication checklist

- Add `LICENSE`
- Add this docs set
- Add `.gitignore` to exclude runtime private artifacts
- Review `credentials/`, `logs/`, local session traces before push
- Ensure third-party notices and license files are present when vendoring assets

## 6. Commercial licensing path

If you later want to commercialize:
- keep source provenance clear
- define dual-license terms
- publish explicit commercial grant policy
