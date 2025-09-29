// API 调用封装
const API_BASE = '';

class ApiClient {
    async request(url, options = {}) {
        try {
            const response = await fetch(API_BASE + url, {
                headers: {
                    'Content-Type': 'application/json',
                    ...options.headers
                },
                ...options
            });
            
            const data = await response.json();
            
            if (!response.ok) {
                throw new Error(data.error || '请求失败');
            }
            
            return data;
        } catch (error) {
            console.error('API请求错误:', error);
            throw error;
        }
    }

    // 获取所有赛事
    async getTournaments() {
        return this.request('/api/tournaments');
    }

    // 获取赛事详情
    async getTournament(id) {
        return this.request(`/api/tournament/${id}`);
    }

    // 获取所有选手
    async getPlayers() {
        return this.request('/api/players');
    }

    // 获取赛事比赛
    async getMatches(tournamentId) {
        return this.request(`/api/matches/${tournamentId}`);
    }

    // 提交比赛结果
    async submitMatchResult(matchData) {
        return this.request('/api/match/submit', {
            method: 'POST',
            body: JSON.stringify(matchData)
        });
    }
}

// 全局API客户端
window.api = new ApiClient();

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', function() {
    initializeApp();
});

async function initializeApp() {
    try {
        // 检查API状态
        const status = await window.api.request('/api/status');
        console.log('API状态:', status);
        
        // 加载页面内容
        await loadHomePage();
    } catch (error) {
        console.error('初始化失败:', error);
        showError('应用初始化失败，请刷新页面重试');
    }
}

async function loadHomePage() {
    try {
        const tournamentsData = await window.api.getTournaments();
        
        // 更新页面内容
        const loading = document.getElementById('loading');
        const container = document.getElementById('content');
        
        if (loading && container) {
            loading.style.display = 'none';
            container.style.display = 'block';
            container.innerHTML = generateTournamentsHTML(tournamentsData.tournaments);
        }
    } catch (error) {
        console.error('加载首页失败:', error);
        showError('加载赛事列表失败');
    }
}

function generateTournamentsHTML(tournaments) {
    if (!tournaments || tournaments.length === 0) {
        return '<div class="no-data">暂无赛事</div>';
    }
    
    let html = '<div class="tournaments-list">';
    tournaments.forEach(tournament => {
        html += `
            <div class="tournament-card" onclick="loadTournament(${tournament.t_id})">
                <h3>${tournament.t_name}</h3>
                <p>参赛人数: ${tournament.player_count}</p>
                <p>状态: ${getTournamentStatus(tournament.t_status)}</p>
            </div>
        `;
    });
    html += '</div>';
    
    return html;
}

function getTournamentStatus(status) {
    const statusMap = {
        0: '未开始',
        1: '进行中',
        2: '已结束'
    };
    return statusMap[status] || '未知';
}

async function loadTournament(tournamentId) {
    try {
        const tournamentData = await window.api.getTournament(tournamentId);
        const matchesData = await window.api.getMatches(tournamentId);
        
        // 更新页面内容
        const container = document.getElementById('content');
        if (container) {
            container.innerHTML = generateTournamentHTML(tournamentData.tournament, matchesData.matches);
        }
        
        // 更新页面标题
        document.title = `${tournamentData.tournament.t_name} - 冰壶大师赛`;
    } catch (error) {
        console.error('加载赛事详情失败:', error);
        showError('加载赛事详情失败');
    }
}

function generateTournamentHTML(tournament, matches) {
    let html = `
        <div class="tournament-detail">
            <button class="back-button" onclick="goHome()">← 返回首页</button>
            
            <h1>${tournament.t_name}</h1>
            
            ${tournament.season ? `<p class="season">${tournament.season.year} - 第${tournament.type_session_number}届</p>` : ''}
            
            <div class="tournament-info">
                <div class="info-item">
                    <label>格式:</label>
                    <span>${tournament.format_name}</span>
                </div>
                <div class="info-item">
                    <label>参赛人数:</label>
                    <span>${tournament.player_count || 0}</span>
                </div>
                <div class="info-item">
                    <label>状态:</label>
                    <span>${getTournamentStatus(tournament.t_status)}</span>
                </div>
                <div class="info-item">
                    <label>类型:</label>
                    <span>${getTournamentType(tournament.type)}</span>
                </div>
            </div>
            
            ${tournament.description ? `<div class="description"><h3>赛事说明</h3><p>${tournament.description}</p></div>` : ''}
            
            ${tournament.participants && tournament.participants.length > 0 ? `
                <div class="participants-section">
                    <h3>参赛选手</h3>
                    <div class="participants-grid">
                        ${tournament.participants.map(p => `
                            <div class="participant-card">
                                <span class="participant-name">${p.name}</span>
                                ${p.handicap ? `<span class="participant-handicap">让杆: ${p.handicap}</span>` : ''}
                            </div>
                        `).join('')}
                    </div>
                </div>
            ` : ''}
            
            ${tournament.groups && tournament.groups.length > 0 ? `
                <div class="groups-section">
                    <h3>小组信息</h3>
                    <div class="groups-grid">
                        ${tournament.groups.map(g => `
                            <div class="group-card">
                                <span class="group-name">${g.group_name}</span>
                                <span class="group-count">${g.player_count}人</span>
                            </div>
                        `).join('')}
                    </div>
                </div>
            ` : ''}
            
            <div class="matches-section">
                <h3>比赛列表</h3>
                <div class="matches-list">
    `;
    
    if (matches && matches.length > 0) {
        matches.forEach(match => {
            html += `
                <div class="match-card">
                    <div class="match-players">
                        <span class="player1">${match.player_1 || '未定'}</span>
                        <span class="vs">vs</span>
                        <span class="player2">${match.player_2 || '未定'}</span>
                    </div>
                    <div class="match-score">
                        <span class="score">${match.player_1_score || 0} : ${match.player_2_score || 0}</span>
                    </div>
                    <div class="match-type">${getMatchType(match.m_type)}</div>
                </div>
            `;
        });
    } else {
        html += '<div class="no-data">暂无比赛</div>';
    }
    
    html += `
                </div>
            </div>
        </div>
    `;
    
    return html;
}

function getTournamentType(type) {
    const typeMap = {
        1: '正赛',
        2: '小赛 (CM250)',
        3: '总决赛'
    };
    return typeMap[type] || '未知类型';
}

function getMatchType(mType) {
    const typeMap = {
        1: '小组赛',
        2: '小组赛',
        3: '小组赛',
        7: '升降赛',
        8: '1/4决赛',
        9: '半决赛资格赛',
        10: '半决赛',
        11: '铜牌赛',
        12: '金牌赛',
        13: '1/4决赛资格赛',
        14: '晋级赛',
        15: '胜者组',
        16: '败者组',
        17: '双败淘汰赛决赛'
    };
    return typeMap[mType] || '未知';
}

function showError(message) {
    const loading = document.getElementById('loading');
    const container = document.getElementById('content');
    
    if (loading && container) {
        loading.style.display = 'none';
        container.style.display = 'block';
        container.innerHTML = `<div class="error-message">${message}</div>`;
    }
}

// 返回首页
function goHome() {
    loadHomePage();
}
