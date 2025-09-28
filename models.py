from db import db
from werkzeug.security import generate_password_hash, check_password_hash


class Season(db.Model):
    __tablename__ = 'seasons'
    season_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    year = db.Column(db.String)

    def __repr__(self):
        return f'<Season {self.year}>'


class Tournament(db.Model):
    __tablename__ = 'tournament'
    t_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    season_id = db.Column(db.Integer, db.ForeignKey('seasons.season_id'), nullable=False)
    type = db.Column(db.Integer, nullable=False)
    # 赛制：参见 README 或前端映射
    t_format = db.Column(db.Integer, nullable=True)
    # 每届比赛的参赛人数（用于填写历届比赛选手排名）
    player_count = db.Column(db.Integer, nullable=True)
    # 报名截止时间
    signup_deadline = db.Column(db.String, nullable=True)
    # 赛事状态：1=正常, 2=取消
    status = db.Column(db.Integer, nullable=False, default=1)

    season = db.relationship('Season', backref=db.backref('tournaments', lazy=True))

    def __repr__(self):
        return f'<Tournament {self.t_id}>'


class Player(db.Model):
    __tablename__ = 'players'
    player_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String, unique=True)
    # status: 1=参与当前排名, 2=不参与当前排名, 3=不可用
    status = db.Column(db.Integer, nullable=False, default=1)

    def __repr__(self):
        return f'<Player {self.name}>'


class Match(db.Model):
    __tablename__ = 'matches'
    m_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    t_id = db.Column(db.Integer, db.ForeignKey('tournament.t_id'), nullable=False)
    # 比赛场次类型（m_type）：用于区分小组赛/淘汰赛/决赛等
    m_type = db.Column(db.Integer, nullable=True)
    player_1_id = db.Column(db.Integer, db.ForeignKey('players.player_id'), nullable=False)
    player_1_score = db.Column(db.Integer, nullable=False)
    player_2_id = db.Column(db.Integer, db.ForeignKey('players.player_id'), nullable=False)
    player_2_score = db.Column(db.Integer, nullable=False)

    player1 = db.relationship('Player', foreign_keys=[player_1_id])
    player2 = db.relationship('Player', foreign_keys=[player_2_id])
    tournament = db.relationship('Tournament', backref=db.backref('matches', lazy=True))

    def winner_id(self):
        if self.player_1_score > self.player_2_score:
            return self.player_1_id
        if self.player_2_score > self.player_1_score:
            return self.player_2_id
        return None

    def to_dict(self):
        return {
            'm_id': self.m_id,
            't_id': self.t_id,
            'player_1_id': self.player_1_id,
            'player_1_score': self.player_1_score,
            'player_2_id': self.player_2_id,
            'player_2_score': self.player_2_score,
            'winner_id': self.winner_id()
        }


class Ranking(db.Model):
    __tablename__ = 'rankings'
    r_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    t_id = db.Column(db.Integer, db.ForeignKey('tournament.t_id'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('players.player_id'), nullable=False)
    ranks = db.Column(db.Integer, nullable=False)
    scores = db.Column(db.Integer, nullable=True)

    player = db.relationship('Player')
    tournament = db.relationship('Tournament')


class Manager(db.Model):
    __tablename__ = 'managers'
    manager_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String, nullable=False)
    # store hashed password
    password = db.Column(db.String, nullable=False)

    def __repr__(self):
        return f'<Manager {self.username}>'

    def set_password(self, raw_password: str):
        self.password = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password, raw_password)


class User(db.Model):
    __tablename__ = 'users'
    uid = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String, unique=True, nullable=False)
    password = db.Column(db.String, nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('players.player_id'), nullable=True)
    role = db.Column(db.Integer, nullable=False, default=0)  # 0=普通用户, 1=管理员
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    
    player = db.relationship('Player', backref=db.backref('users', lazy=True))

    def __repr__(self):
        return f'<User {self.username}>'

    def set_password(self, raw_password: str):
        self.password = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password, raw_password)


class Signup(db.Model):
    __tablename__ = 'signups'
    s_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    u_id = db.Column(db.Integer, db.ForeignKey('users.uid'), nullable=False)
    t_id = db.Column(db.Integer, db.ForeignKey('tournament.t_id'), nullable=False)
    
    user = db.relationship('User', backref=db.backref('signups', lazy=True))
    tournament = db.relationship('Tournament', backref=db.backref('signups', lazy=True))

    def __repr__(self):
        return f'<Signup {self.u_id} -> {self.t_id}>'


