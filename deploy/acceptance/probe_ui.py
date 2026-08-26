import httpx, os, json
os.environ['NO_PROXY'] = '*'
base = 'http://localhost:8081'

# ① SPA 页面可达
r = httpx.get(base + '/chat')
print('① /chat 页面:', r.status_code, '| 是SPA:', '<div id="app">' in r.text)

# ② 会话历史回放
tok = httpx.post(base + '/api/auth/login',
                 json={'username': 'it001', 'password': 'Abc12345!'}).json()['data']['access_token']
H = {'Authorization': 'Bearer ' + tok}
sessions = httpx.get(base + '/api/ai/sessions', headers=H).json()['data']
print('② 会话数:', len(sessions))
ok_pairs = False
if sessions:
    sid = sessions[0]['session_id']
    msgs = httpx.get(f'{base}/api/ai/sessions/{sid}/messages', headers=H).json()['data']
    roles = [m['role'] for m in msgs]
    ok_pairs = 'user' in roles and 'assistant' in roles
    print('   最新会话消息数:', len(msgs), '| user+assistant 成对:', ok_pairs)
    unauth_log = any(m.get('unauthorized_unit_ids') for m in msgs if m['role'] == 'assistant')
    print('③ 历史中权限缺失留痕:', unauth_log)
