SELECT 
    p.player_id,
    SUM(CASE WHEN mr.winner_id = p.player_id THEN 1 ELSE 0 END) AS wins,
    SUM(CASE WHEN mr.loser_id = p.player_id THEN 1 ELSE 0 END) AS losses,
    SUM(CASE WHEN mr.is_draw = 1 
             AND (p.player_id IN (mr.player_1_id, mr.player_2_id)) 
             THEN 1 ELSE 0 END) AS draws,
    COUNT(mr.m_id) AS total_matches,
    ROUND(
        SUM(CASE WHEN mr.winner_id = p.player_id THEN 1 ELSE 0 END) * 1.0 /
        COUNT(mr.m_id), 3
    ) AS win_rate,
    ROUND(
        SUM(CASE WHEN mr.is_draw = 1 
                 AND (p.player_id IN (mr.player_1_id, mr.player_2_id)) 
                 THEN 1 ELSE 0 END) * 1.0 /
        COUNT(mr.m_id), 3
    ) AS draw_rate,
    ROUND(
        SUM(CASE WHEN mr.loser_id = p.player_id THEN 1 ELSE 0 END) * 1.0 /
        COUNT(mr.m_id), 3
    ) AS loss_rate
FROM players p
JOIN MatchResults mr
  ON p.player_id IN (mr.player_1_id, mr.player_2_id)
WHERE mr.t_id IN (
    SELECT t_id FROM tournament WHERE season_id = 1
)
GROUP BY p.player_id;
