# Agent instructions

## Project

This Home Assistant integration advises when to open or close each room's windows using indoor temperatures, target ranges, and hourly weather forecasts. It also provides whole-home advice.

## Working in this repository

- Keep room-level and whole-home recommendations consistent with the documented behavior in `README.md`.
- When changing recommendation logic, update or extend the tests, especially the differential check against the original Jinja templates.
- Before changing CI, check [pschmitt/ci-workflows](https://github.com/pschmitt/ci-workflows) for reusable components and preserve this repository's existing checks.

## Validation

- Run `uvx --with jinja2 pytest tests/` for the test suite.
- Run `uvx ruff check .` and `uvx ruff format --check .` for Python changes.
- CI also runs Hassfest.
