# Curling Masters - 本地网站

这是一个基于 Flask 的示例网站，绑定到仓库根目录的 `curling_masters.db` SQLite 数据库，也支持通过环境变量 `DATABASE_URL` 切换到远程数据库（例如 Turso）。

快速开始（Windows PowerShell）:

```powershell
python -m venv .venv; .venv\Scripts\Activate.ps1
pip install -r requirements.txt
# (可选) 设置远程数据库: $env:DATABASE_URL = 'postgresql://user:pass@host/db'
python app.py
```

默认路由:
- / : 赛季列表
- /season/<id> : 赛季详情与比赛
- /tournament/<id> : 比赛详情与场次
- /player/<id> : 选手详情

隐藏后台管理（不在站点导航中）:
- /admin-secret : 管理员管理页面（添加管理员等）

切换数据库:
在运行前设置 `DATABASE_URL` 环境变量，格式根据目标数据库而定。若未设置，程序会自动使用仓库根目录的 `curling_masters.db`。
