#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
碎碎念 · 云服务器版（PostgreSQL + 用户系统）
- 数据库：PostgreSQL（环境变量 DATABASE_URL）
- 用户系统：注册/登录/Token认证
- 数据隔离：每个用户只能操作自己的数据
- 冷启动容错：Neon休眠唤醒自动重试
"""
import os, hashlib, time, base64
from datetime import datetime
import datetime as dt
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__)

# 中国时区
CN_TZ = dt.timezone(dt.timedelta(hours=8))
def cn_time(fmt='%m-%d %H:%M'):
    return datetime.now(CN_TZ).strftime(fmt)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ★★★ Railway 关键：必须使用 /tmp 目录，其他路径只读 ★★★
UPLOAD_DIR = '/tmp/uploads'
AVATAR_DIR = '/tmp/uploads/avatars'
os.makedirs(AVATAR_DIR, exist_ok=True)

app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 限制 16MB

# ===== PostgreSQL（读取环境变量，禁止硬编码） =====
DATABASE_URL = os.environ.get('DATABASE_URL', '')
if not DATABASE_URL:
    raise RuntimeError('❌ 请设置环境变量 DATABASE_URL（PostgreSQL连接串）')

import psycopg2
import psycopg2.extras

def get_conn(retries=3):
    """获取数据库连接，支持重试（冷启动容错：指数退避）"""
    for i in range(retries):
        try:
            conn = psycopg2.connect(DATABASE_URL, connect_timeout=8)
            conn.autocommit = True
            # ★ Neon免费版：每次连接设置search_path到自定义schema ★
            cur = conn.cursor()
            cur.execute("SET search_path TO sui")
            cur.close()
            return conn
        except Exception as e:
            if i < retries - 1:
                time.sleep(2 ** i)  # 1s, 2s, 4s
                continue
            raise e

def init_db():
    """启动时尝试建表，若权限不足则只警告（表须在Neon SQL Editor中手动创建）"""
    print('⏳ 正在初始化数据库...')
    conn = get_conn()
    try:
        cur = conn.cursor()
        # ★★★ Neon免费版无public权限，创建自定义schema并设为默认 ★★★
        cur.execute("CREATE SCHEMA IF NOT EXISTS sui")
        cur.execute("SET search_path TO sui")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password VARCHAR(100) NOT NULL,
                nickname VARCHAR(50) DEFAULT '',
                avatar VARCHAR(50) DEFAULT '🌸',
                color VARCHAR(20) DEFAULT '#7C4DFF',
                theme TEXT DEFAULT '{}',
                token VARCHAR(64) UNIQUE,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                text TEXT DEFAULT '',
                mood VARCHAR(50) DEFAULT '',
                time VARCHAR(20) DEFAULT '',
                visible VARCHAR(20) DEFAULT 'public',
                visible_to TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS comments (
                id SERIAL PRIMARY KEY,
                post_id INTEGER REFERENCES posts(id) ON DELETE CASCADE,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                text TEXT DEFAULT '',
                time VARCHAR(20) DEFAULT '',
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS diaries (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                title TEXT DEFAULT '',
                content TEXT DEFAULT '',
                mood VARCHAR(50) DEFAULT '',
                date VARCHAR(20) DEFAULT '',
                time VARCHAR(20) DEFAULT '',
                color VARCHAR(20) DEFAULT '#7C4DFF',
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        # 图片支持迁移（老表加列）
        for tbl in ['posts', 'diaries']:
            try:
                cur.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS image TEXT DEFAULT ''")
            except Exception:
                pass  # 部分环境不支持 IF NOT EXISTS，忽略
        # 语音支持迁移
        try:
            cur.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS audio TEXT DEFAULT ''")
        except Exception:
            pass
        # ★★ 仅指定人可见支持（老表加列）★★
        try:
            cur.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS visible_to TEXT DEFAULT ''")
            print('  ✅ posts.visible_to 已添加')
        except Exception:
            pass
        # 日记公开/私密支持
        try:
            cur.execute("ALTER TABLE diaries ADD COLUMN IF NOT EXISTS visible VARCHAR(20) DEFAULT 'private'")
        except Exception:
            pass
        cur.execute("""
            CREATE TABLE IF NOT EXISTS agents (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                name VARCHAR(100) DEFAULT '新智能体',
                avatar VARCHAR(200) DEFAULT '🤖',
                color VARCHAR(20) DEFAULT '#7C4DFF',
                prompt TEXT DEFAULT '你是一个温柔可爱的助手。',
                api_key VARCHAR(500) DEFAULT '',
                api_base_url VARCHAR(500) DEFAULT '',
                model VARCHAR(100) DEFAULT '',
                created VARCHAR(20) DEFAULT '',
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id SERIAL PRIMARY KEY,
                agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE,
                role VARCHAR(20) DEFAULT 'user',
                content TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS friends (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                friend_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                status VARCHAR(20) DEFAULT 'pending',
                action_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS private_messages (
                id SERIAL PRIMARY KEY,
                from_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                to_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                content TEXT DEFAULT '',
                read BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        # 索引
        for idx in [
            'idx_posts_user ON posts(user_id)',
            'idx_posts_visible ON posts(visible)',
            'idx_comments_post ON comments(post_id)',
            'idx_diaries_user ON diaries(user_id)',
            'idx_agents_user ON agents(user_id)',
            'idx_chat_messages_agent ON chat_messages(agent_id)',
            'idx_users_token ON users(token)',
            'idx_friends_user ON friends(user_id)',
            'idx_friends_friend ON friends(friend_id)',
            'idx_friends_status ON friends(status)',
            'idx_pm_from ON private_messages(from_user_id)',
            'idx_pm_to ON private_messages(to_user_id)'
        ]:
            cur.execute(f'CREATE INDEX IF NOT EXISTS {idx}')
        conn.commit()
        # ★★ migration: users/agents 的 avatar 字段扩展为 TEXT（支持 base64 存储，部署不丢） ★★
        for tbl, col in [('users','avatar'), ('agents','avatar')]:
            try:
                cur.execute(f"ALTER TABLE {tbl} ALTER COLUMN {col} TYPE TEXT")
                print(f'  ✅ {tbl}.{col} 已扩展为 TEXT')
            except Exception:
                pass
        # ★★ migration: 添加 theme 字段 ★★
        try:
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS theme TEXT DEFAULT '{}'")
            print('  ✅ users.theme 字段已添加')
        except Exception:
            pass
        print('✅ 数据库表初始化完成')
    except Exception as e:
        print(f'⚠️ 数据库建表失败（{e}），可能权限不足')
        print('💡 请手动在Neon SQL Editor中执行建表SQL，详见文档')
    finally:
        conn.close()

# ★ 不阻塞启动：即使init_db失败，app也能启动（表通过Neon SQL Editor手动建）
try:
    init_db()
except Exception as e:
    print(f'⚠️ init_db 异常（{e}），跳过建表，假设表已存在')

# ===== 辅助函数 =====

def gen_token():
    return hashlib.sha256(os.urandom(32)).hexdigest()

def get_current_user():
    """从请求头 Authorization 获取当前登录用户"""
    auth = request.headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        token = auth[7:]
        if token:
            conn = get_conn()
            try:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute('SELECT id, username, nickname, avatar, color, theme, api_key, api_base_url FROM users WHERE token = %s', (token,))
                return cur.fetchone()
            finally:
                conn.close()
    return None

@app.route('/')
def index():
    return send_from_directory(BASE_DIR, 'index.html')

# ===== 用户系统 API =====

@app.route('/api/register', methods=['POST'])
def register():
    body = request.get_json(silent=True) or {}
    username = body.get('username', '').strip()
    password = body.get('password', '')
    if len(username) < 2:
        return jsonify({'error': '用户名至少2个字符'}), 400
    if len(password) < 4:
        return jsonify({'error': '密码至少4个字符'}), 400
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute('SELECT id FROM users WHERE username = %s', (username,))
        if cur.fetchone():
            return jsonify({'error': '用户名已被注册'}), 409
        token = gen_token()
        pwd_hash = hashlib.sha256(password.encode()).hexdigest()
        cur.execute(
            'INSERT INTO users (username, password, nickname, token) VALUES (%s, %s, %s, %s) RETURNING id, nickname, avatar, color',
            (username, pwd_hash, username, token)
        )
        user = cur.fetchone()
        conn.commit()
        return jsonify({
            'id': user['id'], 'username': username,
            'nickname': user['nickname'], 'avatar': user['avatar'],
            'color': user['color'], 'token': token
        })
    finally:
        conn.close()

@app.route('/api/login', methods=['POST'])
def login():
    body = request.get_json(silent=True) or {}
    username = body.get('username', '').strip()
    password = body.get('password', '')
    if not username or not password:
        return jsonify({'error': '请输入用户名和密码'}), 400
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        pwd_hash = hashlib.sha256(password.encode()).hexdigest()
        cur.execute('SELECT id, username, nickname, avatar, color, token FROM users WHERE username = %s AND password = %s', (username, pwd_hash))
        user = cur.fetchone()
        if not user:
            return jsonify({'error': '用户名或密码错误'}), 401
        return jsonify(dict(user))
    finally:
        conn.close()

@app.route('/api/profile', methods=['GET', 'PUT'])
def profile():
    user = get_current_user()
    if not user:
        return jsonify({'error': '未登录'}), 401
    if request.method == 'GET':
        import json
        u = dict(user)
        if isinstance(u.get('theme'), str) and u['theme']:
            try:
                u['theme'] = json.loads(u['theme'])
            except Exception:
                u['theme'] = {}
        return jsonify(u)
    body = request.get_json(silent=True) or {}
    conn = get_conn()
    try:
        cur = conn.cursor()
        for key in ['nickname', 'avatar', 'color', 'theme', 'api_key', 'api_base_url']:
            if key in body:
                val = body[key]
                # theme 存 JSON 字符串
                if key == 'theme' and isinstance(val, dict):
                    import json
                    val = json.dumps(val, ensure_ascii=False)
                cur.execute(f'UPDATE users SET {key} = %s WHERE id = %s', (val, user['id']))
        conn.commit()
        return jsonify({'ok': True})
    finally:
        conn.close()

# ===== 碎碎念 API =====

@app.route('/api/posts', methods=['GET'])
def get_posts():
    user = get_current_user()
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if user:
            # 获取好友ID列表（用于friends可见性）
            cur.execute("""
                SELECT friend_id FROM friends WHERE user_id = %s AND status = 'accepted'
                UNION SELECT user_id FROM friends WHERE friend_id = %s AND status = 'accepted'
            """, (user['id'], user['id']))
            friend_ids = [r['friend_id'] for r in cur.fetchall()]
            sql = """
                SELECT p.id, p.text, p.mood, p.time, p.visible, p.image, p.audio, p.visible_to,
                       u.nickname AS author, u.avatar, u.color
                FROM posts p JOIN users u ON p.user_id = u.id
                WHERE p.visible = 'public'
                   OR (p.visible = 'private' AND p.user_id = %s)
                   OR (p.visible = 'custom' AND (p.user_id = %s OR %s = ANY(string_to_array(p.visible_to, ',')::int[])))
            """
            params = [user['id'], user['id'], user['id']]
            if friend_ids:
                sql += " OR (p.visible = 'friends' AND p.user_id = ANY(%s::int[]))"
                params.append(friend_ids)
            sql += " ORDER BY p.id DESC"
            cur.execute(sql, tuple(params))
        else:
            cur.execute("""
                SELECT p.id, p.text, p.mood, p.time, p.visible, p.image, p.audio, p.visible_to,
                       u.nickname AS author, u.avatar, u.color
                FROM posts p JOIN users u ON p.user_id = u.id
                WHERE p.visible = 'public'
                ORDER BY p.id DESC
            """)
        posts = []
        for row in cur.fetchall():
            post = dict(row)
            # visible_to 字符串转数组返回给前端
            try:
                post['visible_to'] = [int(x) for x in (post.get('visible_to') or '').split(',') if x.strip().isdigit()]
            except Exception:
                post['visible_to'] = []
            c2 = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            c2.execute("""
                SELECT c.text, c.time, u.nickname AS name, u.avatar, u.color
                FROM comments c JOIN users u ON c.user_id = u.id
                WHERE c.post_id = %s ORDER BY c.id
            """, (post['id'],))
            post['comments'] = [dict(r) for r in c2.fetchall()]
            c2.close()
            posts.append(post)
        return jsonify(posts)
    finally:
        conn.close()

@app.route('/api/posts', methods=['POST'])
def add_post():
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401
    body = request.get_json(silent=True) or {}
    # visible_to 支持数组或逗号分隔字符串
    visible_to = body.get('visible_to', '')
    if isinstance(visible_to, list):
        visible_to = ','.join(str(x) for x in visible_to if str(x).isdigit())
    else:
        visible_to = ','.join(x.strip() for x in str(visible_to).split(',') if x.strip().isdigit())
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "INSERT INTO posts (user_id, text, mood, time, visible, image, audio, visible_to) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (user['id'], body.get('text', ''), body.get('mood', ''),
             datetime.now(CN_TZ).strftime('%m-%d %H:%M'), body.get('visible', 'public'),
             body.get('image', ''), body.get('audio', ''), visible_to)
        )
        post_id = cur.fetchone()['id']
        conn.commit()
        return jsonify({
            'id': post_id, 'text': body.get('text', ''), 'mood': body.get('mood', ''),
            'time': datetime.now(CN_TZ).strftime('%m-%d %H:%M'),
            'visible': body.get('visible', 'public'),
            'visible_to': [int(x) for x in visible_to.split(',') if x],
            'image': body.get('image', ''),
            'audio': body.get('audio', ''),
            'author': user['nickname'], 'avatar': user['avatar'],
            'color': user['color'], 'comments': []
        })
    finally:
        conn.close()

@app.route('/api/posts/<int:pid>/comments', methods=['POST'])
def add_comment(pid):
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401
    body = request.get_json(silent=True) or {}
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "INSERT INTO comments (post_id, user_id, text, time) VALUES (%s, %s, %s, %s) RETURNING id",
            (pid, user['id'], body.get('text', ''), datetime.now(CN_TZ).strftime('%m-%d %H:%M'))
        )
        cid = cur.fetchone()['id']
        conn.commit()
        return jsonify({
            'id': cid, 'text': body.get('text', ''),
            'time': datetime.now(CN_TZ).strftime('%m-%d %H:%M'),
            'name': user['nickname'], 'avatar': user['avatar'], 'color': user['color']
        })
    finally:
        conn.close()

@app.route('/api/posts/<int:pid>', methods=['DELETE'])
def delete_post(pid):
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute('DELETE FROM posts WHERE id = %s AND user_id = %s', (pid, user['id']))
        conn.commit()
        return jsonify({'ok': True})
    finally:
        conn.close()

@app.route('/api/clean-all', methods=['POST'])
def clean_all():
    """一键清除当前用户的所有帖子和日记"""
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute('DELETE FROM posts WHERE user_id = %s', (user['id'],))
        cur.execute('DELETE FROM diaries WHERE user_id = %s', (user['id'],))
        conn.commit()
        return jsonify({'ok': True, 'message': '已清除所有帖子和日记'})
    finally:
        conn.close()

# ===== 日记 API =====

@app.route('/api/diaries', methods=['GET'])
def get_diaries():
    user = get_current_user()
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if user:
            cur.execute("""
                SELECT d.*, u.nickname AS author, u.avatar AS user_avatar, u.color AS user_color
                FROM diaries d JOIN users u ON d.user_id = u.id
                WHERE d.user_id = %s OR d.visible = 'public'
                ORDER BY d.id DESC
            """, (user['id'],))
        else:
            cur.execute("""
                SELECT d.*, u.nickname AS author, u.avatar AS user_avatar, u.color AS user_color
                FROM diaries d JOIN users u ON d.user_id = u.id
                WHERE d.visible = 'public'
                ORDER BY d.id DESC
            """)
        return jsonify([dict(r) for r in cur.fetchall()])
    finally:
        conn.close()

@app.route('/api/diaries', methods=['POST'])
def add_diary():
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401
    body = request.get_json(silent=True) or {}
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        now = datetime.now(CN_TZ)
        cur.execute(
            "INSERT INTO diaries (user_id, title, content, mood, date, time, color, image, visible) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
            (user['id'], body.get('title', ''), body.get('content', ''),
             body.get('mood', ''), body.get('date', now.strftime('%Y-%m-%d')),
             now.strftime('%H:%M'), body.get('color', '#7C4DFF'),
             body.get('image', ''), body.get('visible', 'private'))
        )
        diary = cur.fetchone()
        conn.commit()
        return jsonify(dict(diary))
    finally:
        conn.close()

@app.route('/api/diaries/<int:did>', methods=['DELETE'])
def delete_diary(did):
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute('DELETE FROM diaries WHERE id = %s AND user_id = %s', (did, user['id']))
        conn.commit()
        return jsonify({'ok': True})
    finally:
        conn.close()

# ===== 智能体 API =====

# 智谱AI免费模型列表
FREE_MODELS = {
    'chat': [  # 可用于智能体对话
        {'id': 'GLM-4-Flash-250414', 'name': 'GLM-4-Flash-250414', 'desc': '最新版免费对话模型'},
        {'id': 'GLM-4.6V-Flash', 'name': 'GLM-4.6V-Flash', 'desc': '免费多模态（可看图片）'},
        {'id': 'GLM-4.1V-Thinking-Flash', 'name': 'GLM-4.1V-Thinking-Flash', 'desc': '免费多模态+深度思考'},
        {'id': 'GLM-4V-Flash', 'name': 'GLM-4V-Flash', 'desc': '免费视觉模型'},
    ],
    'image': [  # 文生图
        {'id': 'Cogview-3-Flash', 'name': 'Cogview-3-Flash', 'desc': '免费AI画图'},
    ],
    'video': [  # 文生视频
        {'id': 'CogVideoX-Flash', 'name': 'CogVideoX-Flash', 'desc': '免费AI视频生成'},
    ]
}

@app.route('/api/models', methods=['GET'])
def get_models():
    return jsonify(FREE_MODELS)

# ===== 文件上传 API =====

@app.route('/uploads/<path:filename>')
def serve_upload(filename):
    return send_from_directory(UPLOAD_DIR, filename)

@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': '没有上传文件'}), 400
    f = request.files['file']
    if f.filename == '':
        return jsonify({'error': '文件名为空'}), 400
    # 只允许图片
    if not f.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
        return jsonify({'error': '仅支持 PNG/JPG/GIF/WEBP 格式'}), 400
    # ★★ 改为 base64 存储，不依赖文件系统，Railway 部署不丢 ★★
    ext = os.path.splitext(f.filename)[1].lstrip('.').lower()
    if ext == 'jpg': ext = 'jpeg'
    img_data = f.read()
    b64 = base64.b64encode(img_data).decode()
    data_url = f'data:image/{ext};base64,{b64}'
    return jsonify({'url': data_url, 'filename': f.filename})

# ===== 智能体 API =====

@app.route('/api/agents', methods=['GET'])
def get_agents():
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute('SELECT * FROM agents WHERE user_id = %s ORDER BY id DESC', (user['id'],))
        return jsonify([dict(r) for r in cur.fetchall()])
    finally:
        conn.close()

@app.route('/api/agents', methods=['POST'])
def add_agent():
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401
    body = request.get_json(silent=True) or {}
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "INSERT INTO agents (user_id, name, avatar, color, prompt, api_key, api_base_url, model, created) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
            (user['id'],
             body.get('name', '新智能体'),
             body.get('avatar', '🤖'),
             body.get('color', '#7C4DFF'),
             body.get('prompt', '你是一个温柔可爱的助手。'),
             body.get('api_key', ''),
             body.get('api_base_url', ''),
             body.get('model', ''),
             datetime.now(CN_TZ).strftime('%Y-%m-%d'))
        )
        agent = cur.fetchone()
        conn.commit()
        return jsonify(dict(agent))
    finally:
        conn.close()

@app.route('/api/agents/<int:aid>', methods=['PUT'])
def update_agent(aid):
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401
    body = request.get_json(silent=True) or {}
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        # 先验证归属
        cur.execute('SELECT * FROM agents WHERE id = %s AND user_id = %s', (aid, user['id']))
        agent = cur.fetchone()
        if not agent:
            return jsonify({'error': '智能体不存在'}), 404
        updates = []
        vals = []
        for key in ['name', 'avatar', 'color', 'prompt', 'api_key', 'api_base_url', 'model']:
            if key in body:
                updates.append(f'{key} = %s')
                vals.append(body[key])
        if updates:
            vals.append(aid)
            vals.append(user['id'])
            cur.execute(f'UPDATE agents SET {", ".join(updates)} WHERE id = %s AND user_id = %s', vals)
            conn.commit()
            cur.execute('SELECT * FROM agents WHERE id = %s', (aid,))
            agent = cur.fetchone()
        return jsonify(dict(agent))
    finally:
        conn.close()

@app.route('/api/agents/<int:aid>', methods=['DELETE'])
def delete_agent(aid):
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute('DELETE FROM agents WHERE id = %s AND user_id = %s', (aid, user['id']))
        conn.commit()
        return jsonify({'ok': True})
    finally:
        conn.close()

@app.route('/api/agents/<int:aid>/messages', methods=['GET'])
def get_agent_messages(aid):
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        # 验证智能体归属
        cur.execute('SELECT id FROM agents WHERE id = %s AND user_id = %s', (aid, user['id']))
        if not cur.fetchone():
            return jsonify({'error': '智能体不存在'}), 404
        cur.execute(
            "SELECT role, content, created_at FROM chat_messages WHERE agent_id = %s ORDER BY id",
            (aid,)
        )
        return jsonify([dict(r) for r in cur.fetchall()])
    finally:
        conn.close()

@app.route('/api/agents/<int:aid>/chat', methods=['POST'])
def chat_with_agent(aid):
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401
    body = request.get_json(silent=True) or {}
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute('SELECT * FROM agents WHERE id = %s AND user_id = %s', (aid, user['id']))
        agent = cur.fetchone()
        if not agent:
            return jsonify({'error': '智能体不存在'}), 404
    finally:
        conn.close()

    messages = [{'role': 'system', 'content': agent['prompt']}]
    for msg in body.get('messages', []):
        messages.append({'role': msg.get('role', 'user'), 'content': msg.get('content', '')})

    try:
        import requests
        # 优先级：智能体自己的配置 → 用户全局配置 → 环境变量默认值
        user_config = {}
        conn2 = get_conn()
        try:
            c2 = conn2.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            c2.execute('SELECT api_key, api_base_url FROM users WHERE id = %s', (user['id'],))
            row = c2.fetchone()
            if row:
                user_config = dict(row)
        finally:
            conn2.close()

        api_key = agent.get('api_key') or user_config.get('api_key') or os.environ.get('AI_API_KEY', '30edd9feafb94229a1b2847f64b4e9d5.VbckSSfgvpTGHiTi')
        base_url = agent.get('api_base_url') or user_config.get('api_base_url') or os.environ.get('AI_API_BASE_URL', 'https://open.bigmodel.cn/api/paas/v4')
        # 根据base_url自动推断默认model（用户填DeepSeek则自动用deepseek-chat）
        default_model = 'deepseek-chat' if 'deepseek' in base_url else 'GLM-4-Flash-250414'
        model = agent.get('model') or os.environ.get('AI_MODEL', default_model)

        # 保存用户消息到数据库（只保存最新的那条，避免重复）
        if body.get('messages'):
            last_msg = body['messages'][-1]
            if last_msg.get('role') in ('user', 'assistant'):
                conn3 = get_conn()
                try:
                    c3 = conn3.cursor()
                    c3.execute(
                        "INSERT INTO chat_messages (agent_id, role, content) VALUES (%s, %s, %s)",
                        (aid, last_msg['role'], last_msg.get('content', ''))
                    )
                    conn3.commit()
                finally:
                    conn3.close()

        resp = requests.post(
            f'{base_url}/chat/completions',
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={'model': model, 'messages': messages, 'max_tokens': 1024},
            timeout=30
        )
        result = resp.json()
        reply = result['choices'][0]['message']['content']

        # 保存AI回复到数据库
        conn4 = get_conn()
        try:
            c4 = conn4.cursor()
            c4.execute(
                "INSERT INTO chat_messages (agent_id, role, content) VALUES (%s, %s, %s)",
                (aid, 'assistant', reply)
            )
            conn4.commit()
        finally:
            conn4.close()

        return jsonify({'reply': reply})
    except Exception as e:
        return jsonify({'error': f'AI 对话出错: {str(e)}'}), 500

# ====== 好友与私信系统 ======

@app.route('/api/users/search', methods=['GET'])
def search_users():
    """搜索用户"""
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401
    q = request.args.get('q', '').strip()
    if not q or len(q) < 1:
        return jsonify([])
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT id, nickname, avatar, color FROM users WHERE id != %s AND nickname ILIKE %s LIMIT 20",
            (user['id'], f'%{q}%')
        )
        return jsonify([dict(r) for r in cur.fetchall()])
    finally:
        conn.close()

@app.route('/api/friends/request', methods=['POST'])
def send_friend_request():
    """发送好友请求"""
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401
    body = request.get_json(silent=True) or {}
    friend_id = body.get('friend_id')
    if not friend_id:
        return jsonify({'error': '请指定好友'}), 400
    if friend_id == user['id']:
        return jsonify({'error': '不能添加自己为好友'}), 400
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT * FROM friends
            WHERE (user_id = %s AND friend_id = %s) OR (user_id = %s AND friend_id = %s)
        """, (user['id'], friend_id, friend_id, user['id']))
        existing = cur.fetchone()
        if existing:
            if existing['status'] == 'accepted':
                return jsonify({'error': '已经是好友了'}), 400
            elif existing['status'] == 'pending':
                return jsonify({'error': '已发送过好友请求'}), 400
            else:
                cur.execute("DELETE FROM friends WHERE id = %s", (existing['id'],))
                conn.commit()
        cur.execute('SELECT id FROM users WHERE id = %s', (friend_id,))
        if not cur.fetchone():
            return jsonify({'error': '用户不存在'}), 404
        cur.execute(
            "INSERT INTO friends (user_id, friend_id, status, action_user_id) VALUES (%s, %s, 'pending', %s)",
            (user['id'], friend_id, user['id'])
        )
        conn.commit()
        return jsonify({'ok': True, 'message': '好友请求已发送 ✨'})
    finally:
        conn.close()

@app.route('/api/friends/requests', methods=['GET'])
def get_friend_requests():
    """获取好友请求列表"""
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT f.id, f.user_id, u.nickname, u.avatar, u.color, f.created_at
            FROM friends f JOIN users u ON u.id = f.user_id
            WHERE f.friend_id = %s AND f.status = 'pending'
            ORDER BY f.created_at DESC
        """, (user['id'],))
        incoming = [dict(r) for r in cur.fetchall()]
        cur.execute("""
            SELECT f.id, f.friend_id AS user_id, u.nickname, u.avatar, u.color, f.created_at
            FROM friends f JOIN users u ON u.id = f.friend_id
            WHERE f.user_id = %s AND f.status = 'pending' AND f.action_user_id = %s
            ORDER BY f.created_at DESC
        """, (user['id'], user['id']))
        outgoing = [dict(r) for r in cur.fetchall()]
        return jsonify({'incoming': incoming, 'outgoing': outgoing})
    finally:
        conn.close()

@app.route('/api/friends/respond', methods=['POST'])
def respond_friend_request():
    """处理好友请求"""
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401
    body = request.get_json(silent=True) or {}
    request_id = body.get('request_id')
    action = body.get('action')
    if not request_id or action not in ('accept', 'reject'):
        return jsonify({'error': '参数错误'}), 400
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM friends WHERE id = %s AND friend_id = %s AND status = 'pending'", (request_id, user['id']))
        row = cur.fetchone()
        if not row:
            return jsonify({'error': '请求不存在或已处理'}), 404
        if action == 'accept':
            cur.execute("UPDATE friends SET status = 'accepted' WHERE id = %s", (request_id,))
            conn.commit()
            return jsonify({'ok': True, 'message': '已接受好友请求 🎉'})
        else:
            cur.execute("DELETE FROM friends WHERE id = %s", (request_id,))
            conn.commit()
            return jsonify({'ok': True, 'message': '已拒绝好友请求'})
    finally:
        conn.close()

@app.route('/api/friends', methods=['GET'])
def get_friends():
    """获取好友列表"""
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT u.id, u.nickname, u.avatar, u.color
            FROM friends f JOIN users u ON u.id = f.friend_id
            WHERE f.user_id = %s AND f.status = 'accepted'
            UNION
            SELECT u.id, u.nickname, u.avatar, u.color
            FROM friends f JOIN users u ON u.id = f.user_id
            WHERE f.friend_id = %s AND f.status = 'accepted'
            ORDER BY nickname
        """, (user['id'], user['id']))
        return jsonify([dict(r) for r in cur.fetchall()])
    finally:
        conn.close()

@app.route('/api/messages/send', methods=['POST'])
def send_private_message():
    """发送私信"""
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401
    body = request.get_json(silent=True) or {}
    to_user_id = body.get('to_user_id')
    content = body.get('content', '').strip()
    if not to_user_id or not content:
        return jsonify({'error': '参数错误'}), 400
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id FROM friends
            WHERE ((user_id = %s AND friend_id = %s) OR (user_id = %s AND friend_id = %s))
            AND status = 'accepted'
        """, (user['id'], to_user_id, to_user_id, user['id']))
        if not cur.fetchone():
            return jsonify({'error': '还不是好友，不能发消息'}), 403
        cur.execute(
            "INSERT INTO private_messages (from_user_id, to_user_id, content) VALUES (%s, %s, %s)",
            (user['id'], to_user_id, content)
        )
        conn.commit()
        return jsonify({'ok': True, 'message': '消息已发送'})
    finally:
        conn.close()

@app.route('/api/messages/<int:other_id>', methods=['GET'])
def get_private_messages(other_id):
    """获取私信记录"""
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "UPDATE private_messages SET read = TRUE WHERE from_user_id = %s AND to_user_id = %s AND read = FALSE",
            (other_id, user['id'])
        )
        conn.commit()
        cur.execute("""
            SELECT id, from_user_id, to_user_id, content, read, created_at
            FROM private_messages
            WHERE (from_user_id = %s AND to_user_id = %s) OR (from_user_id = %s AND to_user_id = %s)
            ORDER BY id
        """, (user['id'], other_id, other_id, user['id']))
        return jsonify([dict(r) for r in cur.fetchall()])
    finally:
        conn.close()

@app.route('/api/ping', methods=['GET'])
def ping():
    """轻量心跳检测"""
    return jsonify({'pong': True, 'time': str(datetime.now(CN_TZ))})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8792))
    print(f'✨ 碎碎念服务已启动: http://0.0.0.0:{port}')
