BEGIN TRANSACTION;
DROP TABLE IF EXISTS "seasons";
CREATE TABLE "seasons" (
	"season_id"	INTEGER NOT NULL,
	"year"	TEXT,
	PRIMARY KEY("season_id" AUTOINCREMENT)
);
INSERT INTO "seasons" ("season_id","year") VALUES (1,'2025年上半年'),
 (2,'2025年下半年');
DROP VIEW IF EXISTS "MatchResults";
CREATE VIEW MatchResults AS
SELECT
    m_id,
    t_id,
    player_1_id,
    player_2_id,
    player_1_score,
    player_2_score,
    CASE 
        WHEN player_1_score > player_2_score THEN player_1_id
        WHEN player_2_score > player_1_score THEN player_2_id
        ELSE NULL  -- 平局
    END AS winner_id,
    CASE 
        WHEN player_1_score < player_2_score THEN player_1_id
        WHEN player_2_score < player_1_score THEN player_2_id
        ELSE NULL  -- 平局
    END AS loser_id,
    CASE 
        WHEN player_1_score = player_2_score THEN 1 ELSE 0
    END AS is_draw
FROM Matches;
DROP VIEW IF EXISTS "tournament_session_view";
CREATE VIEW tournament_session_view AS
SELECT 
    t.t_id,
    t.season_id,
    s.year,
    t.type,
    ROW_NUMBER() OVER (PARTITION BY t.season_id, t.type ORDER BY t.t_id) as type_session_number
FROM tournament t
JOIN seasons s ON t.season_id = s.season_id;
COMMIT;
