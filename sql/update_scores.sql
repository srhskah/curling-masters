-- 更新积分的函数（或触发器）
CREATE TRIGGER calculate_scores AFTER INSERT ON rankings
BEGIN
    UPDATE rankings
    SET score = 
        CASE 
            WHEN (SELECT type FROM tournament WHERE t_id = NEW.t_id) = 1 THEN
                -- 大赛积分计算
                CASE 
                    WHEN NEW.rank = 1 THEN (SELECT player_count * 30 FROM tournament WHERE t_id = NEW.t_id)
                    WHEN NEW.rank = (SELECT player_count FROM tournament WHERE t_id = NEW.t_id) THEN 10
                    ELSE
                        -- 计算等比数列中的积分
                        (SELECT player_count * 30 FROM tournament WHERE t_id = NEW.t_id) * 
                        POWER(
                            (10.0 / (SELECT player_count * 30 FROM tournament WHERE t_id = NEW.t_id)), 
                            (NEW.rank - 1.0) / ((SELECT player_count FROM tournament WHERE t_id = NEW.t_id) - 1.0)
                        )
                END
            WHEN (SELECT type FROM tournament WHERE t_id = NEW.t_id) = 2 THEN
                -- 小赛积分计算
                CASE 
                    WHEN NEW.rank = 1 THEN (SELECT player_count * 20 FROM tournament WHERE t_id = NEW.t_id)
                    WHEN NEW.rank = (SELECT player_count FROM tournament WHERE t_id = NEW.t_id) THEN 10
                    ELSE
                        -- 计算等比数列中的积分
                        (SELECT player_count * 20 FROM tournament WHERE t_id = NEW.t_id) * 
                        POWER(
                            (10.0 / (SELECT player_count * 20 FROM tournament WHERE t_id = NEW.t_id)), 
                            (NEW.rank - 1.0) / ((SELECT player_count FROM tournament WHERE t_id = NEW.t_id) - 1.0)
                        )
                END
            WHEN (SELECT type FROM tournament WHERE t_id = NEW.t_id) = 3 THEN
                -- 总决赛积分计算（等差数列）
                CASE 
                    WHEN NEW.rank = 1 THEN (SELECT player_count FROM tournament WHERE t_id = NEW.t_id)
                    WHEN NEW.rank = (SELECT player_count FROM tournament WHERE t_id = NEW.t_id) THEN 1
                    ELSE
                        -- 计算等差数列中的积分
                        (SELECT player_count FROM tournament WHERE t_id = NEW.t_id) - 
                        ((NEW.rank - 1) * 
                         ((SELECT player_count FROM tournament WHERE t_id = NEW.t_id) - 1.0) / 
                         ((SELECT player_count FROM tournament WHERE t_id = NEW.t_id) - 1.0))
                END
        END
    WHERE id = NEW.id;
END;