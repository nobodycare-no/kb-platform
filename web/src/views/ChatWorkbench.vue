<template>
  <div class="chat-layout">
    <!-- 会话列表 -->
    <div class="session-panel">
      <el-button type="primary" style="width:100%" @click="newSession">＋ 新会话</el-button>
      <div v-for="s in sessions" :key="s.session_id"
           class="session-item" :class="{active: s.session_id===currentSessionId}"
           @click="switchSession(s)">
        {{ s.title }}
      </div>
    </div>

    <!-- 对话区 -->
    <div class="chat-panel">
      <div ref="msgBox" class="messages">
        <template v-for="(m, idx) in messages" :key="idx">
          <div :class="['bubble-row', m.role]">
            <div class="bubble" :class="m.role">
              <div v-if="m.role === 'assistant'" class="md" v-html="render(m.content)"></div>
              <template v-else>{{ m.content }}</template>
            </div>
          </div>
          <div v-if="m.role==='assistant' && m.sources?.length" class="sources">
            <el-tag v-for="s in m.sources" :key="s.citation ?? s.faq_id" size="small"
                    :type="s.via ? 'warning' : 'success'" effect="plain">
              [{{ s.citation }}] {{ s.title }}
            </el-tag>
          </div>
          <div v-if="m.role==='assistant' && m.unauthorized?.length" class="unauth">
            ⚠️ 您缺少以下知识的访问权限：{{ m.unauthorized.map(u => u.title).join('、') }}
          </div>
          <div v-if="m.role==='assistant' && m.degraded" class="degraded">⚠️ 当前处于降级检索模式</div>
        </template>
        <div v-if="streaming" class="typing">AI 正在思考…</div>
      </div>

      <div class="input-bar">
        <el-input v-model="question" type="textarea" :rows="2" resize="none"
                  placeholder="输入问题，Enter 发送 / Shift+Enter 换行"
                  @keydown.enter.exact.prevent="send" />
        <el-button type="primary" :loading="streaming" @click="send">发送</el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { nextTick, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import MarkdownIt from 'markdown-it'
import { createSession, listSessions, sessionMessages } from '../api'

const md = new MarkdownIt({ breaks: true })
const render = (t) => md.render(t || '')

const sessions = ref([])
const currentSessionId = ref(null)
const messages = ref([])
const question = ref('')
const streaming = ref(false)
const msgBox = ref(null)
let abortCtrl = null

function scrollBottom() {
  nextTick(() => { msgBox.value && (msgBox.value.scrollTop = msgBox.value.scrollHeight) })
}

async function refreshSessions() {
  sessions.value = await listSessions() || []
}

async function switchSession(s) {
  currentSessionId.value = s.session_id
  const msgs = await sessionMessages(s.session_id)
  messages.value = msgs || []
  scrollBottom()
}

async function newSession() {
  const data = await createSession()
  currentSessionId.value = data.session_id
  messages.value = []
  await refreshSessions()
}

onMounted(async () => {
  await refreshSessions()
  if (sessions.value.length) await switchSession(sessions.value[0])
  else await newSession()
})

async function send() {
  const q = question.value.trim()
  if (!q || streaming.value) return
  question.value = ''
  messages.value.push({ role: 'user', content: q })
  const assistant = reactive({ role: 'assistant', content: '', sources: [], unauthorized: [] })
  messages.value.push(assistant)
  streaming.value = true
  scrollBottom()

  abortCtrl = new AbortController()
  try {
    const token = localStorage.getItem('kb_token')
    const resp = await fetch('/api/ai/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ session_id: currentSessionId.value, question: q }),
      signal: abortCtrl.signal
    })
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const reader = resp.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buf = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const blocks = buf.split('\n\n')
      buf = blocks.pop() || ''
      for (const block of blocks) {
        let ev = 'message', data = {}
        for (const line of block.split('\n')) {
          if (line.startsWith('event:')) ev = line.slice(6).trim()
          else if (line.startsWith('data:')) data = JSON.parse(line.slice(5).trim())
        }
        if (ev === 'delta') { assistant.content += data.delta_text; scrollBottom() }
        else if (ev === 'sources') assistant.sources = data.items
        else if (ev === 'unauthorized') assistant.unauthorized = data.units
        else if (ev === 'done') { assistant.degraded = data.degraded }
        else if (ev === 'error') ElMessage.error(data.message || '生成失败')
      }
    }
  } catch (e) {
    if (e.name !== 'AbortError') ElMessage.error(e.message || '连接中断')
  } finally {
    streaming.value = false
    await refreshSessions()
  }
}
</script>

<script>
import { reactive } from 'vue'
export default {}
</script>

<style scoped>
.chat-layout { display:flex; gap:12px; height: calc(100vh - 110px); }
.session-panel { width:220px; background:#fff; border-radius:8px; padding:10px;
                 overflow:auto; border:1px solid #e6e6e6; }
.session-item { padding:10px; border-radius:6px; cursor:pointer; margin-top:6px;
                white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.session-item:hover, .session-item.active { background:#ecf5ff; color:#409EFF; }
.chat-panel { flex:1; display:flex; flex-direction:column; background:#fff;
              border-radius:8px; border:1px solid #e6e6e6; }
.messages { flex:1; overflow-y:auto; padding:18px; }
.bubble-row { display:flex; margin-bottom:12px; }
.bubble-row.user { justify-content:flex-end; }
.bubble { max-width:72%; padding:10px 14px; border-radius:10px; line-height:1.65; }
.bubble.user { background:#409EFF; color:#fff; }
.bubble.assistant { background:#f4f4f5; color:#303133; }
.md :deep(p) { margin: 0 0 6px; }
.md :deep(code) { background:#eee; padding:1px 4px; border-radius:3px; }
.sources { margin: -6px 0 12px 0; display:flex; gap:6px; flex-wrap:wrap; }
.unauth, .degraded { background:#fdf6ec; color:#b88230; font-size:13px;
                     padding:8px 12px; border-radius:6px; margin-bottom:12px; }
.typing { color:#909399; font-size:13px; }
.input-bar { display:flex; gap:10px; padding:12px; border-top:1px solid #eee; align-items:flex-end; }
</style>
