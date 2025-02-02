.PHONY: tests lint install mypy update docs build

tests:
	poetry run pytest

lint:
	poetry run ruff motion/* --fix

install:
	pip install poetry
	poetry install --all-extras

mypy:
	poetry run mypy

update:
	poetry update

docs:
	poetry run mkdocs serve

build:
	rm -rf motion/static
	cd ui && npm install && npm run build
	cd ..
	cp -r ui/build motion/static
	poetry install --all-extras