.PHONY: test local-backend local-frontend deploy proxy sync-dataform deploy-agent

PROJECT_ID ?= house-tully-310623
REGION ?= us-central1

test:
	PYTHONPATH=backend python3 -m unittest discover -s tests -v

local-backend:
	PYTHONPATH=backend LOCAL_INPROCESS_ETL=true uvicorn app.main:app --reload --port 8080 --app-dir backend

local-frontend:
	cd frontend && npm run dev

deploy:
	bash scripts/deploy.sh

sync-dataform:
	PYTHONPATH=backend python3 scripts/sync_dataform.py

deploy-agent:
	PYTHONPATH=backend python3 scripts/deploy_agent_engine.py

proxy:
	gcloud run services proxy nvd-health-web --region=$(REGION) --project=$(PROJECT_ID)
