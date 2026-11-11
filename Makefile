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

tiles:
	@docker exec -i 3dcitydb psql -U citydb -d citydb -v ON_ERROR_STOP=1 < sql/building_tiles.sql
	@rm -rf data/out/3dtiles
	@docker compose -f ./docker-compose.yaml run --rm -T pg2b3dm --connection 'Host=3dcitydb;Port=5432;Username=citydb;Password=citydb;Database=citydb' -t citydb.building_tiles -c geometry -a cd_identificador,predio_number,predio_name,height_m,height_source -o /data/out/3dtiles
