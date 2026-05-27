# Contributing to SILD

Thank you for your interest in contributing to SILD.

## Licence and Copyleft

SILD is **dual-licensed**: **AGPL-3.0-only OR Commercial** (ISCaD GmbH).

By contributing, you agree that:

- Your contributions are licensed under **AGPL-3.0-only**
- **Modifications must be returned** to the reference system (copyleft clause)
- Copyleft covers network use (SaaS) — clinical SaaS deployments must open their source
- You have the right to contribute the code you submit
- ISCaD GmbH may offer your contribution under the commercial licence

### SPDX header for new files

```text
SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
```

## How to Contribute

### Bug Reports

Open an issue at: https://github.com/fmatten/SILD/issues

Please include:
- SILD version
- Docker / Python version
- Minimal reproducible example
- Expected vs. actual behaviour

### Pull Requests

1. Fork the repository on GitHub or Codeberg
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Test your changes with the monitoring stack: `docker compose up -d`
4. Submit a pull request with a clear description

### Code Standards

- Python 3.11+
- FM-4 conformance must be maintained (all 15 gaps remain closed)
- No patient data in tests — use synthetic HL7v2/FHIR samples only
- Preserve four-pattern taxonomy: TN, TC, AD, RS

### NOT a Medical Device

SILD must never be modified to:
- Process real patient data in production without appropriate governance
- Provide clinical decision support
- Claim CE marking or MDR compliance

## Development Setup

```bash
git clone https://github.com/fmatten/SILD.git
cd SILD/sild_monitoring_stack
docker compose up -d
```

## Questions

Contact: friedhelm.matten@iscad-it.de  
GitHub: https://github.com/fmatten/SILD/issues  
Codeberg: https://codeberg.org/fmatten/sild
