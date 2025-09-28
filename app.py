import os
from flask import Flask, render_template, request, redirect, url_for, jsonify, abort, session, flash
from dotenv import load_dotenv

load_dotenv()

from sqlalchemy.pool import NullPool
from sqlalchemy.exc import OperationalError as SAOperationalError
import time
from sqlalchemy import text

app = Flask(__name__)

# app.run(host="0.0.0.0", port=5000, debug=True)


# 数据库配置 - 支持本地SQLCipher和远程Turso一键切换
from database_config import get_database_config

# 获取数据库配置
db_config = get_database_config()

# 应用数据库配置
app.config['SQLALCHEMY_DATABASE_URI'] = db_config['SQLALCHEMY_DATABASE_URI']
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'change-me')
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = db_config['SQLALCHEMY_ENGINE_OPTIONS']

from db import db

# initialize db with app
db.init_app(app)

# 在应用上下文中添加事件监听器
with app.app_context():
    from sqlalchemy import event
    
    # 添加事件监听器来设置 SQLCipher 密钥
    @event.listens_for(db.engine, "connect")
    def set_sqlcipher_key(dbapi_connection, connection_record):
        """在连接时设置 SQLCipher 加密密钥"""
        cursor = dbapi_connection.cursor()
        cursor.execute(f"PRAGMA key = '{ENCRYPTION_KEY}';")
        cursor.close()

# 添加Jinja2过滤器
@app.template_filter('get_factors')
def get_factors_filter(n):
    """获取数字的所有因数（除了自身）"""
    factors = []
    for i in range(1, n):
        if n % i == 0:
            factors.append(i)
    return factors

# import models after db is initialized to avoid circular imports
with app.app_context():
    from models import Season, Tournament, Player, Match, Manager, Ranking, User, Signup

# 在每次底层连接建立时设置 SQLite PRAGMA，以使用 WAL 模式和外键支持，减少锁冲突
from sqlalchemy import event
from sqlalchemy.engine import Engine
from functools import wraps


@event.listens_for(Engine, 'connect')
def _set_sqlite_pragma(dbapi_connection, connection_record):
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute('PRAGMA journal_mode=WAL')
        cursor.execute('PRAGMA synchronous=NORMAL')
        cursor.execute('PRAGMA busy_timeout=30000')
    # NOTE: do not force foreign_keys=ON here because some existing DB schemas
    # in this project contain malformed FOREIGN KEY definitions (REFERENCES ""),
    # which cause SQLite to error when foreign key enforcement is enabled.
    # We will fix the schema with a migration script; until then, keep
    # foreign_keys as the database default to avoid "no such table: main." errors.
    # cursor.execute('PRAGMA foreign_keys=ON')
        cursor.close()
    except Exception:
        # 非 SQLite 或执行失败则忽略
        pass


def commit_with_retry(retries: int = 5, initial_delay: float = 0.05):
    """尝试提交，若遇到 sqlite 锁定则回退并重试（指数回退）。"""
    delay = initial_delay
    for i in range(retries):
        try:
            db.session.commit()
            return
        except SAOperationalError as e:
            if 'database is locked' in str(e).lower():
                try:
                    db.session.rollback()
                except Exception:
                    pass
                time.sleep(delay)
                delay *= 2
                continue
            raise
    # 最后一次尝试，让异常抛出
    db.session.commit()


def get_tournament_pagination(t_id):
    """获取赛事翻页信息"""
    try:
        # 获取当前赛事信息
        current_tournament = db.session.get(Tournament, t_id)
        if not current_tournament:
            return None
        
        # 获取同类型赛事翻页信息（先按赛季排序，再按届次排序）
        # 特殊规则：season_id=1跳过第13届正赛
        from sqlalchemy import text
        same_type_query = text("""
            SELECT t.t_id, t.type, t.season_id, s.year, tsv.type_session_number
            FROM tournament t
            JOIN tournament_session_view tsv ON t.t_id = tsv.t_id
            JOIN seasons s ON t.season_id = s.season_id
            WHERE t.type = :tournament_type
            AND NOT (t.season_id = 1 AND t.t_id = 14)  -- 跳过season_id=1的第13届正赛
            ORDER BY s.year, tsv.type_session_number
        """)
        
        result = db.session.execute(same_type_query, {'tournament_type': current_tournament.type})
        same_type_tournaments = result.fetchall()
        
        # 找到当前赛事在同类型中的位置
        current_index = None
        for i, (t_id_val, t_type, season_id, year, session_num) in enumerate(same_type_tournaments):
            if t_id_val == t_id:
                current_index = i
                break
        
        same_type_pagination = None
        if current_index is not None:
            prev_info = None
            next_info = None
            
            if current_index > 0:
                prev_t_id, prev_type, prev_season_id, prev_year, prev_session_num = same_type_tournaments[current_index - 1]
                prev_info = {
                    't_id': prev_t_id,
                    'season_year': prev_year,
                    'session_number': prev_session_num,
                    'type_name': '正赛' if prev_type == 1 else '小赛' if prev_type == 2 else '总决赛' if prev_type == 3 else f'类型{prev_type}'
                }
            
            if current_index < len(same_type_tournaments) - 1:
                next_t_id, next_type, next_season_id, next_year, next_session_num = same_type_tournaments[current_index + 1]
                next_info = {
                    't_id': next_t_id,
                    'season_year': next_year,
                    'session_number': next_session_num,
                    'type_name': '正赛' if next_type == 1 else '小赛' if next_type == 2 else '总决赛' if next_type == 3 else f'类型{next_type}'
                }
            
            same_type_pagination = {
                'has_prev': current_index > 0,
                'has_next': current_index < len(same_type_tournaments) - 1,
                'prev_info': prev_info,
                'next_info': next_info,
                'current_index': current_index + 1,
                'total_count': len(same_type_tournaments)
            }
        
        # 获取所有赛事翻页信息 - 实现正赛小赛交替排序
        # 从2025年下半年第5届正赛开始，默认是一届正赛后一届小赛
        all_tournaments_query = text("""
            SELECT t.t_id, t.type, t.season_id, s.year, tsv.type_session_number, t.status,
                   CASE 
                     WHEN s.year = '2025年下半年' THEN
                       -- 2025年下半年，按交替顺序排序
                       CASE 
                         WHEN t.type = 1 AND tsv.type_session_number <= 4 THEN 
                           -- 第1-4届正赛：编号1-4
                           tsv.type_session_number
                         WHEN t.type = 1 AND tsv.type_session_number = 5 THEN 
                           -- 第5届正赛：编号5
                           5
                         WHEN t.type = 2 AND tsv.type_session_number = 1 THEN 
                           -- 第1届小赛：编号6
                           6
                         WHEN t.type = 1 AND tsv.type_session_number = 6 THEN 
                           -- 第6届正赛：编号7
                           7
                         WHEN t.type = 2 AND tsv.type_session_number = 2 THEN 
                           -- 第2届小赛：编号8
                           8
                         WHEN t.type = 1 AND tsv.type_session_number >= 7 THEN 
                           -- 第7届及以后正赛：编号9, 11, 13...
                           (tsv.type_session_number - 7) * 2 + 9
                         WHEN t.type = 2 AND tsv.type_session_number >= 3 THEN 
                           -- 第3届及以后小赛：编号10, 12, 14...
                           (tsv.type_session_number - 3) * 2 + 10
                         ELSE tsv.type_session_number + 1000  -- 其他类型放最后
                       END
                     ELSE
                       -- 其他情况按原逻辑排序，但确保唯一性
                       CASE 
                         WHEN t.type = 1 THEN tsv.type_session_number + 20000
                         WHEN t.type = 2 THEN tsv.type_session_number + 30000
                         WHEN t.type = 3 THEN tsv.type_session_number + 40000
                         ELSE tsv.type_session_number + 50000
                       END
                   END as sort_order
            FROM tournament t
            JOIN tournament_session_view tsv ON t.t_id = tsv.t_id
            JOIN seasons s ON t.season_id = s.season_id
            WHERE t.status = 1  -- 只显示正常状态的赛事
            ORDER BY s.year, sort_order, t.t_id
        """)
        
        result = db.session.execute(all_tournaments_query)
        all_tournaments = result.fetchall()
        
        # 找到当前赛事在历届中的位置
        current_all_index = None
        for i, (t_id_val, t_type, season_id, year, session_num, status, sort_order) in enumerate(all_tournaments):
            if t_id_val == t_id:
                current_all_index = i
                break
        
        all_tournaments_pagination = None
        if current_all_index is not None:
            prev_info = None
            next_info = None
            
            if current_all_index > 0:
                prev_t_id, prev_type, prev_season_id, prev_year, prev_session_num, prev_status, prev_sort_order = all_tournaments[current_all_index - 1]
                prev_info = {
                    't_id': prev_t_id,
                    'season_year': prev_year,
                    'session_number': prev_session_num,
                    'type_name': '正赛' if prev_type == 1 else '小赛' if prev_type == 2 else '总决赛' if prev_type == 3 else f'类型{prev_type}'
                }
            
            if current_all_index < len(all_tournaments) - 1:
                next_t_id, next_type, next_season_id, next_year, next_session_num, next_status, next_sort_order = all_tournaments[current_all_index + 1]
                next_info = {
                    't_id': next_t_id,
                    'season_year': next_year,
                    'session_number': next_session_num,
                    'type_name': '正赛' if next_type == 1 else '小赛' if next_type == 2 else '总决赛' if next_type == 3 else f'类型{next_type}'
                }
            
            all_tournaments_pagination = {
                'has_prev': current_all_index > 0,
                'has_next': current_all_index < len(all_tournaments) - 1,
                'prev_info': prev_info,
                'next_info': next_info,
                'current_index': current_all_index + 1,
                'total_count': len(all_tournaments)
            }
        
        return {
            'same_type': same_type_pagination,
            'all_tournaments': all_tournaments_pagination
        }
        
    except Exception as e:
        print(f"获取翻页信息失败: {e}")
        import traceback
        traceback.print_exc()
        return None

def get_season_pagination(season_id):
    """获取赛季翻页信息"""
    try:
        # 获取所有赛季，按年份排序
        seasons = Season.query.order_by(Season.year).all()
        
        # 找到当前赛季的位置
        current_index = None
        for i, season in enumerate(seasons):
            if season.season_id == season_id:
                current_index = i
                break
        
        if current_index is None:
            return None
        
        # 构建翻页信息
        prev_info = None
        next_info = None
        
        if current_index > 0:
            prev_season = seasons[current_index - 1]
            prev_info = {
                'season_id': prev_season.season_id,
                'year': prev_season.year
            }
        
        if current_index < len(seasons) - 1:
            next_season = seasons[current_index + 1]
            next_info = {
                'season_id': next_season.season_id,
                'year': next_season.year
            }
        
        return {
            'has_prev': current_index > 0,
            'has_next': current_index < len(seasons) - 1,
            'prev_info': prev_info,
            'next_info': next_info,
            'current_index': current_index + 1,
            'total_count': len(seasons)
        }
        
    except Exception as e:
        print(f"获取赛季翻页信息失败: {e}")
        import traceback
        traceback.print_exc()
        return None

def calculate_tournament_scores(t_id):
    """计算指定赛事的积分并更新到数据库"""
    try:
        # 获取赛事信息
        tournament = db.session.get(Tournament, t_id)
        if not tournament:
            print(f"赛事 {t_id} 不存在")
            return False
        
        # 获取该赛事的所有排名
        rankings = Ranking.query.filter_by(t_id=t_id).order_by(Ranking.ranks).all()
        if not rankings:
            print(f"赛事 {t_id} 没有排名数据")
            return False
        
        player_count = len(rankings)
        tournament_type = tournament.type
        
        print(f"计算赛事 {t_id} 积分: type={tournament_type}, player_count={player_count}")
        
        # 根据赛事类型计算积分
        if tournament_type == 1:  # 大赛
            # 第1名: player_count*30, 最后一名: 10
            first_score = player_count * 30
            last_score = 10
            
            if player_count == 1:
                # 只有1个人
                scores = [first_score]
            elif player_count == 2:
                # 只有2个人
                scores = [first_score, last_score]
            else:
                # 等比数列计算
                # 第1名: first_score, 第2名: first_score/r, ..., 倒数第2名: last_score*r, 最后一名: last_score
                # 等比数列: a1, a1*r, a1*r^2, ..., a1*r^(n-1)
                # 其中 a1 = first_score, a1*r^(n-1) = last_score
                # 所以 r^(n-1) = last_score/first_score
                # r = (last_score/first_score)^(1/(n-1))
                r = (last_score / first_score) ** (1 / (player_count - 1))
                scores = [first_score * (r ** (i - 1)) for i in range(1, player_count + 1)]
                
        elif tournament_type == 2:  # 小赛
            # 第1名: player_count*20, 最后一名: 10
            first_score = player_count * 20
            last_score = 10
            
            if player_count == 1:
                scores = [first_score]
            elif player_count == 2:
                scores = [first_score, last_score]
            else:
                # 等比数列计算
                r = (last_score / first_score) ** (1 / (player_count - 1))
                scores = [first_score * (r ** (i - 1)) for i in range(1, player_count + 1)]
                
        elif tournament_type == 3:  # 总决赛
            # 第1名: player_count, 最后一名: 1, 等差数列
            first_score = player_count
            last_score = 1
            
            if player_count == 1:
                scores = [first_score]
            elif player_count == 2:
                scores = [first_score, last_score]
            else:
                # 等差数列计算
                # a1 = first_score, an = last_score
                # d = (an - a1) / (n - 1)
                d = (last_score - first_score) / (player_count - 1)
                scores = [first_score + d * (i - 1) for i in range(1, player_count + 1)]
        else:
            print(f"未知的赛事类型: {tournament_type}")
            return False
        
        # 更新积分到数据库
        for i, ranking in enumerate(rankings):
            ranking.scores = int(round(scores[i]))
            print(f"  排名 {ranking.ranks}: 选手 {ranking.player_id} -> 积分 {ranking.scores}")
        
        # 使用直接SQL更新确保保存成功
        import sqlite3
        DB = os.path.join(os.path.dirname(__file__), 'curling_masters.db')
        conn = sqlite3.connect(DB)
        cur = conn.cursor()
        for i, ranking in enumerate(rankings):
            cur.execute('UPDATE rankings SET scores = ? WHERE r_id = ?', (int(round(scores[i])), ranking.r_id))
        conn.commit()
        conn.close()
        print(f"赛事 {t_id} 积分计算完成")
        return True
        
    except Exception as e:
        print(f"计算赛事 {t_id} 积分时出错: {e}")
        import traceback
        traceback.print_exc()
        return False

def check_playoff_result(t_id, player1_id, player2_id):
    """检查两个选手之间是否有附加赛结果"""
    from sqlalchemy import text
    
    playoff_query = text("""
        SELECT player_1_score, player_2_score
        FROM matches
        WHERE t_id = :t_id AND m_type = 14
        AND ((player_1_id = :p1_id AND player_2_id = :p2_id) OR 
             (player_1_id = :p2_id AND player_2_id = :p1_id))
        AND player_1_score IS NOT NULL AND player_2_score IS NOT NULL
    """)
    
    result = db.session.execute(playoff_query, {
        't_id': t_id, 
        'p1_id': player1_id, 
        'p2_id': player2_id
    }).fetchone()
    
    if not result:
        return 0  # 没有附加赛
    
    score1, score2 = result
    
    # 需要确定哪个是player1的分数
    # 先查询比赛的主客队信息
    match_query = text("""
        SELECT player_1_id, player_2_id
        FROM matches
        WHERE t_id = :t_id AND m_type = 14
        AND ((player_1_id = :p1_id AND player_2_id = :p2_id) OR 
             (player_1_id = :p2_id AND player_2_id = :p1_id))
        LIMIT 1
    """)
    
    match_result = db.session.execute(match_query, {
        't_id': t_id,
        'p1_id': player1_id,
        'p2_id': player2_id
    }).fetchone()
    
    if match_result:
        match_p1_id, match_p2_id = match_result
        if match_p1_id == player1_id:  # player1是主队
            if score1 > score2:
                return 1  # player1胜
            elif score2 > score1:
                return -1  # player2胜
            else:
                return 0  # 平局
        else:  # player2是主队
            if score2 > score1:
                return 1  # player1胜
            elif score1 > score2:
                return -1  # player2胜
            else:
                return 0  # 平局
    
    return 0  # 默认平局

def apply_playoff_results(t_id, players):
    """应用附加赛结果到选手数据中（只影响净胜分和总进球，不影响积分）"""
    from sqlalchemy import text
    
    for player in players:
        player_id = player['player_id']
        
        # 查询该选手的附加赛结果
        playoff_query = text("""
            SELECT player_1_score, player_2_score, player_1_id, player_2_id
            FROM matches
            WHERE t_id = :t_id AND m_type = 14
            AND (player_1_id = :player_id OR player_2_id = :player_id)
            AND player_1_score IS NOT NULL AND player_2_score IS NOT NULL
            AND player_1_score >= 0 AND player_2_score >= 0
        """)
        
        playoff_results = db.session.execute(playoff_query, {
            't_id': t_id,
            'player_id': player_id
        }).fetchall()
        
        # 应用附加赛结果（只有胜者获得净胜分和总进球的增加）
        for score1, score2, p1_id, p2_id in playoff_results:
            if p1_id == player_id:
                # 该选手是主队
                if score1 > score2:
                    # 该选手获胜，增加净胜分和总进球
                    player['goals_for'] += score1
                    player['goals_against'] += score2
                    player['goal_difference'] = player['goals_for'] - player['goals_against']
                # 如果该选手失败，不改变任何数据
            else:
                # 该选手是客队
                if score2 > score1:
                    # 该选手获胜，增加净胜分和总进球
                    player['goals_for'] += score2
                    player['goals_against'] += score1
                    player['goal_difference'] = player['goals_for'] - player['goals_against']
                # 如果该选手失败，不改变任何数据

def generate_playoff_matches(t_id, tied_players):
    """为完全相同的选手生成附加赛"""
    from sqlalchemy import text
    
    # 检查是否已经有附加赛
    existing_playoffs_query = text("""
        SELECT COUNT(*) FROM matches
        WHERE t_id = :t_id AND m_type = 14
    """)
    
    existing_count = db.session.execute(existing_playoffs_query, {'t_id': t_id}).fetchone()[0]
    
    if existing_count > 0:
        return  # 已经有附加赛，不重复生成
    
    # 为每对完全相同的选手生成附加赛
    for i in range(len(tied_players)):
        for j in range(i + 1, len(tied_players)):
            player1 = tied_players[i]
            player2 = tied_players[j]
            
            # 检查是否已经有这两人的附加赛
            check_query = text("""
                SELECT COUNT(*) FROM matches
                WHERE t_id = :t_id AND m_type = 14
                AND ((player_1_id = :p1_id AND player_2_id = :p2_id) OR 
                     (player_1_id = :p2_id AND player_2_id = :p1_id))
            """)
            
            count = db.session.execute(check_query, {
                't_id': t_id,
                'p1_id': player1['player_id'],
                'p2_id': player2['player_id']
            }).fetchone()[0]
            
            if count == 0:
                # 生成附加赛
                insert_query = text("""
                    INSERT INTO matches (t_id, player_1_id, player_2_id, player_1_score, player_2_score, m_type)
                    VALUES (:t_id, :p1_id, :p2_id, 0, 0, 14)
                """)
                
                db.session.execute(insert_query, {
                    't_id': t_id,
                    'p1_id': player1['player_id'],
                    'p2_id': player2['player_id']
                })
    
    db.session.commit()

def calculate_same_points_ranking_for_round_robin(players_with_same_points, t_id, generate_playoffs=False):
    """计算单循环赛同积分选手的内部胜负关系排名"""
    from sqlalchemy import text
    
    # 获取这些选手之间的所有比赛
    player_ids = [p['player_id'] for p in players_with_same_points]
    player_ids_str = ','.join(map(str, player_ids))
    
    matches_query = text(f"""
        SELECT player_1_id, player_2_id, player_1_score, player_2_score
        FROM matches
        WHERE t_id = :t_id AND m_type = 1
        AND player_1_id IN ({player_ids_str}) AND player_2_id IN ({player_ids_str})
        AND player_1_score IS NOT NULL AND player_2_score IS NOT NULL
    """)
    
    result = db.session.execute(matches_query, {'t_id': t_id}).fetchall()
    
    # 计算每个选手对同积分选手的胜负关系
    for player in players_with_same_points:
        h2h_points = 0
        h2h_wins = 0
        h2h_draws = 0
        h2h_losses = 0
        h2h_goals_for = 0
        h2h_goals_against = 0
        
        for match in result:
            p1_id, p2_id, score_1, score_2 = match
            
            if p1_id == player['player_id']:
                # 该选手是主队
                h2h_goals_for += score_1
                h2h_goals_against += score_2
                if score_1 > score_2:
                    h2h_wins += 1
                    h2h_points += 3
                elif score_1 == score_2:
                    h2h_draws += 1
                    h2h_points += 1
                else:
                    h2h_losses += 1
            elif p2_id == player['player_id']:
                # 该选手是客队
                h2h_goals_for += score_2
                h2h_goals_against += score_1
                if score_2 > score_1:
                    h2h_wins += 1
                    h2h_points += 3
                elif score_2 == score_1:
                    h2h_draws += 1
                    h2h_points += 1
                else:
                    h2h_losses += 1
        
        player['h2h_points'] = h2h_points
        player['h2h_wins'] = h2h_wins
        player['h2h_draws'] = h2h_draws
        player['h2h_losses'] = h2h_losses
        player['h2h_goal_difference'] = h2h_goals_for - h2h_goals_against
    
    # 按照正确的排序：净胜分 -> 内部胜负关系 -> 总得分
    def compare_h2h(player1, player2):
        # 1. 先比较净胜分（当届比赛的总净胜分）
        if player1['goal_difference'] != player2['goal_difference']:
            return player2['goal_difference'] - player1['goal_difference']
        
        # 2. 净胜分相同，比较内部胜负关系积分
        if player1['h2h_points'] != player2['h2h_points']:
            return player2['h2h_points'] - player1['h2h_points']
        
        # 3. 内部胜负关系积分相同，比较相互之间的胜负关系
        for match in result:
            p1_id, p2_id, score_1, score_2 = match
            
            # 找到两人之间的比赛
            if (p1_id == player1['player_id'] and p2_id == player2['player_id']) or \
               (p1_id == player2['player_id'] and p2_id == player1['player_id']):
                
                if p1_id == player1['player_id']:
                    # player1是主队
                    if score_1 > score_2:
                        return -1  # player1排在前面
                    elif score_2 > score_1:
                        return 1   # player2排在前面
                    else:
                        break  # 平局，继续比较其他指标
                else:
                    # player2是主队
                    if score_2 > score_1:
                        return -1  # player2排在前面
                    elif score_1 > score_2:
                        return 1   # player1排在前面
                    else:
                        break  # 平局，继续比较其他指标
        
        # 4. 相互胜负关系相同（平局或未交手），比较总得分
        if player1['goals_for'] != player2['goals_for']:
            return player2['goals_for'] - player1['goals_for']
        
        # 5. 所有指标都相同，需要生成附加赛
        # 先检查是否已经有附加赛
        playoff_result = check_playoff_result(t_id, player1['player_id'], player2['player_id'])
        if playoff_result != 0:
            return -playoff_result  # 1表示player1胜，返回-1让player1排在前面
        
        # 6. 没有附加赛或附加赛平局，按姓名排序
        if player1['name'] < player2['name']:
            return -1
        elif player1['name'] > player2['name']:
            return 1
        else:
            return 0
    
    from functools import cmp_to_key
    players_with_same_points.sort(key=cmp_to_key(compare_h2h))
    
    # 应用附加赛结果到排名计算中
    apply_playoff_results(t_id, players_with_same_points)
    
    # 检测完全相同的选手（所有指标都相同）
    tied_groups = []
    current_group = [players_with_same_points[0]]
    
    for i in range(1, len(players_with_same_points)):
        prev_player = players_with_same_points[i-1]
        curr_player = players_with_same_points[i]
        
        # 检查是否所有指标都相同
        if (prev_player['goal_difference'] == curr_player['goal_difference'] and
            prev_player['h2h_points'] == curr_player['h2h_points'] and
            prev_player['goals_for'] == curr_player['goals_for']):
            current_group.append(curr_player)
        else:
            if len(current_group) > 1:
                tied_groups.append(current_group)
            current_group = [curr_player]
    
    # 处理最后一组
    if len(current_group) > 1:
        tied_groups.append(current_group)
    
    # 为完全相同的选手生成附加赛（仅在明确要求时）
    if generate_playoffs:
        for tied_group in tied_groups:
            generate_playoff_matches(t_id, tied_group)
    
    return players_with_same_points

def calculate_head_to_head_result(player1_id, player2_id, matches):
    """计算两个选手之间的胜负关系（谁赢了谁）"""
    player1_wins = 0
    player2_wins = 0
    
    for match in matches:
        if len(match) == 5:  # 包含m_type字段
            p1_id, p1_score, p2_id, p2_score, m_type = match
        else:  # 不包含m_type字段（向后兼容）
            p1_id, p1_score, p2_id, p2_score = match
            m_type = 1
        
        # 检查是否是这两个选手之间的比赛
        if ((p1_id == player1_id and p2_id == player2_id) or 
            (p1_id == player2_id and p2_id == player1_id)):
            
            if p1_id == player1_id:
                # player1是主队
                if p1_score > p2_score:
                    player1_wins += 1
                elif p2_score > p1_score:
                    player2_wins += 1
            else:
                # player1是客队
                if p2_score > p1_score:
                    player1_wins += 1
                elif p1_score > p2_score:
                    player2_wins += 1
    
    # 返回胜负关系：1表示player1胜，-1表示player2胜，0表示平局或未交手
    if player1_wins > player2_wins:
        return 1
    elif player2_wins > player1_wins:
        return -1
    else:
        return 0

def calculate_knockout_matches(t_id):
    """计算淘汰赛数据（通用函数，支持所有赛制）"""
    try:
        from sqlalchemy import text
        
        # 获取所有淘汰赛类型的比赛
        knockout_query = text("""
            SELECT m.m_id, m.m_type, m.player_1_id, m.player_1_score, m.player_2_id, m.player_2_score,
                   p1.name as player1_name, p2.name as player2_name
            FROM matches m
            LEFT JOIN players p1 ON m.player_1_id = p1.player_id
            LEFT JOIN players p2 ON m.player_2_id = p2.player_id
            WHERE m.t_id = :t_id AND m.m_type IN (8, 9, 10, 11, 12, 13)
            ORDER BY m.m_type, m.m_id
        """)
        
        knockout_result = db.session.execute(knockout_query, {'t_id': t_id}).fetchall()
        
        if not knockout_result:
            return []
        
        knockout_matches = []
        for match_row in knockout_result:
            m_id, m_type, player_1_id, player_1_score, player_2_id, player_2_score, player1_name, player2_name = match_row
            
            knockout_matches.append({
                'm_id': m_id,
                'm_type': m_type,
                'player_1_id': player_1_id,
                'player_1_score': player_1_score,
                'player_2_id': player_2_id,
                'player_2_score': player_2_score,
                'player1': {'name': player1_name or '待定'},
                'player2': {'name': player2_name or '待定'}
            })
        
        return knockout_matches
        
    except Exception as e:
        print(f"计算淘汰赛数据失败: {e}")
        return []


def calculate_round_robin_standings(t_id):
    try:
        from sqlalchemy import text
        
        # 获取赛事格式信息
        tournament_query = text("""
            SELECT t_format FROM tournament WHERE t_id = :t_id
        """)
        tournament_result = db.session.execute(tournament_query, {'t_id': t_id}).fetchone()
        if not tournament_result:
            return []
        
        t_format = tournament_result[0]
        
        # 根据赛事格式确定要统计的比赛类型
        if t_format == 6:  # 苏超赛制（CM250）
            # 苏超赛制：统计主客场小组赛（m_type=2和3）
            matches_query = text("""
                SELECT player_1_id, player_1_score, player_2_id, player_2_score, m_type
                FROM matches
                WHERE t_id = :t_id AND m_type IN (2, 3) AND player_1_score IS NOT NULL AND player_2_score IS NOT NULL
                AND player_1_score >= 0 AND player_2_score >= 0
            """)
        elif t_format == 4:  # 单循环赛
            # 单循环赛：统计所有小组赛类型的比赛（m_type=1,2,3），附加赛不参与积分计算
            matches_query = text("""
                SELECT player_1_id, player_1_score, player_2_id, player_2_score, m_type
                FROM matches
                WHERE t_id = :t_id AND m_type IN (1, 2, 3) AND player_1_score IS NOT NULL AND player_2_score IS NOT NULL AND player_1_score >= 0 AND player_2_score >= 0
            """)
        else:
            # 其他赛制：统计普通小组赛（m_type=1）
            matches_query = text("""
                SELECT player_1_id, player_1_score, player_2_id, player_2_score, m_type
                FROM matches
                WHERE t_id = :t_id AND m_type = 1 AND player_1_score IS NOT NULL AND player_2_score IS NOT NULL
                AND player_1_score >= 0 AND player_2_score >= 0
            """)
        matches = db.session.execute(matches_query, {'t_id': t_id}).fetchall()
        
        # 获取该赛事的所有参赛选手
        players_query = text("""
            SELECT DISTINCT p.player_id, p.name
            FROM players p
            JOIN rankings r ON p.player_id = r.player_id
            WHERE r.t_id = :t_id
            ORDER BY p.name
        """)
        players = db.session.execute(players_query, {'t_id': t_id}).fetchall()
        
        # 初始化选手统计数据
        standings = {}
        for player_id, player_name in players:
            # 计算该选手需要打的总场次数
            total_matches = calculate_player_total_matches(t_id, player_id, t_format)
            
            standings[player_id] = {
                'player_id': player_id,
                'name': player_name,
                'matches_played': 0,
                'total_matches': total_matches,  # 添加总场次字段
                'wins': 0,
                'draws': 0,
                'losses': 0,
                'goals_for': 0,
                'goals_against': 0,
                'goal_difference': 0,
                'points': 0
            }
        
        # 确保比赛中的所有选手都在standings中
        for match in matches:
            if len(match) == 5:  # 包含m_type字段
                player_1_id, player_1_score, player_2_id, player_2_score, m_type = match
            else:  # 不包含m_type字段（向后兼容）
                player_1_id, player_1_score, player_2_id, player_2_score = match
                m_type = 1
            
            if player_1_id not in standings:
                # 计算该选手需要打的总场次数
                total_matches = calculate_player_total_matches(t_id, player_1_id, t_format)
                
                standings[player_1_id] = {
                    'player_id': player_1_id,
                    'name': f'选手{player_1_id}',
                    'matches_played': 0,
                    'total_matches': total_matches,  # 添加总场次字段
                    'wins': 0,
                    'draws': 0,
                    'losses': 0,
                    'goals_for': 0,
                    'goals_against': 0,
                    'goal_difference': 0,
                    'points': 0
                }
            if player_2_id not in standings:
                # 计算该选手需要打的总场次数
                total_matches = calculate_player_total_matches(t_id, player_2_id, t_format)
                
                standings[player_2_id] = {
                    'player_id': player_2_id,
                    'name': f'选手{player_2_id}',
                    'matches_played': 0,
                    'total_matches': total_matches,  # 添加总场次字段
                    'wins': 0,
                    'draws': 0,
                    'losses': 0,
                    'goals_for': 0,
                    'goals_against': 0,
                    'goal_difference': 0,
                    'points': 0
                }
        
        # 计算比赛结果
        for match in matches:
            if len(match) == 5:  # 包含m_type字段
                player_1_id, player_1_score, player_2_id, player_2_score, m_type = match
            else:  # 不包含m_type字段（向后兼容）
                player_1_id, player_1_score, player_2_id, player_2_score = match
                m_type = 1
            
            # 更新比赛场次
            standings[player_1_id]['matches_played'] += 1
            standings[player_2_id]['matches_played'] += 1
            
            # 更新进球数
            standings[player_1_id]['goals_for'] += player_1_score
            standings[player_1_id]['goals_against'] += player_2_score
            standings[player_2_id]['goals_for'] += player_2_score
            standings[player_2_id]['goals_against'] += player_1_score
            
            # 判断胜负
            if player_1_score > player_2_score:
                standings[player_1_id]['wins'] += 1
                standings[player_1_id]['points'] += 3
                standings[player_2_id]['losses'] += 1
            elif player_2_score > player_1_score:
                standings[player_2_id]['wins'] += 1
                standings[player_2_id]['points'] += 3
                standings[player_1_id]['losses'] += 1
            elif player_1_score == player_2_score and player_1_score > 0:
                # 只有双方都有得分且得分相同才算平局，0-0不算平局
                standings[player_1_id]['draws'] += 1
                standings[player_1_id]['points'] += 1
                standings[player_2_id]['draws'] += 1
                standings[player_2_id]['points'] += 1
            # 0-0的情况暂不计入胜平负统计，只计入场次和进球数
        
        # 计算净胜球
        for player_id in standings:
            standings[player_id]['goal_difference'] = standings[player_id]['goals_for'] - standings[player_id]['goals_against']
        
        # 按排名规则排序：积分 > 胜负关系 > 净胜球 > 总进球
        
        # 转换为列表并排序
        standings_list = list(standings.values())
        
        # 按积分分组，对同积分选手进行特殊排序
        from collections import defaultdict
        points_groups = defaultdict(list)
        
        for player in standings_list:
            points_groups[player['points']].append(player)
        
        # 重新排序
        final_standings = []
        for points in sorted(points_groups.keys(), reverse=True):
            group = points_groups[points]
            if len(group) == 1:
                # 只有一个选手，直接添加
                final_standings.extend(group)
            else:
                # 多个选手同积分，需要计算内部胜负关系
                ranked_group = calculate_same_points_ranking_for_round_robin(group, t_id, generate_playoffs=False)
                final_standings.extend(ranked_group)
        
        standings_list = final_standings
        
        # 添加排名
        for i, player_data in enumerate(standings_list):
            player_data['rank'] = i + 1
        
        return standings_list
        
    except Exception as e:
        print(f"计算单循环排名失败: {e}")
        print(f"错误详情: 赛事ID={t_id}")
        import traceback
        traceback.print_exc()
        return []


def check_round_robin_complete(t_id):
    """检查小组赛是否全部完成（两两交手）"""
    try:
        from sqlalchemy import text
        
        # 获取赛事格式信息
        tournament_query = text("""
            SELECT t_format FROM tournament WHERE t_id = :t_id
        """)
        tournament_result = db.session.execute(tournament_query, {'t_id': t_id}).fetchone()
        if not tournament_result:
            return False
        
        t_format = tournament_result[0]
        
        # 获取参赛选手数量
        players_query = text("""
            SELECT COUNT(DISTINCT player_id) as player_count
            FROM rankings
            WHERE t_id = :t_id
        """)
        player_count = db.session.execute(players_query, {'t_id': t_id}).fetchone()[0]
        
        # 根据赛事格式计算应该进行的比赛场次
        if t_format == 6:  # 苏超赛制（CM250）
            # 苏超赛制：单循环但区分主客场，n*(n-1)/2场
            expected_matches = player_count * (player_count - 1) // 2
            
            # 计算已完成的主客场小组赛场次
            completed_matches_query = text("""
                SELECT COUNT(*) as completed_count
                FROM matches
                WHERE t_id = :t_id AND m_type IN (2, 3) 
                AND player_1_score IS NOT NULL AND player_2_score IS NOT NULL
                AND player_1_score >= 0 AND player_2_score >= 0
            """)
        else:
            # 其他赛制：单循环，n*(n-1)/2场
            expected_matches = player_count * (player_count - 1) // 2
            
            # 计算已完成的小组赛场次
            completed_matches_query = text("""
                SELECT COUNT(*) as completed_count
                FROM matches
                WHERE t_id = :t_id AND m_type = 1 
                AND player_1_score IS NOT NULL AND player_2_score IS NOT NULL
                AND player_1_score >= 0 AND player_2_score >= 0
            """)
        
        completed_matches = db.session.execute(completed_matches_query, {'t_id': t_id}).fetchone()[0]
        
        format_name = "苏超赛制" if t_format == 6 else "单循环"
        print(f"小组赛完成检查 - 赛事{t_id} ({format_name}): 参赛选手{player_count}人, 应比赛{expected_matches}场, 已完成{completed_matches}场")
        
        return completed_matches >= expected_matches
        
    except Exception as e:
        print(f"检查小组赛完成状态失败: {e}")
        return False


def calculate_correct_final_rankings(t_id):
    """计算正确的最终排名（排除重复选手）"""
    try:
        from sqlalchemy import text
        
        # 获取循环赛阶段的排名
        round_robin_standings = calculate_round_robin_standings(t_id)
        
        if len(round_robin_standings) < 6:
            return round_robin_standings
        
        # 获取各种淘汰赛的比赛
        knockout_query = text("""
            SELECT m_type, player_1_id, player_1_score, player_2_id, player_2_score
            FROM matches
            WHERE t_id = :t_id AND m_type IN (9, 10, 11, 12)
            ORDER BY m_type
        """)
        knockout_matches = db.session.execute(knockout_query, {'t_id': t_id}).fetchall()
        
        # 获取选手信息
        players_query = text("""
            SELECT player_id, name FROM players WHERE player_id IN (
                SELECT DISTINCT player_id FROM rankings WHERE t_id = :t_id
            )
        """)
        players_result = db.session.execute(players_query, {'t_id': t_id}).fetchall()
        players_dict = {p[0]: p[1] for p in players_result}
        
        # 分析淘汰赛结果
        gold_match = None
        bronze_match = None
        
        for match in knockout_matches:
            m_type, player_1_id, player_1_score, player_2_id, player_2_score = match
            match_info = {
                'player_1_id': player_1_id,
                'player_1_name': players_dict.get(player_1_id, ''),
                'player_1_score': player_1_score,
                'player_2_id': player_2_id,
                'player_2_name': players_dict.get(player_2_id, ''),
                'player_2_score': player_2_score,
                'winner_id': player_1_id if player_1_score > player_2_score else player_2_id if player_2_score > player_1_score else None
            }
            
            if m_type == 12:  # 金牌赛
                gold_match = match_info
            elif m_type == 11:  # 铜牌赛
                bronze_match = match_info
        
        # 计算最终排名
        final_rankings = []
        
        # 如果所有淘汰赛都已完成，计算最终排名
        if gold_match and bronze_match and gold_match['winner_id'] and bronze_match['winner_id']:
            # 金牌赛胜者第1名
            gold_winner = next((p for p in round_robin_standings if p['player_id'] == gold_match['winner_id']), None)
            if gold_winner:
                final_rankings.append({**gold_winner, 'final_rank': 1})
            
            # 金牌赛负者第2名
            gold_loser_id = gold_match['player_2_id'] if gold_match['winner_id'] == gold_match['player_1_id'] else gold_match['player_1_id']
            gold_loser = next((p for p in round_robin_standings if p['player_id'] == gold_loser_id), None)
            if gold_loser:
                final_rankings.append({**gold_loser, 'final_rank': 2})
            
            # 铜牌赛胜者第3名
            bronze_winner = next((p for p in round_robin_standings if p['player_id'] == bronze_match['winner_id']), None)
            if bronze_winner:
                final_rankings.append({**bronze_winner, 'final_rank': 3})
            
            # 铜牌赛负者第4名
            bronze_loser_id = bronze_match['player_2_id'] if bronze_match['winner_id'] == bronze_match['player_1_id'] else bronze_match['player_1_id']
            bronze_loser = next((p for p in round_robin_standings if p['player_id'] == bronze_loser_id), None)
            if bronze_loser:
                final_rankings.append({**bronze_loser, 'final_rank': 4})
            
            # 其余选手按循环赛排名（排除已进入决赛的选手）
            final_player_ids = {gold_match['winner_id'], gold_match['player_1_id'], gold_match['player_2_id'],
                               bronze_match['winner_id'], bronze_match['player_1_id'], bronze_match['player_2_id']}
            
            remaining_rank = 5
            for player in round_robin_standings:
                if player['player_id'] not in final_player_ids:
                    final_rankings.append({**player, 'final_rank': remaining_rank})
                    remaining_rank += 1
        else:
            # 淘汰赛未完成，返回循环赛排名
            final_rankings = round_robin_standings
        
        return final_rankings
        
    except Exception as e:
        print(f"计算最终排名失败: {e}")
        return []


def update_final_rankings_and_scores(t_id):
    """根据特殊淘汰赛结果更新最终排名和积分"""
    try:
        from sqlalchemy import text
        
        # 获取赛事信息
        tournament = db.session.get(Tournament, t_id)
        if not tournament:
            print(f"赛事 {t_id} 不存在")
            return False
        
        # 获取正确的最终排名
        final_rankings = calculate_correct_final_rankings(t_id)
        
        if not final_rankings:
            print(f"无法获取最终排名")
            return False
        
        # 检查是否所有淘汰赛都已完成（通过检查最终排名是否包含决赛选手）
        if len(final_rankings) < 4 or final_rankings[0].get('final_rank', 0) != 1:
            print(f"淘汰赛未完成，不更新最终排名")
            return False
        
        print(f"开始更新最终排名和积分...")
        
        # 删除现有的排名数据
        delete_query = text("DELETE FROM rankings WHERE t_id = :t_id")
        db.session.execute(delete_query, {'t_id': t_id})
        
        # 根据赛事类型计算积分
        tournament_type = tournament.type
        player_count = len(final_rankings)
        
        if tournament_type == 1:  # 大赛
            first_score = player_count * 30
            last_score = 10
        elif tournament_type == 2:  # 小赛
            first_score = player_count * 20
            last_score = 10
        elif tournament_type == 3:  # 总决赛
            first_score = player_count
            last_score = 1
        else:
            print(f"未知的赛事类型: {tournament_type}")
            return False
        
        # 计算积分
        if player_count == 1:
            scores = [first_score]
        elif player_count == 2:
            scores = [first_score, last_score]
        else:
            if tournament_type == 3:  # 总决赛使用等差数列
                d = (last_score - first_score) / (player_count - 1)
                scores = [first_score + d * (i - 1) for i in range(1, player_count + 1)]
            else:  # 大赛和小赛使用等比数列
                r = (last_score / first_score) ** (1 / (player_count - 1))
                scores = [first_score * (r ** (i - 1)) for i in range(1, player_count + 1)]
        
        # 获取所有参赛选手的状态信息
        players_status_query = text("""
            SELECT DISTINCT p.player_id, p.status
            FROM players p
            JOIN rankings r ON p.player_id = r.player_id
            WHERE r.t_id = :t_id
        """)
        players_status_result = db.session.execute(players_status_query, {'t_id': t_id}).fetchall()
        players_status_dict = {p[0]: p[1] for p in players_status_result}
        
        # 插入新的排名数据
        for i, player_data in enumerate(final_rankings):
            player_id = player_data['player_id']
            rank = i + 1
            player_status = players_status_dict.get(player_id, 1)
            
            # 只对"参与排名"的选手计算积分
            if player_status == 1 or player_status == 2:  # 参与排名
                score = int(round(scores[i]))
            else:  # 不可用或其他状态
                score = None
            
            ranking = Ranking(
                t_id=t_id,
                player_id=player_id,
                ranks=rank,
                scores=score
            )
            db.session.add(ranking)
            
            status_text = '参与排名' if player_status == 1 else '不可用' if player_status == 3 else '其他'
            score_text = f'{score}分' if score is not None else '不计分'
            print(f"  排名 {rank}: 选手 {player_id}({status_text}) -> {score_text}")
        
        db.session.commit()
        print(f"最终排名和积分更新完成")
        return True
        
    except Exception as e:
        print(f"更新最终排名和积分失败: {e}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        return False


def update_final_matchups(t_id):
    """更新铜牌赛和金牌赛对阵（根据半决赛结果）"""
    try:
        from sqlalchemy import text
        
        # 获取半决赛结果
        semifinal_query = text("""
            SELECT m_id, player_1_id, player_1_score, player_2_id, player_2_score
            FROM matches
            WHERE t_id = :t_id AND m_type = 10
            ORDER BY m_id
        """)
        semifinal_matches = db.session.execute(semifinal_query, {'t_id': t_id}).fetchall()
        
        if len(semifinal_matches) != 2:
            print(f"半决赛数量不正确: {len(semifinal_matches)}")
            return False
        
        # 计算半决赛的胜者和负者
        semifinal_winners = []
        semifinal_losers = []
        
        for match in semifinal_matches:
            m_id, p1_id, p1_score, p2_id, p2_score = match
            if p1_score > p2_score:
                semifinal_winners.append(p1_id)
                semifinal_losers.append(p2_id)
            elif p2_score > p1_score:
                semifinal_winners.append(p2_id)
                semifinal_losers.append(p1_id)
            else:
                print(f"半决赛{m_id}未分出胜负: {p1_score}-{p2_score}")
                return False
        
        if len(semifinal_winners) != 2 or len(semifinal_losers) != 2:
            print(f"半决赛结果不完整")
            return False
        
        # 获取铜牌赛和金牌赛
        final_query = text("""
            SELECT m_id, m_type FROM matches
            WHERE t_id = :t_id AND m_type IN (11, 12)
            ORDER BY m_type, m_id
        """)
        final_matches = db.session.execute(final_query, {'t_id': t_id}).fetchall()
        
        if len(final_matches) != 2:
            print(f"决赛数量不正确: {len(final_matches)}")
            return False
        
        # 更新金牌赛：半决赛胜者对决
        gold_match_id = None
        bronze_match_id = None
        
        for m_id, m_type in final_matches:
            if m_type == 12:  # 金牌赛
                gold_match_id = m_id
            elif m_type == 11:  # 铜牌赛
                bronze_match_id = m_id
        
        if gold_match_id and bronze_match_id:
            # 更新金牌赛：半决赛胜者对决
            gold_update_query = text("""
                UPDATE matches 
                SET player_1_id = :p1_id, player_2_id = :p2_id
                WHERE m_id = :m_id
            """)
            db.session.execute(gold_update_query, {
                'p1_id': semifinal_winners[0],
                'p2_id': semifinal_winners[1],
                'm_id': gold_match_id
            })
            
            # 更新铜牌赛：半决赛负者对决
            bronze_update_query = text("""
                UPDATE matches 
                SET player_1_id = :p1_id, player_2_id = :p2_id
                WHERE m_id = :m_id
            """)
            db.session.execute(bronze_update_query, {
                'p1_id': semifinal_losers[0],
                'p2_id': semifinal_losers[1],
                'm_id': bronze_match_id
            })
            
            db.session.commit()
            print(f"铜牌赛和金牌赛对阵已更新")
            return True
        else:
            print(f"未找到金牌赛或铜牌赛")
            return False
        
    except Exception as e:
        print(f"更新决赛对阵失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def update_semifinal_matchups(t_id):
    """更新半决赛对阵（根据半决赛资格赛结果）"""
    try:
        from sqlalchemy import text
        
        # 获取半决赛资格赛结果
        qualification_query = text("""
            SELECT m_id, player_1_id, player_1_score, player_2_id, player_2_score
            FROM matches
            WHERE t_id = :t_id AND m_type = 9
            ORDER BY m_id
        """)
        qualification_matches = db.session.execute(qualification_query, {'t_id': t_id}).fetchall()
        
        if len(qualification_matches) != 2:
            print(f"半决赛资格赛数量不正确: {len(qualification_matches)}")
            return False
        
        # 获取半决赛对阵
        semifinal_query = text("""
            SELECT m_id, player_1_id, player_2_id
            FROM matches
            WHERE t_id = :t_id AND m_type = 10
            ORDER BY m_id
        """)
        semifinal_matches = db.session.execute(semifinal_query, {'t_id': t_id}).fetchall()
        
        if len(semifinal_matches) != 2:
            print(f"半决赛数量不正确: {len(semifinal_matches)}")
            return False
        
        # 计算半决赛资格赛的胜者（只处理已完成的比赛）
        winners = []
        for match in qualification_matches:
            m_id, p1_id, p1_score, p2_id, p2_score = match
            # 跳过未完成的比赛（比分为0:0）
            if p1_score == 0 and p2_score == 0:
                continue
            if p1_score > p2_score:
                winners.append(p1_id)
            elif p2_score > p1_score:
                winners.append(p2_id)
            else:
                print(f"半决赛资格赛{m_id}未分出胜负: {p1_score}-{p2_score}")
                return False
        
        if len(winners) < 2:
            print(f"半决赛资格赛完成数量不足: {len(winners)}/2")
            return False
        
        # 获取小组排名来确定半决赛对阵
        group_standings_dict = calculate_total_group_rankings(t_id)
        
        # 将字典转换为列表
        group_standings = []
        for tg_id, standings in group_standings_dict.items():
            group_standings.extend(standings)
        
        group_a = [p for p in group_standings if p.get('group_name') == 'A']
        group_b = [p for p in group_standings if p.get('group_name') == 'B']
        
        if len(group_a) < 1 or len(group_b) < 1:
            print(f"小组排名数据不完整")
            return False
        
        # 更新半决赛对阵
        semifinal_updates = [
            (semifinal_matches[0][0], group_a[0]['player_id'], winners[0]),  # A组第1 vs 资格赛1胜者
            (semifinal_matches[1][0], group_b[0]['player_id'], winners[1]),  # B组第1 vs 资格赛2胜者
        ]
        
        for m_id, p1_id, p2_id in semifinal_updates:
            update_query = text("""
                UPDATE matches 
                SET player_1_id = :p1_id, player_2_id = :p2_id
                WHERE m_id = :m_id
            """)
            db.session.execute(update_query, {
                'p1_id': p1_id,
                'p2_id': p2_id,
                'm_id': m_id
            })
        
        db.session.commit()
        print(f"半决赛对阵已更新")
        return True
        
    except Exception as e:
        print(f"更新半决赛对阵失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def auto_generate_special_knockout_matches(t_id):
    """自动生成特殊淘汰赛对阵（半决赛资格赛、半决赛、金牌赛、铜牌赛）"""
    try:
        from sqlalchemy import text
        
        # 检查循环赛是否完成
        if not check_round_robin_complete(t_id):
            print(f"循环赛未完成，无法生成特殊淘汰赛对阵")
            return False
        
        # 获取循环赛排名
        round_robin_standings = calculate_round_robin_standings(t_id)
        
        if len(round_robin_standings) < 6:
            print(f"参赛选手不足6人，无法生成特殊淘汰赛对阵")
            return False
        
        # 获取排名前6的选手
        top6_players = round_robin_standings[:6]
        
        # 检查是否已经存在淘汰赛
        existing_knockout_query = text("""
            SELECT m_id, m_type FROM matches 
            WHERE t_id = :t_id AND m_type IN (9, 10, 11, 12)
            ORDER BY m_type, m_id
        """)
        existing_matches = db.session.execute(existing_knockout_query, {'t_id': t_id}).fetchall()
        
        if len(existing_matches) >= 6:
            print(f"发现已存在的特殊淘汰赛对阵，将更新选手ID")
            
            # 更新现有比赛的选手ID
            match_updates = [
                # 半决赛资格赛
                (existing_matches[0][0], 9, top6_players[3]['player_id'], top6_players[4]['player_id']),  # 第4名 vs 第5名
                (existing_matches[1][0], 9, top6_players[2]['player_id'], top6_players[5]['player_id']),  # 第3名 vs 第6名
                # 半决赛
                (existing_matches[2][0], 10, top6_players[0]['player_id'], top6_players[3]['player_id']), # 第1名 vs 第4名
                (existing_matches[3][0], 10, top6_players[1]['player_id'], top6_players[2]['player_id']), # 第2名 vs 第3名
                # 金牌赛和铜牌赛
                (existing_matches[4][0], 12, top6_players[0]['player_id'], top6_players[1]['player_id']), # 金牌赛
                (existing_matches[5][0], 11, top6_players[2]['player_id'], top6_players[3]['player_id']), # 铜牌赛
            ]
            
            for m_id, m_type, p1_id, p2_id in match_updates:
                update_query = text("""
                    UPDATE matches 
                    SET player_1_id = :p1_id, player_2_id = :p2_id
                    WHERE m_id = :m_id
                """)
                db.session.execute(update_query, {
                    'p1_id': p1_id,
                    'p2_id': p2_id,
                    'm_id': m_id
                })
            
            db.session.commit()
            
            print(f"成功更新特殊淘汰赛对阵:")
            print(f"  半决赛资格赛1: {top6_players[3]['name']} vs {top6_players[4]['name']}")
            print(f"  半决赛资格赛2: {top6_players[2]['name']} vs {top6_players[5]['name']}")
            print(f"  半决赛1: {top6_players[0]['name']} vs {top6_players[3]['name']}")
            print(f"  半决赛2: {top6_players[1]['name']} vs {top6_players[2]['name']}")
            print(f"  金牌赛: {top6_players[0]['name']} vs {top6_players[1]['name']}")
            print(f"  铜牌赛: {top6_players[2]['name']} vs {top6_players[3]['name']}")
            
        else:
            print(f"未找到足够的特殊淘汰赛对阵，需要创建新比赛")
            # 如果比赛数量不够，才创建新比赛
            return False
        
        return True
        
    except Exception as e:
        print(f"自动生成特殊淘汰赛对阵失败: {e}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        return False


def auto_generate_next_round_matches(t_id):
    """
    通用的自动生成下一轮比赛对阵模块
    根据赛事类型和当前状态自动生成相应的下一轮比赛
    """
    try:
        from sqlalchemy import text
        
        # 获取赛事信息
        tournament_query = text("""
            SELECT t.type, t.t_format, tsv.type_session_number
            FROM tournament t
            JOIN tournament_session_view tsv ON t.t_id = tsv.t_id
            WHERE t.t_id = :t_id
        """)
        tournament_result = db.session.execute(tournament_query, {'t_id': t_id}).fetchone()
        
        if not tournament_result:
            print(f"无法获取赛事信息")
            return False
            
        tournament_type, t_format, session_number = tournament_result
        
        # 根据赛事类型和格式选择相应的生成逻辑
        if tournament_type == 1:  # 大赛
            if t_format == 1:  # 小组赛+1/4决赛
                return auto_generate_quarterfinal_matches(t_id)
            elif t_format == 3:  # 小组赛+半决赛资格赛
                return auto_generate_semifinal_qualifier_matches(t_id)
            elif t_format in [4, 5, 6]:  # 单循环赛/双循环赛/苏超赛制
                return auto_generate_round_robin_knockout_matches(t_id)
        elif tournament_type == 2:  # 小赛
            if session_number >= 2:  # 从第2届起
                return auto_generate_minor_tournament_matches(t_id)
        
        print(f"不支持的赛事类型或格式: type={tournament_type}, format={t_format}")
        return False
        
    except Exception as e:
        print(f"自动生成下一轮比赛失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def auto_generate_quarterfinal_matches(t_id):
    """小组赛+1/4决赛：1/4决赛结束，排半决赛的表；半决赛结束，排金牌赛、铜牌赛的表"""
    try:
        from sqlalchemy import text
        
        # 检查1/4决赛是否完成
        quarterfinal_query = text("""
            SELECT COUNT(*) FROM matches 
            WHERE t_id = :t_id AND m_type = 8 AND player_1_score IS NOT NULL AND player_2_score IS NOT NULL
            AND NOT (player_1_score = 0 AND player_2_score = 0)
            AND NOT (player_1_score = -1 AND player_2_score = -1)
        """)
        quarterfinal_count = db.session.execute(quarterfinal_query, {'t_id': t_id}).fetchone()[0]
        
        if quarterfinal_count < 4:  # 需要4场1/4决赛
            print(f"1/4决赛未完成，无法生成半决赛")
            return False
        
        # 检查半决赛是否已存在
        semifinal_query = text("""
            SELECT COUNT(*) FROM matches 
            WHERE t_id = :t_id AND m_type = 10
        """)
        semifinal_count = db.session.execute(semifinal_query, {'t_id': t_id}).fetchone()[0]
        
        if semifinal_count > 0:
            print(f"半决赛已存在，更新对阵")
            # 更新现有半决赛对阵
            return update_quarterfinal_semifinals(t_id)
        
        # 获取1/4决赛结果，确定半决赛对阵
        quarterfinal_results = text("""
            SELECT m_id, player_1_id, player_1_score, player_2_id, player_2_score
            FROM matches 
            WHERE t_id = :t_id AND m_type = 8 AND player_1_score IS NOT NULL AND player_2_score IS NOT NULL
            AND NOT (player_1_score = 0 AND player_2_score = 0)
            AND NOT (player_1_score = -1 AND player_2_score = -1)
            ORDER BY m_id
        """)
        results = db.session.execute(quarterfinal_results, {'t_id': t_id}).fetchall()
        
        if len(results) != 4:
            print(f"1/4决赛结果不完整")
            return False
        
        # 确定半决赛对阵
        semifinal_matches = []
        for i in range(0, 4, 2):
            match1 = results[i]
            match2 = results[i + 1]
            
            # 确定每场比赛的胜者
            winner1 = match1[1] if match1[2] > match1[4] else match1[3]
            winner2 = match2[1] if match2[2] > match2[4] else match2[3]
            
            # 创建半决赛对阵
            semifinal_match = Match(
                t_id=t_id,
                m_type=10,  # 半决赛
                player_1_id=winner1,
                player_2_id=winner2,
                player_1_score=0,
                player_2_score=0
            )
            semifinal_matches.append(semifinal_match)
        
        # 保存半决赛对阵
        for match in semifinal_matches:
            db.session.add(match)
        db.session.commit()
        
        print(f"成功生成半决赛对阵")
        return True
        
    except Exception as e:
        print(f"生成1/4决赛下一轮失败: {e}")
        db.session.rollback()
        return False


def update_quarterfinal_semifinals(t_id):
    """更新1/4决赛后的半决赛对阵"""
    try:
        from sqlalchemy import text
        
        # 获取1/4决赛结果
        quarterfinal_results = text("""
            SELECT m_id, player_1_id, player_1_score, player_2_id, player_2_score
            FROM matches 
            WHERE t_id = :t_id AND m_type = 8 AND player_1_score IS NOT NULL AND player_2_score IS NOT NULL
            AND NOT (player_1_score = 0 AND player_2_score = 0)
            AND NOT (player_1_score = -1 AND player_2_score = -1)
            ORDER BY m_id
        """)
        results = db.session.execute(quarterfinal_results, {'t_id': t_id}).fetchall()
        
        if len(results) != 4:
            print(f"1/4决赛结果不完整，无法更新半决赛")
            return False
        
        # 获取现有半决赛
        existing_semifinals = text("""
            SELECT m_id, player_1_id, player_2_id
            FROM matches 
            WHERE t_id = :t_id AND m_type = 10
            ORDER BY m_id
        """)
        semifinals = db.session.execute(existing_semifinals, {'t_id': t_id}).fetchall()
        
        if len(semifinals) != 2:
            print(f"半决赛数量不正确")
            return False
        
        # 确定新的半决赛对阵
        new_matchups = []
        for i in range(0, 4, 2):
            match1 = results[i]
            match2 = results[i + 1]
            
            # 确定每场比赛的胜者
            winner1 = match1[1] if match1[2] > match1[4] else match1[3]
            winner2 = match2[1] if match2[2] > match2[4] else match2[3]
            
            new_matchups.append((winner1, winner2))
        
        # 更新半决赛对阵
        for i, semifinal in enumerate(semifinals):
            semifinal_id = semifinal[0]
            new_player1, new_player2 = new_matchups[i]
            
            # 更新对阵
            update_query = text("""
                UPDATE matches 
                SET player_1_id = :player1, player_2_id = :player2, player_1_score = 0, player_2_score = 0
                WHERE m_id = :match_id
            """)
            db.session.execute(update_query, {
                'player1': new_player1,
                'player2': new_player2,
                'match_id': semifinal_id
            })
        
        db.session.commit()
        print(f"半决赛对阵已更新")
        
        # 不在这里生成金牌赛和铜牌赛，等半决赛完成后再生成
        return True
        
    except Exception as e:
        print(f"更新半决赛对阵时出错: {e}")
        import traceback
        traceback.print_exc()
        return False


def generate_final_matches_from_standings(t_id):
    """从排名生成金牌赛和铜牌赛（用于单循环/双循环/苏超赛制）"""
    try:
        from sqlalchemy import text
        
        # 检查是否已经存在金牌赛和铜牌赛
        existing_query = text("""
            SELECT COUNT(*) FROM matches 
            WHERE t_id = :t_id AND m_type IN (11, 12)
        """)
        existing_count = db.session.execute(existing_query, {'t_id': t_id}).fetchone()[0]
        
        if existing_count > 0:
            print(f"金牌赛和铜牌赛已存在")
            return True
        
        # 获取小组赛排名
        round_robin_standings = calculate_round_robin_standings(t_id)
        
        if len(round_robin_standings) < 4:
            print(f"参赛选手不足4人，无法生成金牌赛和铜牌赛")
            return False
        
        # 获取排名前4的选手
        top4_players = round_robin_standings[:4]
        
        # 生成金牌赛：第1名 vs 第2名
        gold_match = Match(
            t_id=t_id,
            m_type=12,  # 金牌赛
            player_1_id=top4_players[0]['player_id'],
            player_2_id=top4_players[1]['player_id'],
            player_1_score=0,
            player_2_score=0
        )
        
        # 生成铜牌赛：第3名 vs 第4名
        bronze_match = Match(
            t_id=t_id,
            m_type=11,  # 铜牌赛
            player_1_id=top4_players[2]['player_id'],
            player_2_id=top4_players[3]['player_id'],
            player_1_score=0,
            player_2_score=0
        )
        
        # 保存到数据库
        db.session.add(gold_match)
        db.session.add(bronze_match)
        db.session.commit()
        
        print(f"成功生成金牌赛和铜牌赛:")
        print(f"  金牌赛: {top4_players[0]['name']} vs {top4_players[1]['name']}")
        print(f"  铜牌赛: {top4_players[2]['name']} vs {top4_players[3]['name']}")
        
        return True
        
    except Exception as e:
        print(f"生成金牌赛和铜牌赛失败: {e}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        return False

def auto_generate_knockout_matches(t_id):
    """自动生成金牌赛和铜牌赛对阵（从第2届小赛开始）"""
    try:
        from sqlalchemy import text
        
        # 检查是否是第2届及以后的小赛
        tournament_query = text("""
            SELECT t.type, tsv.type_session_number
            FROM tournament t
            JOIN tournament_session_view tsv ON t.t_id = tsv.t_id
            WHERE t.t_id = :t_id
        """)
        tournament_result = db.session.execute(tournament_query, {'t_id': t_id}).fetchone()
        
        if not tournament_result:
            print(f"无法获取赛事信息")
            return False
            
        tournament_type, session_number = tournament_result
        
        # 所有支持小组赛的赛事都可以生成淘汰赛
        if tournament_type not in [1, 2, 3]:
            print(f"不支持的赛事类型，不自动生成淘汰赛")
            return False
        
        # 检查小组赛是否完成
        if not check_round_robin_complete(t_id):
            print(f"小组赛未完成，无法生成淘汰赛对阵")
            return False
        
        # 获取赛事格式，总决赛可能需要不同的淘汰赛生成逻辑
        tournament_format_query = text("SELECT t_format FROM tournament WHERE t_id = :t_id")
        tournament_format_result = db.session.execute(tournament_format_query, {'t_id': t_id}).fetchone()
        if not tournament_format_result:
            print(f"无法获取赛事格式")
            return False
        tournament_format = tournament_format_result[0]
        
        # 根据赛事格式生成相应的淘汰赛
        print(f"赛事格式: {tournament_format}")
        
        if tournament_format == 1:  # 小组赛+1/4决赛
            return auto_generate_quarterfinal_matches(t_id)
        elif tournament_format == 3:  # 小组赛+半决赛资格赛
            return auto_generate_semifinal_qualifier_matches(t_id)
        elif tournament_format in [4, 5, 6]:  # 单循环/双循环/苏超赛制
            # 这些赛制直接生成金牌赛和铜牌赛
            return generate_final_matches_from_standings(t_id)
        else:
            print(f"不支持的赛事格式: {tournament_format}")
            return False
        
    except Exception as e:
        print(f"自动生成淘汰赛对阵失败: {e}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        return False

# 半决赛资格赛、半决赛、金牌赛、铜牌赛
def calculate_special_knockout_stages(t_id):
    """计算特殊淘汰赛阶段（半决赛资格赛、半决赛、金牌赛、铜牌赛）"""
    try:
        from sqlalchemy import text
        
        # 获取循环赛阶段的排名
        round_robin_standings = calculate_round_robin_standings(t_id)
        
        if len(round_robin_standings) < 6:
            return {
                'round_robin': round_robin_standings,
                'qualification_matches': None,
                'semifinal_matches': None,
                'gold_match': None,
                'bronze_match': None,
                'final_rankings': round_robin_standings
            }
        
        # 获取各种淘汰赛的比赛
        knockout_query = text("""
            SELECT m_type, player_1_id, player_1_score, player_2_id, player_2_score
            FROM matches
            WHERE t_id = :t_id AND m_type IN (9, 10, 11, 12)  -- 9=半决赛资格赛, 10=半决赛, 11=铜牌赛, 12=金牌赛
            ORDER BY m_type
        """)
        knockout_matches = db.session.execute(knockout_query, {'t_id': t_id}).fetchall()
        
        # 获取选手信息
        players_query = text("""
            SELECT player_id, name FROM players WHERE player_id IN (
                SELECT DISTINCT player_id FROM rankings WHERE t_id = :t_id
            )
        """)
        players_result = db.session.execute(players_query, {'t_id': t_id}).fetchall()
        players_dict = {p[0]: p[1] for p in players_result}
        
        # 分析淘汰赛结果
        qualification_matches = []
        semifinal_matches = []
        gold_match = None
        bronze_match = None
        
        for match in knockout_matches:
            m_type, player_1_id, player_1_score, player_2_id, player_2_score = match
            match_info = {
                'player_1_id': player_1_id,
                'player_1_name': players_dict.get(player_1_id, ''),
                'player_1_score': player_1_score,
                'player_2_id': player_2_id,
                'player_2_name': players_dict.get(player_2_id, ''),
                'player_2_score': player_2_score,
                'winner_id': player_1_id if player_1_score > player_2_score else player_2_id if player_2_score > player_1_score else None
            }
            
            if m_type == 9:  # 半决赛资格赛
                qualification_matches.append(match_info)
            elif m_type == 10:  # 半决赛
                semifinal_matches.append(match_info)
            elif m_type == 12:  # 金牌赛
                gold_match = match_info
            elif m_type == 11:  # 铜牌赛
                bronze_match = match_info
        
        # 计算最终排名
        final_rankings = []
        
        # 如果所有淘汰赛都已完成，计算最终排名
        if gold_match and bronze_match and gold_match['winner_id'] and bronze_match['winner_id']:
            # 金牌赛胜者第1名
            gold_winner = next((p for p in round_robin_standings if p['player_id'] == gold_match['winner_id']), None)
            if gold_winner:
                final_rankings.append({**gold_winner, 'final_rank': 1})
            
            # 金牌赛负者第2名
            gold_loser_id = gold_match['player_2_id'] if gold_match['winner_id'] == gold_match['player_1_id'] else gold_match['player_1_id']
            gold_loser = next((p for p in round_robin_standings if p['player_id'] == gold_loser_id), None)
            if gold_loser:
                final_rankings.append({**gold_loser, 'final_rank': 2})
            
            # 铜牌赛胜者第3名
            bronze_winner = next((p for p in round_robin_standings if p['player_id'] == bronze_match['winner_id']), None)
            if bronze_winner:
                final_rankings.append({**bronze_winner, 'final_rank': 3})
            
            # 铜牌赛负者第4名
            bronze_loser_id = bronze_match['player_2_id'] if bronze_match['winner_id'] == bronze_match['player_1_id'] else bronze_match['player_1_id']
            bronze_loser = next((p for p in round_robin_standings if p['player_id'] == bronze_loser_id), None)
            if bronze_loser:
                final_rankings.append({**bronze_loser, 'final_rank': 4})
            
            # 其余选手按循环赛排名
            for player in round_robin_standings[4:]:
                final_rankings.append({**player, 'final_rank': player['rank']})
        else:
            # 淘汰赛未完成，返回循环赛排名
            final_rankings = round_robin_standings
        
        return {
            'round_robin': round_robin_standings,
            'qualification_matches': qualification_matches,
            'semifinal_matches': semifinal_matches,
            'gold_match': gold_match,
            'bronze_match': bronze_match,
            'final_rankings': final_rankings
        }
        
    except Exception as e:
        print(f"计算特殊淘汰赛失败: {e}")
        return {
            'round_robin': [],
            'qualification_matches': None,
            'semifinal_matches': None,
            'gold_match': None,
            'bronze_match': None,
            'final_rankings': []
        }

# 小赛淘汰赛
def calculate_minor_tournament_knockout(t_id):
    """计算小赛循环赛的淘汰赛阶段（金牌赛和铜牌赛）"""
    try:
        from sqlalchemy import text
        
        # 获取循环赛阶段的排名
        round_robin_standings = calculate_round_robin_standings(t_id)
        
        if len(round_robin_standings) < 4:
            return {
                'round_robin': round_robin_standings,
                'gold_match': None,
                'bronze_match': None,
                'final_rankings': round_robin_standings
            }
        
        # 获取金牌赛和铜牌赛的比赛
        knockout_query = text("""
            SELECT m_id, m_type, player_1_id, player_1_score, player_2_id, player_2_score
            FROM matches
            WHERE t_id = :t_id AND m_type IN (11, 12)  -- 11=铜牌赛, 12=金牌赛
            ORDER BY m_type
        """)
        knockout_matches = db.session.execute(knockout_query, {'t_id': t_id}).fetchall()
        
        # 获取选手信息
        players_query = text("""
            SELECT player_id, name FROM players WHERE player_id IN (
                SELECT DISTINCT player_id FROM rankings WHERE t_id = :t_id
            )
        """)
        players_result = db.session.execute(players_query, {'t_id': t_id}).fetchall()
        players_dict = {p[0]: p[1] for p in players_result}
        
        # 分析淘汰赛结果
        gold_match = None
        bronze_match = None
        
        for match in knockout_matches:
            m_id, m_type, player_1_id, player_1_score, player_2_id, player_2_score = match
            if m_type == 12:  # 金牌赛
                gold_match = {
                    'm_id': m_id,
                    'player_1_id': player_1_id,
                    'player_1_name': players_dict.get(player_1_id, ''),
                    'player_1_score': player_1_score,
                    'player_2_id': player_2_id,
                    'player_2_name': players_dict.get(player_2_id, ''),
                    'player_2_score': player_2_score,
                    'winner_id': player_1_id if player_1_score > player_2_score else player_2_id if player_2_score > player_1_score else None
                }
            elif m_type == 11:  # 铜牌赛
                bronze_match = {
                    'm_id': m_id,
                    'player_1_id': player_1_id,
                    'player_1_name': players_dict.get(player_1_id, ''),
                    'player_1_score': player_1_score,
                    'player_2_id': player_2_id,
                    'player_2_name': players_dict.get(player_2_id, ''),
                    'player_2_score': player_2_score,
                    'winner_id': player_1_id if player_1_score > player_2_score else player_2_id if player_2_score > player_1_score else None
                }
        
        # 计算最终排名
        final_rankings = []
        
        # 如果金牌赛和铜牌赛都已完成，计算最终排名
        if gold_match and bronze_match and gold_match['winner_id'] and bronze_match['winner_id']:
            # 金牌赛胜者第1名
            gold_winner = next((p for p in round_robin_standings if p['player_id'] == gold_match['winner_id']), None)
            if gold_winner:
                final_rankings.append({**gold_winner, 'final_rank': 1})
            
            # 金牌赛负者第2名
            gold_loser_id = gold_match['player_2_id'] if gold_match['winner_id'] == gold_match['player_1_id'] else gold_match['player_1_id']
            gold_loser = next((p for p in round_robin_standings if p['player_id'] == gold_loser_id), None)
            if gold_loser:
                final_rankings.append({**gold_loser, 'final_rank': 2})
            
            # 铜牌赛胜者第3名
            bronze_winner = next((p for p in round_robin_standings if p['player_id'] == bronze_match['winner_id']), None)
            if bronze_winner:
                final_rankings.append({**bronze_winner, 'final_rank': 3})
            
            # 铜牌赛负者第4名
            bronze_loser_id = bronze_match['player_2_id'] if bronze_match['winner_id'] == bronze_match['player_1_id'] else bronze_match['player_1_id']
            bronze_loser = next((p for p in round_robin_standings if p['player_id'] == bronze_loser_id), None)
            if bronze_loser:
                final_rankings.append({**bronze_loser, 'final_rank': 4})
            
            # 其余选手按循环赛排名
            for player in round_robin_standings[4:]:
                final_rankings.append({**player, 'final_rank': player['rank']})
            
            # 计算最终排名的积分
            final_rankings = calculate_final_ranking_scores(final_rankings, t_id)
            
            # 更新rankings表
            update_rankings_table_with_final_scores(t_id, final_rankings)
        else:
            # 淘汰赛未完成，返回循环赛排名
            final_rankings = round_robin_standings
        
        return {
            'round_robin': round_robin_standings,
            'gold_match': gold_match,
            'bronze_match': bronze_match,
            'final_rankings': final_rankings
        }
        
    except Exception as e:
        print(f"计算小赛淘汰赛失败: {e}")
        return {
            'round_robin': [],
            'gold_match': None,
            'bronze_match': None,
            'final_rankings': []
        }


def calculate_final_ranking_scores(final_rankings, t_id):
    """计算最终排名的积分"""
    try:
        # 获取赛事信息
        tournament = db.session.get(Tournament, t_id)
        if not tournament:
            print(f"赛事 {t_id} 不存在")
            return final_rankings
        
        player_count = len(final_rankings)
        tournament_type = tournament.type
        
        print(f"计算最终排名积分: type={tournament_type}, player_count={player_count}")
        
        # 根据赛事类型计算积分
        if tournament_type == 1:  # 大赛
            # 第1名: player_count*30, 最后一名: 10
            first_score = player_count * 30
            last_score = 10
            
            if player_count == 1:
                scores = [first_score]
            elif player_count == 2:
                scores = [first_score, last_score]
            else:
                # 等比数列计算
                r = (last_score / first_score) ** (1 / (player_count - 1))
                scores = [first_score * (r ** (i - 1)) for i in range(1, player_count + 1)]
                
        elif tournament_type == 2:  # 小赛
            # 第1名: player_count*20, 最后一名: 10
            first_score = player_count * 20
            last_score = 10
            
            if player_count == 1:
                scores = [first_score]
            elif player_count == 2:
                scores = [first_score, last_score]
            else:
                # 等比数列计算
                r = (last_score / first_score) ** (1 / (player_count - 1))
                scores = [first_score * (r ** (i - 1)) for i in range(1, player_count + 1)]
                
        elif tournament_type == 3:  # 总决赛
            # 第1名: player_count, 最后一名: 1, 等差数列
            first_score = player_count
            last_score = 1
            
            if player_count == 1:
                scores = [first_score]
            elif player_count == 2:
                scores = [first_score, last_score]
            else:
                # 等差数列计算
                d = (last_score - first_score) / (player_count - 1)
                scores = [first_score + d * (i - 1) for i in range(1, player_count + 1)]
        else:
            print(f"未知的赛事类型: {tournament_type}")
            return final_rankings
        
        # 为每个选手分配积分
        for i, player in enumerate(final_rankings):
            player['final_points'] = int(round(scores[i]))
            print(f"  最终排名 {player.get('final_rank', i+1)}: 选手 {player['player_id']} -> 积分 {player['final_points']}")
        
        return final_rankings
        
    except Exception as e:
        print(f"计算最终排名积分失败: {e}")
        return final_rankings


def update_rankings_table_with_final_scores(t_id, final_rankings):
    """将最终排名的积分更新到rankings表"""
    try:
        from sqlalchemy import text
        
        # 删除现有的排名数据
        delete_query = text("DELETE FROM rankings WHERE t_id = :t_id")
        db.session.execute(delete_query, {'t_id': t_id})
        
        # 插入新的排名数据
        for i, player_data in enumerate(final_rankings):
            final_rank = player_data.get('final_rank', i + 1)
            final_points = player_data.get('final_points', 0)
            
            insert_query = text("""
                INSERT INTO rankings (t_id, player_id, ranks, scores)
                VALUES (:t_id, :player_id, :ranks, :scores)
            """)
            
            db.session.execute(insert_query, {
                't_id': t_id,
                'player_id': player_data['player_id'],
                'ranks': final_rank,
                'scores': final_points
            })
            
            print(f"更新排名: 选手 {player_data['player_id']} -> 排名 {final_rank}, 积分 {final_points}")
        
        db.session.commit()
        print(f"成功更新rankings表，共 {len(final_rankings)} 条记录")
        return True
        
    except Exception as e:
        print(f"更新rankings表失败: {e}")
        db.session.rollback()
        return False


def calculate_medal_standings():
    """计算奖牌榜"""
    try:
        from sqlalchemy import text
        
        # 获取所有参与排名的选手（status=1）
        players = Player.query.filter_by(status=1).all()
        
        # 为每个选手计算奖牌数
        medal_stats = {}
        
        for player in players:
            # 统计大赛奖牌
            major_medal_query = text("""
                SELECT 
                    SUM(CASE WHEN r.ranks = 1 THEN 1 ELSE 0 END) as gold,
                    SUM(CASE WHEN r.ranks = 2 THEN 1 ELSE 0 END) as silver,
                    SUM(CASE WHEN r.ranks = 3 THEN 1 ELSE 0 END) as bronze
                FROM rankings r
                JOIN tournament t ON r.t_id = t.t_id
                WHERE r.player_id = :player_id 
                AND t.type = 1 AND t.status = 1
                AND r.ranks IN (1, 2, 3)
            """)
            
            # 统计小赛奖牌
            minor_medal_query = text("""
                SELECT 
                    SUM(CASE WHEN r.ranks = 1 THEN 1 ELSE 0 END) as gold,
                    SUM(CASE WHEN r.ranks = 2 THEN 1 ELSE 0 END) as silver,
                    SUM(CASE WHEN r.ranks = 3 THEN 1 ELSE 0 END) as bronze
                FROM rankings r
                JOIN tournament t ON r.t_id = t.t_id
                WHERE r.player_id = :player_id 
                AND t.type = 2 AND t.status = 1
                AND r.ranks IN (1, 2, 3)
            """)
            
            # 统计总决赛奖牌
            final_medal_query = text("""
                SELECT 
                    SUM(CASE WHEN r.ranks = 1 THEN 1 ELSE 0 END) as gold,
                    SUM(CASE WHEN r.ranks = 2 THEN 1 ELSE 0 END) as silver,
                    SUM(CASE WHEN r.ranks = 3 THEN 1 ELSE 0 END) as bronze
                FROM rankings r
                JOIN tournament t ON r.t_id = t.t_id
                WHERE r.player_id = :player_id 
                AND t.type = 3 AND t.status = 1
                AND r.ranks IN (1, 2, 3)
            """)
            
            major_result = db.session.execute(major_medal_query, {'player_id': player.player_id}).fetchone()
            minor_result = db.session.execute(minor_medal_query, {'player_id': player.player_id}).fetchone()
            final_result = db.session.execute(final_medal_query, {'player_id': player.player_id}).fetchone()
            
            medal_stats[player.player_id] = {
                'player_id': player.player_id,
                'name': player.name,
                'major': {
                    'gold': major_result[0] or 0,
                    'silver': major_result[1] or 0,
                    'bronze': major_result[2] or 0
                },
                'minor': {
                    'gold': minor_result[0] or 0,
                    'silver': minor_result[1] or 0,
                    'bronze': minor_result[2] or 0
                },
                'final': {
                    'gold': final_result[0] or 0,
                    'silver': final_result[1] or 0,
                    'bronze': final_result[2] or 0
                }
            }
        
        return medal_stats
        
    except Exception as e:
        print(f"计算奖牌榜失败: {e}")
        return {}


def get_medal_standings_by_type(tournament_type):
    """按比赛类型获取奖牌榜排名"""
    try:
        from sqlalchemy import text
        
        medal_query = text("""
            SELECT 
                p.player_id,
                p.name,
                SUM(CASE WHEN r.ranks = 1 THEN 1 ELSE 0 END) as gold,
                SUM(CASE WHEN r.ranks = 2 THEN 1 ELSE 0 END) as silver,
                SUM(CASE WHEN r.ranks = 3 THEN 1 ELSE 0 END) as bronze
            FROM players p
            LEFT JOIN rankings r ON p.player_id = r.player_id
            LEFT JOIN tournament t ON r.t_id = t.t_id
            WHERE p.status = 1 
            AND t.type = :tournament_type 
            AND t.status = 1
            AND r.ranks IN (1, 2, 3)
            GROUP BY p.player_id, p.name
            HAVING (gold + silver + bronze) > 0
            ORDER BY gold DESC, silver DESC, bronze DESC, p.name ASC
        """)
        
        result = db.session.execute(medal_query, {'tournament_type': tournament_type})
        standings = []
        
        for row in result.fetchall():
            standings.append({
                'player_id': row[0],
                'name': row[1],
                'gold': row[2] or 0,
                'silver': row[3] or 0,
                'bronze': row[4] or 0,
                'total': (row[2] or 0) + (row[3] or 0) + (row[4] or 0)
            })
        
        return standings
        
    except Exception as e:
        print(f"获取奖牌榜失败: {e}")
        return []


def get_season_medal_standings_by_type(season_id, tournament_type):
    """按赛季和比赛类型获取奖牌榜排名"""
    try:
        from sqlalchemy import text
        
        medal_query = text("""
            SELECT 
                p.player_id,
                p.name,
                SUM(CASE WHEN r.ranks = 1 THEN 1 ELSE 0 END) as gold,
                SUM(CASE WHEN r.ranks = 2 THEN 1 ELSE 0 END) as silver,
                SUM(CASE WHEN r.ranks = 3 THEN 1 ELSE 0 END) as bronze
            FROM players p
            LEFT JOIN rankings r ON p.player_id = r.player_id
            LEFT JOIN tournament t ON r.t_id = t.t_id
            WHERE p.status = 1 
            AND t.season_id = :season_id
            AND t.type = :tournament_type 
            AND t.status = 1
            AND r.ranks IN (1, 2, 3)
            GROUP BY p.player_id, p.name
            HAVING (gold + silver + bronze) > 0
            ORDER BY gold DESC, silver DESC, bronze DESC, p.name ASC
        """)
        
        result = db.session.execute(medal_query, {'season_id': season_id, 'tournament_type': tournament_type})
        standings = []
        
        for row in result.fetchall():
            standings.append({
                'player_id': row[0],
                'name': row[1],
                'gold': row[2] or 0,
                'silver': row[3] or 0,
                'bronze': row[4] or 0,
                'total': (row[2] or 0) + (row[3] or 0) + (row[4] or 0)
            })
        
        return standings
        
    except Exception as e:
        print(f"获取赛季奖牌榜失败: {e}")
        return []


def calculate_player_total_scores():
    """计算所有选手的总积分排名"""
    try:
        from sqlalchemy import text
        
        # 获取所有参与排名的选手（status=1）
        players = Player.query.filter_by(status=1).all()
        
        # 获取最新赛季ID
        latest_season_query = text("""
            SELECT MAX(season_id) as latest_season_id
            FROM tournament
            WHERE status = 1
        """)
        latest_season_result = db.session.execute(latest_season_query)
        latest_season_id = latest_season_result.fetchone()[0]
        
        # 获取最新赛季的大赛和小赛
        latest_season_major_query = text("""
            SELECT t.t_id, tsv.type_session_number
            FROM tournament t
            JOIN tournament_session_view tsv ON t.t_id = tsv.t_id
            WHERE t.status = 1 AND t.type = 1 AND t.season_id = :latest_season_id
            ORDER BY tsv.type_session_number DESC
        """)
        
        latest_season_minor_query = text("""
            SELECT t.t_id, tsv.type_session_number
            FROM tournament t
            JOIN tournament_session_view tsv ON t.t_id = tsv.t_id
            WHERE t.status = 1 AND t.type = 2 AND t.season_id = :latest_season_id
            ORDER BY tsv.type_session_number DESC
        """)
        
        latest_major_result = db.session.execute(latest_season_major_query, {'latest_season_id': latest_season_id})
        latest_minor_result = db.session.execute(latest_season_minor_query, {'latest_season_id': latest_season_id})
        
        latest_major_tournaments = latest_major_result.fetchall()
        latest_minor_tournaments = latest_minor_result.fetchall()
        
        # 构建最近20届大赛的t_id列表
        recent_major_t_ids = []
        if len(latest_major_tournaments) >= 20:
            # 最新赛季就有20届或更多大赛
            recent_major_t_ids = [row[0] for row in latest_major_tournaments[:20]]
        else:
            # 最新赛季大赛不够20届，需要从上个赛季补足
            recent_major_t_ids = [row[0] for row in latest_major_tournaments]
            remaining_needed = 20 - len(latest_major_tournaments)
            
            # 获取其他赛季的大赛，按赛季和届数降序排列
            other_seasons_major_query = text("""
                SELECT t.t_id, tsv.type_session_number
                FROM tournament t
                JOIN tournament_session_view tsv ON t.t_id = tsv.t_id
                WHERE t.status = 1 AND t.type = 1 AND t.season_id < :latest_season_id
                ORDER BY t.season_id DESC, tsv.type_session_number DESC
                LIMIT :remaining_needed
            """)
            
            other_major_result = db.session.execute(other_seasons_major_query, {
                'latest_season_id': latest_season_id,
                'remaining_needed': remaining_needed
            })
            other_major_tournaments = other_major_result.fetchall()
            recent_major_t_ids.extend([row[0] for row in other_major_tournaments])
        
        # 构建最近20届小赛的t_id列表
        recent_minor_t_ids = []
        if len(latest_minor_tournaments) >= 20:
            # 最新赛季就有20届或更多小赛
            recent_minor_t_ids = [row[0] for row in latest_minor_tournaments[:20]]
        else:
            # 最新赛季小赛不够20届，需要从上个赛季补足
            recent_minor_t_ids = [row[0] for row in latest_minor_tournaments]
            remaining_needed = 20 - len(latest_minor_tournaments)
            
            # 获取其他赛季的小赛，按赛季和届数降序排列
            other_seasons_minor_query = text("""
                SELECT t.t_id, tsv.type_session_number
                FROM tournament t
                JOIN tournament_session_view tsv ON t.t_id = tsv.t_id
                WHERE t.status = 1 AND t.type = 2 AND t.season_id < :latest_season_id
                ORDER BY t.season_id DESC, tsv.type_session_number DESC
                LIMIT :remaining_needed
            """)
            
            other_minor_result = db.session.execute(other_seasons_minor_query, {
                'latest_season_id': latest_season_id,
                'remaining_needed': remaining_needed
            })
            other_minor_tournaments = other_minor_result.fetchall()
            recent_minor_t_ids.extend([row[0] for row in other_minor_tournaments])
        
        # 为每个选手计算总积分
        player_scores = {}
        
        for player in players:
            # 获取该选手在最近20届大赛中的积分
            major_scores = []
            if recent_major_t_ids:
                # 使用字符串格式化构建查询
                major_placeholders = ','.join([str(t_id) for t_id in recent_major_t_ids])
                major_query = text(f"""
                    SELECT r.scores
                    FROM rankings r
                    WHERE r.player_id = {player.player_id} 
                    AND r.t_id IN ({major_placeholders})
                    AND r.scores IS NOT NULL
                """)
                
                major_result = db.session.execute(major_query)
                major_scores = [row[0] for row in major_result.fetchall()]
            
            # 获取该选手在最近20届小赛中的积分
            minor_scores = []
            if recent_minor_t_ids:
                # 使用字符串格式化构建查询
                minor_placeholders = ','.join([str(t_id) for t_id in recent_minor_t_ids])
                minor_query = text(f"""
                    SELECT r.scores
                    FROM rankings r
                    WHERE r.player_id = {player.player_id} 
                    AND r.t_id IN ({minor_placeholders})
                    AND r.scores IS NOT NULL
                """)
                
                minor_result = db.session.execute(minor_query)
                minor_scores = [row[0] for row in minor_result.fetchall()]
            
            # 计算总积分
            total_score = sum(major_scores) + sum(minor_scores)
            
            # 计算起计分：如果参赛次数≥10次，取积分第10高的；否则为0
            all_scores = major_scores + minor_scores
            if len(all_scores) >= 10:
                all_scores.sort(reverse=True)
                baseline_score = all_scores[9]  # 第10高积分（索引9）
            else:
                baseline_score = 0
            
            # 统计该选手在所有赛季参加的大赛和小赛总数
            all_major_count_query = text(f"""
                SELECT COUNT(*)
                FROM rankings r
                JOIN tournament t ON r.t_id = t.t_id
                WHERE r.player_id = {player.player_id} 
                AND t.type = 1 AND t.status = 1
                AND r.scores IS NOT NULL
            """)
            
            all_minor_count_query = text(f"""
                SELECT COUNT(*)
                FROM rankings r
                JOIN tournament t ON r.t_id = t.t_id
                WHERE r.player_id = {player.player_id} 
                AND t.type = 2 AND t.status = 1
                AND r.scores IS NOT NULL
            """)
            
            all_major_count_result = db.session.execute(all_major_count_query)
            all_minor_count_result = db.session.execute(all_minor_count_query)
            
            all_major_count = all_major_count_result.fetchone()[0]
            all_minor_count = all_minor_count_result.fetchone()[0]
            
            player_scores[player.player_id] = {
                'player_id': player.player_id,
                'name': player.name,
                'total_score': total_score,
                'baseline_score': baseline_score,
                'major_count': all_major_count,  # 所有赛季的大赛参与次数
                'minor_count': all_minor_count,   # 所有赛季的小赛参与次数
                'total_count': all_major_count + all_minor_count
            }
        
        # 按总积分降序排序
        sorted_players = sorted(player_scores.values(), key=lambda x: x['total_score'], reverse=True)
        
        # 更新排名
        for rank, player_data in enumerate(sorted_players, 1):
            player_data['rank'] = rank
        
        return sorted_players
        
    except Exception as e:
        print(f"计算选手总积分失败: {e}")
        return []


@app.route('/')
def index():
    seasons = Season.query.order_by(Season.year.desc()).all()
    
    # 计算选手总积分排名
    player_rankings_data = calculate_player_total_scores()
    
    # 将字典数据转换为对象格式，以便模板使用
    class PlayerRanking:
        def __init__(self, data):
            self.player_id = data['player_id']
            self.name = data['name']
            self.rank = data['rank']
            self.total_score = data['total_score']
            self.baseline_score = data['baseline_score']
            self.total_count = data['total_count']
    
    player_rankings = [PlayerRanking(data) for data in player_rankings_data]
    
    # 获取奖牌榜数据
    major_medal_standings = get_medal_standings_by_type(1)  # 大赛
    minor_medal_standings = get_medal_standings_by_type(2)  # 小赛
    final_medal_standings = get_medal_standings_by_type(3)  # 总决赛
    
    return render_template('index.html', 
                         seasons=seasons, 
                         player_rankings=player_rankings,
                         major_medal_standings=major_medal_standings,
                         minor_medal_standings=minor_medal_standings,
                         final_medal_standings=final_medal_standings)


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return wrapper


@app.route('/admin-secret/matches/add-score', methods=['POST'])
@admin_required
def add_match_score():
    """添加新比赛（JSON API）"""
    try:
        from sqlalchemy import text
        
        data = request.get_json()
        t_id = data.get('t_id')
        player_1_id = int(data['player_1_id'])
        player_2_id = int(data['player_2_id'])
        player_1_score = int(data.get('player_1_score') or 0)
        player_2_score = int(data.get('player_2_score') or 0)
        m_type = int(data.get('m_type') or 1)
        
        # 验证比赛类型是否有效
        tournament = db.session.get(Tournament, t_id)
        if not tournament:
            return jsonify({'success': False, 'error': '赛事不存在'})
        
        # 根据赛事类型和格式验证m_type
        valid_m_types = []
        if tournament.t_id == 24:  # 特殊处理：赛事24
            valid_m_types = [2, 3, 9, 10, 11, 12]  # 苏超赛制 + 特殊淘汰赛
        elif tournament.t_format == 6:  # 苏超赛制
            valid_m_types = [2, 3, 11, 12]  # 苏超赛制 + 金牌铜牌赛
        elif tournament.type == 2:  # 小赛
            valid_m_types = [1, 11, 12]  # 小组赛 + 金牌铜牌赛
        else:  # 大赛或其他
            valid_m_types = [1, 7, 8, 9, 10, 11, 12]  # 标准比赛类型
        
        if m_type not in valid_m_types:
            return jsonify({'success': False, 'error': f'比赛类型{m_type}不适用于当前赛事'})
        
        # 获取参赛选手ID列表
        # 检查该赛事是否已有排名数据
        has_rankings = db.session.execute(text("""
            SELECT COUNT(*) FROM rankings WHERE t_id = :t_id
        """), {'t_id': t_id}).fetchone()[0] > 0
        
        if has_rankings:
            # 如果已有排名，从排名表中获取参赛选手
            participants_query = text("""
                SELECT DISTINCT p.player_id
                FROM players p
                JOIN rankings r ON p.player_id = r.player_id
                WHERE r.t_id = :t_id
            """)
        else:
            # 如果还没有排名，从所有选手中选择（只选择参与排名的选手）
            participants_query = text("""
                SELECT p.player_id
                FROM players p
                WHERE p.status IN (1, 2)
            """)
        
        participants_result = db.session.execute(participants_query, {'t_id': t_id}).fetchall()
        participant_ids = [row[0] for row in participants_result]
        
        # 验证选手是否在参赛名单中
        if player_1_id not in participant_ids or player_2_id not in participant_ids:
            return jsonify({'success': False, 'error': '选择的选手不在参赛名单中'})
        
        # 创建新比赛
        match = Match(
            t_id=t_id,
            player_1_id=player_1_id,
            player_2_id=player_2_id,
            player_1_score=player_1_score,
            player_2_score=player_2_score,
            m_type=m_type
        )
        
        db.session.add(match)
        db.session.commit()
        
        return jsonify({'success': True, 'message': '比赛添加成功'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})


@app.route('/admin-secret/tournaments/generate-special-knockout', methods=['POST'])
@admin_required
def generate_special_knockout_matches():
    """手动生成特殊淘汰赛对阵"""
    try:
        data = request.get_json()
        t_id = data.get('t_id')
        
        if not t_id:
            return jsonify({'success': False, 'error': '缺少赛事ID'})
        
        # 检查赛事是否存在且为小赛
        tournament = db.session.get(Tournament, t_id)
        if not tournament:
            return jsonify({'success': False, 'error': '赛事不存在'})
        
        if tournament.type != 2:
            return jsonify({'success': False, 'error': '只有小赛才能生成特殊淘汰赛对阵'})
        
        # 生成特殊淘汰赛对阵
        success = auto_generate_special_knockout_matches(t_id)
        
        if success:
            return jsonify({'success': True, 'message': '特殊淘汰赛对阵生成成功'})
        else:
            return jsonify({'success': False, 'error': '生成失败，请检查循环赛是否完成'})
        
    except Exception as e:
        print(f"生成特殊淘汰赛对阵失败: {e}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/admin-secret/tournaments/generate-knockout', methods=['POST'])
@admin_required
def generate_knockout_matches():
    """手动生成淘汰赛对阵"""
    try:
        data = request.get_json()
        t_id = data.get('t_id')
        
        if not t_id:
            return jsonify({'success': False, 'error': '缺少赛事ID'})
        
        # 检查赛事是否存在且为小赛
        tournament = db.session.get(Tournament, t_id)
        if not tournament:
            return jsonify({'success': False, 'error': '赛事不存在'})
        
        if tournament.type != 2:
            return jsonify({'success': False, 'error': '只有小赛才能生成淘汰赛对阵'})
        
        # 生成淘汰赛对阵
        success = auto_generate_knockout_matches(t_id)
        
        if success:
            return jsonify({'success': True, 'message': '淘汰赛对阵生成成功'})
        else:
            return jsonify({'success': False, 'error': '生成失败，请检查小组赛是否完成'})
        
    except Exception as e:
        print(f"生成淘汰赛对阵失败: {e}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/admin-secret/matches/update-scores', methods=['POST'])
@admin_required
def update_match_scores():
    """更新比赛比分"""
    try:
        data = request.get_json()
        scores = data.get('scores', {})
        
        updated_matches = 0
        for match_id, match_scores in scores.items():
            try:
                match_id = int(match_id)
                player_1_score = int(match_scores.get('1') or 0)
                player_2_score = int(match_scores.get('2') or 0)
                
                # 更新比赛比分
                match = db.session.get(Match, match_id)
                if match:
                    match.player_1_score = player_1_score
                    match.player_2_score = player_2_score
                    updated_matches += 1
                    
            except (ValueError, TypeError) as e:
                print(f"更新比赛 {match_id} 比分时出错: {e}")
                continue
        
        db.session.commit()
        
        # 自动重新计算积分和排名
        if updated_matches > 0:
            # 获取第一个更新的比赛的赛事ID
            first_match = db.session.get(Match, list(scores.keys())[0])
            if first_match:
                tournament_id = first_match.t_id
                print(f"重新计算赛事 {tournament_id} 的积分")
                # 重新计算积分
                calculate_tournament_scores(tournament_id)
                
                # 检查是否需要更新淘汰赛对阵（适用于所有赛事）
                tournament = db.session.get(Tournament, tournament_id)
                if tournament and tournament.t_format in [1, 3]:  # 支持淘汰赛的赛事格式
                    # 检查是否有淘汰赛的比分被更新
                    knockout_updated = False
                    
                    for match_id, match_scores in scores.items():
                        match = db.session.get(Match, int(match_id))
                        if match and match.m_type in [8, 9, 10, 11, 12, 13]:  # 所有淘汰赛类型
                            knockout_updated = True
                            break
                    
                    if knockout_updated:
                        print(f"检测到赛事 {tournament_id} 淘汰赛比分更新，更新淘汰赛对阵")
                        # 调用通用的淘汰赛更新函数
                        try:
                            # 这里我们需要调用update_knockout_bracket的逻辑
                            # 但由于这是POST请求，我们需要直接调用逻辑
                            update_knockout_bracket_logic(tournament_id)
                        except Exception as e:
                            print(f"更新淘汰赛对阵时出错: {e}")
        
        return jsonify({'success': True, 'updated_matches': updated_matches})
        
    except Exception as e:
        db.session.rollback()
        print(f"更新比分失败: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/admin-secret/tournament/<int:t_id>/match/<int:match_id>/score', methods=['POST'])
def update_single_match_score(t_id, match_id):
    """更新单个比赛的比分"""
    try:
        # 检查权限
        if not session.get('admin_logged_in') and not session.get('user_logged_in'):
            return jsonify({'success': False, 'error': '请先登录'}), 401
        
        # 获取比赛信息
        match = Match.query.get_or_404(match_id)
        
        # 检查用户权限
        if not can_user_edit_match(match, session.get('user_id')):
            return jsonify({'success': False, 'error': '没有权限修改此比赛比分'}), 403
        
        data = request.get_json()
        player_1_score = int(data.get('player_1_score') or 0)
        player_2_score = int(data.get('player_2_score') or 0)
        
        # 检查是否双方都是0分
        if player_1_score == 0 and player_2_score == 0:
            return jsonify({'success': False, 'error': '双方比分不能都为0'}), 400
        
        # 检查比分是否有效（不能为负数）
        if player_1_score < 0 or player_2_score < 0:
            return jsonify({'success': False, 'error': '比分不能为负数'}), 400
        
        # 更新比赛比分
        match = db.session.get(Match, match_id)
        if not match:
            return jsonify({'success': False, 'error': '比赛不存在'}), 404
        
        if match.t_id != t_id:
            return jsonify({'success': False, 'error': '比赛与赛事不匹配'}), 400
        
        match.player_1_score = player_1_score
        match.player_2_score = player_2_score
        
        db.session.commit()
        
        # 重新计算积分和排名
        print(f"重新计算赛事 {t_id} 的积分")
        calculate_tournament_scores(t_id)
        
        # 检查是否需要更新淘汰赛对阵
        tournament = db.session.get(Tournament, t_id)
        if tournament and tournament.t_format in [1, 3]:  # 支持淘汰赛的赛事格式
            try:
                update_knockout_bracket_logic(t_id)
            except Exception as e:
                print(f"更新淘汰赛对阵时出错: {e}")
        
        return jsonify({'success': True, 'message': '比分更新成功'})
        
    except Exception as e:
        db.session.rollback()
        print(f"更新比分失败: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/season/<int:season_id>')
def season_view(season_id):
    season = Season.query.get_or_404(season_id)
    
    # 使用SQL视图获取带序号的届次数据
    from sqlalchemy import text
    view_query = text("""
        SELECT t.t_id, t.season_id, s.year, t.type, t.player_count, t.t_format,
               ts.type_session_number
        FROM tournament t
        JOIN seasons s ON t.season_id = s.season_id
        JOIN tournament_session_view ts ON t.t_id = ts.t_id
        WHERE t.season_id = :season_id
        ORDER BY t.type, t.t_id
    """)
    
    result = db.session.execute(view_query, {'season_id': season_id})
    tournaments_data = result.fetchall()
    
    # 将查询结果转换为对象列表
    tournaments = []
    for row in tournaments_data:
        tournament = db.session.get(Tournament, row.t_id)
        tournament.type_session_number = row.type_session_number
        tournaments.append(tournament)
    
        # attach top-3 podium names if available
    for tt in tournaments:
        try:
            top = Ranking.query.filter_by(t_id=tt.t_id).order_by(Ranking.ranks).limit(3).all()
            podium = {1: '', 2: '', 3: ''}
            for r in top:
                try:
                    pname = r.player.name
                except Exception:
                    pname = ''
                podium.get(r.ranks)  # ensure key exists
                podium[r.ranks] = pname
            tt.podium = podium
        except Exception:
            tt.podium = {1: '', 2: '', 3: ''}
    
    # 获取当前赛季的奖牌榜数据（只显示大赛和小赛）
    major_medal_standings = get_season_medal_standings_by_type(season_id, 1)  # 大赛
    minor_medal_standings = get_season_medal_standings_by_type(season_id, 2)  # 小赛
    
    # 获取赛季翻页信息
    season_pagination = get_season_pagination(season_id)
    
    return render_template('season.html', 
                         season=season, 
                         tournaments=tournaments,
                         major_medal_standings=major_medal_standings,
                         minor_medal_standings=minor_medal_standings,
                         season_pagination=season_pagination)


@app.route('/tournament/<int:t_id>')
def tournament_view(t_id):
    t = Tournament.query.get_or_404(t_id)
    
    # 使用SQL视图获取该届次的序号
    from sqlalchemy import text
    view_query = text("""
        SELECT type_session_number
        FROM tournament_session_view
        WHERE t_id = :t_id
    """)
    
    result = db.session.execute(view_query, {'t_id': t_id})
    row = result.fetchone()
    if row:
        t.type_session_number = row.type_session_number
    else:
        t.type_session_number = None
    
    # 获取翻页信息
    pagination_info = get_tournament_pagination(t_id)
    
    # fetch matches and group by m_type (ascending)
    matches = Match.query.filter_by(t_id=t_id).order_by(Match.m_type.asc(), Match.m_id.asc()).all()
    from collections import OrderedDict
    matches_grouped = OrderedDict()
    for m in matches:
        key = m.m_type or 0
        matches_grouped.setdefault(key, []).append(m)
    # rankings for this tournament
    rankings = Ranking.query.filter_by(t_id=t_id).order_by(Ranking.ranks).all()
    # compute points for group-stage only (小组赛): 胜者+3, 平局+1, 负者不加分
    points = {}
    try:
        is_group = (t.type != 1)
    except Exception:
        is_group = False
    if is_group:
        for m in matches:
            # ensure scores are present
            try:
                s1 = int(m.player_1_score)
                s2 = int(m.player_2_score)
            except Exception:
                continue
            if s1 > s2:
                points[m.player_1_id] = points.get(m.player_1_id, 0) + 3
            elif s2 > s1:
                points[m.player_2_id] = points.get(m.player_2_id, 0) + 3
            elif s1 == s2 and s2 != 0:
                points[m.player_1_id] = points.get(m.player_1_id, 0) + 1
                points[m.player_2_id] = points.get(m.player_2_id, 0) + 1
            else:
                # 0-0不算平局，双方都不加分
                points[m.player_1_id] = points.get(m.player_1_id, 0)
                points[m.player_2_id] = points.get(m.player_2_id, 0)
    
    # 获取参赛选手信息（用于填写比分和分组设置）
    participants = []
    try:
        # 优先从小组赛数据中获取参赛选手
        has_groups = db.session.execute(text("""
            SELECT COUNT(*) FROM tgroups WHERE t_id = :t_id
        """), {'t_id': t_id}).fetchone()[0] > 0
        
        if has_groups:
            # 如果已有小组赛数据，从小组赛中获取参赛选手
            participants_query = text("""
                SELECT DISTINCT p.player_id, p.name
                FROM players p
                JOIN tg_players tgp ON p.player_id = tgp.player_id
                JOIN tgroups tg ON tgp.tg_id = tg.tg_id
                WHERE tg.t_id = :t_id
                ORDER BY p.name
            """)
        else:
            # 检查该赛事是否已有排名数据
            has_rankings = db.session.execute(text("""
                SELECT COUNT(*) FROM rankings WHERE t_id = :t_id
            """), {'t_id': t_id}).fetchone()[0] > 0
            
            if has_rankings:
                # 如果已有排名，从排名表中获取参赛选手
                participants_query = text("""
                    SELECT DISTINCT p.player_id, p.name
                    FROM players p
                    JOIN rankings r ON p.player_id = r.player_id
                    WHERE r.t_id = :t_id
                    ORDER BY p.name
                """)
            else:
                # 如果还没有排名，从所有选手中选择（只选择参与排名的选手）
                # 对于分组设置，我们需要获取所有可用选手
                participants_query = text("""
                    SELECT p.player_id, p.name
                    FROM players p
                    WHERE p.status IN (1, 2)
                    ORDER BY p.name
                """)
        
        participants_result = db.session.execute(participants_query, {'t_id': t_id}).fetchall()
        participants = [{'player_id': row[0], 'name': row[1]} for row in participants_result]
        
        # 如果分组设置需要更多选手，确保有足够的选手
        if t.player_count > len(participants):
            print(f"警告：赛事需要 {t.player_count} 名选手，但只有 {len(participants)} 名可用选手")
            
    except Exception as e:
        print(f"获取参赛选手失败: {e}")
    
    # 计算单循环赛制的实时排名（如果是单循环赛制）
    round_robin_standings = []
    minor_knockout_data = None
    special_knockout_data = None
    try:
        # 检查是否是单循环赛制（t_format = 1 表示单循环）或苏超赛制（t_format = 6）
        if t.t_format in [1, 6]:
            round_robin_standings = calculate_round_robin_standings(t_id)
        
        # 如果是支持小组赛的赛事（type = 1, 2, 3），计算淘汰赛阶段
        if t.type in [1, 2, 3]:
            # 特殊处理：赛事24使用特殊淘汰赛阶段
            if t_id == 24:
                # 检查特殊淘汰赛是否存在，如果不存在才生成
                from sqlalchemy import text
                knockout_check_query = text("""
                    SELECT COUNT(*) FROM matches 
                    WHERE t_id = :t_id AND m_type IN (9, 10, 11, 12)
                """)
                knockout_count = db.session.execute(knockout_check_query, {'t_id': t_id}).fetchone()[0]
                
                if knockout_count == 0:
                    # 没有特殊淘汰赛，生成新的
                    auto_generate_special_knockout_matches(t_id)
                
                special_knockout_data = calculate_special_knockout_stages(t_id)
            else:
                # 其他小赛使用标准淘汰赛
                # 不在这里自动生成淘汰赛，等当前阶段完成后再生成
                minor_knockout_data = calculate_minor_tournament_knockout(t_id)
    except Exception as e:
        print(f"计算排名失败: {e}")
    
    # 重新获取比赛数据，以防特殊淘汰赛生成时删除了旧的对阵
    matches = Match.query.filter_by(t_id=t_id).order_by(Match.m_type.asc(), Match.m_id.asc()).all()
    matches_grouped = OrderedDict()
    for m in matches:
        key = m.m_type or 0
        matches_grouped.setdefault(key, []).append(m)
    
    # 获取小组赛数据（大赛、小赛和总决赛都支持小组赛显示）
    group_stage_data = None
    top8_players = []
    if t.type in [1, 2, 3]:  # 大赛、小赛和总决赛都支持小组赛显示
        groups = get_tournament_groups(t_id)
        if groups:
            # 计算总排名
            total_rankings = calculate_total_group_rankings(t_id)
            
            # 获取总排名前8名选手（用于1/4决赛手动指定位次）
            all_players = []
            for group_id, players in total_rankings.items():
                all_players.extend(players)
            
            # 按total_rank排序，确保正确的总排名顺序
            all_players.sort(key=lambda x: x['total_rank'])
            top8_players = all_players[:8]
            
            group_stage_data = {
                'groups': groups,
                'group_standings': total_rankings
            }
        elif t.type == 2:  # 小赛没有分组数据时，创建虚拟分组显示所有比赛
            # 为小赛创建单循环显示
            single_round_robin_data = create_single_round_robin_display(t_id)
            if single_round_robin_data:
                group_stage_data = single_round_robin_data
        elif t.type == 1 and t.t_format in [4, 5, 6]:  # 大赛单循环/双循环赛/苏超赛制
            # 为大赛的单循环/双循环赛/苏超赛制创建虚拟分组显示
            single_round_robin_data = create_single_round_robin_display(t_id)
            if single_round_robin_data:
                group_stage_data = single_round_robin_data
    
    # 获取淘汰赛数据（通用，支持所有赛制）
    knockout_matches = calculate_knockout_matches(t_id)
    
    # 获取当前用户信息
    current_user = None
    if session.get('user_logged_in'):
        current_user = User.query.get(session['user_id'])
    
    # 获取报名截止时间
    signup_deadline = t.signup_deadline
    
    return render_template('tournament.html', 
                         tournament=t, 
                         matches=matches, 
                         matches_grouped=matches_grouped, 
                         rankings=rankings, 
                         points=points, 
                         pagination=pagination_info,
                         round_robin_standings=round_robin_standings,
                         minor_knockout_data=minor_knockout_data,
                         special_knockout_data=special_knockout_data,
                         group_stage_data=group_stage_data,
                         knockout_matches=knockout_matches,
                         participants=participants,
                         top8_players=top8_players,
                         current_user=current_user,
                         signup_deadline=signup_deadline)


# 小组赛相关函数
def get_tournament_factors(player_count):
    """获取参赛人数的所有因数（除了自身）"""
    factors = []
    for i in range(1, player_count):
        if player_count % i == 0:
            factors.append(i)
    return factors

def is_power_of_two(n):
    """检查是否为2的幂次方"""
    return n > 0 and (n & (n - 1)) == 0

def calculate_group_info(player_count, group_size):
    """计算分组信息"""
    if group_size == 0:
        return None
    
    groups_count = player_count // group_size
    remaining_players = player_count % group_size
    
    if remaining_players > 0:
        groups_count += 1
    
    return {
        'groups_count': groups_count,
        'remaining_players': remaining_players,
        'last_group_size': group_size + remaining_players if remaining_players > 0 else group_size
    }

def generate_group_names(groups_count):
    """生成组别名称（A-Z）"""
    if groups_count > 26:
        return None
    
    group_names = []
    for i in range(groups_count):
        group_names.append(chr(ord('A') + i))
    return group_names

def create_tournament_groups(t_id, group_size, group_names):
    """创建赛事分组"""
    from sqlalchemy import text
    
    # 删除现有分组
    db.session.execute(text("DELETE FROM tg_players WHERE tg_id IN (SELECT tg_id FROM tgroups WHERE t_id = :t_id)"), {'t_id': t_id})
    db.session.execute(text("DELETE FROM tgroups WHERE t_id = :t_id"), {'t_id': t_id})
    
    # 创建新分组
    for group_name in group_names:
        db.session.execute(text("INSERT INTO tgroups (t_id, t_name) VALUES (:t_id, :t_name)"), 
                          {'t_id': t_id, 't_name': group_name})
    
    db.session.commit()
    return True

def get_tournament_groups(t_id):
    """获取赛事的所有分组，包括选手和比赛数据"""
    from sqlalchemy import text
    
    # 获取分组信息
    query = text("""
        SELECT tg.tg_id, tg.t_name, COUNT(tgp.player_id) as current_player_count
        FROM tgroups tg
        LEFT JOIN tg_players tgp ON tg.tg_id = tgp.tg_id
        WHERE tg.t_id = :t_id
        GROUP BY tg.tg_id, tg.t_name
        ORDER BY tg.t_name
    """)
    
    result = db.session.execute(query, {'t_id': t_id}).fetchall()
    groups = []
    
    # 获取赛事总人数和分组数，计算每组应该有多少人
    tournament = db.session.get(Tournament, t_id)
    if tournament and result:
        total_players = tournament.player_count
        group_count = len(result)
        expected_group_size = total_players // group_count
        remaining_players = total_players % group_count
        
        for i, row in enumerate(result):
            # 最后一组可能人数不同
            if i == group_count - 1 and remaining_players > 0:
                expected_size = expected_group_size + remaining_players
            else:
                expected_size = expected_group_size
            
            tg_id = row[0]
            t_name = row[1]
            
            # 获取该分组的选手信息，直接从比赛结果计算统计数据
            players_query = text("""
                SELECT p.player_id, p.name,
                       COALESCE(stats.wins, 0) as wins,
                       COALESCE(stats.losses, 0) as losses,
                       COALESCE(stats.draws, 0) as draws,
                       COALESCE(stats.goals_for, 0) as goals_for,
                       COALESCE(stats.goals_against, 0) as goals_against
                FROM tg_players tgp
                JOIN players p ON tgp.player_id = p.player_id
                LEFT JOIN (
                    SELECT 
                        player_id,
                        SUM(wins) as wins,
                        SUM(losses) as losses,
                        SUM(draws) as draws,
                        SUM(goals_for) as goals_for,
                        SUM(goals_against) as goals_against
                    FROM (
                        SELECT 
                            player_1_id as player_id,
                            CASE WHEN player_1_score > player_2_score THEN 1 ELSE 0 END as wins,
                            CASE WHEN player_1_score < player_2_score THEN 1 ELSE 0 END as losses,
                            CASE WHEN player_1_score = player_2_score AND player_1_score > 0 THEN 1 ELSE 0 END as draws,
                            player_1_score as goals_for,
                            player_2_score as goals_against
                        FROM matches 
                        WHERE t_id = :t_id AND m_type IN (1, 2, 3) 
                        AND player_1_score IS NOT NULL AND player_2_score IS NOT NULL
                        AND player_1_id IN (SELECT player_id FROM tg_players WHERE tg_id = :tg_id)
                        
                        UNION ALL
                        
                        SELECT 
                            player_2_id as player_id,
                            CASE WHEN player_2_score > player_1_score THEN 1 ELSE 0 END as wins,
                            CASE WHEN player_2_score < player_1_score THEN 1 ELSE 0 END as losses,
                            CASE WHEN player_1_score = player_2_score AND player_1_score > 0 THEN 1 ELSE 0 END as draws,
                            player_2_score as goals_for,
                            player_1_score as goals_against
                        FROM matches 
                        WHERE t_id = :t_id AND m_type IN (1, 2, 3) 
                        AND player_1_score IS NOT NULL AND player_2_score IS NOT NULL
                        AND player_2_id IN (SELECT player_id FROM tg_players WHERE tg_id = :tg_id)
                    ) match_stats
                    GROUP BY player_id
                ) stats ON p.player_id = stats.player_id
                WHERE tgp.tg_id = :tg_id
                ORDER BY tgp.tgp_id ASC
            """)
            
            players_result = db.session.execute(players_query, {'t_id': t_id, 'tg_id': tg_id}).fetchall()
            
            # 先计算组内排名
            group_players = []
            for player_row in players_result:
                # 计算该选手需要打的总场次数
                total_matches = calculate_player_total_matches(t_id, player_row[0])
                
                player_data = {
                    'player_id': player_row[0],
                    'name': player_row[1],
                    'wins': player_row[2] or 0,
                    'losses': player_row[3] or 0,
                    'draws': player_row[4] or 0,
                    'goals_for': player_row[5] or 0,
                    'goals_against': player_row[6] or 0,
                    'total_matches': total_matches,  # 添加总场次字段
                }
                player_data['goal_difference'] = player_data['goals_for'] - player_data['goals_against']
                player_data['points'] = player_data['wins'] * 3 + player_data['draws']
                group_players.append(player_data)
            
            # 按积分 → 净胜分 → 总得分 → 姓名排序，计算组内排名
            def compare_group_players(player1, player2):
                # 1. 积分
                if player1['points'] != player2['points']:
                    return player2['points'] - player1['points']
                
                # 2. 净胜分
                if player1['goal_difference'] != player2['goal_difference']:
                    return player2['goal_difference'] - player1['goal_difference']
                
                # 3. 总得分
                if player1['goals_for'] != player2['goals_for']:
                    return player2['goals_for'] - player1['goals_for']
                
                # 4. 按姓名排序
                if player1['name'] < player2['name']:
                    return -1
                elif player1['name'] > player2['name']:
                    return 1
                else:
                    return 0
            
            from functools import cmp_to_key
            group_players.sort(key=cmp_to_key(compare_group_players))
            
            # 分配组内排名
            for i, player in enumerate(group_players):
                player['group_rank'] = i + 1
            
            # 存储到临时变量中，稍后计算总排名
            groups.append({
                'tg_id': tg_id,
                't_name': t_name,
                'player_count': row[2],  # 当前实际人数
                'expected_size': expected_size,  # 期望人数
                'temp_players': group_players
            })
        
        # 现在计算总排名
        from collections import defaultdict
        
        # 获取所有比赛数据用于计算胜负关系
        all_matches_query = text("""
            SELECT player_1_id, player_2_id, player_1_score, player_2_score, m_type
            FROM matches
            WHERE t_id = :t_id AND m_type IN (1, 2, 3)
            AND player_1_score IS NOT NULL AND player_2_score IS NOT NULL
        """)
        
        all_matches_result = db.session.execute(all_matches_query, {'t_id': t_id}).fetchall()
        all_matches = []
        for match_row in all_matches_result:
            all_matches.append((match_row[0], match_row[1], match_row[2], match_row[3], match_row[4]))
        
        # 收集所有选手的排名数据
        all_standings = []
        for group in groups:
            for player in group['temp_players']:
                player['group_name'] = group['t_name']
                all_standings.append(player)
        
        # 按组内排名分组，然后按排名顺序排序
        rank_groups = defaultdict(list)
        for player in all_standings:
            rank_groups[player['group_rank']].append(player)
        
        # 按排名顺序排序：第1名 → 第2名 → 第3名 → ...
        final_all_standings = []
        for rank in sorted(rank_groups.keys()):
            rank_players = rank_groups[rank]
            
            # 对同排名选手按积分 → 胜负关系 → 净胜分 → 总得分排序
            def compare_same_rank(player1, player2):
                # 1. 积分
                if player1['points'] != player2['points']:
                    return player2['points'] - player1['points']
                
                # 2. 积分相同，需要计算内部胜负关系
                # 获取这两个选手之间的比赛记录
                h2h_result = calculate_head_to_head_result(player1['player_id'], player2['player_id'], all_matches)
                if h2h_result != 0:
                    return -h2h_result  # 1表示player1胜，返回-1让player1排在前面
                
                # 3. 胜负关系相同（平局或未交手），比较净胜分
                if player1['goal_difference'] != player2['goal_difference']:
                    return player2['goal_difference'] - player1['goal_difference']
                
                # 4. 净胜分相同，比较总得分
                if player1['goals_for'] != player2['goals_for']:
                    return player2['goals_for'] - player1['goals_for']
                
                # 5. 按姓名排序
                if player1['name'] < player2['name']:
                    return -1
                elif player1['name'] > player2['name']:
                    return 1
                else:
                    return 0
            
            from functools import cmp_to_key
            rank_players.sort(key=cmp_to_key(compare_same_rank))
            final_all_standings.extend(rank_players)
        
        # 分配总排名
        for i, standing in enumerate(final_all_standings):
            standing['total_rank'] = i + 1
        
        # 构建最终结果
        final_groups = []
        for group in groups:
            # 获取该分组的比赛信息
            matches_query = text("""
                SELECT m.m_id, m.player_1_id, m.player_2_id, m.player_1_score, m.player_2_score,
                       p1.name as player1_name, p2.name as player2_name, m.m_type
                FROM matches m
                JOIN players p1 ON m.player_1_id = p1.player_id
                JOIN players p2 ON m.player_2_id = p2.player_id
                WHERE m.t_id = :t_id AND m.m_type IN (1, 2, 3)
                AND m.player_1_id IN (SELECT player_id FROM tg_players WHERE tg_id = :tg_id)
                AND m.player_2_id IN (SELECT player_id FROM tg_players WHERE tg_id = :tg_id)
                ORDER BY m.m_id
            """)
            
            matches_result = db.session.execute(matches_query, {'t_id': t_id, 'tg_id': group['tg_id']}).fetchall()
            matches = []
            
            for match_row in matches_result:
                matches.append({
                    'm_id': match_row[0],
                    'player_1_id': match_row[1],
                    'player_2_id': match_row[2],
                    'player_1_score': match_row[3] or 0,
                    'player_2_score': match_row[4] or 0,
                    'player1': {'name': match_row[5]},
                    'player2': {'name': match_row[6]},
                    'm_type': match_row[7]
                })
            
            final_groups.append({
                'tg_id': group['tg_id'],
                't_name': group['t_name'],
                'player_count': group['player_count'],
                'expected_size': group['expected_size'],
                'players': group['temp_players'],
                'matches': matches
            })
        
        return final_groups

def assign_player_to_group(player_id, tg_id):
    """将选手分配到指定分组"""
    from sqlalchemy import text
    
    # 获取当前分组所属的赛事ID
    group_info = db.session.execute(text("""
        SELECT t_id FROM tgroups WHERE tg_id = :tg_id
    """), {'tg_id': tg_id}).fetchone()
    
    if not group_info:
        return False
    
    t_id = group_info[0]
    
    # 先删除选手在当前赛事中的现有分组（只删除当前赛事的，不影响其他赛事）
    db.session.execute(text("""
        DELETE FROM tg_players 
        WHERE player_id = :player_id 
        AND tg_id IN (SELECT tg_id FROM tgroups WHERE t_id = :t_id)
    """), {'player_id': player_id, 't_id': t_id})
    
    # 添加到新分组
    db.session.execute(text("INSERT INTO tg_players (player_id, tg_id) VALUES (:player_id, :tg_id)"), 
                      {'player_id': player_id, 'tg_id': tg_id})
    
    db.session.commit()
    return True

def assign_players_to_group(t_id, group_name, player_ids):
    """将多个选手分配到指定分组"""
    from sqlalchemy import text
    
    # 获取分组ID
    group_query = text("""
        SELECT tg_id FROM tgroups WHERE t_id = :t_id AND t_name = :group_name
    """)
    group_result = db.session.execute(group_query, {'t_id': t_id, 'group_name': group_name}).fetchone()
    
    if not group_result:
        return False
    
    tg_id = group_result[0]
    
    # 为每个选手分配分组
    for player_id in player_ids:
        assign_player_to_group(player_id, tg_id)
    
    return True

def clear_tournament_groups_and_matches(t_id):
    """清除赛事的所有分组和比赛"""
    from sqlalchemy import text
    
    # 删除比赛
    db.session.execute(text("DELETE FROM matches WHERE t_id = :t_id"), {'t_id': t_id})
    
    # 删除分组选手关联
    db.session.execute(text("""
        DELETE FROM tg_players 
        WHERE tg_id IN (SELECT tg_id FROM tgroups WHERE t_id = :t_id)
    """), {'t_id': t_id})
    
    # 删除分组
    db.session.execute(text("DELETE FROM tgroups WHERE t_id = :t_id"), {'t_id': t_id})
    
    db.session.commit()

def generate_group_matches(t_id, round_robin_type='single'):
    """为所有分组生成比赛场次"""
    from sqlalchemy import text
    
    # 获取所有分组
    groups_query = text("SELECT tg_id FROM tgroups WHERE t_id = :t_id")
    groups_result = db.session.execute(groups_query, {'t_id': t_id}).fetchall()
    
    is_double = (round_robin_type == 'double')
    
    for group_row in groups_result:
        tg_id = group_row[0]
        generate_group_round_robin_matches(t_id, tg_id, is_double)

def handle_player_withdraw(t_id, player_id, group_name):
    """处理选手退赛，自动填充剩余比赛结果"""
    from sqlalchemy import text
    
    # 获取分组ID
    group_query = text("""
        SELECT tg_id FROM tgroups WHERE t_id = :t_id AND t_name = :group_name
    """)
    group_result = db.session.execute(group_query, {'t_id': t_id, 'group_name': group_name}).fetchone()
    
    if not group_result:
        return False
    
    tg_id = group_result[0]
    
    # 获取该选手在该组内的所有未完成比赛
    matches_query = text("""
        SELECT m_id, player_1_id, player_2_id 
        FROM matches 
        WHERE t_id = :t_id AND m_type IN (1, 2, 3)
        AND (player_1_id = :player_id OR player_2_id = :player_id)
        AND (player_1_score IS NULL OR player_2_score IS NULL OR 
             (player_1_score = 0 AND player_2_score = 0))
        AND m_id IN (
            SELECT m.m_id FROM matches m
            JOIN tg_players tgp1 ON m.player_1_id = tgp1.player_id
            JOIN tg_players tgp2 ON m.player_2_id = tgp2.player_id
            WHERE tgp1.tg_id = :tg_id AND tgp2.tg_id = :tg_id
        )
    """)
    
    matches_result = db.session.execute(matches_query, {
        't_id': t_id, 
        'player_id': player_id, 
        'tg_id': tg_id
    }).fetchall()
    
    # 更新比赛结果
    for match in matches_result:
        m_id, player_1_id, player_2_id = match
        
        if player_1_id == player_id:
            # 退赛选手是player_1，结果0-2
            update_query = text("""
                UPDATE matches 
                SET player_1_score = 0, player_2_score = 2 
                WHERE m_id = :m_id
            """)
        else:
            # 退赛选手是player_2，结果2-0
            update_query = text("""
                UPDATE matches 
                SET player_1_score = 2, player_2_score = 0 
                WHERE m_id = :m_id
            """)
        
        db.session.execute(update_query, {'m_id': m_id})
    
    db.session.commit()
    return True

def get_group_players(tg_id):
    """获取分组内的所有选手，按照分配顺序"""
    from sqlalchemy import text
    
    query = text("""
        SELECT p.player_id, p.name
        FROM players p
        JOIN tg_players tgp ON p.player_id = tgp.player_id
        WHERE tgp.tg_id = :tg_id
        ORDER BY tgp.tgp_id
    """)
    
    result = db.session.execute(query, {'tg_id': tg_id}).fetchall()
    players = []
    for row in result:
        players.append({
            'player_id': row[0],
            'name': row[1]
        })
    return players

def generate_group_round_robin_matches(t_id, tg_id, is_double_round_robin=False):
    """为指定分组生成循环赛对阵"""
    from sqlalchemy import text
    
    # 获取分组内的选手
    players = get_group_players(tg_id)
    if len(players) < 2:
        return False
    
    # 检查是否已有比赛（检查所有小组赛类型）
    existing_matches_query = text("""
        SELECT COUNT(*) FROM matches 
        WHERE t_id = :t_id AND m_type IN (1, 2, 3) AND 
              (player_1_id IN (SELECT player_id FROM tg_players WHERE tg_id = :tg_id) OR
               player_2_id IN (SELECT player_id FROM tg_players WHERE tg_id = :tg_id))
    """)
    
    existing_count = db.session.execute(existing_matches_query, {'t_id': t_id, 'tg_id': tg_id}).fetchone()[0]
    
    if existing_count > 0:
        # 已有比赛，更新选手ID但不重置比分
        print(f"分组{tg_id}已有{existing_count}场比赛，将更新选手ID")
        
        # 获取现有比赛（所有小组赛类型）
        existing_matches_query = text("""
            SELECT m_id, player_1_id, player_2_id, m_type FROM matches 
            WHERE t_id = :t_id AND m_type IN (1, 2, 3) AND 
                  (player_1_id IN (SELECT player_id FROM tg_players WHERE tg_id = :tg_id) OR
                   player_2_id IN (SELECT player_id FROM tg_players WHERE tg_id = :tg_id))
            ORDER BY m_id
        """)
        
        existing_matches = db.session.execute(existing_matches_query, {'t_id': t_id, 'tg_id': tg_id}).fetchall()
        
        # 生成新的对阵
        new_matches = []
        
        if is_double_round_robin:
            # 双循环：先生成所有主场比赛
            for i in range(len(players)):
                for j in range(i + 1, len(players)):
                    player1 = players[i]
                    player2 = players[j]
                    new_matches.append({
                        'player_1_id': player1['player_id'],
                        'player_2_id': player2['player_id'],
                        'm_type': 2  # 小组赛（主）
                    })
            
            # 再生成所有客场比赛
            for i in range(len(players)):
                for j in range(i + 1, len(players)):
                    player1 = players[i]
                    player2 = players[j]
                    new_matches.append({
                        'player_1_id': player1['player_id'],
                        'player_2_id': player2['player_id'],
                        'm_type': 3  # 小组赛（客）
                    })
        else:
            # 单循环（小组赛普通）：每对选手比赛一次
            for i in range(len(players)):
                for j in range(i + 1, len(players)):
                    player1 = players[i]
                    player2 = players[j]
                    new_matches.append({
                        'player_1_id': player1['player_id'],
                        'player_2_id': player2['player_id'],
                        'm_type': 1
                    })
        
        # 更新现有比赛
        for i, match in enumerate(new_matches):
            if i < len(existing_matches):
                existing_match = existing_matches[i]
                m_id = existing_match[0]
                db.session.execute(text("""
                    UPDATE matches 
                    SET player_1_id = :player_1_id, player_2_id = :player_2_id, m_type = :m_type
                    WHERE m_id = :m_id
                """), {
                    'm_id': m_id,
                    'player_1_id': match['player_1_id'],
                    'player_2_id': match['player_2_id'],
                    'm_type': match['m_type']
                })
            else:
                # 如果新对阵比现有比赛多，插入新比赛
                db.session.execute(text("""
                    INSERT INTO matches (t_id, m_type, player_1_id, player_2_id, player_1_score, player_2_score)
                    VALUES (:t_id, :m_type, :player_1_id, :player_2_id, 0, 0)
                """), {
                    't_id': t_id,
                    'm_type': match['m_type'],
                    'player_1_id': match['player_1_id'],
                    'player_2_id': match['player_2_id']
                })
    else:
        # 没有现有比赛，直接插入
        matches = []
        
        if is_double_round_robin:
            # 双循环：先生成所有主场比赛
            for i in range(len(players)):
                for j in range(i + 1, len(players)):
                    player1 = players[i]
                    player2 = players[j]
                    matches.append({
                        'player_1_id': player1['player_id'],
                        'player_2_id': player2['player_id'],
                        'player_1_score': 0,
                        'player_2_score': 0,
                        'm_type': 2  # 小组赛（主）
                    })
            
            # 再生成所有客场比赛
            for i in range(len(players)):
                for j in range(i + 1, len(players)):
                    player1 = players[i]
                    player2 = players[j]
                    matches.append({
                        'player_1_id': player1['player_id'],
                        'player_2_id': player2['player_id'],
                        'player_1_score': 0,
                        'player_2_score': 0,
                        'm_type': 3  # 小组赛（客）
                    })
        else:
            # 单循环（小组赛普通）：每对选手比赛一次
            for i in range(len(players)):
                for j in range(i + 1, len(players)):
                    player1 = players[i]
                    player2 = players[j]
                    matches.append({
                        'player_1_id': player1['player_id'],
                        'player_2_id': player2['player_id'],
                        'player_1_score': 0,
                        'player_2_score': 0,
                        'm_type': 1  # 小组赛（普通）
                    })
        
        # 插入比赛到数据库
        for match in matches:
            db.session.execute(text("""
                INSERT INTO matches (t_id, m_type, player_1_id, player_2_id, player_1_score, player_2_score)
                VALUES (:t_id, :m_type, :player_1_id, :player_2_id, :player_1_score, :player_2_score)
            """), {
                't_id': t_id,
                'm_type': match['m_type'],
                'player_1_id': match['player_1_id'],
                'player_2_id': match['player_2_id'],
                'player_1_score': match['player_1_score'],
                'player_2_score': match['player_2_score']
            })
    
    db.session.commit()
    return True

def calculate_player_total_matches(t_id, player_id, t_format=None):
    """计算指定选手在小组赛中需要打的总场次数"""
    from sqlalchemy import text
    
    # 如果没有提供t_format，从数据库获取
    if t_format is None:
        tournament_query = text("SELECT t_format FROM tournament WHERE t_id = :t_id")
        tournament_result = db.session.execute(tournament_query, {'t_id': t_id}).fetchone()
        if not tournament_result:
            return 0
        t_format = tournament_result[0]
    
    # 获取该选手所在分组的其他选手数量
    if t_format in [4, 5, 6]:  # 单循环/双循环赛/苏超赛制（大赛）
        # 获取所有参赛选手数量
        players_query = text("""
            SELECT COUNT(DISTINCT player_id) as player_count
            FROM rankings
            WHERE t_id = :t_id
        """)
        player_count = db.session.execute(players_query, {'t_id': t_id}).fetchone()[0]
    else:
        # 分组赛制，获取该选手所在分组的选手数量
        group_query = text("""
            SELECT COUNT(*) as group_player_count
            FROM tg_players tgp1
            WHERE tgp1.tg_id = (
                SELECT tgp2.tg_id 
                FROM tg_players tgp2 
                JOIN tgroups tg ON tgp2.tg_id = tg.tg_id
                WHERE tgp2.player_id = :player_id AND tg.t_id = :t_id
            )
        """)
        result = db.session.execute(group_query, {'player_id': player_id, 't_id': t_id}).fetchone()
        if not result or result[0] is None:
            return 0
        player_count = result[0]
    
    # 根据赛制计算每个选手需要打的场次数
    if t_format == 1:  # 小组赛+淘汰赛
        # 检查该选手的小组赛比赛类型，判断是单循环还是双循环
        group_matches_query = text("""
            SELECT DISTINCT m_type
            FROM matches m
            JOIN tg_players tgp1 ON m.player_1_id = tgp1.player_id
            JOIN tg_players tgp2 ON m.player_2_id = tgp2.player_id
            WHERE m.t_id = :t_id AND m.m_type IN (1, 2, 3)
            AND tgp1.tg_id = tgp2.tg_id
            AND (m.player_1_id = :player_id OR m.player_2_id = :player_id)
        """)
        result = db.session.execute(group_matches_query, {'t_id': t_id, 'player_id': player_id}).fetchall()
        match_types = [row[0] for row in result]
        
        if len(match_types) > 1:  # 有多个比赛类型，说明是双循环
            total_matches = (player_count - 1) * 2
        else:  # 只有一个比赛类型，说明是单循环
            total_matches = player_count - 1
    elif t_format == 5:  # 双循环赛
        # 双循环：每个选手需要与其他每个选手比赛2次（主场+客场）
        total_matches = (player_count - 1) * 2
    elif t_format == 6:  # 苏超赛制
        # 苏超赛制：单循环但区分主客场，每个选手只需与其他每个选手比赛1次
        total_matches = player_count - 1
    else:  # 单循环赛或其他赛制
        # 单循环：每个选手需要与其他每个选手比赛1次
        total_matches = player_count - 1
    
    return total_matches

def calculate_group_standings(t_id, tg_id):
    """计算分组内的排名"""
    # print(f"DEBUG: 开始计算分组 {tg_id} 的排名")
    from sqlalchemy import text
    
    # 获取分组内的选手
    players = get_group_players(tg_id)
    if not players:
        return []
    
    # 获取分组内的比赛（包括所有小组赛类型：1=普通，2=主，3=客）
    query = text("""
        SELECT m.player_1_id, m.player_2_id, m.player_1_score, m.player_2_score, m.m_type
        FROM matches m
        JOIN tg_players tgp1 ON m.player_1_id = tgp1.player_id
        JOIN tg_players tgp2 ON m.player_2_id = tgp2.player_id
        WHERE m.t_id = :t_id AND m.m_type IN (1, 2, 3) AND tgp1.tg_id = :tg_id AND tgp2.tg_id = :tg_id
    """)
    
    result = db.session.execute(query, {'t_id': t_id, 'tg_id': tg_id}).fetchall()
    
    # 计算每个选手的统计数据
    standings = {}
    for player in players:
        # 计算该选手需要打的总场次数
        total_matches = calculate_player_total_matches(t_id, player['player_id'])
        
        standings[player['player_id']] = {
            'player_id': player['player_id'],
            'name': player['name'],
            'matches_played': 0,
            'total_matches': total_matches,  # 添加总场次字段
            'wins': 0,
            'draws': 0,
            'losses': 0,
            'goals_for': 0,
            'goals_against': 0,
            'goal_difference': 0,
            'points': 0
        }
    
    # 处理比赛结果
    for row in result:
        player_1_id, player_2_id, score_1, score_2, m_type = row
        
        if score_1 is None or score_2 is None:
            continue
            
        standings[player_1_id]['matches_played'] += 1
        standings[player_2_id]['matches_played'] += 1
        
        standings[player_1_id]['goals_for'] += score_1
        standings[player_1_id]['goals_against'] += score_2
        standings[player_2_id]['goals_for'] += score_2
        standings[player_2_id]['goals_against'] += score_1
        
        if score_1 > score_2:
            standings[player_1_id]['wins'] += 1
            standings[player_1_id]['points'] += 3
            standings[player_2_id]['losses'] += 1
        elif score_2 > score_1:
            standings[player_2_id]['wins'] += 1
            standings[player_2_id]['points'] += 3
            standings[player_1_id]['losses'] += 1
        elif score_1 == score_2 and score_1 > 0:
            # 只有双方都有得分且得分相同才算平局，0-0不算平局
            standings[player_1_id]['draws'] += 1
            standings[player_1_id]['points'] += 1
            standings[player_2_id]['draws'] += 1
            standings[player_2_id]['points'] += 1
        # 0-0的情况暂不计入胜平负统计，只计入场次和进球数
    
    # 计算净胜球
    for player_id in standings:
        standings[player_id]['goal_difference'] = standings[player_id]['goals_for'] - standings[player_id]['goals_against']
    
    # 转换为列表
    standings_list = list(standings.values())
    
    # 小组赛同积分排名逻辑
    def calculate_same_points_ranking(players_with_same_points, all_matches):
        """计算同积分选手的排名"""
        # print(f"DEBUG: 开始计算同积分选手排名，选手: {[p['name'] for p in players_with_same_points]}")
        # print(f"DEBUG: 选手ID映射: {[(p['name'], p['player_id']) for p in players_with_same_points]}")
        
        # 为每个选手计算对同分选手的胜负关系
        for player in players_with_same_points:
            player_id = player['player_id']
            h2h_points = 0
            h2h_wins = 0
            h2h_draws = 0
            h2h_losses = 0
            h2h_goals_for = 0
            h2h_goals_against = 0
            
            # print(f"DEBUG: 计算 {player['name']} 对同分选手的胜负关系")
            
            # 遍历所有比赛，找到与同分选手的比赛
            for match in all_matches:
                p1_id, p2_id, score_1, score_2, m_type = match
                if score_1 is None or score_2 is None:
                    continue
                
                    # print(f"DEBUG: 检查比赛 {p1_id}({score_1}) vs {p2_id}({score_2})")
                
                # 检查这场比赛是否涉及当前选手和同分选手
                if p1_id == player_id:
                    # 当前选手是主队
                    for other_player in players_with_same_points:
                        if other_player['player_id'] == p2_id and other_player['player_id'] != player_id:
                            # print(f"DEBUG: 找到同分选手比赛: {player['name']}({player_id}) vs {other_player['name']}({p2_id})")
                            h2h_goals_for += score_1
                            h2h_goals_against += score_2
                            if score_1 > score_2:
                                h2h_points += 3
                                h2h_wins += 1
                                # print(f"DEBUG: {player['name']} 胜 {other_player['name']} ({score_1}-{score_2})")
                            elif score_1 == score_2:
                                h2h_points += 1
                                h2h_draws += 1
                                # print(f"DEBUG: {player['name']} 平 {other_player['name']} ({score_1}-{score_2})")
                            else:
                                h2h_losses += 1
                                # print(f"DEBUG: {player['name']} 负 {other_player['name']} ({score_1}-{score_2})")
                            break
                elif p2_id == player_id:
                    # 当前选手是客队
                    for other_player in players_with_same_points:
                        if other_player['player_id'] == p1_id and other_player['player_id'] != player_id:
                            # print(f"DEBUG: 找到同分选手比赛: {player['name']}({player_id}) vs {other_player['name']}({p1_id})")
                            h2h_goals_for += score_2
                            h2h_goals_against += score_1
                            if score_2 > score_1:
                                h2h_points += 3
                                h2h_wins += 1
                                # print(f"DEBUG: {player['name']} 胜 {other_player['name']} ({score_2}-{score_1})")
                            elif score_1 == score_2:
                                h2h_points += 1
                                h2h_draws += 1
                                # print(f"DEBUG: {player['name']} 平 {other_player['name']} ({score_1}-{score_2})")
                            else:
                                h2h_losses += 1
                                # print(f"DEBUG: {player['name']} 负 {other_player['name']} ({score_1}-{score_2})")
                            break
            
            # 保存胜负关系数据
            player['h2h_points'] = h2h_points
            player['h2h_wins'] = h2h_wins
            player['h2h_draws'] = h2h_draws
            player['h2h_losses'] = h2h_losses
            player['h2h_goals_for'] = h2h_goals_for
            player['h2h_goals_against'] = h2h_goals_against
            player['h2h_goal_difference'] = h2h_goals_for - h2h_goals_against
            
            # print(f"DEBUG: {player['name']} 对同分选手: {h2h_points}分 ({h2h_wins}胜{h2h_draws}平{h2h_losses}负), 净胜球:{player['h2h_goal_difference']}")
        
        # 按照胜负关系排序：积分 -> 相互胜负关系 -> 净胜球 -> 总进球
        def compare_h2h(player1, player2):
            # 1. 胜负关系积分
            if player1['h2h_points'] != player2['h2h_points']:
                return player2['h2h_points'] - player1['h2h_points']
            
            # 2. 胜负关系积分相同时，比较相互之间的胜负关系
            # print(f"DEBUG: 比较相互胜负关系: {player1['name']} vs {player2['name']}")
            
            # 查找两人之间的直接比赛
            for match in all_matches:
                p1_id, p2_id, score_1, score_2, m_type = match
                if score_1 is None or score_2 is None:
                    continue
                
                # 找到两人之间的比赛
                if (p1_id == player1['player_id'] and p2_id == player2['player_id']) or \
                   (p1_id == player2['player_id'] and p2_id == player1['player_id']):
                    # print(f"DEBUG: 找到直接比赛: {p1_id}({score_1}) vs {p2_id}({score_2})")
                    
                    if p1_id == player1['player_id']:
                        # player1是主队
                        if score_1 > score_2:
                            # print(f"DEBUG: {player1['name']} 胜 {player2['name']}")
                            return -1  # player1排在前面
                        elif score_2 > score_1:
                            # print(f"DEBUG: {player2['name']} 胜 {player1['name']}")
                            return 1   # player2排在前面
                        else:
                            # print(f"DEBUG: {player1['name']} 平 {player2['name']}")
                            break  # 平局，继续比较其他指标
                    else:
                        # player1是客队
                        if score_2 > score_1:
                            # print(f"DEBUG: {player1['name']} 胜 {player2['name']}")
                            return -1  # player1排在前面
                        elif score_1 > score_2:
                            # print(f"DEBUG: {player2['name']} 胜 {player1['name']}")
                            return 1   # player2排在前面
                        else:
                            # print(f"DEBUG: {player1['name']} 平 {player2['name']}")
                            break  # 平局，继续比较其他指标
            
            # 3. 相互胜负关系相同（平局或未交手），比较总净胜球
            if player1['goal_difference'] != player2['goal_difference']:
                return player2['goal_difference'] - player1['goal_difference']
            
            # 4. 净胜球相同，比较总进球
            if player1['goals_for'] != player2['goals_for']:
                return player2['goals_for'] - player1['goals_for']
            
            # 5. 所有指标都相同，按姓名排序
            if player1['name'] < player2['name']:
                return -1
            elif player1['name'] > player2['name']:
                return 1
            else:
                return 0
        
        from functools import cmp_to_key
        players_with_same_points.sort(key=cmp_to_key(compare_h2h))
        
        # print(f"DEBUG: 同积分选手排名完成")
        for i, player in enumerate(players_with_same_points):
            # print(f"DEBUG: 排名 {i+1}: {player['name']} (胜负关系积分:{player['h2h_points']}, 净胜球:{player['h2h_goal_difference']})")
            pass  # 添加pass语句以满足Python语法要求
        
        return players_with_same_points
    
    # 按积分分组，对同积分选手进行特殊排序
    from collections import defaultdict
    points_groups = defaultdict(list)
    
    for player in standings_list:
        points_groups[player['points']].append(player)
    
    # 重新排序
    final_standings = []
    for points in sorted(points_groups.keys(), reverse=True):
        group = points_groups[points]
        if len(group) == 1:
            # 只有一个选手，直接添加
            final_standings.extend(group)
        else:
            # 多个选手同积分，需要计算胜负关系
            ranked_group = calculate_same_points_ranking(group, result)
            final_standings.extend(ranked_group)
    
    standings_list = final_standings
    
    # print(f"DEBUG: 分组 {tg_id} 排名计算完成")
    for i, player in enumerate(standings_list):
        # print(f"DEBUG: 排名 {i+1}: {player['name']} (积分:{player['points']})")
        pass  # 添加pass语句以满足Python语法要求
    
    return standings_list

def calculate_total_group_rankings(t_id):
    """计算所有小组的总排名"""
    from sqlalchemy import text
    
    # 获取所有小组
    groups = get_tournament_groups(t_id)
    if not groups:
        return {}
    
    # 收集所有选手的排名数据
    all_standings = []
    for group in groups:
        group_standings = calculate_group_standings(t_id, group['tg_id'])
        for i, standing in enumerate(group_standings):
            standing['group_name'] = group['t_name']
            standing['group_rank'] = i + 1
            all_standings.append(standing)
    
    # 按组内排名分组，然后按排名顺序排序
    from collections import defaultdict
    rank_groups = defaultdict(list)
    
    # 获取所有比赛数据用于计算胜负关系
    all_matches_query = text("""
        SELECT player_1_id, player_2_id, player_1_score, player_2_score, m_type
        FROM matches
        WHERE t_id = :t_id AND m_type IN (1, 2, 3)
        AND player_1_score IS NOT NULL AND player_2_score IS NOT NULL
    """)
    
    all_matches_result = db.session.execute(all_matches_query, {'t_id': t_id}).fetchall()
    matches = []
    for match_row in all_matches_result:
        matches.append((match_row[0], match_row[1], match_row[2], match_row[3], match_row[4]))
    
    for player in all_standings:
        rank_groups[player['group_rank']].append(player)
    
    # 按排名顺序排序：第1名 → 第2名 → 第3名 → ...
    final_all_standings = []
    for rank in sorted(rank_groups.keys()):
        rank_players = rank_groups[rank]
        
        # 对同排名选手按积分 → 胜负关系 → 净胜分 → 总得分排序
        def compare_same_rank(player1, player2):
            # 1. 积分
            if player1['points'] != player2['points']:
                return player2['points'] - player1['points']
            
            # 2. 积分相同，先比较净胜分
            if player1['goal_difference'] != player2['goal_difference']:
                return player2['goal_difference'] - player1['goal_difference']
            
            # 3. 净胜分相同，比较内部胜负关系
            # 获取这两个选手之间的比赛记录
            h2h_result = calculate_head_to_head_result(player1['player_id'], player2['player_id'], matches)
            if h2h_result != 0:
                return -h2h_result  # 1表示player1胜，返回-1让player1排在前面
            
            # 4. 胜负关系相同（平局或未交手），比较总得分
            if player1['goals_for'] != player2['goals_for']:
                return player2['goals_for'] - player1['goals_for']
            
            # 5. 按姓名排序
            if player1['name'] < player2['name']:
                return -1
            elif player1['name'] > player2['name']:
                return 1
            else:
                return 0
        
        from functools import cmp_to_key
        rank_players.sort(key=cmp_to_key(compare_same_rank))
        final_all_standings.extend(rank_players)
    
    all_standings = final_all_standings
    
    # 分配总排名
    for i, standing in enumerate(all_standings):
        standing['total_rank'] = i + 1
    
    # 按小组分组返回
    result = {}
    for group in groups:
        result[group['tg_id']] = [s for s in all_standings if s['group_name'] == group['t_name']]
    
    return result

# 小组赛API端点
@app.route('/admin-secret/tournaments/set-group-stage', methods=['POST'])
def set_group_stage():
    """设置小组赛分组和选手分配"""
    if not session.get('admin_logged_in'):
        return jsonify({'success': False, 'message': '未授权访问'}), 403
    
    data = request.get_json()
    t_id = data.get('t_id')
    group_size = data.get('group_size')
    round_robin_type = data.get('round_robin_type', 'single')
    quarterfinal_format = data.get('quarterfinal_format')
    groups = data.get('groups', [])
    withdraw_players = data.get('withdraw_players', [])
    
    if not t_id or not group_size or not groups:
        return jsonify({'success': False, 'message': '缺少必要参数'}), 400
    
    try:
        # 获取赛事信息
        tournament = Tournament.query.get_or_404(t_id)
        
        # 计算分组信息
        group_info = calculate_group_info(tournament.player_count, group_size)
        if not group_info:
            return jsonify({'success': False, 'message': '无法计算分组信息'}), 400
        
        # 检查分组数是否超过26
        if group_info['groups_count'] > 26:
            return jsonify({'success': False, 'message': '分组数不能超过26个'}), 400
        
        # 生成组别名称
        group_names = generate_group_names(group_info['groups_count'])
        if not group_names:
            return jsonify({'success': False, 'message': '无法生成组别名称'}), 400
        
        # 清除现有的分组和比赛
        clear_tournament_groups_and_matches(t_id)
        
        # 创建新的分组
        create_tournament_groups(t_id, group_size, group_names)
        
        # 分配选手到分组
        for group_data in groups:
            group_number = group_data['groupNumber']
            player_ids = group_data['players']
            
            if group_number <= len(group_names):
                group_name = group_names[group_number - 1]
                assign_players_to_group(t_id, group_name, player_ids)
        
        # 生成比赛场次
        generate_group_matches(t_id, round_robin_type)
        
        # 处理退赛选手
        for withdraw_data in withdraw_players:
            player_id = withdraw_data['player_id']
            group_number = withdraw_data['group_number']
            
            if group_number <= len(group_names):
                group_name = group_names[group_number - 1]
                handle_player_withdraw(t_id, player_id, group_name)
        
        # 如果设置了1/4决赛格式，生成淘汰赛
        if quarterfinal_format and tournament.t_format in [1, 3]:
            if quarterfinal_format == 'direct':
                # 直接1/4决赛
                pass  # 将在小组赛完成后自动生成
            elif quarterfinal_format == 'qualifier':
                # 资格赛模式
                pass  # 将在小组赛完成后自动生成
        
        return jsonify({
            'success': True, 
            'message': f'成功创建{group_info["groups_count"]}个分组并分配选手',
            'group_info': group_info,
            'group_names': group_names
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'设置分组失败: {str(e)}'}), 500

@app.route('/admin-secret/tournaments/check-player-matches', methods=['POST'])
def check_player_matches():
    """检查选手是否在指定组有交手记录"""
    if not session.get('admin_logged_in'):
        return jsonify({'success': False, 'message': '未授权访问'}), 403
    
    data = request.get_json()
    player_id = data.get('player_id')
    group_id = data.get('group_id')
    tournament_id = data.get('tournament_id')
    
    if not all([player_id, group_id, tournament_id]):
        return jsonify({'success': False, 'message': '缺少必要参数'}), 400
    
    try:
        from sqlalchemy import text
        
        # 检查选手是否在指定组有交手记录
        matches_query = text("""
            SELECT COUNT(*) as match_count
            FROM matches m
            JOIN tg_players tgp1 ON m.player_1_id = tgp1.player_id
            JOIN tg_players tgp2 ON m.player_2_id = tgp2.player_id
            WHERE m.t_id = :tournament_id 
            AND m.m_type IN (1, 2, 3)
            AND (m.player_1_id = :player_id OR m.player_2_id = :player_id)
            AND tgp1.tg_id = :group_id AND tgp2.tg_id = :group_id
            AND (m.player_1_score IS NOT NULL AND m.player_2_score IS NOT NULL)
            AND NOT (m.player_1_score = 0 AND m.player_2_score = 0)
        """)
        
        result = db.session.execute(matches_query, {
            'tournament_id': tournament_id,
            'player_id': player_id,
            'group_id': group_id
        }).fetchone()
        
        has_matches = result[0] > 0 if result else False
        
        return jsonify({
            'success': True,
            'has_matches': has_matches,
            'match_count': result[0] if result else 0
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'检查失败: {str(e)}'}), 500

@app.route('/admin-secret/tournaments/<int:t_id>/assign-player', methods=['POST'])
def assign_player_to_group_api(t_id):
    if not session.get('admin_logged_in'):
        return jsonify({'success': False, 'message': '未授权访问'}), 403
    
    data = request.get_json()
    player_id = data.get('player_id')
    tg_id = data.get('tg_id')
    
    if not player_id or not tg_id:
        return jsonify({'success': False, 'message': '缺少必要参数'}), 400
    
    try:
        assign_player_to_group(player_id, tg_id)
        return jsonify({'success': True, 'message': '选手分配成功'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'分配失败: {str(e)}'}), 500

@app.route('/admin-secret/tournament/<int:t_id>/create-groups', methods=['POST'])
@admin_required
def create_tournament_groups_api(t_id):
    """创建赛事分组API"""
    data = request.get_json()
    group_size = data.get('group_size')
    round_robin_type = data.get('round_robin_type', 'single')
    
    if not group_size:
        return jsonify({'success': False, 'error': '缺少必要参数'}), 400
    
    try:
        # 获取赛事信息
        tournament = Tournament.query.get_or_404(t_id)
        
        # 计算分组信息
        group_info = calculate_group_info(tournament.player_count, group_size)
        if not group_info:
            return jsonify({'success': False, 'error': '无法计算分组信息'}), 400
        
        # 检查分组数是否超过26
        if group_info['groups_count'] > 26:
            return jsonify({'success': False, 'error': '分组数不能超过26个'}), 400
        
        # 生成组别名称
        group_names = generate_group_names(group_info['groups_count'])
        if not group_names:
            return jsonify({'success': False, 'error': '无法生成组别名称'}), 400
        
        # 清除现有的分组和比赛
        clear_tournament_groups_and_matches(t_id)
        
        # 创建新的分组
        create_tournament_groups(t_id, group_size, group_names)
        
        return jsonify({
            'success': True, 
            'message': f'成功创建{group_info["groups_count"]}个分组',
            'group_info': group_info,
            'group_names': group_names
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'创建分组失败: {str(e)}'}), 500

@app.route('/admin-secret/tournament/<int:t_id>/assign-players', methods=['POST'])
@admin_required
def assign_players_to_groups_api(t_id):
    """分配选手到分组API"""
    data = request.get_json()
    groupings = data.get('groupings', [])
    
    # 调试：输出接收到的数据
    print(f"接收到分组数据: {groupings}")
    
    if not groupings:
        return jsonify({'success': False, 'error': '缺少分组数据'}), 400
    
    try:
        # 分配选手到分组
        for group_data in groupings:
            group_name = group_data['group_name']
            players = group_data['players']
            player_ids = [player['player_id'] for player in players]
            
            print(f"尝试分配选手到分组: {group_name}, 选手IDs: {player_ids}")
            
            success = assign_players_to_group(t_id, group_name, player_ids)
            if not success:
                raise Exception(f"无法找到分组: {group_name}")
        
        # 生成比赛场次
        round_robin_type = 'single'  # 默认单循环，可以根据需要调整
        generate_group_matches(t_id, round_robin_type)
        
        return jsonify({
            'success': True, 
            'message': '选手分组成功'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'选手分组失败: {str(e)}'}), 500

@app.route('/admin-secret/tournament/<int:t_id>/get-players', methods=['GET'])
@admin_required
def get_tournament_players_api(t_id):
    """获取赛事可用选手API"""
    try:
        from sqlalchemy import text
        
        # 获取所有可用选手
        players_query = text("""
            SELECT p.player_id, p.name
            FROM players p
            WHERE p.status IN (1, 2)
            ORDER BY p.name
        """)
        
        players_result = db.session.execute(players_query).fetchall()
        players = [{'player_id': row[0], 'name': row[1]} for row in players_result]
        
        return jsonify({
            'success': True,
            'players': players
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'获取选手数据失败: {str(e)}'}), 500

@app.route('/admin-secret/tournaments/set-participants', methods=['POST'])
@admin_required
def set_tournament_participants():
    """设置大赛的参赛选手"""
    try:
        from sqlalchemy import text
        
        print("=== set_tournament_participants 开始 ===")
        data = request.get_json()
        print(f"接收到的数据: {data}")
        
        t_id = data.get('t_id')
        player_ids = data.get('player_ids', [])
        
        print(f"t_id: {t_id}, player_ids: {player_ids}")
        
        if not t_id:
            print("错误：缺少赛事ID")
            return jsonify({'success': False, 'error': '缺少赛事ID'})
        
        if not player_ids or len(player_ids) < 2:
            print("错误：参赛选手数量不足")
            return jsonify({'success': False, 'error': '参赛选手数量不足'})
        
        # 检查赛事是否存在且为大赛
        tournament = db.session.get(Tournament, t_id)
        print(f"查询到的赛事: {tournament}")
        
        if not tournament:
            print("错误：赛事不存在")
            return jsonify({'success': False, 'error': '赛事不存在'})
        
        # if tournament.type != 1:
        #     print(f"错误：赛事类型不是大赛，当前类型: {tournament.type}")
        #     return jsonify({'success': False, 'error': '只有大赛才能使用此功能'})
        
        if tournament.t_format not in [4, 5, 6]:
            print(f"错误：赛事格式不支持，当前格式: {tournament.t_format}")
            return jsonify({'success': False, 'error': '只有单循环/双循环赛/苏超赛制才能使用此功能'})
        
        print("开始清空现有排名数据...")
        # 清空现有排名数据
        delete_rankings_query = text("DELETE FROM rankings WHERE t_id = :t_id")
        db.session.execute(delete_rankings_query, {'t_id': t_id})
        
        print("开始插入新的排名数据...")
        # 插入新的排名数据
        for i, player_id in enumerate(player_ids):
            print(f"插入选手 {i+1}: player_id={player_id}")
            insert_ranking_query = text("""
                INSERT INTO rankings (t_id, player_id, ranks, scores)
                VALUES (:t_id, :player_id, :ranks, 0)
            """)
            db.session.execute(insert_ranking_query, {
                't_id': t_id,
                'player_id': player_id,
                'ranks': i + 1
            })
        
        print("提交数据库事务...")
        db.session.commit()
        
        # 自动生成场次
        print("开始自动生成场次...")
        try:
            # 获取所有参赛选手
            players_query = text("""
                SELECT DISTINCT p.player_id, p.name
                FROM players p
                JOIN rankings r ON p.player_id = r.player_id
                WHERE r.t_id = :t_id
                ORDER BY p.name
            """)
            
            players_result = db.session.execute(players_query, {'t_id': t_id}).fetchall()
            players = [{'player_id': row[0], 'name': row[1]} for row in players_result]
            print(f"获取到 {len(players)} 名参赛选手")
            
            if len(players) >= 2:
                # 清空现有场次
                print("清空现有场次...")
                delete_query = text("DELETE FROM matches WHERE t_id = :t_id")
                delete_result = db.session.execute(delete_query, {'t_id': t_id})
                print(f"删除了 {delete_result.rowcount} 场现有场次")
                
                # 根据赛事格式生成场次
                new_matches = []
                print(f"赛事格式: {tournament.t_format}")
                
                if tournament.t_format == 4:  # 单循环赛
                    print("生成单循环赛场次...")
                    # 生成单循环赛场次
                    for i in range(len(players)):
                        for j in range(i + 1, len(players)):
                            player1 = players[i]
                            player2 = players[j]
                            new_matches.append({
                                'player_1_id': player1['player_id'],
                                'player_2_id': player2['player_id'],
                                'm_type': 1  # 小组赛（普通）
                            })
                elif tournament.t_format == 5:  # 双循环赛
                    print("生成双循环赛场次...")
                    # 生成双循环赛场次
                    # 主场比赛
                    for i in range(len(players)):
                        for j in range(i + 1, len(players)):
                            player1 = players[i]
                            player2 = players[j]
                            new_matches.append({
                                'player_1_id': player1['player_id'],
                                'player_2_id': player2['player_id'],
                                'm_type': 2  # 小组赛（主）
                            })
                    # 客场比赛
                    for i in range(len(players)):
                        for j in range(i + 1, len(players)):
                            player1 = players[i]
                            player2 = players[j]
                            new_matches.append({
                                'player_1_id': player1['player_id'],
                                'player_2_id': player2['player_id'],
                                'm_type': 3  # 小组赛（客）
                            })
                elif tournament.t_format == 6:  # 苏超赛制
                    # 苏超赛制不在这里生成场次，需要用户手动选择主客场
                    print("苏超赛制需要用户手动选择主客场，不自动生成场次")
                    new_matches = []
                
                print(f"准备插入 {len(new_matches)} 场新场次")
                
                # 插入新场次
                for i, match in enumerate(new_matches):
                    try:
                        insert_query = text("""
                            INSERT INTO matches (t_id, player_1_id, player_2_id, player_1_score, player_2_score, m_type)
                            VALUES (:t_id, :player_1_id, :player_2_id, -1, -1, :m_type)
                        """)
                        db.session.execute(insert_query, {
                            't_id': t_id,
                            'player_1_id': match['player_1_id'],
                            'player_2_id': match['player_2_id'],
                            'm_type': match['m_type']
                        })
                        if (i + 1) % 10 == 0:  # 每10场打印一次进度
                            print(f"已插入 {i + 1} 场次...")
                    except Exception as match_error:
                        print(f"插入第 {i + 1} 场次时出错: {str(match_error)}")
                        raise match_error
                
                print("提交数据库事务...")
                db.session.commit()
                print(f"成功生成 {len(new_matches)} 场次")
            else:
                print("选手数量不足，跳过场次生成")
                
        except Exception as e:
            print(f"生成场次时出错: {str(e)}")
            import traceback
            traceback.print_exc()
            db.session.rollback()
            # 不抛出异常，因为选手设置已经成功
        
        print("=== set_tournament_participants 成功 ===")
        return jsonify({
            'success': True, 
            'message': f'成功设置{len(player_ids)}名参赛选手并生成单循环赛场次'
        })
        
    except Exception as e:
        print(f"=== set_tournament_participants 异常: {str(e)} ===")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/admin-secret/tournaments/generate-jiangsu-premier-league-matches', methods=['POST'])
@admin_required
def generate_jiangsu_premier_league_matches():
    """为苏超赛制生成场次"""
    try:
        from sqlalchemy import text
        
        data = request.get_json()
        t_id = data.get('t_id')
        home_away_data = data.get('home_away_data')
        
        if not t_id or not home_away_data:
            return jsonify({'success': False, 'error': '缺少必要参数'})
        
        # 检查赛事是否存在且为苏超赛制
        tournament = db.session.get(Tournament, t_id)
        if not tournament:
            return jsonify({'success': False, 'error': '赛事不存在'})
        
        # if tournament.type != 1:
        #     return jsonify({'success': False, 'error': '只有大赛才能使用此功能'})
        
        if tournament.t_format != 6:
            return jsonify({'success': False, 'error': '只有苏超赛制才能使用此功能'})
        
        # 获取所有参赛选手ID
        players_query = text("""
            SELECT DISTINCT player_id
            FROM rankings
            WHERE t_id = :t_id
            ORDER BY player_id
        """)
        all_player_ids = [row[0] for row in db.session.execute(players_query, {'t_id': t_id}).fetchall()]
        
        player_count = len(all_player_ids)
        if player_count < 2:
            return jsonify({'success': False, 'error': '参赛选手不足2人'})
        
        # 验证主客场数据
        expected_home_matches = (player_count - 1) // 2
        
        for player_id, home_opponents in home_away_data.items():
            if len(home_opponents) != expected_home_matches:
                return jsonify({'success': False, 'error': f'选手 {player_id} 的主场对手数量不正确，应为{expected_home_matches}个'})
        
        # 检查主客场分配的对称性
        for player_id, home_opponents in home_away_data.items():
            for opponent_id in home_opponents:
                if home_away_data.get(str(opponent_id), []).count(int(player_id)) > 0:
                    return jsonify({'success': False, 'error': f'主客场分配冲突：选手 {player_id} 和 {opponent_id} 都选择了对方作为主场对手'})
        
        # 清空现有场次
        delete_query = text("DELETE FROM matches WHERE t_id = :t_id")
        db.session.execute(delete_query, {'t_id': t_id})
        
        # 实现苏超赛制逻辑
        new_matches = []
        processed_pairs = set()
        
        # 统计每个选手被选为主场对手的次数
        home_selected_count = {player_id: 0 for player_id in all_player_ids}
        
        # 处理用户选择的主场对手
        for player_id, home_opponents in home_away_data.items():
            player_id = int(player_id)
            
            # 生成主场场次（该选手作为player_1）
            for opponent_id in home_opponents:
                pair = tuple(sorted([player_id, opponent_id]))
                if pair not in processed_pairs:
                    new_matches.append({
                        'player_1_id': player_id,
                        'player_2_id': opponent_id,
                        'm_type': 2  # 小组赛（主）
                    })
                    processed_pairs.add(pair)
                    home_selected_count[opponent_id] += 1
        
        # 自动分配剩余场次
        while len(processed_pairs) < player_count * (player_count - 1) // 2:
            # 找到已经被(n-1)/2个其他选手选为主场对手的选手
            candidates = [player_id for player_id in all_player_ids 
                         if home_selected_count[player_id] == expected_home_matches]
            
            if not candidates:
                # 如果没有符合条件的选手，选择被选次数最少的选手
                min_count = min(home_selected_count.values())
                candidates = [player_id for player_id in all_player_ids 
                             if home_selected_count[player_id] == min_count]
            
            # 选择第一个候选选手
            current_player = candidates[0]
            
            # 找到该选手还没有比赛的对手
            played_opponents = set()
            for pair in processed_pairs:
                if current_player in pair:
                    played_opponents.add(pair[0] if pair[1] == current_player else pair[1])
            
            remaining_opponents = set(all_player_ids) - {current_player} - played_opponents
            
            # 为该选手自动分配剩余场次（作为主场）
            for opponent_id in remaining_opponents:
                pair = tuple(sorted([current_player, opponent_id]))
                if pair not in processed_pairs:
                    new_matches.append({
                        'player_1_id': current_player,
                        'player_2_id': opponent_id,
                        'm_type': 2  # 小组赛（主）
                    })
                    processed_pairs.add(pair)
                    home_selected_count[opponent_id] += 1
                    break  # 一次只分配一场
        
        # 插入新场次
        for match in new_matches:
            insert_query = text("""
                INSERT INTO matches (t_id, player_1_id, player_2_id, player_1_score, player_2_score, m_type)
                VALUES (:t_id, :player_1_id, :player_2_id, -1, -1, :m_type)
            """)
            db.session.execute(insert_query, {
                't_id': t_id,
                'player_1_id': match['player_1_id'],
                'player_2_id': match['player_2_id'],
                'm_type': match['m_type']
            })
        
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': f'成功生成{len(new_matches)}场苏超赛制比赛'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/admin-secret/tournaments/generate-jiangsu-premier-league-finals', methods=['POST'])
@admin_required
def generate_jiangsu_premier_league_finals():
    """为苏超赛制生成淘汰赛"""
    try:
        from sqlalchemy import text
        
        data = request.get_json()
        t_id = data.get('t_id')
        knockout_type = data.get('knockout_type', 'finals')
        
        if not t_id:
            return jsonify({'success': False, 'error': '缺少赛事ID'})
        
        # 检查赛事是否存在且为苏超赛制
        tournament = db.session.get(Tournament, t_id)
        if not tournament:
            return jsonify({'success': False, 'error': '赛事不存在'})
        
        if tournament.type != 1:
            return jsonify({'success': False, 'error': '只有大赛才能使用此功能'})
        
        if tournament.t_format != 6:
            return jsonify({'success': False, 'error': '只有苏超赛制才能使用此功能'})
        
        # 检查循环赛是否完成
        if not check_round_robin_complete(t_id):
            return jsonify({'success': False, 'error': '循环赛未完成，无法生成淘汰赛'})
        
        # 检查淘汰赛是否已存在
        knockout_query = text("""
            SELECT COUNT(*) FROM matches 
            WHERE t_id = :t_id AND m_type IN (9, 10, 11, 12)
        """)
        knockout_count = db.session.execute(knockout_query, {'t_id': t_id}).fetchone()[0]
        
        if knockout_count > 0:
            return jsonify({'success': False, 'error': '淘汰赛已存在'})
        
        # 获取循环赛排名
        round_robin_standings = calculate_round_robin_standings(t_id)
        
        if len(round_robin_standings) < 4:
            return jsonify({'success': False, 'error': '参赛选手不足4人，无法生成淘汰赛'})
        
        # 清空现有淘汰赛场次
        delete_knockout_query = text("DELETE FROM matches WHERE t_id = :t_id AND m_type IN (9, 10, 11, 12)")
        db.session.execute(delete_knockout_query, {'t_id': t_id})
        
        knockout_matches = []
        
        if knockout_type == 'finals':
            # 直接生成金牌赛和铜牌赛
            # 金牌赛：第1名 vs 第2名
            gold_match = Match(
                t_id=t_id,
                m_type=12,  # 金牌赛
                player_1_id=round_robin_standings[0]['player_id'],  # 第1名
                player_2_id=round_robin_standings[1]['player_id'],  # 第2名
                player_1_score=-1,
                player_2_score=-1
            )
            knockout_matches.append(gold_match)
            
            # 铜牌赛：第3名 vs 第4名
            bronze_match = Match(
                t_id=t_id,
                m_type=11,  # 铜牌赛
                player_1_id=round_robin_standings[2]['player_id'],  # 第3名
                player_2_id=round_robin_standings[3]['player_id'],  # 第4名
                player_1_score=-1,
                player_2_score=-1
            )
            knockout_matches.append(bronze_match)
            
        elif knockout_type == 'semifinals':
            # 生成半决赛资格赛
            if len(round_robin_standings) < 6:
                return jsonify({'success': False, 'error': '参赛选手不足6人，无法生成半决赛资格赛'})
            
            # 上半区资格赛：第4 vs 第5
            qualifier1 = Match(
                t_id=t_id,
                m_type=9,  # 半决赛资格赛
                player_1_id=round_robin_standings[3]['player_id'],  # 第4名
                player_2_id=round_robin_standings[4]['player_id'],  # 第5名
                player_1_score=-1,
                player_2_score=-1
            )
            knockout_matches.append(qualifier1)
            
            # 下半区资格赛：第3 vs 第6
            qualifier2 = Match(
                t_id=t_id,
                m_type=9,  # 半决赛资格赛
                player_1_id=round_robin_standings[2]['player_id'],  # 第3名
                player_2_id=round_robin_standings[5]['player_id'],  # 第6名
                player_1_score=-1,
                player_2_score=-1
            )
            knockout_matches.append(qualifier2)
        
        # 插入淘汰赛场次
        for match in knockout_matches:
            db.session.add(match)
        
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': f'成功生成{len(knockout_matches)}场{"决赛" if knockout_type == "finals" else "半决赛资格赛"}'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/admin-secret/tournaments/generate-round-robin-matches', methods=['POST'])
@admin_required
def generate_round_robin_matches():
    """为大赛单循环/双循环赛生成场次"""
    try:
        data = request.get_json()
        t_id = data.get('t_id')
        is_double_round_robin = data.get('is_double_round_robin', False)
        
        if not t_id:
            return jsonify({'success': False, 'error': '缺少赛事ID'})
        
        # 检查赛事是否存在且为大赛
        tournament = db.session.get(Tournament, t_id)
        if not tournament:
            return jsonify({'success': False, 'error': '赛事不存在'})
        
        if tournament.type != 1:
            return jsonify({'success': False, 'error': '只有大赛才能使用此功能'})
        
        if tournament.t_format not in [4, 5, 6]:
            return jsonify({'success': False, 'error': '只有单循环/双循环赛/苏超赛制才能使用此功能'})
        
        # 获取所有参赛选手
        players_query = text("""
            SELECT DISTINCT p.player_id, p.name
            FROM players p
            JOIN rankings r ON p.player_id = r.player_id
            WHERE r.t_id = :t_id
            ORDER BY p.name
        """)
        
        players_result = db.session.execute(players_query, {'t_id': t_id}).fetchall()
        players = [{'player_id': row[0], 'name': row[1]} for row in players_result]
        
        if len(players) < 2:
            return jsonify({'success': False, 'error': '参赛选手数量不足，无法生成比赛'})
        
        # 清空现有场次
        delete_query = text("DELETE FROM matches WHERE t_id = :t_id")
        db.session.execute(delete_query, {'t_id': t_id})
        
        # 生成新的场次
        new_matches = []
        
        if tournament.t_format == 6:  # 苏超赛制
            return jsonify({'success': False, 'error': '苏超赛制请使用专门的主客场选择功能'})
        elif is_double_round_robin:
            # 双循环：先生成所有主场比赛
            for i in range(len(players)):
                for j in range(i + 1, len(players)):
                    player1 = players[i]
                    player2 = players[j]
                    new_matches.append({
                        'player_1_id': player1['player_id'],
                        'player_2_id': player2['player_id'],
                        'm_type': 2  # 小组赛（主）
                    })
            
            # 再生成所有客场比赛
            for i in range(len(players)):
                for j in range(i + 1, len(players)):
                    player1 = players[i]
                    player2 = players[j]
                    new_matches.append({
                        'player_1_id': player1['player_id'],
                        'player_2_id': player2['player_id'],
                        'm_type': 3  # 小组赛（客）
                    })
        else:
            # 单循环：每对选手比赛一次
            for i in range(len(players)):
                for j in range(i + 1, len(players)):
                    player1 = players[i]
                    player2 = players[j]
                    new_matches.append({
                        'player_1_id': player1['player_id'],
                        'player_2_id': player2['player_id'],
                        'm_type': 1  # 小组赛（普通）
                    })
        
        # 插入新场次
        for match in new_matches:
            insert_query = text("""
                INSERT INTO matches (t_id, player_1_id, player_2_id, player_1_score, player_2_score, m_type)
                VALUES (:t_id, :player_1_id, :player_2_id, 0, 0, :m_type)
            """)
            db.session.execute(insert_query, {
                't_id': t_id,
                'player_1_id': match['player_1_id'],
                'player_2_id': match['player_2_id'],
                'm_type': match['m_type']
            })
        
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': f'成功生成{len(new_matches)}场{"双循环" if is_double_round_robin else "单循环"}赛'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/admin-secret/tournaments/clear-all-matches', methods=['POST'])
@admin_required
def clear_all_matches():
    """清空所有场次"""
    try:
        data = request.get_json()
        t_id = data.get('t_id')
        
        if not t_id:
            return jsonify({'success': False, 'error': '缺少赛事ID'})
        
        # 检查赛事是否存在且为大赛
        tournament = db.session.get(Tournament, t_id)
        if not tournament:
            return jsonify({'success': False, 'error': '赛事不存在'})
        
        if tournament.type != 1:
            return jsonify({'success': False, 'error': '只有大赛才能使用此功能'})
        
        # 清空所有场次
        delete_query = text("DELETE FROM matches WHERE t_id = :t_id")
        result = db.session.execute(delete_query, {'t_id': t_id})
        deleted_count = result.rowcount
        
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': f'成功清空{deleted_count}场次'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/admin-secret/tournaments/<int:t_id>/generate-matches', methods=['POST'])
def generate_group_matches_api(t_id):
    if not session.get('admin_logged_in'):
        return jsonify({'success': False, 'message': '未授权访问'}), 403
    
    data = request.get_json()
    is_double_round_robin = data.get('is_double_round_robin', False)
    
    try:
        # 获取所有分组
        groups = get_tournament_groups(t_id)
        if not groups:
            return jsonify({'success': False, 'message': '没有找到分组'}), 400
        
        # 检查每个分组是否有选手
        for group in groups:
            players = get_group_players(group['tg_id'])
            if len(players) < 2:
                return jsonify({'success': False, 'message': f'{group["t_name"]}组选手数量不足，无法生成比赛'}), 400
        
        # 为每个分组生成比赛
        for group in groups:
            generate_group_round_robin_matches(t_id, group['tg_id'], is_double_round_robin)
        
        return jsonify({'success': True, 'message': '比赛生成成功'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'生成比赛失败: {str(e)}'}), 500

@app.route('/player/<int:player_id>')
def player_view(player_id):
    p = Player.query.get_or_404(player_id)
    # matches involving this player
    matches = Match.query.filter((Match.player_1_id == player_id) | (Match.player_2_id == player_id)).all()
    
    # 为每个比赛添加序号信息
    for match in matches:
        if match.tournament:
            # 使用SQL视图获取该届次的序号
            from sqlalchemy import text
            view_query = text("""
                SELECT type_session_number
                FROM tournament_session_view
                WHERE t_id = :t_id
            """)
            
            result = db.session.execute(view_query, {'t_id': match.tournament.t_id})
            row = result.fetchone()
            if row:
                match.tournament.type_session_number = row.type_session_number
            else:
                match.tournament.type_session_number = None
    
    # 计算该选手的总积分和排名
    player_rankings = calculate_player_total_scores()
    player_stats = None
    for player_data in player_rankings:
        if player_data['player_id'] == player_id:
            player_stats = player_data
            break
    
    # 获取该选手的历届排名和积分
    from sqlalchemy import text
    history_query = text("""
        SELECT t.t_id, t.type, s.year, tsv.type_session_number, r.ranks, r.scores
        FROM rankings r
        JOIN tournament t ON r.t_id = t.t_id
        JOIN seasons s ON t.season_id = s.season_id
        JOIN tournament_session_view tsv ON t.t_id = tsv.t_id
        WHERE r.player_id = :player_id 
        AND t.status = 1
        AND r.scores IS NOT NULL
        ORDER BY s.year DESC, tsv.type_session_number DESC
    """)
    
    result = db.session.execute(history_query, {'player_id': player_id})
    tournament_history = result.fetchall()
    
    # 计算该选手最近20届比赛中的第10高分
    recent_20_scores = []
    for t_id, t_type, year, session_num, ranks, scores in tournament_history[:20]:
        if scores is not None:
            recent_20_scores.append(scores)
    
    # 找到第10高分
    tenth_highest_score = None
    if len(recent_20_scores) >= 10:
        recent_20_scores.sort(reverse=True)
        tenth_highest_score = recent_20_scores[9]  # 第10高分（索引9）
    
    # 获取该选手的奖牌统计
    medal_stats = calculate_medal_standings()
    player_medal_stats = medal_stats.get(player_id, {
        'major': {'gold': 0, 'silver': 0, 'bronze': 0},
        'minor': {'gold': 0, 'silver': 0, 'bronze': 0},
        'final': {'gold': 0, 'silver': 0, 'bronze': 0}
    })
    
    return render_template('player.html', 
                         player=p, 
                         matches=matches, 
                         player_stats=player_stats, 
                         tournament_history=tournament_history,
                         player_medal_stats=player_medal_stats,
                         tenth_highest_score=tenth_highest_score)


@app.route('/api/matches/<int:t_id>')
def api_matches(t_id):
    matches = Match.query.filter_by(t_id=t_id).all()
    return jsonify([m.to_dict() for m in matches])


# 管理后台（隐藏路由，不在站点导航中公开）
@app.route('/admin-secret')
@admin_required
def admin_index():
    managers = Manager.query.all()
    players = Player.query.order_by(Player.name).all()
    
    # 计算选手总积分排名
    player_rankings = calculate_player_total_scores()
    
    # 创建积分排名字典，方便查找
    ranking_dict = {player_data['player_id']: player_data for player_data in player_rankings}
    
    # 为每个选手添加积分排名信息
    for player in players:
        if player.player_id in ranking_dict:
            player.rank = ranking_dict[player.player_id]['rank']
            player.total_score = ranking_dict[player.player_id]['total_score']
            player.baseline_score = ranking_dict[player.player_id]['baseline_score']
            player.major_count = ranking_dict[player.player_id]['major_count']
            player.minor_count = ranking_dict[player.player_id]['minor_count']
            player.total_count = ranking_dict[player.player_id]['total_count']
        else:
            player.rank = None
            player.total_score = 0
            player.baseline_score = 0
            player.major_count = 0
            player.minor_count = 0
            player.total_count = 0
    
    # group players by status for display: show status=1 first, then 2, then 3
    # 对于参与排名的选手，按排名升序排列
    players_grouped = {
        1: sorted([p for p in players if getattr(p, 'status', 1) == 1], key=lambda x: x.rank or 999),
        2: [p for p in players if getattr(p, 'status', 1) == 2],
        3: [p for p in players if getattr(p, 'status', 1) == 3],
    }
    
    # 使用SQL视图获取带序号的届次数据
    from sqlalchemy import text
    view_query = text("""
        SELECT t.t_id, t.season_id, s.year, t.type, t.player_count, t.t_format,
               ts.type_session_number
        FROM tournament t
        JOIN seasons s ON t.season_id = s.season_id
        JOIN tournament_session_view ts ON t.t_id = ts.t_id
        ORDER BY s.year DESC, t.type, t.t_id
    """)
    
    result = db.session.execute(view_query)
    tournaments_data = result.fetchall()
    
    # 将查询结果转换为对象列表
    tournaments = []
    for row in tournaments_data:
        tournament = db.session.get(Tournament, row.t_id)
        tournament.type_session_number = row.type_session_number
        tournaments.append(tournament)
    
    seasons = Season.query.order_by(Season.year.desc()).all()
    
    # 获取所有用户
    users = User.query.order_by(User.created_at.desc()).all()
    
    return render_template('admin/index.html', managers=managers, players=players, players_grouped=players_grouped, tournaments=tournaments, seasons=seasons, users=users)


@app.route('/admin-secret/managers/add', methods=['GET', 'POST'])
@admin_required
def admin_add_manager():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        m = Manager(username=username)
        m.set_password(password)
        db.session.add(m)
        commit_with_retry()
        flash('管理员已添加')
        return redirect(url_for('admin_index'))
    return render_template('admin/add_manager.html')


@app.route('/admin-secret/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        # 检查是否已登录普通用户
        if session.get('user_logged_in'):
            flash('普通用户已登录，请先退出普通用户登录')
            return render_template('admin/login.html')
        
        m = Manager.query.filter_by(username=username).first()
        if m and m.check_password(password):
            session['admin_logged_in'] = True
            session['admin_username'] = username
            flash('登录成功')
            return redirect(url_for('admin_index'))
        flash('用户名或密码错误')
    return render_template('admin/login.html')


@app.route('/admin-secret/register', methods=['GET', 'POST'])
def admin_register():
    # allow open registration only if no manager exists, otherwise require login
    has_manager = Manager.query.first() is not None
    if has_manager and not session.get('admin_logged_in'):
        flash('已存在管理员，请先登录。')
        return redirect(url_for('admin_login'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        m = Manager(username=username)
        m.set_password(password)
        db.session.add(m)
        commit_with_retry()
        flash('注册成功')
        return redirect(url_for('admin_login'))
    return render_template('admin/register.html')


@app.route('/admin-secret/logout')
def admin_logout():
    session.clear()
    return redirect(url_for('index'))


# Player CRUD
@app.route('/admin-secret/players/add', methods=['GET', 'POST'])
@admin_required
def admin_add_player():
    if request.method == 'POST':
        name = request.form['name']
        status = int(request.form.get('status') or 1)
        p = Player(name=name, status=status)
        db.session.add(p)
        commit_with_retry()
        flash('选手已添加')
        return redirect(url_for('admin_index'))
    return render_template('admin/add_player.html')


@app.route('/admin-secret/players/<int:player_id>/edit', methods=['GET', 'POST'])
@admin_required
def admin_edit_player(player_id):
    p = Player.query.get_or_404(player_id)
    if request.method == 'POST':
        name = request.form.get('name')
        if not name:
            flash('缺少姓名字段，未保存')
            return redirect(request.url)
        p.name = name
        p.status = int(request.form.get('status') or p.status or 1)
        commit_with_retry()
        flash('已更新')
        return redirect(url_for('admin_index'))
    return render_template('admin/edit_player.html', player=p)


@app.route('/admin-secret/players/<int:player_id>/delete', methods=['POST'])
@admin_required
def admin_delete_player(player_id):
    p = Player.query.get_or_404(player_id)
    db.session.delete(p)
    commit_with_retry()
    flash('已删除')
    return redirect(url_for('admin_index'))


# Season CRUD
@app.route('/admin-secret/seasons/add', methods=['GET', 'POST'])
@admin_required
def admin_add_season():
    if request.method == 'POST':
        year = request.form['year']
        s = Season(year=year)
        db.session.add(s)
        commit_with_retry()
        flash('赛季已添加')
        return redirect(url_for('admin_index'))
    return render_template('admin/add_season.html')


@app.route('/admin-secret/seasons/<int:season_id>/delete', methods=['POST'])
@admin_required
def admin_delete_season(season_id):
    s = Season.query.get_or_404(season_id)
    db.session.delete(s)
    commit_with_retry()
    flash('赛季已删除')
    return redirect(url_for('admin_index'))


@app.route('/admin-secret/tournaments/add', methods=['GET', 'POST'])
@admin_required
def admin_add_tournament():
    if request.method == 'POST':
        try:
            season_id = int(request.form['season_id'])
            t_type = int(request.form.get('t_type', 1))
            player_count = int(request.form.get('player_count') or 0)
            t_format = int(request.form.get('t_format') or 0)
            signup_deadline_str = request.form.get('signup_deadline')
            
            print(f"收到表单数据: season_id={season_id}, t_type={t_type}, player_count={player_count}, t_format={t_format}, signup_deadline={signup_deadline_str}")
            
            # 验证赛季是否存在
            season = db.session.get(Season, season_id)
            if not season:
                flash(f'错误: 赛季ID {season_id} 不存在')
                return redirect(url_for('admin_index'))
            
            # 验证双败淘汰赛的人数限制
            if t_format == 7:  # 双败淘汰赛
                if not is_power_of_two(player_count) or player_count < 4:
                    flash('错误: 双败淘汰赛需要2的幂次方人数（4, 8, 16, 32）')
                    return redirect(url_for('admin_add_tournament'))
                
                # 检查数据库中的选手数量
                total_players = db.session.query(Player).filter(Player.status.in_([1, 2])).count()
                if player_count > total_players:
                    flash(f'错误: 参赛人数不能超过数据库中的选手数量（{total_players}）')
                    return redirect(url_for('admin_add_tournament'))
            
            t = Tournament(season_id=season_id, type=t_type, player_count=player_count, t_format=t_format)
            db.session.add(t)
            
            # 处理报名截止时间
            signup_deadline_str = request.form.get('signup_deadline')
            if signup_deadline_str:
                from datetime import datetime
                try:
                    # 直接设置tournament的signup_deadline字段
                    t.signup_deadline = signup_deadline_str
                except ValueError:
                    flash('报名截止时间格式错误')
                    return redirect(url_for('admin_index'))
            
            try:
                commit_with_retry()
                new_id = t.t_id
                print(f"SQLAlchemy插入成功，新ID: {new_id}")
            except Exception as e:
                # fallback: use sqlite3 to insert directly if SQLAlchemy has issues with schema/connection
                import sqlite3, os
                DB = os.path.join(os.path.dirname(__file__), 'curling_masters.db')
                conn = sqlite3.connect(DB)
                cur = conn.cursor()
                cur.execute('INSERT INTO tournament (season_id, type, player_count, t_format) VALUES (?, ?, ?, ?)', (season_id, t_type, player_count, t_format))
                conn.commit()
                new_id = cur.lastrowid
                conn.close()
                print(f"使用fallback插入，错误: {e}")
            
            flash('单届比赛已添加')
            # Safely redirect to rankings page if we have a new_id; fall back to admin index
            # Prefer direct path string to avoid url_for build issues when DB/endpoint state is unexpected
            try:
                if new_id:
                    return redirect(f'/admin-secret/tournaments/{int(new_id)}/rankings')
            except Exception:
                # fall back
                pass
            return redirect(url_for('admin_index'))
                
        except Exception as e:
            print(f"添加届次时发生错误: {e}")
            flash(f'添加届次时发生错误: {str(e)}')
            return redirect(url_for('admin_index'))
    
    seasons = Season.query.order_by(Season.year.desc()).all()
    # 支持从URL参数预选赛季
    pre_season_id = request.args.get('season_id', type=int)
    return render_template('admin/add_tournament.html', seasons=seasons, pre_season_id=pre_season_id)


@app.route('/admin-secret/tournaments/<int:t_id>/rankings', methods=['GET', 'POST'])
@admin_required
def admin_tournament_rankings(t_id):
    t = Tournament.query.get_or_404(t_id)
    
    # 使用SQL视图获取该届次的序号
    from sqlalchemy import text
    view_query = text("""
        SELECT type_session_number
        FROM tournament_session_view
        WHERE t_id = :t_id
    """)
    
    result = db.session.execute(view_query, {'t_id': t_id})
    row = result.fetchone()
    if row:
        t.type_session_number = row.type_session_number
    else:
        t.type_session_number = None
    
    players = Player.query.order_by(Player.name).all()
    # existing rankings for this tournament
    existing = {r.ranks: r for r in Ranking.query.filter_by(t_id=t_id).all()}
    if request.method == 'POST':
        # iterate ranks 1..player_count
        for rank_pos in range(1, (t.player_count or 0) + 1):
            field = f'rank_{rank_pos}'
            val = request.form.get(field)
            if val:
                player_id = int(val)
                # upsert ranking
                r = Ranking.query.filter_by(t_id=t_id, ranks=rank_pos).first()
                if r:
                    r.player_id = player_id
                else:
                    r = Ranking(t_id=t_id, player_id=player_id, ranks=rank_pos)
                    db.session.add(r)
            else:
                # empty -> remove existing if present
                r = Ranking.query.filter_by(t_id=t_id, ranks=rank_pos).first()
                if r:
                    db.session.delete(r)
        commit_with_retry()
        flash('名次已保存')
        
        # 自动计算积分
        try:
            if calculate_tournament_scores(t_id):
                flash('积分已自动计算并更新')
            else:
                flash('积分计算失败，请手动重新保存排名')
        except Exception as e:
            print(f"积分计算异常: {e}")
            flash(f'积分计算异常: {str(e)}')
        
        # 返回对应赛事页面而不是首页
        return redirect(url_for('tournament_view', t_id=t_id))
    return render_template('admin/edit_rankings.html', tournament=t, players=players, existing=existing)


@app.route('/admin-secret/tournaments/<int:t_id>/edit', methods=['GET', 'POST'])
@admin_required
def admin_edit_tournament(t_id):
    t = Tournament.query.get_or_404(t_id)
    
    # 使用SQL视图获取该届次的序号
    from sqlalchemy import text
    view_query = text("""
        SELECT type_session_number
        FROM tournament_session_view
        WHERE t_id = :t_id
    """)
    
    result = db.session.execute(view_query, {'t_id': t_id})
    row = result.fetchone()
    if row:
        t.type_session_number = row.type_session_number
    else:
        t.type_session_number = None
    
    if request.method == 'POST':
        # allow updating season_id, type and player_count
        season_id = request.form.get('season_id')
        if season_id:
            t.season_id = int(season_id)
        t.type = int(request.form.get('t_type', t.type))
        t.player_count = int(request.form.get('player_count') or 0)
        t.t_format = int(request.form.get('t_format') or t.t_format or 0)
        
        # 处理报名截止时间
        signup_deadline_str = request.form.get('signup_deadline')
        if signup_deadline_str:
            from datetime import datetime
            try:
                # 直接设置tournament的signup_deadline字段
                t.signup_deadline = signup_deadline_str
            except ValueError:
                flash('报名截止时间格式错误')
                return redirect(request.url)
        else:
            # 清空报名截止时间
            t.signup_deadline = None
        
        commit_with_retry()
        flash('届次已更新')
        # redirect back to provided next (e.g., rankings page) or admin index
        nxt = request.form.get('next') or request.args.get('next')
        if nxt:
            return redirect(nxt)
        return redirect(url_for('admin_index'))
    
    seasons = Season.query.order_by(Season.year.desc()).all()
    # 获取报名截止时间
    signup_deadline = t.signup_deadline
    return render_template('admin/edit_tournament.html', tournament=t, seasons=seasons, signup_deadline=signup_deadline)


# Match CRUD
@app.route('/admin-secret/matches/add', methods=['GET', 'POST'])
@admin_required
def admin_add_match():
    if request.method == 'POST':
        t_id = int(request.form['t_id'])
        p1 = int(request.form['player_1_id'])
        p2 = int(request.form['player_2_id'])
        s1 = int(request.form.get('player_1_score', 0))
        s2 = int(request.form.get('player_2_score', 0))
        m_type = int(request.form.get('m_type') or 0)
        m = Match(t_id=t_id, m_type=m_type, player_1_id=p1, player_2_id=p2, player_1_score=s1, player_2_score=s2)
        db.session.add(m)
        commit_with_retry()
        flash('单场比赛已添加')
        return redirect(url_for('admin_index'))

    players = Player.query.order_by(Player.name).all()
    tournaments = Tournament.query.order_by(Tournament.t_id).all()
    # 使用SQL视图获取带序号的届次数据
    from sqlalchemy import text
    view_query = text("""
        SELECT t.t_id, ts.type_session_number
        FROM tournament t
        JOIN tournament_session_view ts ON t.t_id = ts.t_id
        ORDER BY t.season_id, t.type, t.t_id
    """)
    
    result = db.session.execute(view_query)
    tournaments_data = result.fetchall()
    
    # 为每个届次添加序号
    tournament_numbers = {row.t_id: row.type_session_number for row in tournaments_data}
    for tt in tournaments:
        tt.type_session_number = tournament_numbers.get(tt.t_id)
    # support pre-selection from query params (e.g., /admin-secret/matches/add?season_id=1&t_id=2)
    pre_t_id = request.args.get('t_id', type=int)
    pre_season_id = request.args.get('season_id', type=int)
    return render_template('admin/add_match.html', players=players, tournaments=tournaments, pre_t_id=pre_t_id, pre_season_id=pre_season_id)


@app.route('/admin-secret/matches/<int:m_id>/edit', methods=['GET', 'POST'])
@admin_required
def admin_edit_match(m_id):
    m = Match.query.get_or_404(m_id)
    if request.method == 'POST':
        m.t_id = int(request.form['t_id'])
        m.player_1_id = int(request.form['player_1_id'])
        m.player_2_id = int(request.form['player_2_id'])
        m.m_type = int(request.form.get('m_type') or m.m_type or 0)
        m.player_1_score = int(request.form.get('player_1_score', 0))
        m.player_2_score = int(request.form.get('player_2_score', 0))
        commit_with_retry()
        flash('已更新')
        return redirect(url_for('admin_index'))

    players = Player.query.order_by(Player.name).all()
    tournaments = Tournament.query.order_by(Tournament.t_id).all()
    
    # 使用SQL视图获取带序号的届次数据
    from sqlalchemy import text
    view_query = text("""
        SELECT t.t_id, ts.type_session_number
        FROM tournament t
        JOIN tournament_session_view ts ON t.t_id = ts.t_id
        ORDER BY t.season_id, t.type, t.t_id
    """)
    
    result = db.session.execute(view_query)
    tournaments_data = result.fetchall()
    
    # 为每个届次添加序号
    tournament_numbers = {row.t_id: row.type_session_number for row in tournaments_data}
    for tt in tournaments:
        tt.type_session_number = tournament_numbers.get(tt.t_id)
    
    return render_template('admin/edit_match.html', match=m, players=players, tournaments=tournaments)


@app.route('/admin-secret/matches/<int:m_id>/delete', methods=['POST'])
@admin_required
def admin_delete_match(m_id):
    m = Match.query.get_or_404(m_id)
    db.session.delete(m)
    commit_with_retry()
    flash('已删除')
    return redirect(url_for('admin_index'))


@app.route('/admin-secret/tournaments/<int:t_id>/calculate-scores', methods=['POST'])
@admin_required
def admin_calculate_scores(t_id):
    """手动计算指定赛事的积分"""
    if calculate_tournament_scores(t_id):
        flash('积分计算完成')
    else:
        flash('积分计算失败')
    # 重定向回赛事页面而不是首页
    return redirect(url_for('tournament_view', t_id=t_id))


@app.route('/admin-secret/tournaments/calculate-all-scores', methods=['POST'])
@admin_required
def admin_calculate_all_scores():
    """计算所有已提交排名的赛事积分"""
    # 获取所有有排名数据的赛事
    tournaments_with_rankings = db.session.query(Tournament).join(Ranking).distinct().all()
    
    success_count = 0
    total_count = len(tournaments_with_rankings)
    
    for tournament in tournaments_with_rankings:
        if calculate_tournament_scores(tournament.t_id):
            success_count += 1
    
    flash(f'积分计算完成: {success_count}/{total_count} 个赛事')
    return redirect(url_for('admin_index'))


@app.route('/admin-secret/tournaments/<int:t_id>/toggle-status', methods=['POST'])
@admin_required
def admin_toggle_tournament_status(t_id):
    """切换赛事状态（正常/取消）"""
    try:
        tournament = Tournament.query.get_or_404(t_id)
        
        # 切换状态：1=正常, 2=取消
        if tournament.status == 1:
            tournament.status = 2
            status_text = "取消"
        else:
            tournament.status = 1
            status_text = "恢复"
        
        commit_with_retry()
        flash(f'成功{status_text}赛事：第{tournament.type_session_number}届', 'success')
        
    except Exception as e:
        print(f"切换赛事状态失败: {e}")
        flash('切换赛事状态失败', 'error')
    
    # 支持重定向到指定页面
    next_url = request.form.get('next') or request.args.get('next')
    if next_url:
        return redirect(next_url)
    
    return redirect(url_for('admin_index'))


def init_db():
    # 如果数据库文件不存在，创建表
    with app.app_context():
        db.create_all()


@app.context_processor
def inject_formats():
    t_format_labels = {
        1: '小组赛 + 1/4决赛',
        2: '小组赛 + 升降赛',
        3: '小组赛 + 半决赛资格赛',
        4: '单循环赛',
        5: '双循环赛',
        6: '苏超赛制（CM250）',
        7: '双败淘汰赛',
        8: '其他'
    }
    m_type_labels = {
        1: '小组赛（普通）',
        2: '小组赛（主）',
        3: '小组赛（客）',
        4: '首轮（双败淘汰赛）',
        5: '胜者组比赛',
        6: '败者组比赛',
        7: '升降赛',
        8: '1/4决赛',
        9: '半决赛资格赛',
        10: '半决赛',
        11: '铜牌赛',
        12: '金牌赛',
        13: '1/4决赛资格赛',
        14: '附加赛',
        15: '不可用'
    }
    # allowed m_type per t_format
    allowed = {
        1: [1,2,3,8,10,11,12,13,14],  # 小组赛 + 1/4决赛 + 附加赛
        2: [1,2,3,7,14],  # 小赛 + 附加赛
        3: [1,2,3,9,10,11,12,13,14],  # 小组赛 + 半决赛资格赛 + 附加赛
        4: [1,9,10,11,12,14],  # 单循环赛 + 附加赛
        5: [2,3,9,10,11,12,14],  # 双循环赛 + 附加赛
        6: [2,3,9,10,11,12,14],  # 苏超赛制 + 附加赛
        7: [4,5,6,11,12,14],  # 双败淘汰赛 + 附加赛
        8: [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15]  # 其他格式
    }
    return dict(t_format_labels=t_format_labels, m_type_labels=m_type_labels, format_allowed=allowed)


# 淘汰赛管理辅助函数
def get_group_stage_standings(t_id):
    """获取小组赛排名数据，用于淘汰赛生成"""
    try:
        tournament = db.session.get(Tournament, t_id)
        if not tournament or tournament.type != 1:  # 只有大赛才有小组赛
            return None
        
        groups = get_tournament_groups(t_id)
        if not groups:
            return None
        
        # 计算总排名
        total_rankings = calculate_total_group_rankings(t_id)
        
        # 构建与tournament_view相同的格式
        result = {}
        for group in groups:
            group_standings = calculate_group_standings(t_id, group['tg_id'])
            result[group['tg_id']] = {
                'group_name': group['t_name'],
                'standings': group_standings
            }
        
        # 添加总排名数据 - 保持按组内排名的顺序
        all_players = []
        for group_id, players in total_rankings.items():
            all_players.extend(players)
        
        # 按total_rank排序，确保正确的总排名顺序
        all_players.sort(key=lambda x: x['total_rank'])
        result['all_players'] = all_players
        
        return result
    except Exception as e:
        print(f"获取小组赛排名时出错: {e}")
        return None


# 新的淘汰赛系统
class KnockoutManager:
    """淘汰赛管理器"""
    
    def __init__(self, t_id):
        self.t_id = t_id
        self.tournament = db.session.get(Tournament, t_id)
        self.standings = get_group_stage_standings(t_id)
    
    def get_quarterfinal_format(self):
        """获取1/4决赛格式"""
        # 检查是否已有1/4决赛比赛
        existing_qf = Match.query.filter(
            Match.t_id == self.t_id,
            Match.m_type == 8
        ).first()
        
        if existing_qf:
            # 检查是否有资格赛
            existing_qualifier = Match.query.filter(
                Match.t_id == self.t_id,
                Match.m_type == 13
            ).first()
            
            if existing_qualifier:
                return 'qualifier'  # 有资格赛
            else:
                return 'direct'  # 直接1/4决赛
        else:
            return None  # 未生成
    
    def generate_quarterfinal(self, format_type):
        """生成1/4决赛"""
        if not self.standings or not self.standings.get('all_players'):
            return {'success': False, 'error': '请先完成小组赛'}
        
        # 检查小组赛是否完成（没有0-0的比赛）
        incomplete_matches = Match.query.filter(
            Match.t_id == self.t_id,
            Match.m_type.in_([1, 2]),  # 小组赛类型
            Match.player_1_score == 0,
            Match.player_2_score == 0
        ).count()
        
        if incomplete_matches > 0:
            return {'success': False, 'error': f'小组赛还有{incomplete_matches}场比赛未完成，请先完成所有小组赛'}
        
        all_players = self.standings['all_players']
        
        if format_type == 'direct':
            # 直接1/4决赛：前8名
            if len(all_players) < 8:
                return {'success': False, 'error': '参赛选手不足8人'}
            
            matches = [
                (all_players[0]['player_id'], all_players[7]['player_id'], 8),  # 上半区: 1 vs 8
                (all_players[3]['player_id'], all_players[4]['player_id'], 8),  # 上半区: 4 vs 5
                (all_players[1]['player_id'], all_players[6]['player_id'], 8),  # 下半区: 2 vs 7
                (all_players[2]['player_id'], all_players[5]['player_id'], 8),  # 下半区: 3 vs 6
            ]
            
        elif format_type == 'qualifier':
            # 有资格赛：前6名直接晋级，7-10名资格赛
            if len(all_players) < 10:
                return {'success': False, 'error': '参赛选手不足10人'}
            
            # 创建资格赛
            qualifier_matches = [
                (all_players[6]['player_id'], all_players[9]['player_id'], 13),  # 7 vs 10
                (all_players[7]['player_id'], all_players[8]['player_id'], 13),  # 8 vs 9
            ]
            
            # 创建1/4决赛（部分待更新）
            matches = [
                (all_players[0]['player_id'], -1, 8),  # 1 vs 待定
                (all_players[3]['player_id'], all_players[4]['player_id'], 8),  # 4 vs 5
                (all_players[1]['player_id'], -1, 8),  # 2 vs 待定
                (all_players[2]['player_id'], all_players[5]['player_id'], 8),  # 3 vs 6
            ]
            
            # 先创建资格赛
            for player1_id, player2_id, m_type in qualifier_matches:
                match = Match(
                    t_id=self.t_id,
                    player_1_id=player1_id,
                    player_2_id=player2_id,
                    m_type=m_type,
                    player_1_score=0,
                    player_2_score=0
                )
                db.session.add(match)
        
        # 创建1/4决赛
        for player1_id, player2_id, m_type in matches:
            match = Match(
                t_id=self.t_id,
                player_1_id=player1_id,
                player_2_id=player2_id,
                m_type=m_type,
                player_1_score=0,
                player_2_score=0
            )
            db.session.add(match)
        
        db.session.commit()
        return {'success': True, 'message': f'成功生成1/4决赛（{format_type}模式）'}
    
    def check_and_update_next_round(self):
        """检查并更新下一轮"""
        print(f"开始检查赛事 {self.t_id} 的淘汰赛更新")
        
        # 检查1/4决赛资格赛
        print("检查1/4决赛资格赛...")
        self._update_quarterfinal_qualifiers()
        
        # 检查1/4决赛
        print("检查1/4决赛...")
        self._update_semifinals()
        
        # 检查半决赛
        print("检查半决赛...")
        self._update_finals()
        
        print(f"赛事 {self.t_id} 的淘汰赛更新检查完成")
    
    def _update_quarterfinal_qualifiers(self):
        """更新1/4决赛资格赛结果"""
        qualifiers = Match.query.filter(
            Match.t_id == self.t_id,
            Match.m_type == 13
        ).all()
        
        if not qualifiers:
            return
        
        # 检查资格赛是否完成
        for qualifier in qualifiers:
            if qualifier.player_1_score == 0 and qualifier.player_2_score == 0:
                return  # 还有未完成的资格赛
        
        # 更新1/4决赛对阵
        quarterfinals = Match.query.filter(
            Match.t_id == self.t_id,
            Match.m_type == 8
        ).all()
        
        for qf in quarterfinals:
            if qf.player_2_id == -1:  # 待定位置
                # 根据资格赛结果确定对手
                if qf.player_1_id == self.standings['all_players'][0]['player_id']:  # 第1名
                    # 第1名 vs 资格赛胜者
                    winner = self._get_qualifier_winner(qualifiers[0])
                    qf.player_2_id = winner
                elif qf.player_1_id == self.standings['all_players'][1]['player_id']:  # 第2名
                    # 第2名 vs 资格赛胜者
                    winner = self._get_qualifier_winner(qualifiers[1])
                    qf.player_2_id = winner
        
        db.session.commit()
    
    def _get_qualifier_winner(self, qualifier):
        """获取资格赛胜者"""
        if qualifier.player_1_score > qualifier.player_2_score:
            return qualifier.player_1_id
        else:
            return qualifier.player_2_id
    
    def _update_semifinals(self):
        """更新半决赛对阵"""
        quarterfinals = Match.query.filter(
            Match.t_id == self.t_id,
            Match.m_type == 8
        ).all()
        
        if not quarterfinals:
            return
        
        # 检查1/4决赛是否完成
        for qf in quarterfinals:
            if qf.player_1_score == 0 and qf.player_2_score == 0:
                return  # 还有未完成的1/4决赛
        
        # 检查是否已有半决赛
        existing_semifinals = Match.query.filter(
            Match.t_id == self.t_id,
            Match.m_type == 10
        ).count()
        
        if existing_semifinals > 0:
            return  # 半决赛已存在
        
        # 获取1/4决赛胜者
        winners = []
        for qf in quarterfinals:
            if qf.player_1_score > qf.player_2_score:
                winners.append(qf.player_1_id)
            else:
                winners.append(qf.player_2_id)
        
        # 生成半决赛
        if len(winners) >= 4:
            # 上半区：第1场胜者 vs 第2场胜者
            # 下半区：第3场胜者 vs 第4场胜者
            semifinal1 = Match(
                t_id=self.t_id,
                player_1_id=winners[0],
                player_2_id=winners[1],
                m_type=10,
                player_1_score=0,
                player_2_score=0
            )
            semifinal2 = Match(
                t_id=self.t_id,
                player_1_id=winners[2],
                player_2_id=winners[3],
                m_type=10,
                player_1_score=0,
                player_2_score=0
            )
            
            db.session.add(semifinal1)
            db.session.add(semifinal2)
            db.session.commit()
    
    def _update_finals(self):
        """更新决赛对阵"""
        semifinals = Match.query.filter(
            Match.t_id == self.t_id,
            Match.m_type == 10
        ).all()
        
        if not semifinals:
            return
        
        # 检查半决赛是否完成
        for sf in semifinals:
            if sf.player_1_score == 0 and sf.player_2_score == 0:
                return  # 还有未完成的半决赛
        
        # 检查是否已有决赛
        existing_finals = Match.query.filter(
            Match.t_id == self.t_id,
            Match.m_type.in_([11, 12])
        ).count()
        
        if existing_finals > 0:
            return  # 决赛已存在
        
        # 获取半决赛胜者和败者
        winners = []
        losers = []
        
        for sf in semifinals:
            if sf.player_1_score > sf.player_2_score:
                winners.append(sf.player_1_id)
                losers.append(sf.player_2_id)
            else:
                winners.append(sf.player_2_id)
                losers.append(sf.player_1_id)
        
        # 生成金牌赛和铜牌赛
        if len(winners) >= 2 and len(losers) >= 2:
            # 金牌赛：半决赛胜者
            gold_match = Match(
                t_id=self.t_id,
                player_1_id=winners[0],
                player_2_id=winners[1],
                m_type=12,  # 金牌赛
                player_1_score=0,
                player_2_score=0
            )
            
            # 铜牌赛：半决赛败者
            bronze_match = Match(
                t_id=self.t_id,
                player_1_id=losers[0],
                player_2_id=losers[1],
                m_type=11,  # 铜牌赛
                player_1_score=0,
                player_2_score=0
            )
            
            db.session.add(gold_match)
            db.session.add(bronze_match)
            db.session.commit()
    
    def generate_quarterfinal_manual(self, position_data):
        """手动指定位次生成1/4决赛"""
        if not self.standings or not self.standings.get('all_players'):
            return {'success': False, 'error': '请先完成小组赛'}
        
        # 检查小组赛是否完成（没有0-0的比赛）
        incomplete_matches = Match.query.filter(
            Match.t_id == self.t_id,
            Match.m_type.in_([1, 2]),  # 小组赛类型
            Match.player_1_score == 0,
            Match.player_2_score == 0
        ).count()
        
        if incomplete_matches > 0:
            return {'success': False, 'error': f'小组赛还有{incomplete_matches}场比赛未完成，请先完成所有小组赛'}
        
        # 验证位次数据
        if len(position_data) != 8:
            return {'success': False, 'error': '必须指定8个位次'}
        
        # 创建位次映射
        position_map = {}
        for i, player_id in enumerate(position_data, 1):
            position_map[i] = player_id
        
        # 生成1/4决赛对阵
        # 上半区：1位 vs 8位，4位 vs 5位
        # 下半区：2位 vs 7位，3位 vs 6位
        matches = [
            (position_map[1], position_map[8], 8),  # 上半区: 1位 vs 8位
            (position_map[4], position_map[5], 8),  # 上半区: 4位 vs 5位
            (position_map[2], position_map[7], 8),  # 下半区: 2位 vs 7位
            (position_map[3], position_map[6], 8),  # 下半区: 3位 vs 6位
        ]
        
        # 创建比赛记录
        for player1_id, player2_id, m_type in matches:
            match = Match(
                t_id=self.t_id,
                player_1_id=player1_id,
                player_2_id=player2_id,
                m_type=m_type,
                player_1_score=0,
                player_2_score=0
            )
            db.session.add(match)
        
        db.session.commit()
        return {'success': True, 'message': '成功生成1/4决赛（手动指定位次）'}
    
    def generate_quarterfinal_random(self, random_sub_option):
        """随机位次生成1/4决赛"""
        if not self.standings or not self.standings.get('all_players'):
            return {'success': False, 'error': '请先完成小组赛'}
        
        # 检查小组赛是否完成（没有0-0的比赛）
        incomplete_matches = Match.query.filter(
            Match.t_id == self.t_id,
            Match.m_type.in_([1, 2]),  # 小组赛类型
            Match.player_1_score == 0,
            Match.player_2_score == 0
        ).count()
        
        if incomplete_matches > 0:
            return {'success': False, 'error': f'小组赛还有{incomplete_matches}场比赛未完成，请先完成所有小组赛'}
        
        all_players = self.standings['all_players']
        
        if len(all_players) < 8:
            return {'success': False, 'error': '参赛选手不足8人'}
        
        # 获取前8名选手
        top8_players = all_players[:8]
        
        # 随机打乱顺序
        import random
        random.shuffle(top8_players)
        
        # 生成1/4决赛对阵
        matches = [
            (top8_players[0]['player_id'], top8_players[7]['player_id'], 8),  # 1 vs 8
            (top8_players[3]['player_id'], top8_players[4]['player_id'], 8),  # 4 vs 5
            (top8_players[1]['player_id'], top8_players[6]['player_id'], 8),  # 2 vs 7
            (top8_players[2]['player_id'], top8_players[5]['player_id'], 8),  # 3 vs 6
        ]
        
        # 创建比赛记录
        for player1_id, player2_id, m_type in matches:
            match = Match(
                t_id=self.t_id,
                player_1_id=player1_id,
                player_2_id=player2_id,
                m_type=m_type,
                player_1_score=0,
                player_2_score=0
            )
            db.session.add(match)
        
        db.session.commit()
        return {'success': True, 'message': '成功生成1/4决赛（随机位次）'}
    
    def generate_quarterfinal_direct(self):
        """直接生成1/4决赛"""
        return self.generate_quarterfinal('direct')
    
    def generate_quarterfinal_qualifier(self):
        """生成带资格赛的1/4决赛"""
        return self.generate_quarterfinal('qualifier')


class PromotionRelegationManager:
    """升降赛管理器 - 基于排序网络逻辑"""
    
    def __init__(self, t_id):
        self.t_id = t_id
        self.tournament = db.session.get(Tournament, t_id)
        self.standings = get_group_stage_standings(t_id)
        
        # 使用现有的升降赛 m_type = 7
        # 所有升降赛轮次都使用同一个 m_type = 7
        self.promotion_relegation_type = 7
    
    def get_status(self):
        """获取升降赛状态"""
        try:
            # 检查升降赛比赛
            matches = Match.query.filter(
                Match.t_id == self.t_id,
                Match.m_type == self.promotion_relegation_type
            ).all()
            
            if not matches:
                return {
                    'success': True,
                    'current_round': 0,
                    'completed_rounds': 0,
                    'status': '未开始'
                }
            
            # 检查未完成的比赛
            incomplete_matches = Match.query.filter(
                Match.t_id == self.t_id,
                Match.m_type == self.promotion_relegation_type,
                Match.player_1_score == 0,
                Match.player_2_score == 0
            ).count()
            
            total_matches = len(matches)
            completed_matches = total_matches - incomplete_matches
            
            # 每轮4场比赛，总共4轮16场比赛
            completed_rounds = completed_matches // 4
            current_round = completed_rounds + 1 if incomplete_matches > 0 else completed_rounds
            
            return {
                'success': True,
                'current_round': current_round,
                'completed_rounds': completed_rounds,
                'total_matches': total_matches,
                'completed_matches': completed_matches,
                'status': '进行中' if incomplete_matches > 0 else '已完成'
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def generate_next_round(self):
        """生成下一轮比赛"""
        try:
            # 检查小组赛是否完成
            if not self.standings or not self.standings.get('all_players'):
                return {'success': False, 'error': '请先完成小组赛'}
            
            # 获取当前状态
            status = self.get_status()
            if not status['success']:
                return status
            
            current_round = status['current_round']
            completed_rounds = status['completed_rounds']
            
            # 确定要生成的轮次
            if current_round == 0:
                # 生成第1轮
                next_round = 1
            elif completed_rounds == current_round:
                # 当前轮已完成，生成下一轮
                next_round = current_round + 1
            else:
                # 当前轮未完成
                return {'success': False, 'error': f'第{current_round}轮比赛尚未完成，请先完成所有比赛'}
            
            if next_round > 4:
                return {'success': False, 'error': '升降赛最多4轮'}
            
            # 生成指定轮次的比赛
            result = self._generate_round_matches(next_round)
            return result
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def _generate_round_matches(self, round_num):
        """生成指定轮次的比赛"""
        try:
            # 检查该轮是否已存在（通过比赛数量判断）
            existing_matches = Match.query.filter(
                Match.t_id == self.t_id,
                Match.m_type == self.promotion_relegation_type
            ).count()
            
            # 每轮4场比赛，检查是否已有该轮次的比赛
            expected_matches = round_num * 4
            if existing_matches >= expected_matches:
                return {'success': False, 'error': f'第{round_num}轮比赛已存在'}
            
            # 获取当前排名（基于已完成轮次的结果）
            current_ranking = self._get_current_ranking(round_num - 1)
            
            # 根据排序网络逻辑生成比赛
            matches = self._get_round_matches(round_num, current_ranking)
            
            # 创建比赛记录
            for player1_id, player2_id in matches:
                match = Match(
                    t_id=self.t_id,
                    player_1_id=player1_id,
                    player_2_id=player2_id,
                    m_type=self.promotion_relegation_type,
                    player_1_score=0,
                    player_2_score=0
                )
                db.session.add(match)
            
            db.session.commit()
            return {'success': True, 'message': f'成功生成第{round_num}轮比赛'}
            
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'error': str(e)}
    
    def _get_current_ranking(self, completed_rounds):
        """获取当前排名（基于已完成轮次的结果）"""
        if completed_rounds == 0:
            # 第1轮前，使用小组赛排名
            all_players = self.standings.get('all_players', [])
            return [player['player_id'] for player in all_players[:8]]
        
        # 基于已完成轮次的结果计算当前排名
        current_ranking = [player['player_id'] for player in self.standings.get('all_players', [])[:8]]
        
        for round_num in range(1, completed_rounds + 1):
            current_ranking = self._calculate_next_ranking(round_num, current_ranking)
        
        return current_ranking
    
    def _get_round_matches(self, round_num, current_ranking):
        """根据升降赛规则获取指定轮次的比赛"""
        if round_num == 1:
            # 第1轮: 1vs2, 3vs4, 5vs6, 7vs8
            return [
                (current_ranking[0], current_ranking[1]),  # 1vs2
                (current_ranking[2], current_ranking[3]),  # 3vs4
                (current_ranking[4], current_ranking[5]),  # 5vs6
                (current_ranking[6], current_ranking[7])   # 7vs8
            ]
        elif round_num == 2:
            # 第2轮: 根据第1轮结果重新配对
            # 12名胜者落位下轮1号位，负者落位下轮3号位
            # 34名胜者落位下轮2号位，负者落位下轮5号位
            # 56名胜者落位下轮4号位，负者落位下轮7号位
            # 78名胜者落位下轮6号位，负者落位下轮8号位
            next_ranking = self._calculate_next_ranking(1, current_ranking)
            return [
                (next_ranking[0], next_ranking[1]),  # 1vs2
                (next_ranking[2], next_ranking[3]),  # 3vs4
                (next_ranking[4], next_ranking[5]),  # 5vs6
                (next_ranking[6], next_ranking[7])   # 7vs8
            ]
        elif round_num == 3:
            # 第3轮: 根据第2轮结果重新配对
            next_ranking = self._calculate_next_ranking(2, current_ranking)
            return [
                (next_ranking[0], next_ranking[1]),  # 1vs2
                (next_ranking[2], next_ranking[3]),  # 3vs4
                (next_ranking[4], next_ranking[5]),  # 5vs6
                (next_ranking[6], next_ranking[7])   # 7vs8
            ]
        elif round_num == 4:
            # 第4轮: 根据第3轮结果重新配对
            next_ranking = self._calculate_next_ranking(3, current_ranking)
            return [
                (next_ranking[0], next_ranking[1]),  # 1vs2 (8局)
                (next_ranking[2], next_ranking[3]),  # 3vs4 (8局)
                (next_ranking[4], next_ranking[5]),  # 5vs6 (6局)
                (next_ranking[6], next_ranking[7])   # 7vs8 (6局)
            ]
        
        return []
    
    def _calculate_next_ranking(self, round_num, current_ranking):
        """根据指定轮次的结果计算下一轮的排名"""
        # 获取该轮次的比赛结果
        matches = Match.query.filter(
            Match.t_id == self.t_id,
            Match.m_type == self.promotion_relegation_type
        ).order_by(Match.m_id).all()
        
        # 计算该轮次的比赛结果
        round_matches = matches[(round_num-1)*4:round_num*4]
        
        # 初始化下一轮排名
        next_ranking = [None] * 8
        
        for i, match in enumerate(round_matches):
            if match.player_1_score > match.player_2_score:
                winner = match.player_1_id
                loser = match.player_2_id
            elif match.player_2_score > match.player_1_score:
                winner = match.player_2_id
                loser = match.player_1_id
            else:
                # 平局情况，暂时按原排名处理
                winner = match.player_1_id
                loser = match.player_2_id
            
            # 根据规则分配位置
            if i == 0:  # 1vs2
                next_ranking[0] = winner  # 胜者落位1号位
                next_ranking[2] = loser   # 负者落位3号位
            elif i == 1:  # 3vs4
                next_ranking[1] = winner  # 胜者落位2号位
                next_ranking[4] = loser   # 负者落位5号位
            elif i == 2:  # 5vs6
                next_ranking[3] = winner  # 胜者落位4号位
                next_ranking[6] = loser   # 负者落位7号位
            elif i == 3:  # 7vs8
                next_ranking[5] = winner  # 胜者落位6号位
                next_ranking[7] = loser   # 负者落位8号位
        
        return next_ranking
    
    def get_quarterfinal_format(self):
        """获取1/4决赛格式"""
        # 检查是否已有1/4决赛比赛
        existing_qf = Match.query.filter(
            Match.t_id == self.t_id,
            Match.m_type == 8
        ).first()
        
        if existing_qf:
            # 检查是否有资格赛
            existing_qualifier = Match.query.filter(
                Match.t_id == self.t_id,
                Match.m_type == 13
            ).first()
            
            if existing_qualifier:
                return 'qualifier'  # 有资格赛
            else:
                return 'direct'  # 直接1/4决赛
        else:
            return None  # 未生成


class DoubleEliminationManager:
    """双败淘汰赛管理器"""
    
    def __init__(self, t_id):
        self.t_id = t_id
        self.tournament = db.session.get(Tournament, t_id)
        self.player_count = self.tournament.player_count
        self.standings = get_group_stage_standings(t_id)  # 添加standings属性
        
        # 双败淘汰赛的m_type
        self.winner_bracket_type = 15  # 胜者组
        self.loser_bracket_type = 16   # 败者组
        self.final_type = 17           # 决赛
    
    def get_status(self):
        """获取双败淘汰赛状态"""
        try:
            # 检查胜者组比赛
            winner_matches = Match.query.filter(
                Match.t_id == self.t_id,
                Match.m_type == self.winner_bracket_type
            ).all()
            
            # 检查败者组比赛
            loser_matches = Match.query.filter(
                Match.t_id == self.t_id,
                Match.m_type == self.loser_bracket_type
            ).all()
            
            # 检查决赛
            final_matches = Match.query.filter(
                Match.t_id == self.t_id,
                Match.m_type == self.final_type
            ).all()
            
            if not winner_matches and not loser_matches and not final_matches:
                return {
                    'success': True,
                    'current_round': 0,
                    'winner_bracket_status': '未开始',
                    'loser_bracket_status': '未开始',
                    'status': '未开始'
                }
            
            # 计算当前轮次
            current_round = self._calculate_current_round()
            
            return {
                'success': True,
                'current_round': current_round,
                'winner_bracket_status': '进行中' if winner_matches else '未开始',
                'loser_bracket_status': '进行中' if loser_matches else '未开始',
                'status': '进行中' if (winner_matches or loser_matches or final_matches) else '未开始'
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def _calculate_current_round(self):
        """计算当前轮次"""
        # 根据比赛数量计算轮次
        winner_matches = Match.query.filter(
            Match.t_id == self.t_id,
            Match.m_type == self.winner_bracket_type
        ).count()
        
        loser_matches = Match.query.filter(
            Match.t_id == self.t_id,
            Match.m_type == self.loser_bracket_type
        ).count()
        
        final_matches = Match.query.filter(
            Match.t_id == self.t_id,
            Match.m_type == self.final_type
        ).count()
        
        total_matches = winner_matches + loser_matches + final_matches
        
        if total_matches == 0:
            return 0
        
        # 根据总比赛数估算轮次
        if total_matches <= self.player_count // 2:
            return 1
        elif total_matches <= self.player_count:
            return 2
        else:
            return 3
    
    def generate_next_round(self):
        """生成下一轮比赛"""
        try:
            status = self.get_status()
            if not status['success']:
                return status
            
            current_round = status['current_round']
            
            if current_round == 0:
                # 生成第1轮比赛
                return self._generate_first_round()
            else:
                # 生成后续轮次
                return self._generate_next_round_matches(current_round)
                
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def _generate_first_round(self):
        """生成第1轮比赛"""
        try:
            # 检查是否已有第1轮比赛
            existing_matches = Match.query.filter(
                Match.t_id == self.t_id,
                Match.m_type == self.winner_bracket_type
            ).count()
            
            if existing_matches > 0:
                return {'success': False, 'error': '第1轮比赛已存在'}
            
            # 获取参赛选手
            participants = self._get_participants()
            
            if len(participants) < 4:
                return {'success': False, 'error': f'参赛选手不足4人，当前只有{len(participants)}人。请先在赛事页面分配选手。'}
            
            # 生成第1轮比赛（胜者组）
            matches_count = len(participants) // 2
            for i in range(matches_count):
                player1_id = participants[i * 2]
                player2_id = participants[i * 2 + 1]
                
                match = Match(
                    t_id=self.t_id,
                    player_1_id=player1_id,
                    player_2_id=player2_id,
                    m_type=self.winner_bracket_type,
                    player_1_score=0,
                    player_2_score=0
                )
                db.session.add(match)
            
            db.session.commit()
            return {'success': True, 'message': f'成功生成第1轮比赛，共{matches_count}场'}
            
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'error': str(e)}
    
    def _generate_next_round_matches(self, current_round):
        """生成下一轮比赛"""
        try:
            # 检查上一轮是否完成
            if not self._is_round_complete(current_round):
                return {'success': False, 'error': f'第{current_round}轮比赛未完成'}
            
            # 根据当前轮次生成下一轮
            if current_round == 1:
                return self._generate_second_round()
            elif current_round == 2:
                return self._generate_third_round()
            else:
                return {'success': False, 'error': '所有轮次已完成'}
                
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def _generate_second_round(self):
        """生成第2轮比赛"""
        try:
            # 检查是否已有第2轮比赛
            existing_matches = Match.query.filter(
                Match.t_id == self.t_id,
                Match.m_type == self.loser_bracket_type
            ).count()
            
            if existing_matches > 0:
                return {'success': False, 'error': '第2轮比赛已存在'}
            
            # 获取第1轮结果
            first_round_matches = Match.query.filter(
                Match.t_id == self.t_id,
                Match.m_type == self.winner_bracket_type
            ).all()
            
            winners = []
            losers = []
            
            for match in first_round_matches:
                if match.player_1_score > match.player_2_score:
                    winners.append(match.player_1_id)
                    losers.append(match.player_2_id)
                elif match.player_2_score > match.player_1_score:
                    winners.append(match.player_2_id)
                    losers.append(match.player_1_id)
                else:
                    # 平局情况，暂时按原排名处理
                    winners.append(match.player_1_id)
                    losers.append(match.player_2_id)
            
            # 生成胜者组第2轮
            if len(winners) >= 2:
                for i in range(0, len(winners), 2):
                    if i + 1 < len(winners):
                        match = Match(
                            t_id=self.t_id,
                            player_1_id=winners[i],
                            player_2_id=winners[i + 1],
                            m_type=self.winner_bracket_type,
                            player_1_score=0,
                            player_2_score=0
                        )
                        db.session.add(match)
            
            # 生成败者组第1轮
            if len(losers) >= 2:
                for i in range(0, len(losers), 2):
                    if i + 1 < len(losers):
                        match = Match(
                            t_id=self.t_id,
                            player_1_id=losers[i],
                            player_2_id=losers[i + 1],
                            m_type=self.loser_bracket_type,
                            player_1_score=0,
                            player_2_score=0
                        )
                        db.session.add(match)
            
            db.session.commit()
            return {'success': True, 'message': '成功生成第2轮比赛'}
            
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'error': str(e)}
    
    def _generate_third_round(self):
        """生成第3轮比赛（决赛）"""
        try:
            # 检查是否已有决赛
            existing_final = Match.query.filter(
                Match.t_id == self.t_id,
                Match.m_type == self.final_type
            ).count()
            
            if existing_final > 0:
                return {'success': False, 'error': '决赛已存在'}
            
            # 获取胜者组冠军
            winner_bracket_matches = Match.query.filter(
                Match.t_id == self.t_id,
                Match.m_type == self.winner_bracket_type
            ).all()
            
            # 获取败者组冠军
            loser_bracket_matches = Match.query.filter(
                Match.t_id == self.t_id,
                Match.m_type == self.loser_bracket_type
            ).all()
            
            # 这里需要根据实际比赛结果确定冠军
            # 暂时使用最后一场比赛的胜者
            winner_champion = None
            loser_champion = None
            
            if winner_bracket_matches:
                last_winner_match = winner_bracket_matches[-1]
                if last_winner_match.player_1_score > last_winner_match.player_2_score:
                    winner_champion = last_winner_match.player_1_id
                else:
                    winner_champion = last_winner_match.player_2_id
            
            if loser_bracket_matches:
                last_loser_match = loser_bracket_matches[-1]
                if last_loser_match.player_1_score > last_loser_match.player_2_score:
                    loser_champion = last_loser_match.player_1_id
                else:
                    loser_champion = last_loser_match.player_2_id
            
            if winner_champion and loser_champion:
                # 生成决赛
                match = Match(
                    t_id=self.t_id,
                    player_1_id=winner_champion,
                    player_2_id=loser_champion,
                    m_type=self.final_type,
                    player_1_score=0,
                    player_2_score=0
                )
                db.session.add(match)
                
                db.session.commit()
                return {'success': True, 'message': '成功生成决赛'}
            else:
                return {'success': False, 'error': '无法确定决赛选手'}
                
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'error': str(e)}
    
    def _is_round_complete(self, round_num):
        """检查指定轮次是否完成"""
        if round_num == 1:
            matches = Match.query.filter(
                Match.t_id == self.t_id,
                Match.m_type == self.winner_bracket_type
            ).all()
        else:
            matches = Match.query.filter(
                Match.t_id == self.t_id,
                Match.m_type.in_([self.winner_bracket_type, self.loser_bracket_type])
            ).all()
        
        for match in matches:
            if match.player_1_score == 0 and match.player_2_score == 0:
                return False
        
        return True
    
    def _get_participants(self):
        """获取参赛选手"""
        # 从小组赛数据中获取选手
        if hasattr(self, 'standings') and self.standings:
            all_players = self.standings.get('all_players', [])
            if all_players:
                return [player['player_id'] for player in all_players[:self.player_count]]
        
        # 从数据库中获取选手 - 优先从tgroups获取
        participants = db.session.execute(text("""
            SELECT DISTINCT p.player_id
            FROM players p
            JOIN tg_players tgp ON p.player_id = tgp.player_id
            JOIN tgroups tg ON tgp.tg_id = tg.tg_id
            WHERE tg.t_id = :t_id
            ORDER BY p.player_id
            LIMIT :limit
        """), {'t_id': self.t_id, 'limit': self.player_count}).fetchall()
        
        if participants:
            return [row[0] for row in participants]
        
        # 如果tgroups中没有选手，从rankings表获取
        participants = db.session.execute(text("""
            SELECT DISTINCT p.player_id
            FROM players p
            JOIN rankings r ON p.player_id = r.player_id
            WHERE r.t_id = :t_id
            ORDER BY p.player_id
            LIMIT :limit
        """), {'t_id': self.t_id, 'limit': self.player_count}).fetchall()
        
        if participants:
            return [row[0] for row in participants]
        
        # 如果都没有，返回空列表
        return []
    
    def generate_first_round_with_players(self, players):
        """使用指定的选手列表生成第1轮比赛"""
        try:
            # 检查是否已有第1轮比赛
            existing_matches = Match.query.filter(
                Match.t_id == self.t_id,
                Match.m_type == self.winner_bracket_type
            ).count()
            
            if existing_matches > 0:
                return {'success': False, 'error': '第1轮比赛已存在'}
            
            if len(players) < 4:
                return {'success': False, 'error': f'双败淘汰赛至少需要4名选手，当前只有{len(players)}名选手'}
            
            if len(players) != self.player_count:
                return {'success': False, 'error': f'选手数量不匹配，需要{self.player_count}名选手，当前有{len(players)}名选手'}
            
            # 生成第1轮比赛（胜者组）
            matches_count = len(players) // 2
            for i in range(matches_count):
                player1_id = players[i * 2]
                player2_id = players[i * 2 + 1]
                
                match = Match(
                    t_id=self.t_id,
                    player_1_id=player1_id,
                    player_2_id=player2_id,
                    m_type=self.winner_bracket_type,
                    player_1_score=0,
                    player_2_score=0
                )
                db.session.add(match)
            
            db.session.commit()
            return {'success': True, 'message': f'成功生成第1轮比赛，共{matches_count}场'}
            
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'error': str(e)}


# 双败淘汰赛路由
@app.route('/admin-secret/tournament/<int:t_id>/double-elimination/generate', methods=['POST'])
@admin_required
def double_elimination_generate(t_id):
    try:
        data = request.get_json() or {}
        players = data.get('players', [])
        
        manager = DoubleEliminationManager(t_id)
        
        # 如果前端传来了选手列表，使用它们
        if players:
            result = manager.generate_first_round_with_players(players)
        else:
            result = manager.generate_next_round()
        
        return jsonify(result)
    except Exception as e:
        print(f"双败淘汰赛生成失败: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})


@app.route('/admin-secret/tournament/<int:t_id>/double-elimination/status', methods=['GET'])
@admin_required
def double_elimination_status(t_id):
    try:
        manager = DoubleEliminationManager(t_id)
        result = manager.get_status()
        return jsonify(result)
    except Exception as e:
        print(f"获取双败淘汰赛状态失败: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    
    def check_and_update_next_round(self):
        """检查并更新下一轮"""
        print(f"开始检查赛事 {self.t_id} 的淘汰赛更新")
        
        # 检查1/4决赛资格赛
        print("检查1/4决赛资格赛...")
        self._update_quarterfinal_qualifiers()
        
        # 检查1/4决赛
        print("检查1/4决赛...")
        self._update_semifinals()
        
        # 检查半决赛
        print("检查半决赛...")
        self._update_finals()
        
        print(f"赛事 {self.t_id} 的淘汰赛更新检查完成")
    
    def _update_quarterfinal_qualifiers(self):
        """更新1/4决赛资格赛结果"""
        qualifiers = Match.query.filter(
            Match.t_id == self.t_id,
            Match.m_type == 13,
            Match.player_1_score.isnot(None),
            Match.player_2_score.isnot(None)
        ).all()
        
        # 过滤掉0-0和-1:-1的比赛
        completed_qualifiers = []
        for qualifier in qualifiers:
            if not (qualifier.player_1_score == 0 and qualifier.player_2_score == 0) and \
               not (qualifier.player_1_score == -1 and qualifier.player_2_score == -1):
                completed_qualifiers.append(qualifier)
        
        qualifiers = completed_qualifiers
        
        updated = False
        for qualifier in qualifiers:
            winner_id = qualifier.player_1_id if qualifier.player_1_score > qualifier.player_2_score else qualifier.player_2_id
            
            # 根据资格赛的对阵逻辑来确定要更新的1/4决赛
            # 资格赛1: 第8名 vs 第9名 -> 进入QF1 (第1名 vs 资格赛1胜者)
            # 资格赛2: 第7名 vs 第10名 -> 进入QF3 (第2名 vs 资格赛2胜者)
            
            # 获取所有1/4决赛，按m_id排序
            qf_matches = Match.query.filter(
                Match.t_id == self.t_id,
                Match.m_type == 8
            ).order_by(Match.m_id).all()
            
            # 根据资格赛的m_id来确定对应的1/4决赛
            all_qualifiers = Match.query.filter(Match.t_id == self.t_id, Match.m_type == 13).order_by(Match.m_id).all()
            qualifier_index = all_qualifiers.index(qualifier)
            
            if qualifier_index < len(qf_matches):
                qf_match = qf_matches[qualifier_index]
                if qf_match.player_2_id == -1:  # 只有待更新的1/4决赛才更新
                    qf_match.player_2_id = winner_id
                    updated = True
                    print(f"更新1/4决赛 {qf_match.m_id}: {qf_match.player_1_id} vs {winner_id}")
        
        if updated:
            db.session.commit()
    
    def _update_semifinals(self):
        """更新半决赛"""
        quarterfinals = Match.query.filter(
            Match.t_id == self.t_id,
            Match.m_type == 8,
            Match.player_1_score.isnot(None),
            Match.player_2_score.isnot(None)
        ).order_by(Match.m_id).all()
        
        # 过滤掉0-0和-1:-1的比赛
        completed_quarterfinals = []
        for qf in quarterfinals:
            if not (qf.player_1_score == 0 and qf.player_2_score == 0) and \
               not (qf.player_1_score == -1 and qf.player_2_score == -1):
                completed_quarterfinals.append(qf)
        
        quarterfinals = completed_quarterfinals
        
        if len(quarterfinals) >= 4:
            # 检查是否已存在半决赛
            existing_sf = Match.query.filter(
                Match.t_id == self.t_id,
                Match.m_type == 10
            ).all()
            
            if len(existing_sf) < 2:
                # 获取1/4决赛胜者，按对阵顺序
                winners = []
                for qf in quarterfinals:
                    winner_id = qf.player_1_id if qf.player_1_score > qf.player_2_score else qf.player_2_id
                    winners.append(winner_id)
                
                # 按照上下半区对阵：
                # 上半区：QF1胜者 vs QF2胜者 (第1-2行 vs 第3-4行)
                # 下半区：QF3胜者 vs QF4胜者 (第5-6行 vs 第7-8行)
                semifinal1 = Match(
                    t_id=self.t_id,
                    m_type=10,
                    player_1_id=winners[0],  # QF1胜者
                    player_2_id=winners[1],  # QF2胜者
                    player_1_score=0,
                    player_2_score=0
                )
                semifinal2 = Match(
                    t_id=self.t_id,
                    m_type=10,
                    player_1_id=winners[2],  # QF3胜者
                    player_2_id=winners[3],  # QF4胜者
                    player_1_score=0,
                    player_2_score=0
                )
                
                db.session.add(semifinal1)
                db.session.add(semifinal2)
                db.session.commit()
                print(f"创建半决赛: {winners[0]} vs {winners[1]}, {winners[2]} vs {winners[3]}")
    
    def _update_finals(self):
        """更新决赛"""
        semifinals = Match.query.filter(
            Match.t_id == self.t_id,
            Match.m_type == 10,
            Match.player_1_score.isnot(None),
            Match.player_2_score.isnot(None)
        ).order_by(Match.m_id).all()
        
        # 过滤掉0-0和-1:-1的比赛
        completed_semifinals = []
        for sf in semifinals:
            if not (sf.player_1_score == 0 and sf.player_2_score == 0) and \
               not (sf.player_1_score == -1 and sf.player_2_score == -1):
                completed_semifinals.append(sf)
        
        semifinals = completed_semifinals
        
        if len(semifinals) >= 2:
            # 检查是否已存在金牌赛和铜牌赛
            existing_gold = Match.query.filter(
                Match.t_id == self.t_id,
                Match.m_type == 11
            ).first()
            
            existing_bronze = Match.query.filter(
                Match.t_id == self.t_id,
                Match.m_type == 12
            ).first()
            
            # 获取半决赛胜者和败者
            winners = []
            losers = []
            
            for sf in semifinals:
                winner_id = sf.player_1_id if sf.player_1_score > sf.player_2_score else sf.player_2_id
                loser_id = sf.player_2_id if sf.player_1_score > sf.player_2_score else sf.player_1_id
                winners.append(winner_id)
                losers.append(loser_id)
            
            # 只在不存在时才创建金牌赛
            if not existing_gold:
                gold_match = Match(
                    t_id=self.t_id,
                    m_type=12,  # 金牌赛
                    player_1_id=winners[0],
                    player_2_id=winners[1],
                    player_1_score=0,
                    player_2_score=0
                )
                db.session.add(gold_match)
                print(f"创建金牌赛: {winners[0]} vs {winners[1]}")
            
            # 只在不存在时才创建铜牌赛
            if not existing_bronze:
                bronze_match = Match(
                    t_id=self.t_id,
                    m_type=11,  # 铜牌赛
                    player_1_id=losers[0],
                    player_2_id=losers[1],
                    player_1_score=0,
                    player_2_score=0
                )
                db.session.add(bronze_match)
                print(f"创建铜牌赛: {losers[0]} vs {losers[1]}")
            
            db.session.commit()
    
    def generate_quarterfinal_manual(self, position_data):
        """手动指定位次生成1/4决赛"""
        if not self.standings or not self.standings.get('all_players'):
            return {'success': False, 'error': '请先完成小组赛'}
        
        # 检查小组赛是否完成（没有0-0的比赛）
        incomplete_matches = Match.query.filter(
            Match.t_id == self.t_id,
            Match.m_type.in_([1, 2]),  # 小组赛类型
            Match.player_1_score == 0,
            Match.player_2_score == 0
        ).count()
        
        if incomplete_matches > 0:
            return {'success': False, 'error': f'小组赛还有{incomplete_matches}场比赛未完成，请先完成所有小组赛'}
        
        # 验证位次数据
        if len(position_data) != 8:
            return {'success': False, 'error': '必须指定8个位次'}
        
        # 创建位次映射
        position_map = {}
        for i, player_id in enumerate(position_data, 1):
            position_map[i] = player_id
        
        # 生成1/4决赛对阵
        # 上半区：1位 vs 8位，4位 vs 5位
        # 下半区：2位 vs 7位，3位 vs 6位
        matches = [
            (position_map[1], position_map[8], 8),  # 上半区: 1位 vs 8位
            (position_map[4], position_map[5], 8),  # 上半区: 4位 vs 5位
            (position_map[2], position_map[7], 8),  # 下半区: 2位 vs 7位
            (position_map[3], position_map[6], 8),  # 下半区: 3位 vs 6位
        ]
        
        # 创建1/4决赛
        for player1_id, player2_id, m_type in matches:
            match = Match(
                    t_id=self.t_id,
                player_1_id=player1_id,
                player_2_id=player2_id,
                m_type=m_type,
                    player_1_score=0,
                    player_2_score=0
                )
            db.session.add(match)
            
            db.session.commit()
        return {'success': True, 'message': '成功生成1/4决赛（手动指定位次）'}
    
    def generate_quarterfinal_random(self, random_sub_option):
        """随机位次生成1/4决赛"""
        if not self.standings or not self.standings.get('all_players'):
            return {'success': False, 'error': '请先完成小组赛'}
        
        # 检查小组赛是否完成（没有0-0的比赛）
        incomplete_matches = Match.query.filter(
            Match.t_id == self.t_id,
            Match.m_type.in_([1, 2]),  # 小组赛类型
            Match.player_1_score == 0,
            Match.player_2_score == 0
        ).count()
        
        if incomplete_matches > 0:
            return {'success': False, 'error': f'小组赛还有{incomplete_matches}场比赛未完成，请先完成所有小组赛'}
        
        all_players = self.standings['all_players']
        
        if len(all_players) < 8:
            return {'success': False, 'error': '参赛选手不足8人'}
        
        # 获取前8名选手
        top8_players = all_players[:8]
        
        # 随机打乱顺序
        import random
        random.shuffle(top8_players)
        
        # 如果选择回避同组，需要特殊处理
        if random_sub_option == 'avoid':
            # 这里可以添加更复杂的同组回避逻辑
            pass
        
        # 生成1/4决赛对阵
        matches = [
            (top8_players[0]['player_id'], top8_players[7]['player_id'], 8),  # 上半区: 1 vs 8
            (top8_players[3]['player_id'], top8_players[4]['player_id'], 8),  # 上半区: 4 vs 5
            (top8_players[1]['player_id'], top8_players[6]['player_id'], 8),  # 下半区: 2 vs 7
            (top8_players[2]['player_id'], top8_players[5]['player_id'], 8),  # 下半区: 3 vs 6
        ]
        
        # 创建1/4决赛
        for player1_id, player2_id, m_type in matches:
            match = Match(
                t_id=self.t_id,
                player_1_id=player1_id,
                player_2_id=player2_id,
                m_type=m_type,
                player_1_score=0,
                player_2_score=0
            )
            db.session.add(match)
        
        db.session.commit()
        return {'success': True, 'message': '成功生成1/4决赛（随机位次）'}
    
    def generate_quarterfinal_direct(self):
        """直接模式生成1/4决赛"""
        return self.generate_quarterfinal('direct')
    
    def generate_quarterfinal_qualifier(self):
        """资格赛模式生成1/4决赛"""
        return self.generate_quarterfinal('qualifier')
    
    def update_quarterfinal(self):
        """更新1/4决赛"""
        self.check_and_update_next_round()
        return {'success': True, 'message': '1/4决赛更新成功'}


# 淘汰赛API接口
@app.route('/admin-secret/tournament/<int:t_id>/generate-semifinal-qualifier', methods=['POST'])
@admin_required
def generate_semifinal_qualifier(t_id):
    """为各种赛制生成半决赛资格赛"""
    try:
        tournament = db.session.get(Tournament, t_id)
        if not tournament:
            return jsonify({'success': False, 'error': '赛事不存在'})
        
        # 检查循环赛是否完成
        if not check_round_robin_complete(t_id):
            return jsonify({'success': False, 'error': '循环赛未完成，无法生成半决赛资格赛'})
        
        # 检查是否已有淘汰赛
        from sqlalchemy import text
        existing_query = text("""
            SELECT COUNT(*) FROM matches 
            WHERE t_id = :t_id AND m_type IN (8, 9, 10, 11, 12, 13)
        """)
        existing_count = db.session.execute(existing_query, {'t_id': t_id}).fetchone()[0]
        
        if existing_count > 0:
            return jsonify({'success': False, 'error': '淘汰赛已存在，请先清空现有淘汰赛'})
        
        # 根据赛事类型生成半决赛资格赛
        if tournament.type == 1:  # 大赛
            if tournament.t_format in [1, 2, 3]:  # 小组赛+半决赛资格赛、小组赛+1/4决赛、小组赛+半决赛
                success = auto_generate_semifinal_qualifier_matches(t_id)
            elif tournament.t_format in [4, 5, 6]:  # 单循环赛、双循环赛、苏超赛制
                success = auto_generate_round_robin_knockout_matches(t_id)
            else:
                return jsonify({'success': False, 'error': '该赛事格式不支持半决赛资格赛'})
        elif tournament.type == 2:  # 小赛
            success = auto_generate_minor_tournament_matches(t_id)
        else:
            return jsonify({'success': False, 'error': '该赛事类型不支持半决赛资格赛'})
        
        if success:
            return jsonify({'success': True, 'message': '半决赛资格赛生成成功'})
        else:
            return jsonify({'success': False, 'error': '半决赛资格赛生成失败'})
            
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})


def calculate_and_submit_rankings_api(t_id):
    """计算并提交排名API"""
    if not session.get('admin_logged_in'):
        return jsonify({'success': False, 'error': '需要管理员权限'})
    
    result = calculate_and_submit_rankings(t_id)
    return jsonify(result)


@app.route('/admin-secret/tournament/<int:t_id>/top8-players', methods=['GET'])
def get_top8_players_api(t_id):
    """获取小组赛前8名选手"""
    if not session.get('admin_logged_in'):
        return jsonify({'success': False, 'error': '需要管理员权限'})
    
    try:
        from sqlalchemy import text
        
        # 首先尝试从rankings表获取排名
        query = text("""
            SELECT DISTINCT p.player_id, p.name, r.ranks
            FROM players p
            JOIN rankings r ON p.player_id = r.player_id
            WHERE r.t_id = :t_id
            ORDER BY r.ranks ASC
            LIMIT 8
        """)
        
        result = db.session.execute(query, {'t_id': t_id}).fetchall()
        
        players = []
        if result:
            # 有排名数据
            for row in result:
                players.append({
                    'player_id': row[0],
                    'name': row[1],
                    'ranks': row[2]
                })
        else:
            # 没有排名数据，尝试从小组赛结果计算
            print(f"赛事 {t_id} 没有排名数据，尝试从小组赛结果计算...")
            
            # 获取小组赛积分数据
            standings = get_group_stage_standings(t_id)
            if standings and standings.get('all_players'):
                all_players = standings['all_players']
                # 取前8名
                top8 = all_players[:8]
                
                for i, player in enumerate(top8):
                    players.append({
                        'player_id': player['player_id'],
                        'name': player['name'],
                        'ranks': i + 1  # 临时排名
                    })
            else:
                return jsonify({
                    'success': False, 
                    'error': '没有找到小组赛数据，请先完成小组赛'
                })
        
        return jsonify({
            'success': True,
            'players': players
        })
        
    except Exception as e:
        print(f"获取前8名选手失败: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/admin-secret/tournament/<int:t_id>/knockout/quarterfinal', methods=['POST'])
def knockout_quarterfinal(t_id):
    """1/4决赛管理"""
    if not session.get('admin_logged_in'):
        return jsonify({'success': False, 'error': '需要管理员权限'})
    
    try:
        manager = KnockoutManager(t_id)
        data = request.get_json()
        action = data.get('action')
        
        if action == 'generate':
            # 获取生成参数
            quarterfinal_type = data.get('quarterfinal_type', 'direct')
            random_sub_option = data.get('random_sub_option')
            position_data = data.get('position_data')
            
            # 根据类型生成1/4决赛
            if quarterfinal_type == 'manual' and position_data:
                # 手动指定位次
                result = manager.generate_quarterfinal_manual(position_data)
            elif quarterfinal_type == 'random':
                # 随机位次
                result = manager.generate_quarterfinal_random(random_sub_option)
            elif quarterfinal_type == 'direct':
                # 直接模式
                result = manager.generate_quarterfinal_direct()
            elif quarterfinal_type == 'qualifier':
                # 资格赛模式
                result = manager.generate_quarterfinal_qualifier()
            else:
                # 默认模式
                result = manager.generate_quarterfinal()
            
            return jsonify(result)
        
        elif action == 'check_format':
            format_type = manager.get_quarterfinal_format()
            return jsonify({'success': True, 'format': format_type})
        
        return jsonify({'success': False, 'error': '无效的操作'})
        
    except Exception as e:
        print(f"1/4决赛操作失败: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})


@app.route('/admin-secret/tournament/<int:t_id>/promotion-relegation/generate', methods=['POST'])
@admin_required
def generate_promotion_relegation(t_id):
    """生成升降赛"""
    try:
        manager = PromotionRelegationManager(t_id)
        result = manager.generate_next_round()
        return jsonify(result)
        
    except Exception as e:
        print(f"升降赛生成失败: {e}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/admin-secret/tournament/<int:t_id>/promotion-relegation/status', methods=['GET'])
@admin_required
def get_promotion_relegation_status(t_id):
    """获取升降赛状态"""
    try:
        manager = PromotionRelegationManager(t_id)
        result = manager.get_status()
        return jsonify(result)
        
    except Exception as e:
        print(f"获取升降赛状态失败: {e}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/admin-secret/tournament/<int:t_id>/knockout/update', methods=['POST'])
def knockout_update(t_id):
    """更新淘汰赛"""
    if not session.get('admin_logged_in'):
        return jsonify({'success': False, 'error': '需要管理员权限'})
    
    try:
        manager = KnockoutManager(t_id)
        manager.check_and_update_next_round()
        return jsonify({'success': True, 'message': '淘汰赛更新完成'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# 更新比分提交逻辑，集成新的淘汰赛系统
def update_knockout_bracket_logic(t_id):
    """更新淘汰赛对阵的逻辑函数（不依赖HTTP请求）"""
    try:
        manager = KnockoutManager(t_id)
        manager.check_and_update_next_round()
        return True
    except Exception as e:
        print(f"更新淘汰赛对阵时出错: {e}")
        return False


# 旧的淘汰赛函数（保留兼容性）
@app.route('/admin-secret/tournament/<int:t_id>/generate-quarterfinal', methods=['POST'])
def generate_quarterfinal_bracket(t_id):
    """生成1/4决赛对阵（兼容性接口）"""
    if not session.get('admin_logged_in'):
        return jsonify({'success': False, 'error': '需要管理员权限'})
    
    try:
        manager = KnockoutManager(t_id)
        data = request.get_json()
        mode = data.get('mode', 'default')
        
        if mode == 'default':
            format_type = 'direct'
        elif mode == 'qualifier':
            format_type = 'qualifier'
        else:
            return jsonify({'success': False, 'error': '无效的模式'})
        
        result = manager.generate_quarterfinal(format_type)
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/admin-secret/tournament/<int:t_id>/auto-generate-next-round', methods=['POST'])
@admin_required
def auto_generate_next_round_api(t_id):
    """自动生成下一轮比赛对阵的API接口"""
    try:
        # 检查赛事是否存在
        tournament = db.session.get(Tournament, t_id)
        if not tournament:
            return jsonify({'success': False, 'error': '赛事不存在'})
        
        # 调用自动生成函数
        success = auto_generate_next_round_matches(t_id)
        
        if success:
            return jsonify({
                'success': True, 
                'message': '成功生成下一轮比赛对阵'
            })
        else:
            return jsonify({
                'success': False, 
                'error': '生成失败，请检查当前比赛状态'
            })
        
    except Exception as e:
        print(f"自动生成下一轮比赛失败: {e}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/admin-secret/tournament/<int:t_id>/update-knockout-bracket', methods=['POST'])
def update_knockout_bracket(t_id):
    """更新淘汰赛对阵（兼容性接口）"""
    if not session.get('admin_logged_in'):
        return jsonify({'success': False, 'error': '需要管理员权限'})
    
    try:
        success = update_knockout_bracket_logic(t_id)
        if success:
            return jsonify({
                'success': True, 
                'message': '成功更新淘汰赛对阵'
            })
        else:
            return jsonify({'success': False, 'error': '更新失败'})
        
    except Exception as e:
        print(f"更新淘汰赛对阵时出错: {e}")
        return jsonify({'success': False, 'error': f'更新失败: {str(e)}'})


def create_single_round_robin_display(t_id):
    """为小赛创建单循环赛制显示数据"""
    from sqlalchemy import text
    from collections import defaultdict
    
    # 获取所有参赛选手
    players_query = text("""
        SELECT DISTINCT p.player_id, p.name
        FROM players p
        JOIN matches m ON (p.player_id = m.player_1_id OR p.player_id = m.player_2_id)
        WHERE m.t_id = :t_id AND m.m_type IN (1, 2, 3, 14)
        ORDER BY p.name
    """)
    
    players_result = db.session.execute(players_query, {'t_id': t_id}).fetchall()
    if not players_result:
        return None
    
    # 计算每个选手的统计数据
    player_stats = {}
    for player_id, player_name in players_result:
        stats_query = text("""
            SELECT 
                SUM(CASE WHEN player_1_id = :player_id AND player_1_score > player_2_score THEN 1 ELSE 0 END) +
                SUM(CASE WHEN player_2_id = :player_id AND player_2_score > player_1_score THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN player_1_id = :player_id AND player_1_score < player_2_score THEN 1 ELSE 0 END) +
                SUM(CASE WHEN player_2_id = :player_id AND player_2_score < player_1_score THEN 1 ELSE 0 END) as losses,
                SUM(CASE WHEN player_1_id = :player_id AND player_1_score = player_2_score AND player_1_score > 0 THEN 1 ELSE 0 END) +
                SUM(CASE WHEN player_2_id = :player_id AND player_2_score = player_1_score AND player_2_score > 0 THEN 1 ELSE 0 END) as draws,
                SUM(CASE WHEN player_1_id = :player_id THEN player_1_score ELSE 0 END) +
                SUM(CASE WHEN player_2_id = :player_id THEN player_2_score ELSE 0 END) as goals_for,
                SUM(CASE WHEN player_1_id = :player_id THEN player_2_score ELSE 0 END) +
                SUM(CASE WHEN player_2_id = :player_id THEN player_1_score ELSE 0 END) as goals_against
            FROM matches
            WHERE t_id = :t_id AND m_type IN (1, 2, 3) 
            AND player_1_score IS NOT NULL AND player_2_score IS NOT NULL
            AND player_1_score >= 0 AND player_2_score >= 0
            AND (player_1_id = :player_id OR player_2_id = :player_id)
        """)
        
        stats_result = db.session.execute(stats_query, {'t_id': t_id, 'player_id': player_id}).fetchone()
        
        # 计算该选手需要打的总场次数
        total_matches = calculate_player_total_matches(t_id, player_id)
        
        player_stats[player_id] = {
            'player_id': player_id,
            'name': player_name,
            'wins': stats_result[0] or 0,
            'losses': stats_result[1] or 0,
            'draws': stats_result[2] or 0,
            'goals_for': stats_result[3] or 0,
            'goals_against': stats_result[4] or 0,
            'total_matches': total_matches,  # 添加总场次字段
        }
        player_stats[player_id]['goal_difference'] = player_stats[player_id]['goals_for'] - player_stats[player_id]['goals_against']
        player_stats[player_id]['points'] = player_stats[player_id]['wins'] * 3 + player_stats[player_id]['draws']
    
    # 应用附加赛结果到所有选手数据中
    apply_playoff_results(t_id, list(player_stats.values()))
    
    # 按积分分组，对同积分选手进行特殊排序
    from collections import defaultdict
    points_groups = defaultdict(list)
    
    for player in player_stats.values():
        points_groups[player['points']].append(player)
    
    # 重新排序
    sorted_players = []
    for points in sorted(points_groups.keys(), reverse=True):
        group = points_groups[points]
        if len(group) == 1:
            # 只有一个选手，直接添加
            sorted_players.extend(group)
        else:
            # 多个选手同积分，需要计算内部胜负关系
            ranked_group = calculate_same_points_ranking_for_round_robin(group, t_id, generate_playoffs=False)
            sorted_players.extend(ranked_group)
    
    # 分配排名
    for i, player in enumerate(sorted_players):
        player['group_rank'] = i + 1
        player['total_rank'] = i + 1
    
    # 获取所有比赛
    matches_query = text("""
        SELECT m.m_id, m.player_1_id, m.player_2_id, m.player_1_score, m.player_2_score, m.m_type,
               p1.name as player1_name, p2.name as player2_name
        FROM matches m
        JOIN players p1 ON m.player_1_id = p1.player_id
        JOIN players p2 ON m.player_2_id = p2.player_id
        WHERE m.t_id = :t_id AND m.m_type IN (1, 2, 3, 14)
        ORDER BY m.m_id
    """)
    
    matches_result = db.session.execute(matches_query, {'t_id': t_id}).fetchall()
    matches = []
    
    for match_row in matches_result:
        matches.append({
            'm_id': match_row[0],
            'player_1_id': match_row[1],
            'player_2_id': match_row[2],
            'player_1_score': match_row[3] or 0,
            'player_2_score': match_row[4] or 0,
            'm_type': match_row[5],
            'player1': {'name': match_row[6]},
            'player2': {'name': match_row[7]}
        })
    
    # 创建虚拟分组
    virtual_group = {
        'tg_id': 0,
        't_name': '单循环赛',
        'player_count': len(sorted_players),
        'expected_size': len(sorted_players),
        'players': sorted_players,
        'matches': matches
    }
    
    return {
        'groups': [virtual_group],
        'group_standings': sorted_players
    }


def auto_generate_semifinal_qualifier_matches(t_id):
    """小组赛+半决赛资格赛：所有循环赛结束，以半区为单位生成比赛"""
    try:
        from sqlalchemy import text
        
        # 检查循环赛是否完成
        if not check_round_robin_complete(t_id):
            print(f"循环赛未完成，无法生成半决赛资格赛")
            return False
        
        # 检查半决赛资格赛是否已存在
        qualifier_query = text("""
            SELECT COUNT(*) FROM matches 
            WHERE t_id = :t_id AND m_type = 9
        """)
        qualifier_count = db.session.execute(qualifier_query, {'t_id': t_id}).fetchone()[0]
        
        if qualifier_count > 0:
            print(f"半决赛资格赛已存在")
            # 检查资格赛是否完成，如果完成则生成半决赛
            return auto_generate_semifinal_from_qualifier(t_id)
        
        # 获取小组排名
        group_standings_dict = calculate_total_group_rankings(t_id)
        
        # 将字典转换为列表
        group_standings = []
        for tg_id, standings in group_standings_dict.items():
            group_standings.extend(standings)
        
        if len(group_standings) < 6:
            print(f"参赛选手不足6人，无法生成半决赛资格赛")
            return False
        
        # 按小组分组
        group_a = [p for p in group_standings if p.get('group_name') == 'A']
        group_b = [p for p in group_standings if p.get('group_name') == 'B']
        
        if len(group_a) < 3 or len(group_b) < 3:
            print(f"小组人数不足，无法生成半决赛资格赛")
            return False
        
        # 生成半决赛资格赛对阵
        # 上半区：A组第1 vs【B组第2 vs A组第3 胜者】
        # 下半区：B组第1 vs【A组第2 vs B组第3 胜者】
        
        qualifier_matches = []
        
        # 上半区资格赛：B组第2 vs A组第3
        qualifier1 = Match(
            t_id=t_id,
            m_type=9,  # 半决赛资格赛
            player_1_id=group_b[1]['player_id'],  # B组第2
            player_2_id=group_a[2]['player_id'],   # A组第3
            player_1_score=0,
            player_2_score=0
        )
        qualifier_matches.append(qualifier1)
        
        # 下半区资格赛：A组第2 vs B组第3
        qualifier2 = Match(
            t_id=t_id,
            m_type=9,  # 半决赛资格赛
            player_1_id=group_a[1]['player_id'],  # A组第2
            player_2_id=group_b[2]['player_id'],  # B组第3
            player_1_score=0,
            player_2_score=0
        )
        qualifier_matches.append(qualifier2)
        
        # 保存资格赛对阵
        for match in qualifier_matches:
            db.session.add(match)
        db.session.commit()
        
        print(f"成功生成半决赛资格赛对阵")
        return True
        
    except Exception as e:
        print(f"生成半决赛资格赛失败: {e}")
        db.session.rollback()
        return False


def auto_generate_minor_tournament_matches(t_id):
    """小赛（从第2届起）：所有循环赛结束，循环赛第1、2进金牌赛，第3、4进铜牌赛"""
    try:
        from sqlalchemy import text
        
        # 检查循环赛是否完成
        if not check_round_robin_complete(t_id):
            print(f"循环赛未完成，无法生成小赛淘汰赛")
            return False
        
        # 检查金牌赛和铜牌赛是否已存在
        existing_query = text("""
            SELECT COUNT(*) FROM matches 
            WHERE t_id = :t_id AND m_type IN (11, 12)
        """)
        existing_count = db.session.execute(existing_query, {'t_id': t_id}).fetchone()[0]
        
        if existing_count > 0:
            print(f"小赛淘汰赛已存在")
            return True
        
        # 获取循环赛排名
        round_robin_standings = calculate_round_robin_standings(t_id)
        
        if len(round_robin_standings) < 4:
            print(f"参赛选手不足4人，无法生成小赛淘汰赛")
            return False
        
        # 获取排名前4的选手
        top4_players = round_robin_standings[:4]
        
        # 生成金牌赛：第1名 vs 第2名
        gold_match = Match(
            t_id=t_id,
            m_type=12,  # 金牌赛
            player_1_id=top4_players[0]['player_id'],
            player_2_id=top4_players[1]['player_id'],
            player_1_score=0,
            player_2_score=0
        )
        
        # 生成铜牌赛：第3名 vs 第4名
        bronze_match = Match(
            t_id=t_id,
            m_type=11,  # 铜牌赛
            player_1_id=top4_players[2]['player_id'],
            player_2_id=top4_players[3]['player_id'],
            player_1_score=0,
            player_2_score=0
        )
        
        # 保存到数据库
        db.session.add(gold_match)
        db.session.add(bronze_match)
        db.session.commit()
        
        print(f"成功生成小赛淘汰赛对阵:")
        print(f"  金牌赛: {top4_players[0]['name']} vs {top4_players[1]['name']}")
        print(f"  铜牌赛: {top4_players[2]['name']} vs {top4_players[3]['name']}")
        
        return True
        
    except Exception as e:
        print(f"生成小赛淘汰赛失败: {e}")
        db.session.rollback()
        return False


def auto_generate_round_robin_knockout_matches(t_id):
    """单循环赛/双循环赛：所有循环赛结束，以半区为单位生成比赛"""
    try:
        from sqlalchemy import text
        
        # 检查循环赛是否完成
        if not check_round_robin_complete(t_id):
            print(f"循环赛未完成，无法生成淘汰赛")
            return False
        
        # 检查淘汰赛是否已存在
        knockout_query = text("""
            SELECT COUNT(*) FROM matches 
            WHERE t_id = :t_id AND m_type IN (9, 10, 11, 12)
        """)
        knockout_count = db.session.execute(knockout_query, {'t_id': t_id}).fetchone()[0]
        
        if knockout_count > 0:
            print(f"淘汰赛已存在")
            return True
        
        # 获取循环赛排名
        round_robin_standings = calculate_round_robin_standings(t_id)
        
        if len(round_robin_standings) < 6:
            print(f"参赛选手不足6人，无法生成淘汰赛")
            return False
        
        # 生成淘汰赛对阵
        # 上半区：第1 vs【第4 vs 第5 胜者】
        # 下半区：第2 vs【第3 vs 第6 胜者】
        
        knockout_matches = []
        
        # 上半区资格赛：第4 vs 第5
        qualifier1 = Match(
            t_id=t_id,
            m_type=9,  # 半决赛资格赛
            player_1_id=round_robin_standings[3]['player_id'],  # 第4名
            player_2_id=round_robin_standings[4]['player_id'],  # 第5名
            player_1_score=0,
            player_2_score=0
        )
        knockout_matches.append(qualifier1)
        
        # 下半区资格赛：第3 vs 第6
        qualifier2 = Match(
            t_id=t_id,
            m_type=9,  # 半决赛资格赛
            player_1_id=round_robin_standings[2]['player_id'],  # 第3名
            player_2_id=round_robin_standings[5]['player_id'],  # 第6名
            player_1_score=0,
            player_2_score=0
        )
        knockout_matches.append(qualifier2)
        
        # 保存淘汰赛对阵
        for match in knockout_matches:
            db.session.add(match)
        db.session.commit()
        
        print(f"成功生成单循环赛/双循环赛淘汰赛对阵")
        return True
        
    except Exception as e:
        print(f"生成单循环赛/双循环赛淘汰赛失败: {e}")
        db.session.rollback()
        return False


def auto_generate_semifinal_from_qualifier(t_id):
    """从半决赛资格赛生成半决赛"""
    try:
        from sqlalchemy import text
        
        # 检查半决赛资格赛是否完成
        qualifier_query = text("""
            SELECT COUNT(*) FROM matches 
            WHERE t_id = :t_id AND m_type = 9 AND player_1_score IS NOT NULL AND player_2_score IS NOT NULL
            AND NOT (player_1_score = 0 AND player_2_score = 0)
            AND NOT (player_1_score = -1 AND player_2_score = -1)
        """)
        qualifier_count = db.session.execute(qualifier_query, {'t_id': t_id}).fetchone()[0]
        
        if qualifier_count < 2:
            print(f"半决赛资格赛未完成")
            return False
        
        # 检查半决赛是否已存在，如果存在需要更新对阵
        semifinal_query = text("""
            SELECT COUNT(*) FROM matches 
            WHERE t_id = :t_id AND m_type = 10
        """)
        semifinal_count = db.session.execute(semifinal_query, {'t_id': t_id}).fetchone()[0]
        
        # 获取资格赛结果
        qualifier_results = text("""
            SELECT m_id, player_1_id, player_1_score, player_2_id, player_2_score
            FROM matches 
            WHERE t_id = :t_id AND m_type = 9 AND player_1_score IS NOT NULL AND player_2_score IS NOT NULL
            AND NOT (player_1_score = 0 AND player_2_score = 0)
            AND NOT (player_1_score = -1 AND player_2_score = -1)
            ORDER BY m_id
        """)
        results = db.session.execute(qualifier_results, {'t_id': t_id}).fetchall()
        
        if len(results) < 2:
            print(f"资格赛结果不完整，无法生成半决赛")
            return False
        
        # 如果半决赛已存在，需要更新对阵
        if semifinal_count > 0:
            print(f"半决赛已存在，更新对阵")
            return update_semifinal_matchups(t_id)
        
        # 获取小组排名来确定半决赛对阵
        group_standings_dict = calculate_total_group_rankings(t_id)
        
        # 将字典转换为列表
        group_standings = []
        for tg_id, standings in group_standings_dict.items():
            group_standings.extend(standings)
        
        group_a = [p for p in group_standings if p.get('group_name') == 'A']
        group_b = [p for p in group_standings if p.get('group_name') == 'B']
        
        # 确定资格赛胜者
        qualifier1_winner = results[0][1] if results[0][2] > results[0][4] else results[0][3]
        qualifier2_winner = results[1][1] if results[1][2] > results[1][4] else results[1][3]
        
        # 生成半决赛对阵
        semifinal_matches = []
        
        # 上半区：A组第1 vs 资格赛1胜者
        semifinal1 = Match(
            t_id=t_id,
            m_type=10,  # 半决赛
            player_1_id=group_a[0]['player_id'],  # A组第1
            player_2_id=qualifier1_winner,
            player_1_score=0,
            player_2_score=0
        )
        semifinal_matches.append(semifinal1)
        
        # 下半区：B组第1 vs 资格赛2胜者
        semifinal2 = Match(
            t_id=t_id,
            m_type=10,  # 半决赛
            player_1_id=group_b[0]['player_id'],  # B组第1
            player_2_id=qualifier2_winner,
            player_1_score=0,
            player_2_score=0
        )
        semifinal_matches.append(semifinal2)
        
        # 保存半决赛对阵
        for match in semifinal_matches:
            db.session.add(match)
        db.session.commit()
        
        print(f"成功生成半决赛对阵")
        return True
        
    except Exception as e:
        print(f"从资格赛生成半决赛失败: {e}")
        db.session.rollback()
        return False


def update_final_matchups(t_id):
    """更新金牌赛和铜牌赛对阵（根据半决赛结果）"""
    try:
        from sqlalchemy import text
        
        # 获取半决赛结果
        semifinal_results = text("""
            SELECT m_id, player_1_id, player_1_score, player_2_id, player_2_score
            FROM matches 
            WHERE t_id = :t_id AND m_type = 10 
            AND player_1_score IS NOT NULL AND player_2_score IS NOT NULL
            AND NOT (player_1_score = 0 AND player_2_score = 0)
            AND NOT (player_1_score = -1 AND player_2_score = -1)
            ORDER BY m_id
        """)
        results = db.session.execute(semifinal_results, {'t_id': t_id}).fetchall()
        
        if len(results) < 2:
            print(f"半决赛结果不完整，无法更新金牌赛和铜牌赛")
            return False
        
        # 确定半决赛胜者和负者
        semifinal1_winner = results[0][1] if results[0][2] > results[0][4] else results[0][3]
        semifinal1_loser = results[0][3] if results[0][2] > results[0][4] else results[0][1]
        semifinal2_winner = results[1][1] if results[1][2] > results[1][4] else results[1][3]
        semifinal2_loser = results[1][3] if results[1][2] > results[1][4] else results[1][1]
        
        # 获取金牌赛和铜牌赛
        final_matches_query = text("""
            SELECT m_id, m_type FROM matches
            WHERE t_id = :t_id AND m_type IN (11, 12)
            ORDER BY m_type
        """)
        final_matches = db.session.execute(final_matches_query, {'t_id': t_id}).fetchall()
        
        if len(final_matches) != 2:
            print(f"金牌赛和铜牌赛数量不正确: {len(final_matches)}")
            return False
        
        # 更新金牌赛对阵（两个半决赛胜者）
        gold_match_id = None
        bronze_match_id = None
        for m_id, m_type in final_matches:
            if m_type == 12:  # 金牌赛
                gold_match_id = m_id
            elif m_type == 11:  # 铜牌赛
                bronze_match_id = m_id
        
        if gold_match_id and bronze_match_id:
            # 更新金牌赛
            gold_update = text("""
                UPDATE matches 
                SET player_1_id = :p1_id, player_2_id = :p2_id, player_1_score = 0, player_2_score = 0
                WHERE m_id = :m_id
            """)
            db.session.execute(gold_update, {
                'm_id': gold_match_id,
                'p1_id': semifinal1_winner,
                'p2_id': semifinal2_winner
            })
            
            # 更新铜牌赛
            bronze_update = text("""
                UPDATE matches 
                SET player_1_id = :p1_id, player_2_id = :p2_id, player_1_score = 0, player_2_score = 0
                WHERE m_id = :m_id
            """)
            db.session.execute(bronze_update, {
                'm_id': bronze_match_id,
                'p1_id': semifinal1_loser,
                'p2_id': semifinal2_loser
            })
            
            db.session.commit()
            print(f"成功更新金牌赛和铜牌赛对阵")
            return True
        else:
            print(f"无法找到金牌赛或铜牌赛")
            return False
        
    except Exception as e:
        print(f"更新金牌赛和铜牌赛对阵失败: {e}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        return False

def auto_generate_final_matches(t_id):
    """从半决赛生成金牌赛和铜牌赛"""
    try:
        from sqlalchemy import text
        
        # 检查半决赛是否完成
        semifinal_query = text("""
            SELECT COUNT(*) FROM matches 
            WHERE t_id = :t_id AND m_type = 10 
            AND player_1_score IS NOT NULL AND player_2_score IS NOT NULL
            AND NOT (player_1_score = 0 AND player_2_score = 0)
            AND NOT (player_1_score = -1 AND player_2_score = -1)
        """)
        semifinal_count = db.session.execute(semifinal_query, {'t_id': t_id}).fetchone()[0]
        
        if semifinal_count < 2:
            print(f"半决赛未完成")
            return False
        
        # 检查金牌赛和铜牌赛是否已存在
        final_query = text("""
            SELECT COUNT(*) FROM matches 
            WHERE t_id = :t_id AND m_type IN (11, 12)
        """)
        final_count = db.session.execute(final_query, {'t_id': t_id}).fetchone()[0]
        
        # 如果金牌赛和铜牌赛已存在，需要更新对阵
        if final_count > 0:
            print(f"金牌赛和铜牌赛已存在，更新对阵")
            return update_final_matchups(t_id)
        
        # 获取半决赛结果
        semifinal_results = text("""
            SELECT m_id, player_1_id, player_1_score, player_2_id, player_2_score
            FROM matches 
            WHERE t_id = :t_id AND m_type = 10 
            AND player_1_score IS NOT NULL AND player_2_score IS NOT NULL
            AND NOT (player_1_score = 0 AND player_2_score = 0)
            AND NOT (player_1_score = -1 AND player_2_score = -1)
            ORDER BY m_id
        """)
        results = db.session.execute(semifinal_results, {'t_id': t_id}).fetchall()
        
        if len(results) != 2:
            print(f"半决赛结果不完整")
            return False
        
        # 确定半决赛胜者和负者
        semifinal1_winner = results[0][1] if results[0][2] > results[0][4] else results[0][3]
        semifinal1_loser = results[0][3] if results[0][2] > results[0][4] else results[0][1]
        semifinal2_winner = results[1][1] if results[1][2] > results[1][4] else results[1][3]
        semifinal2_loser = results[1][3] if results[1][2] > results[1][4] else results[1][1]
        
        # 生成金牌赛和铜牌赛
        final_matches = []
        
        # 金牌赛：两个半决赛胜者
        gold_match = Match(
            t_id=t_id,
            m_type=12,  # 金牌赛
            player_1_id=semifinal1_winner,
            player_2_id=semifinal2_winner,
            player_1_score=0,
            player_2_score=0
        )
        final_matches.append(gold_match)
        
        # 铜牌赛：两个半决赛负者
        bronze_match = Match(
            t_id=t_id,
            m_type=11,  # 铜牌赛
            player_1_id=semifinal1_loser,
            player_2_id=semifinal2_loser,
            player_1_score=0,
            player_2_score=0
        )
        final_matches.append(bronze_match)
        
        # 保存金牌赛和铜牌赛
        for match in final_matches:
            db.session.add(match)
        db.session.commit()
        
        print(f"成功生成金牌赛和铜牌赛对阵")
        return True
        
    except Exception as e:
        print(f"生成金牌赛和铜牌赛失败: {e}")
        db.session.rollback()
        return False


# 用户系统路由
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'GET':
        return render_template('register.html')
    
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        player_id = data.get('player_id')
        
        # 检查是否已登录管理员
        if session.get('admin_logged_in'):
            return jsonify({'success': False, 'error': '管理员已登录，请先退出管理员登录'})
        
        # 验证用户名格式
        import re
        if not re.match(r'^[a-zA-Z0-9_]{3,20}$', username):
            return jsonify({'success': False, 'error': '用户名格式不正确'})
        
        # 验证密码长度
        if len(password) < 6 or len(password) > 20:
            return jsonify({'success': False, 'error': '密码长度必须在6-20个字符之间'})
        
        # 检查用户名是否已存在
        if User.query.filter_by(username=username).first():
            return jsonify({'success': False, 'error': '用户名已存在'})
        
        # 检查选手是否已被绑定
        if player_id and User.query.filter_by(player_id=player_id).first():
            return jsonify({'success': False, 'error': '该选手已被其他用户绑定'})
        
        # 创建新用户
        user = User(username=username)
        user.set_password(password)
        if player_id:
            user.player_id = player_id
        
        db.session.add(user)
        db.session.commit()
        
        return jsonify({'success': True})
        
    except Exception as e:
        db.session.rollback()
        print(f"注册失败: {e}")
        return jsonify({'success': False, 'error': '注册失败，请重试'})


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')
    
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        
        # 检查是否已登录管理员
        if session.get('admin_logged_in'):
            return jsonify({'success': False, 'error': '管理员已登录，请先退出管理员登录'})
        
        user = User.query.filter_by(username=username).first()
        
        if not user or not user.check_password(password):
            return jsonify({'success': False, 'error': '用户名或密码错误'})
        
        # 设置session
        session['user_id'] = user.uid
        session['username'] = user.username
        session['user_logged_in'] = True
        
        return jsonify({'success': True, 'redirect': '/'})
        
    except Exception as e:
        print(f"登录失败: {e}")
        return jsonify({'success': False, 'error': '登录失败，请重试'})


@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    session.pop('user_logged_in', None)
    return redirect(url_for('index'))


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'GET':
        return render_template('forgot-password.html')
    
    try:
        data = request.get_json()
        username = data.get('username')
        new_password = data.get('newPassword')
        
        # 验证密码长度
        if len(new_password) < 6 or len(new_password) > 20:
            return jsonify({'success': False, 'error': '密码长度必须在6-20个字符之间'})
        
        user = User.query.filter_by(username=username).first()
        
        if not user:
            return jsonify({'success': False, 'error': '用户不存在'})
        
        # 更新密码
        user.set_password(new_password)
        db.session.commit()
        
        return jsonify({'success': True})
        
    except Exception as e:
        db.session.rollback()
        print(f"密码重置失败: {e}")
        return jsonify({'success': False, 'error': '密码重置失败，请重试'})


@app.route('/user/profile')
def user_profile():
    if not session.get('user_logged_in'):
        return redirect(url_for('login'))
    
    user = User.query.get(session['user_id'])
    if not user:
        return redirect(url_for('login'))
    
    # 获取选手参赛记录
    player_rankings = []
    player_rankings_by_season = {}
    seasons = []
    
    # 获取选手历史场次
    player_matches = []
    player_matches_by_season = {}
    
    if user.player:
        rankings = Ranking.query.filter_by(player_id=user.player.player_id).all()
        
        # 获取所有相关的tournament ID
        tournament_ids = set()
        for ranking in rankings:
            tournament_ids.add(ranking.tournament.t_id)
        
        # 使用SQL视图获取所有tournament的届次信息
        from sqlalchemy import text
        if tournament_ids:
            placeholders = ','.join([':t_id' + str(i) for i in range(len(tournament_ids))])
            view_query = text(f"""
                SELECT t_id, type_session_number
                FROM tournament_session_view
                WHERE t_id IN ({','.join([':t_id' + str(i) for i in range(len(tournament_ids))])})
            """)
            
            params = {f't_id{i}': t_id for i, t_id in enumerate(tournament_ids)}
            result = db.session.execute(view_query, params)
            tournament_numbers = {row.t_id: row.type_session_number for row in result}
        else:
            tournament_numbers = {}
        
        # 按赛季和类型分组参赛记录
        for ranking in rankings:
            tournament = ranking.tournament
            tournament.type_session_number = tournament_numbers.get(tournament.t_id)
            season_year = tournament.season.year if tournament.season else tournament.season_id
            
            if season_year not in player_rankings_by_season:
                player_rankings_by_season[season_year] = {}
            
            tournament_type = tournament.type
            if tournament_type not in player_rankings_by_season[season_year]:
                player_rankings_by_season[season_year][tournament_type] = []
            
            player_rankings_by_season[season_year][tournament_type].append(ranking)
            player_rankings.append(ranking)
        
        # 获取选手历史场次
        matches = Match.query.filter(
            (Match.player_1_id == user.player.player_id) | 
            (Match.player_2_id == user.player.player_id)
        ).all()
        
        # 过滤掉未进行的比赛（0-0或-1:-1）
        valid_matches = []
        match_tournament_ids = set()
        for match in matches:
            # 检查是否为未进行的比赛
            if (match.player_1_score == 0 and match.player_2_score == 0) or \
               (match.player_1_score == -1 and match.player_2_score == -1):
                continue
            valid_matches.append(match)
            match_tournament_ids.add(match.tournament.t_id)
        
        # 为历史场次的tournament获取届次信息
        if match_tournament_ids:
            # 合并所有tournament ID
            all_tournament_ids = tournament_ids.union(match_tournament_ids)
            if len(all_tournament_ids) > len(tournament_ids):
                # 如果有新的tournament ID，重新查询
                placeholders = ','.join([':t_id' + str(i) for i in range(len(all_tournament_ids))])
                view_query = text(f"""
                    SELECT t_id, type_session_number
                    FROM tournament_session_view
                    WHERE t_id IN ({','.join([':t_id' + str(i) for i in range(len(all_tournament_ids))])})
                """)
                
                params = {f't_id{i}': t_id for i, t_id in enumerate(all_tournament_ids)}
                result = db.session.execute(view_query, params)
                tournament_numbers = {row.t_id: row.type_session_number for row in result}
        
        # 按赛季和类型分组场次
        for match in valid_matches:
            tournament = match.tournament
            tournament.type_session_number = tournament_numbers.get(tournament.t_id)
            season_year = tournament.season.year if tournament.season else tournament.season_id
            
            if season_year not in player_matches_by_season:
                player_matches_by_season[season_year] = {}
            
            tournament_type = tournament.type
            if tournament_type not in player_matches_by_season[season_year]:
                player_matches_by_season[season_year][tournament_type] = []
            
            player_matches_by_season[season_year][tournament_type].append(match)
            player_matches.append(match)
        
        # 获取所有赛季
        seasons = Season.query.order_by(Season.year.desc()).all()
    
    return render_template('user-profile.html', 
                         user=user, 
                         player_rankings=player_rankings,
                         player_rankings_by_season=player_rankings_by_season,
                         player_matches=player_matches,
                         player_matches_by_season=player_matches_by_season,
                         seasons=seasons,
                         **inject_formats())


@app.route('/user/bind-player', methods=['POST'])
def bind_player():
    if not session.get('user_logged_in'):
        return jsonify({'success': False, 'error': '请先登录'})
    
    try:
        data = request.get_json()
        player_id = data.get('player_id')
        
        user = User.query.get(session['user_id'])
        if not user:
            return jsonify({'success': False, 'error': '用户不存在'})
        
        # 检查选手是否已被绑定
        existing_user = User.query.filter_by(player_id=player_id).first()
        if existing_user and existing_user.uid != user.uid:
            return jsonify({'success': False, 'error': '该选手已被其他用户绑定'})
        
        # 绑定选手
        user.player_id = player_id
        db.session.commit()
        
        return jsonify({'success': True})
        
    except Exception as e:
        db.session.rollback()
        print(f"绑定选手失败: {e}")
        return jsonify({'success': False, 'error': '绑定失败，请重试'})


@app.route('/user/unbind-player', methods=['POST'])
def unbind_player():
    if not session.get('user_logged_in'):
        return jsonify({'success': False, 'error': '请先登录'})
    
    try:
        user = User.query.get(session['user_id'])
        if not user:
            return jsonify({'success': False, 'error': '用户不存在'})
        
        # 解绑选手
        user.player_id = None
        db.session.commit()
        
        return jsonify({'success': True})
        
    except Exception as e:
        db.session.rollback()
        print(f"解绑选手失败: {e}")
        return jsonify({'success': False, 'error': '解绑失败，请重试'})


@app.route('/api/players')
def api_players():
    """获取所有选手列表"""
    try:
        players = Player.query.filter_by(status=1).all()
        return jsonify({
            'success': True,
            'players': [{'player_id': p.player_id, 'name': p.name} for p in players]
        })
    except Exception as e:
        print(f"获取选手列表失败: {e}")
        return jsonify({'success': False, 'error': '获取选手列表失败'})


# 用户权限装饰器
def user_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


# 管理员解绑用户选手
@app.route('/admin-secret/users/<int:uid>/unbind-player', methods=['POST'])
@admin_required
def admin_unbind_user_player(uid):
    try:
        user = User.query.get_or_404(uid)
        user.player_id = None
        db.session.commit()
        flash('已解绑用户选手')
    except Exception as e:
        db.session.rollback()
        print(f"解绑用户选手失败: {e}")
        flash('解绑失败')
    return redirect(url_for('admin_index'))


# 赛事报名页面
@app.route('/tournament/<int:t_id>/signup')
def tournament_signup(t_id):
    tournament = Tournament.query.get_or_404(t_id)
    
    # 使用SQL视图获取该届次的序号
    from sqlalchemy import text
    view_query = text("""
        SELECT type_session_number
        FROM tournament_session_view
        WHERE t_id = :t_id
    """)
    
    result = db.session.execute(view_query, {'t_id': t_id})
    row = result.fetchone()
    if row:
        tournament.type_session_number = row.type_session_number
    else:
        tournament.type_session_number = None
    
    # 获取当前用户信息
    current_user = None
    user_signed_up = False
    user_signup = None
    signup_closed = False
    
    if session.get('user_logged_in'):
        current_user = User.query.get(session['user_id'])
        
        # 检查是否已报名
        user_signup = Signup.query.filter_by(u_id=current_user.uid, t_id=t_id).first()
        user_signed_up = user_signup is not None
        
        # 检查报名是否已截止
        if tournament.signup_deadline:
            from datetime import datetime
            try:
                deadline_dt = datetime.fromisoformat(tournament.signup_deadline)
                signup_closed = datetime.now() > deadline_dt
            except ValueError:
                signup_closed = False
    
    return render_template('tournament-signup.html', 
                         tournament=tournament,
                         current_user=current_user,
                         user_signed_up=user_signed_up,
                         user_signup=user_signup,
                         signup_closed=signup_closed)


# 赛事报名提交
@app.route('/tournament/<int:t_id>/signup', methods=['POST'])
def submit_tournament_signup(t_id):
    if not session.get('user_logged_in'):
        return jsonify({'success': False, 'error': '请先登录'})
    
    try:
        tournament = Tournament.query.get_or_404(t_id)
        user = User.query.get(session['user_id'])
        
        if not user.player_id:
            return jsonify({'success': False, 'error': '请先绑定选手'})
        
        # 检查报名是否已截止
        if tournament.signup_deadline:
            from datetime import datetime
            try:
                deadline_dt = datetime.fromisoformat(tournament.signup_deadline)
                if datetime.now() > deadline_dt:
                    return jsonify({'success': False, 'error': '报名已截止'})
            except ValueError:
                pass  # 如果日期格式错误，忽略截止时间检查
        
        # 检查是否已报名
        existing_signup = Signup.query.filter_by(u_id=user.uid, t_id=t_id).first()
        if existing_signup:
            return jsonify({'success': False, 'error': '您已报名此赛事'})
        
        # 创建报名记录
        signup = Signup(u_id=user.uid, t_id=t_id)
        db.session.add(signup)
        db.session.commit()
        
        return jsonify({'success': True})
        
    except Exception as e:
        db.session.rollback()
        print(f"报名失败: {e}")
        return jsonify({'success': False, 'error': '报名失败，请重试'})


# 检查用户是否有权限修改比赛比分
def can_user_edit_match(match, user_id=None):
    """检查用户是否有权限修改比赛比分"""
    # 管理员可以修改所有比赛
    if session.get('admin_logged_in'):
        return True
    
    # 普通用户只能修改自己选手的比赛
    if session.get('user_logged_in') and user_id:
        user = User.query.get(user_id)
        if user and user.player_id:
            # 检查比赛是否包含该用户的选手
            return match.player_1_id == user.player_id or match.player_2_id == user.player_id
    
    return False


if __name__ == '__main__':
    init_db()
    app.run(debug=False, host='0.0.0.0', port=8080, threaded=True)
