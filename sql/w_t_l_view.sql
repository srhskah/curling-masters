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
