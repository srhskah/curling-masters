CREATE TABLE "matches" (
	"m_id"	INTEGER NOT NULL,
	"t_id"	INTEGER NOT NULL,
	"player_1_id"	INTEGER NOT NULL,
	"player_1_score"	INTEGER NOT NULL,
	"player_2_id"	INTEGER NOT NULL,
	"player_2_score"	INTEGER NOT NULL,
	"m_type"	INTEGER NOT NULL,
	PRIMARY KEY("m_id" AUTOINCREMENT),
	FOREIGN KEY("player_1_id") REFERENCES "players"("player_id"),
	FOREIGN KEY("player_2_id") REFERENCES "players"("player_id"),
	FOREIGN KEY("t_id") REFERENCES "tournament"("t_id")
);