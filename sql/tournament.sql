BEGIN TRANSACTION;
DROP TABLE IF EXISTS "tournament";
CREATE TABLE "tournament" (
	"t_id"	INTEGER NOT NULL,
	"season_id"	INTEGER NOT NULL,
	"type"	INTEGER NOT NULL,
	"t_format"	INTEGER,
	"player_count"	INTEGER,
	"signup_deadline" TEXT,
	"status"	INTEGER NOT NULL DEFAULT 1,
	PRIMARY KEY("t_id" AUTOINCREMENT),
	FOREIGN KEY("season_id") REFERENCES "seasons"("season_id")
);
INSERT INTO "tournament" ("t_id","season_id","type","t_format","player_count","signup_deadline","status") VALUES (1,2,2,6,7,NULL,1),
 (2,1,1,5,6,NULL,1),
 (3,1,1,4,8,NULL,1),
 (4,1,1,5,5,NULL,1),
 (5,2,1,1,12,NULL,1),
 (6,2,1,1,8,NULL,1),
 (7,2,1,4,11,NULL,1),
 (8,2,1,1,10,NULL,1),
 (9,2,1,1,12,NULL,1),
 (10,2,1,4,9,NULL,1),
 (11,2,1,1,15,NULL,1),
 (12,2,1,1,14,NULL,1),
 (13,2,1,1,12,NULL,1),
 (14,2,1,1,16,NULL,1),
 (15,2,2,4,6,NULL,1),
 (16,2,2,4,6,NULL,1),
 (17,2,2,4,6,NULL,1),
 (18,2,2,4,6,NULL,2),
 (19,1,1,1,12,NULL,1),
 (20,1,3,3,8,NULL,1);
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
