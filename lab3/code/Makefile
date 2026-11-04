PYTHON ?= python3
DB ?= ticketing.db

.PHONY: run test lint seed clean

run:
	$(PYTHON) main.py --db $(DB)

test:
	$(PYTHON) -m unittest discover -s tests -t . -v

lint:
	$(PYTHON) -m pylint ticketing tests

seed:
	$(PYTHON) -m ticketing.application.seed

clean:
	rm -f $(DB) $(DB)-wal $(DB)-shm
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf exports
