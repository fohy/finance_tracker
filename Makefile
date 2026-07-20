.PHONY: run docker-up docker-down test lint check

run:
	python app.py

docker-up:
	docker compose up --build

docker-down:
	docker compose down

test:
	python -m pytest

lint:
	python -m ruff check .

check: lint test
