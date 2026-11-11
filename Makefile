up:
	@docker compose -f ./docker-compose.yaml up --remove-orphans -d

down:
	@docker compose -f ./docker-compose.yaml down -v --remove-orphans

import_data:
	@docker compose -f ./docker-compose.yaml run --rm citydb-tool import cityjson /data/out/buildings.city.json

export_data:
	@docker compose -f ./docker-compose.yaml run --rm citydb-tool export citygml --output=/data/out/buildings.city.gml

ingestion:
	@uv run scripts/ingest_geosampa.py
	@uv run scripts/clip_to_aoi.py
	@uv run scripts/build_lod1_buildings.py
