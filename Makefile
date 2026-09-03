.PHONY: install keygen probe up down seed run-gateway run-merchant \
       demo demo-happy demo-policy demo-replay demo-chaos demo-indoubt demo-upsell demo-all \
       kill-merchant metrics verify head tamper verify-reset reset-db test test-cov check

DB_PATH ?= razor402.db

install:
	pip install -e ".[dev]"

keygen:
	python scripts/keygen.py

probe:
	python scripts/probe.py

up: down
	docker compose up -d --build
	@echo "Waiting for services..."
	@ping -n 4 127.0.0.1 > NUL 2>&1 || sleep 3
	$(MAKE) seed

down:
	docker compose down -v 2>NUL || true

seed:
	python scripts/seed.py

run-gateway:
	uvicorn gateway.app:app --port 8000 --reload

run-merchant:
	uvicorn merchant.app:app --port 9000 --reload

demo: demo-happy

demo-happy: reset-db
	python -m agent.buyer --replay --mission rag

demo-policy: reset-db
	bash scripts/demo_policy.sh 2>/dev/null || python scripts/demo_policy.py

demo-replay: reset-db
	bash scripts/demo_replay.sh 2>/dev/null || python scripts/demo_replay.py

demo-chaos: reset-db
	bash scripts/demo_chaos.sh 2>/dev/null || python scripts/demo_chaos.py

demo-indoubt: reset-db
	bash scripts/demo_indoubt.sh 2>/dev/null || python scripts/demo_indoubt.py

demo-upsell: reset-db
	bash scripts/demo_upsell.sh 2>/dev/null || python scripts/demo_upsell.py

demo-all: demo-happy demo-policy demo-replay demo-chaos demo-indoubt demo-upsell

kill-merchant:
	docker kill razor402-merchant 2>NUL || true

metrics:
	python scripts/batch_metrics.py

verify:
	python -m state.audit_cli verify

head:
	python -m state.audit_cli head

tamper:
	python -m state.audit_cli tamper

verify-reset: reset-db

reset-db:
	python scripts/reset_db.py


test:
	pytest tests/ -q

test-cov:
	pytest tests/ -q --tb=short -v

check:
	@echo "=== Honesty grep ==="
	@grep -rniE "immutable ledger|official (http )?402 (spec|standard)|first (ever )?(inr|fiat) x402|endorsed by razorpay|razorpay partner|production[- ]ready upi|guaranteed" --include="*.py" --include="*.md" --include="*.html" . && echo "FAIL: forbidden strings found" && exit 1 || echo "PASS: no forbidden strings"
	@echo "=== Secret leak check ==="
	@git ls-files | xargs grep -lniE "rzp_live|rzp_test_[A-Za-z0-9]{10}|sk-ant-|AIza" && echo "FAIL: secrets found" && exit 1 || echo "PASS: clean"
	@echo "=== Literal drift check ==="
	pytest tests/test_integration.py::test_no_price_literals_outside_catalog -q
