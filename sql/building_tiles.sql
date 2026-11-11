-- One row per building for pg2b3dm: its LOD1 geometry and the attributes shown when it is clicked.
-- Attributes live as rows of citydb.property, so each one is pivoted into its own column.
CREATE OR REPLACE VIEW citydb.building_tiles AS
SELECT
    g.id,
    g.geometry,
    max(coalesce(p.val_int::text, p.val_string)) FILTER (WHERE p.name = 'cd_identificador') AS cd_identificador,
    max(coalesce(p.val_string, p.val_int::text)) FILTER (WHERE p.name = 'predio_number') AS predio_number,
    max(p.val_string) FILTER (WHERE p.name = 'predio_name') AS predio_name,
    max(p.val_double) FILTER (WHERE p.name = 'value') AS height_m,
    max(p.val_string) FILTER (WHERE p.name = 'height_source') AS height_source
FROM citydb.geometry_data AS g
JOIN citydb.feature AS f ON f.id = g.feature_id
JOIN citydb.objectclass AS o ON o.id = f.objectclass_id AND o.classname = 'Building'
LEFT JOIN citydb.property AS p ON p.feature_id = f.id
WHERE g.geometry IS NOT NULL
GROUP BY g.id, g.geometry;
