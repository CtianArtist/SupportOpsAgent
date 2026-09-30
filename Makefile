.PHONY: run seed test eval

run:
	uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

seed:
	uv run python seed.py

test:
	uv run pytest

eval:
	uv run python -m evals.run