.PHONY: run test lint check

run:
	python app.py

test:
	python -m pytest

lint:
	python -m ruff check .

check: lint test
