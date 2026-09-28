"""Key 授权后台管理系统（keyserver）。

独立于 materialsorting 消费端的授权服务：key 生成/绑定/合并/校验扣次/续期/删除
全生命周期 + SQLite 唯一账本（服务端权威）。**禁 import materialsorting**（独立
系统，依赖方向红线，tests AST 守卫锁定）。

模块结构（US-001 起逐故事落地）：
  - ``app.py``     FastAPI 装配 + main()（uvicorn，端口 env MS_KEY_PORT 缺省 8110）
                   + GET /api/key/health；
  - ``db.py``      sqlite3 连接工厂（WAL + busy_timeout=5000 + ensure_schema 自动
                   建表；DB 路径 env MS_KEY_DB 可重定位，缺省 <部署目录>/data/keys.db）；
  - ``models.py``  derive_status(row, now) 纯函数 —— 六态状态机单一真相源；
  - ``keygen.py``  new_key_plaintext()（MS-XXXXX-XXXXX-XXXXX，去混淆字母表）；
  - ``repo.py``    三表读写（keys / key_daily_usage / key_op_log）。
"""
