#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Flask API应用 - 专为Netlify Functions优化
提供REST API接口，返回JSON数据供前端调用
"""

import os
from flask import Flask, request, jsonify, session
from dotenv import load_dotenv

load_dotenv()

from sqlalchemy.pool import NullPool
from sqlalchemy.exc import OperationalError as SAOperationalError
import time
from sqlalchemy import text

app = Flask(__name__)

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

# 导入模型
from models import *

def check_db_connection():
    """检查数据库连接"""
    try:
        # 尝试执行简单查询
        result = db.session.execute(text("SELECT 1")).fetchone()
        return True
    except Exception as e:
        print(f"数据库连接错误: {e}")
        return False

# API 路由

@app.route('/api/status')
def api_status():
    """API状态检查"""
    db_status = check_db_connection()
    return jsonify({
        'status': 'ok',
        'database': 'connected' if db_status else 'error',
        'message': 'Flask API is running'
    })

@app.route('/api/tournaments')
def api_tournaments():
    """获取所有赛事"""
    try:
        tournaments = Tournament.query.all()
        tournaments_data = []
        for tournament in tournaments:
            tournaments_data.append({
                't_id': tournament.t_id,
                't_name': tournament.t_name,
                't_format': tournament.t_format,
                'player_count': tournament.player_count,
                't_status': tournament.t_status
            })
        return jsonify({
            'success': True,
            'tournaments': tournaments_data
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/tournament/<int:t_id>')
def api_tournament_detail(t_id):
    """获取赛事详情"""
    try:
        tournament = db.session.get(Tournament, t_id)
        if not tournament:
            return jsonify({
                'success': False,
                'error': '赛事不存在'
            }), 404
        
        # 获取赛季信息
        season_info = None
        if tournament.season:
            season_info = {
                'year': tournament.season.year,
                'season_name': tournament.season.season_name
            }
        
        # 获取赛事类型信息
        format_names = {
            1: '小组赛+半决赛',
            2: '小组赛+1/4决赛+半决赛', 
            3: '小组赛+1/4决赛+半决赛+决赛',
            4: '单循环赛',
            5: '双循环赛',
            6: '三循环赛',
            7: '双败淘汰赛',
            8: '其他'
        }
        
        # 获取选手信息
        participants = db.session.execute(text("""
            SELECT DISTINCT p.player_id, p.name, p.handicap
            FROM players p
            JOIN tg_players tgp ON p.player_id = tgp.player_id
            JOIN tgroups tg ON tgp.tg_id = tg.tg_id
            WHERE tg.t_id = :t_id
            ORDER BY p.name
        """), {'t_id': t_id}).fetchall()
        
        participants_data = [
            {'player_id': row[0], 'name': row[1], 'handicap': row[2]} 
            for row in participants
        ]
        
        # 获取小组信息
        groups = db.session.execute(text("""
            SELECT tg.tg_id, tg.group_name, COUNT(tgp.player_id) as player_count
            FROM tgroups tg
            LEFT JOIN tg_players tgp ON tg.tg_id = tgp.tg_id
            WHERE tg.t_id = :t_id
            GROUP BY tg.tg_id, tg.group_name
            ORDER BY tg.group_name
        """), {'t_id': t_id}).fetchall()
        
        groups_data = [
            {'group_id': row[0], 'group_name': row[1], 'player_count': row[2]}
            for row in groups
        ]
        
        tournament_data = {
            't_id': tournament.t_id,
            't_name': tournament.t_name,
            't_format': tournament.t_format,
            'format_name': format_names.get(tournament.t_format, '未知格式'),
            'player_count': tournament.player_count,
            't_status': tournament.t_status,
            'type': tournament.type,
            'type_session_number': tournament.type_session_number,
            'season': season_info,
            'participants': participants_data,
            'groups': groups_data,
            'signup_deadline': tournament.signup_deadline.isoformat() if tournament.signup_deadline else None,
            'signup_open': tournament.signup_open,
            'description': tournament.description
        }
        
        return jsonify({
            'success': True,
            'tournament': tournament_data
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/players')
def api_players():
    """获取所有选手"""
    try:
        players = Player.query.all()
        players_data = []
        for player in players:
            players_data.append({
                'player_id': player.player_id,
                'name': player.name,
                'handicap': player.handicap
            })
        return jsonify({
            'success': True,
            'players': players_data
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/matches/<int:t_id>')
def api_tournament_matches(t_id):
    """获取赛事的所有比赛"""
    try:
        matches = Match.query.filter(Match.t_id == t_id).all()
        matches_data = []
        for match in matches:
            matches_data.append({
                'match_id': match.match_id,
                'player_1_id': match.player_1_id,
                'player_2_id': match.player_2_id,
                'player_1_score': match.player_1_score,
                'player_2_score': match.player_2_score,
                'm_type': match.m_type,
                'player_1': match.player_1.name if match.player_1 else None,
                'player_2': match.player_2.name if match.player_2 else None
            })
        
        return jsonify({
            'success': True,
            'matches': matches_data
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api', methods=['GET'])
def api_home():
    """API首页"""
    return jsonify({
        'message': '冰壶大师赛 API',
        'version': '1.0',
        'endpoints': {
            'status': '/api/status',
            'tournaments': '/api/tournaments',
            'tournament': '/api/tournament/{id}',
            'players': '/api/players',
            'matches': '/api/matches/{tournament_id}'
        }
    })

# 错误处理
@app.errorhandler(404)
def not_found(error):
    return jsonify({
        'success': False,
        'error': '页面不存在'
    }), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        'success': False,
        'error': '服务器内部错误'
    }), 500

if __name__ == '__main__':
    app.run(debug=True)
