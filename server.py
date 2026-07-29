#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
碎碎念 · 云服务器版（PostgreSQL + 用户系统）
- 数据库：PostgreSQL（环境变量 DATABASE_URL）
- 用户系统：注册/登录/Token认证
- 数据隔离：每个用户只能操作自己的数据
- 冷启动容错：Neon休眠唤醒自动重试
"""
import os, hashlib, time
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__)

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
    """启动时自动创建所有数据表"""
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
        # 索引
        for idx in [
            'idx_posts_user ON posts(user_id)',
            'idx_posts_visible ON posts(visible)',
            'idx_comments_post ON comments(post_id)',
            'idx_diaries_user ON diaries(user_id)',
            'idx_agents_user ON agents(user_id)',
            'idx_users_token ON users(token)'
        ]:
            cur.execute(f'CREATE INDEX IF NOT EXISTS {idx}')
        conn.commit()
        print('✅ 数据库表初始化完成')
    finally:
        conn.close()

init_db()

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
                cur.execute('SELECT id, username, nickname, avatar, color FROM users WHERE token = %s', (token,))
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
        return jsonify(user)
    body = request.get_json(silent=True) or {}
    conn = get_conn()
    try:
        cur = conn.cursor()
        for key in ['nickname', 'avatar', 'color']:
            if key in body:
                cur.execute(f'UPDATE users SET {key} = %s WHERE id = %s', (body[key], user['id']))
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
            cur.execute("""
                SELECT p.id, p.text, p.mood, p.time, p.visible,
                       u.nickname AS author, u.avatar, u.color
                FROM posts p JOIN users u ON p.user_id = u.id
                WHERE p.visible = 'public' OR p.user_id = %s
                ORDER BY p.id DESC
            """, (user['id'],))
        else:
            cur.execute("""
                SELECT p.id, p.text, p.mood, p.time, p.visible,
                       u.nickname AS author, u.avatar, u.color
                FROM posts p JOIN users u ON p.user_id = u.id
                WHERE p.visible = 'public'
                ORDER BY p.id DESC
            """)
        posts = []
        for row in cur.fetchall():
            post = dict(row)
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
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "INSERT INTO posts (user_id, text, mood, time, visible) VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (user['id'], body.get('text', ''), body.get('mood', ''),
             datetime.now().strftime('%m-%d %H:%M'), body.get('visible', 'public'))
        )
        post_id = cur.fetchone()['id']
        conn.commit()
        return jsonify({
            'id': post_id, 'text': body.get('text', ''), 'mood': body.get('mood', ''),
            'time': datetime.now().strftime('%m-%d %H:%M'),
            'visible': body.get('visible', 'public'),
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
            (pid, user['id'], body.get('text', ''), datetime.now().strftime('%m-%d %H:%M'))
        )
        cid = cur.fetchone()['id']
        conn.commit()
        return jsonify({
            'id': cid, 'text': body.get('text', ''),
            'time': datetime.now().strftime('%m-%d %H:%M'),
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

# ===== 日记 API =====

@app.route('/api/diaries', methods=['GET'])
def get_diaries():
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute('SELECT * FROM diaries WHERE user_id = %s ORDER BY id DESC', (user['id'],))
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
        now = datetime.now()
        cur.execute(
            "INSERT INTO diaries (user_id, title, content, mood, date, time, color) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *",
            (user['id'], body.get('title', ''), body.get('content', ''),
             body.get('mood', ''), body.get('date', now.strftime('%Y-%m-%d')),
             now.strftime('%H:%M'), body.get('color', '#7C4DFF'))
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
        {'id': 'GLM-4.7-Flash', 'name': 'GLM-4.7-Flash', 'desc': '最新版免费对话模型'},
        {'id': 'GLM-4-Flash-250414', 'name': 'GLM-4-Flash-250414', 'desc': 'GLM-4-Flash 2025-04-14版'},
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
    ext = os.path.splitext(f.filename)[1]
    filename = f'avatar_{hashlib.sha256(os.urandom(16)).hexdigest()[:12]}{ext}'
    f.save(os.path.join(AVATAR_DIR, filename))
    url = f'/uploads/avatars/{filename}'
    return jsonify({'url': url, 'filename': filename})

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
             datetime.now().strftime('%Y-%m-%d'))
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
        api_key = agent.get('api_key') or os.environ.get('AI_API_KEY', '30edd9feafb94229a1b2847f64b4e9d5.VbckSSfgvpTGHiTi')
        base_url = agent.get('api_base_url') or os.environ.get('AI_API_BASE_URL', 'https://open.bigmodel.cn/api/paas/v4')
        model = agent.get('model') or os.environ.get('AI_MODEL', 'GLM-4.7-Flash')

        resp = requests.post(
            f'{base_url}/chat/completions',
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={'model': model, 'messages': messages, 'max_tokens': 1024},
            timeout=30
        )
        result = resp.json()
        reply = result['choices'][0]['message']['content']
        return jsonify({'reply': reply})
    except Exception as e:
        return jsonify({'error': f'AI 对话出错: {str(e)}'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8792))
    print(f'✨ 碎碎念服务已启动: http://0.0.0.0:{port}')
    app.run(host='0.0.0.0', port=port, debug=False)