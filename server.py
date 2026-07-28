#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
碎碎念 · 云服务器版
带日记 & 智能体功能
"""
import os, json
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
DATA_FILE = os.path.join(DATA_DIR, 'data.json')
os.makedirs(DATA_DIR, exist_ok=True)

def load():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"posts": [], "next_id": 1, "diaries": [], "next_diary_id": 1, "agents": [], "next_agent_id": 1}

def save(d):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)

@app.route('/')
def index():
    return send_from_directory(BASE_DIR, 'index.html')

# ===== 旧：碎碎念 API =====

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
        'author': body.get('author', ''),
        'avatar': body.get('avatar', '🌸'),
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
                'name': body.get('name', ''),
                'text': body.get('text', ''),
                'time': datetime.now().strftime('%m-%d %H:%M'),
                'avatar': body.get('avatar', '🌸'),
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

# ===== 新：日记 API =====

@app.route('/api/diaries', methods=['GET'])
def get_diaries():
    d = load()
    diaries = sorted(d.get('diaries', []), key=lambda x: x['id'], reverse=True)
    return jsonify(diaries)

@app.route('/api/diaries', methods=['POST'])
def add_diary():
    body = request.get_json(silent=True) or {}
    d = load()
    if 'diaries' not in d:
        d['diaries'] = []
        d['next_diary_id'] = 1
    diary = {
        'id': d['next_diary_id'],
        'title': body.get('title', ''),
        'content': body.get('content', ''),
        'mood': body.get('mood', ''),
        'date': body.get('date', datetime.now().strftime('%Y-%m-%d')),
        'time': datetime.now().strftime('%H:%M'),
        'color': body.get('color', '#7C4DFF')
    }
    d['diaries'].append(diary)
    d['next_diary_id'] += 1
    save(d)
    return jsonify(diary)

@app.route('/api/diaries/<int:did>', methods=['DELETE'])
def delete_diary(did):
    d = load()
    d['diaries'] = [x for x in d.get('diaries', []) if x['id'] != did]
    save(d)
    return jsonify({'ok': True})

# ===== 新：智能体 API =====

@app.route('/api/agents', methods=['GET'])
def get_agents():
    d = load()
    return jsonify(d.get('agents', []))

@app.route('/api/agents', methods=['POST'])
def add_agent():
    body = request.get_json(silent=True) or {}
    d = load()
    if 'agents' not in d:
        d['agents'] = []
        d['next_agent_id'] = 1
    agent = {
        'id': d['next_agent_id'],
        'name': body.get('name', '新智能体'),
        'avatar': body.get('avatar', '🤖'),
        'color': body.get('color', '#7C4DFF'),
        'prompt': body.get('prompt', '你是一个温柔可爱的助手。'),
        'created': datetime.now().strftime('%Y-%m-%d')
    }
    d['agents'].append(agent)
    d['next_agent_id'] += 1
    save(d)
    return jsonify(agent)

@app.route('/api/agents/<int:aid>', methods=['PUT'])
def update_agent(aid):
    body = request.get_json(silent=True) or {}
    d = load()
    for agent in d.get('agents', []):
        if agent['id'] == aid:
            if 'name' in body: agent['name'] = body['name']
            if 'avatar' in body: agent['avatar'] = body['avatar']
            if 'color' in body: agent['color'] = body['color']
            if 'prompt' in body: agent['prompt'] = body['prompt']
            save(d)
            return jsonify(agent)
    return 'Not found', 404

@app.route('/api/agents/<int:aid>', methods=['DELETE'])
def delete_agent(aid):
    d = load()
    d['agents'] = [x for x in d.get('agents', []) if x['id'] != aid]
    save(d)
    return jsonify({'ok': True})

@app.route('/api/agents/<int:aid>/chat', methods=['POST'])
def chat_with_agent(aid):
    body = request.get_json(silent=True) or {}
    d = load()
    agent = None
    for a in d.get('agents', []):
        if a['id'] == aid:
            agent = a
            break
    if not agent:
        return jsonify({'error': '智能体不存在'}), 404
    
    messages = [{'role': 'system', 'content': agent['prompt']}]
    for msg in body.get('messages', []):
        messages.append({'role': msg.get('role', 'user'), 'content': msg.get('content', '')})
    
    try:
        import requests
        api_key = os.environ.get('AI_API_KEY', '')
        base_url = os.environ.get('AI_API_BASE_URL', 'https://api.openai.com/v1')
        model = os.environ.get('AI_MODEL', 'gpt-4o-mini')
        if not api_key:
            return jsonify({'error': 'AI_API_KEY 未配置，请在环境变量中设置'}), 400
        
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
