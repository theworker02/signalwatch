# Contributing to SIGNALWATCH

Thanks for your interest in reliable astronomical research software. Improvements to source ingestion, instrument calibration, provenance, accessibility, tests, and documentation are welcome for discussion.

1. Open an issue describing the problem, expected behavior, and any relevant public data references.
2. Use a branch, keep changes narrowly scoped, and do not add private recordings or credentials.
3. Run `python -m pip install -r requirements-dev.txt` and `python -m pytest -q`. For UI changes, run `python scripts/capture_screenshots.py` after installing Playwright and Chromium.
4. Clearly label all synthetic/test data. Do not present heuristics as scientific confirmation.
5. Include new tests for parser changes and new scientific assertions. Attribute all external datasets.

**Note:** No public software license has yet been selected. Contributions and reuse rights should be discussed with Magnexis before submission. Opening a pull request does not imply a license grant.
