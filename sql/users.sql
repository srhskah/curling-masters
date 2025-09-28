BEGIN TRANSACTION;
DROP TABLE IF EXISTS "managers";
CREATE TABLE "managers" (
	"manager_id"	INTEGER,
	"username"	TEXT NOT NULL,
	"password"	TEXT NOT NULL,
	PRIMARY KEY("manager_id" AUTOINCREMENT)
);
DROP TABLE IF EXISTS "players";
CREATE TABLE "players" (
	"player_id"	INTEGER NOT NULL,
	"name"	TEXT UNIQUE, status INTEGER NOT NULL DEFAULT 1,
	PRIMARY KEY("player_id" AUTOINCREMENT)
);
DROP TABLE IF EXISTS "users";
CREATE TABLE "users" (
	"uid"	INTEGER,
	"player_id"	INTEGER,
	"username"	TEXT,
	"password"	TEXT NOT NULL,
	"role"	INTEGER NOT NULL, created_at TEXT,
	PRIMARY KEY("uid" AUTOINCREMENT),
	FOREIGN KEY("player_id") REFERENCES "players"("player_id")
);
INSERT INTO "players" ("player_id","name","status") VALUES (1,'Team China',1),
 (2,'leon',1),
 (3,'阿方宇',1),
 (4,'Thiem',1),
 (5,'Edin',1),
 (6,'我会咬人wow',1),
 (7,'玄铁🎾',1),
 (8,'大师兄zzz',1),
 (9,'吴庭艳',1),
 (10,'刘豫博🌟',1),
 (11,'费学清',2),
 (12,'辛在',1),
 (13,'Hedgehog',1),
 (14,'异朴凡新',1),
 (15,'九五.',1),
 (16,'小麻',1),
 (17,'哲',1),
 (18,'霍曼(B)',1),
 (19,'霍曼(A)',1),
 (20,'乌干达国家队',1),
 (21,'single',1),
 (22,'老韩',1),
 (23,'Re.',1),
 (24,'Kranj吴老师',1),
 (25,'格林纳达',1),
 (26,'食无味',1),
 (27,'王冰玉',1),
 (28,'名校风暴',1),
 (29,'贺傲',1),
 (30,'马晓朋',1),
 (31,'α蛋',1),
 (32,'Wu',1),
 (33,'👬Lonely',1),
 (34,'La Fe',1),
 (35,'大健',2),
 (36,'高兴她爹🥕',2),
 (37,'in a world like this',2),
 (38,'退赛',3),
 (39,'大赛排名已移除',3),
 (40,'小赛排名已移除',3),
 (41,'Novak',2),
 (42,'管理员（测试）',1),
 (43,'普通选手（测试）',1);
INSERT INTO "users" ("uid","player_id","username","password","role","created_at") VALUES (1,9,'srhskah','scrypt:32768:8:1$ZACaTlwof5iZJ3FI$50efc1a5e345d1001f0e5a8f4b3d615e1c20ad043b6a9e03f37f038606b3d5adec23786ceeed1b48157725d5ccdb9ee79a82f685db6605d053038dee81f641cf',0,'2025-09-27 02:13:05');
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
