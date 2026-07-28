#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
碎碎念 · 云服务器版
基于 Flask 部署，适合 Railway / Render / Koyeb 等云平台
"""
import os, json
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__)

# 数据存储路径（云平台一般有持久化卷或临时存储）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
DATA_FILE = os.path.join(DATA_DIR, 'data.json')
os.makedirs(DATA_DIR, exist_ok=True)

def load():
    """加载数据"""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"posts": [], "next_id": 1}

def save(d):
    """保存数据"""
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)

@app.route('/')
def index():
    return send_from_directory(BASE_DIR, 'index.html')

@app.route('/api/posts', methods=['GET'])
def get_posts():
    d = load()
    posts = sorted(d['posts'], key=lambda x: x['id'], reverse=True)
    return jsonify(posts)

@app.route('/api/posts', methods=['POST'])
def add_post():
    body = request.get_json(silent=True) or {}
    d = load()
    post = {
        'id': d['next_id'],
        'text': body.get('text', ''),
        'mood': body.get('mood', ''),
        'time': datetime.now().strftime('%m-%d %H:%M'),
        'comments': [],
        'author': body.get('author', '沈郁'),
        'avatar': body.get('avatar', '❤️'),
        'color': body.get('color', '#7C4DFF'),
        'visible': body.get('visible', 'public')
    }
    d['posts'].append(post)
    d['next_id'] += 1
    save(d)
    return jsonify(post)

@app.route('/api/posts/<int:pid>/comments', methods=['POST'])
def add_comment(pid):
    body = request.get_json(silent=True) or {}
    d = load()
    for post in d['posts']:
        if post['id'] == pid:
            c = {
                'name': body.get('name', '沈郁'),
                'text': body.get('text', ''),
                'time': datetime.now().strftime('%m-%d %H:%M'),
                'avatar': body.get('avatar', '❤️'),
                'color': body.get('color', '#7C4DFF')
            }
            post['comments'].append(c)
            save(d)
            return jsonify(c)
    return 'Not found', 404

@app.route('/api/posts/<int:pid>', methods=['DELETE'])
def delete_post(pid):
    d = load()
    d['posts'] = [x for x in d['posts'] if x['id'] != pid]
    save(d)
    return jsonify({'ok': True})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8792))
    print(f'✨ 碎碎念服务已启动: http://0.0.0.0:{port}')
    app.run(host='0.0.0.0', port=port, debug=False)
