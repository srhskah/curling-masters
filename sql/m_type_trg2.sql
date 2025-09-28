-- 为UPDATE操作也创建相同的触发器
DROP TRIGGER IF EXISTS validate_m_type_update;
CREATE TRIGGER validate_m_type_update BEFORE UPDATE ON matches
BEGIN
	SELECT
        CASE
            WHEN NEW.t_id NOT IN (SELECT t_id FROM tournament) THEN
                RAISE(ABORT, '无效的锦标赛ID')
            WHEN (SELECT t_format FROM tournament WHERE t_id = NEW.t_id) = 1 AND NEW.m_type NOT IN (1,2,3,8,10,11,12,13,14) THEN
                RAISE(ABORT, 't_format=1时，m_type必须是1,2,3,8,10,11,12,13,14之一')
            WHEN (SELECT t_format FROM tournament WHERE t_id = NEW.t_id) = 2 AND NEW.m_type NOT IN (1,2,3,7,14) THEN
                RAISE(ABORT, 't_format=2时，m_type必须是1,2,3,7,14之一')
            WHEN (SELECT t_format FROM tournament WHERE t_id = NEW.t_id) = 3 AND NEW.m_type NOT IN (1,2,3,9,10,11,12,13,14) THEN
                RAISE(ABORT, 't_format=3时，m_type必须是1,2,3,9,10,11,12,13,14之一')
            WHEN (SELECT t_format FROM tournament WHERE t_id = NEW.t_id) = 4 AND NEW.m_type NOT IN (1,9,10,11,12,14) THEN
                RAISE(ABORT, 't_format=4时，m_type必须是1,9,10,11,12,14之一')
            WHEN (SELECT t_format FROM tournament WHERE t_id = NEW.t_id) = 5 AND NEW.m_type NOT IN (2,3,9,10,11,12,14) THEN
                RAISE(ABORT, 't_format=5时，m_type必须是2,3,9,10,11,12,14之一')
            WHEN (SELECT t_format FROM tournament WHERE t_id = NEW.t_id) = 6 AND NEW.m_type NOT IN (2,3,9,10,11,12,14) THEN
                RAISE(ABORT, 't_format=6时，m_type必须是2,3,9,10,11,12,14之一')
            WHEN (SELECT t_format FROM tournament WHERE t_id = NEW.t_id) = 7 AND NEW.m_type NOT IN (4,5,6,11,12,14) THEN
                RAISE(ABORT, 't_format=7时，m_type必须是4,5,6,11,12,14之一')
            WHEN (SELECT t_format FROM tournament WHERE t_id = NEW.t_id) = 8 AND NEW.m_type NOT IN (1,2,3,4,5,6,7,8,9,10,11,12,13,14,15) THEN
                RAISE(ABORT, 't_format=8时，m_type必须是1,2,3,4,5,6,7,8,9,10,11,12,13,14,15之一')
        END;
END;