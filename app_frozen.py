#!/usr/bin/env python3
"""
Frozen-Flask 应用
专门用于生成静态站点的 Flask 应用
参考：https://github.com/Frozen-Flask/Frozen-Flask
"""

import os
from flask import Flask, render_template, url_for

app = Flask(__name__)

# 设置模板和静态文件夹
app.template_folder = 'templates'
app.static_folder = 'static'

# 模拟数据（静态站点）
MOCK_TOURNAMENTS = [
    {
        't_id': 1,
        't_name': '2025冰壶大师赛',
        't_format': 3,
        'player_count': 8,
        't_status': 1,
        'season': {'year': 2025, 'season_name': '春季'},
        'type_session_number': 1
    },
    {
        't_id': 2,
        't_name': '2025CM250系列',
        't_format': 1,
        'player_count': 4,
        't_status': 0,
        'season': {'year': 2025, 'season_name': '春季'},
        'type_session_number': 1
    },
    {
        't_id': 3,
        't_name': '2025总决赛',
        't_format': 2,
        'player_count': 16,
        't_status': 2,
        'season': {'year': 2024, 'season_name': '秋季'},
        'type_session_number': 2
    }
]

MOCK_PLAYERS = [
    {'player_id': 1, 'name': '张小明', 'handicap': 5},
    {'player_id': 2, 'name': '李小红', 'handicap': 3},
    {'player_id': 3, 'name': '王大华', 'handicap': 7},
    {'player_id': 4, 'name': '赵小龙', 'handicap': 4},
    {'player_id': 5, 'name': '陈大力', 'handicap': 6},
    {'player_id': 6, 'name': '刘小美', 'handicap': 2},
    {'player_id': 7, 'name': '周小龙', 'handicap': 8},
    {'player_id': 8, 'name': '吴大辉', 'handicap': 4},
]
}

MOCK_MATCHES = {
    1: [  # 大师赛
        {'match_id': 1, 'player_1': '张小明', 'player_2': '李小红', 'player_1_score': 6, 'player_2_score': 4, 'm_type': 1},
        {'match_id': 2, 'player_1': '王大华', 'player_2': '赵小龙', 'player_1_score': 5, 'player_2_score': 7, 'm_type': 1},
        {'match_id': 3, 'player_1': '张小明', 'player_2': '王大华', 'player_1_score': 8, 'player_2_score': 2, 'm_type': 10},
        {'match_id': 4, 'player_1': '李小红', 'player_2': '赵小龙', 'player_1_score': 3, 'player_2_score': 9, 'm_type': 11},
    ],
    2: [  # CM250系列
        {'match_id': 5, 'player_1': '张小明', 'player_2': '赵小龙', 'player_1_score': 6, 'player_2_score': 4, 'm_type': 10},
        {'match_id': 6, 'player_1': '李小红', 'player_2': '王大华', 'player_1_score': 5, 'player_2_score': 7, 'm_type': 12},
    ],
    3: []  # 总决赛暂无比赛
}

@app.route('/')
def index():
    """首页"""
    return render_template('index.html', tournaments=MOCK_TOURNAMENTS)

@app.route('/tournament/<int:t_id>')
def tournament_detail(t_id):
    """赛事详情页"""
    tournament = None
    for t in MOCK_TOURNAMENTS:
        if t['t_id'] == t_id:
            tournament = t
            break
    
    if not tournament:
        return render_template('404.html'), 404
    
    matches = MOCK_MATCHES.get(t_id, [])
    return render_template('tournament.html', 
                         tournament=tournament, 
                         matches=matches,
                         participants=MOCK_PLAYERS)

@app.route('/player/<int:player_id>')
def player_profile(player_id):
    """选手档案"""
    player = None
    for p in MOCK_PLAYERS:
        if p['player_id'] == player_id:
            player = p
            break
    
    if not player:
        return render_template('404.html'), 404
    
    return render_template('player.html', player=player)

@app.route('/season/<int:year>')
def season_calendar(year):
    """赛季日历"""
    season_tournaments = [t for t in MOCK_TOURNAMENTS if t['season']['year'] == year]
    return render_template('season.html', 
                         year=year, 
                         tournaments=season_tournaments)

@app.route('/login')
def login():
    """登录页面"""
    return render_template('login.html')

@app.route('/register')
def register():
    """注册页面"""
    return render_template('register.html')

@app.route('/about')
def about():
    """关于页面"""
    return render_template('about.html') if os.path.exists('templates/about.html') else 'About page'

@app.route('/contact')
def contact():
    """联系页面"""
    return render_template('contact.html') if os.path.exists('templates/contact.html') else 'Contact page'

# 错误处理
@app.errorhandler(404)
def not_found(error):
    if os.path.exists('templates/404.html'):
        return render_template('404.html'), 404
    return 'Page Not Found', 404

if __name__ == '__main__':
    app.run(debug=True)
