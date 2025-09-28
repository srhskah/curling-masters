DROP VIEW IF EXISTS "main"."tournament_session_view";
CREATE VIEW tournament_session_view AS
SELECT 
    t.t_id,
    t.season_id,
    s.year,
    t.type,
    ROW_NUMBER() OVER (PARTITION BY t.season_id, t.type ORDER BY t.t_id) as type_session_number
FROM tournament t
JOIN seasons s ON t.season_id = s.season_id;