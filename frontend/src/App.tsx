import React, { useState, useEffect, useRef, useCallback, createContext, useContext } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import { gsap } from 'gsap'

// ─── Types ───

interface Account {
  uid: string; name: string; user_type: string; security_oauth_token: string
  refresh_token: string; machine_id: string; enabled: boolean; last_status: string
  last_error: string | null; quota: number; is_quota_exceeded: boolean
  plan: string | null; user_tag: string | null; next_reset_at: number | null
  proxy_enabled?: boolean; proxy_url?: string; proxy_username?: string; proxy_password_set?: boolean
}
interface AccountsConfig { accounts: Account[]; active_uid: string | null }
interface UIStatus { ready: boolean; mode: string; username: string | null; uid: string | null; user_type: string | null; error: string | null; accounts_count: number }
interface APIConfig { auth_required: boolean; allowed_keys: string[] }

/** 网关 API Key：名称 / 路由策略 / 限流上限（0=不限）+ 实时用量 */
interface ApiKeyEntry {
  api_key: string
  name: string
  strategy: number            // 1=填充（同 Key+模型固定账号） 2=轮询（每次请求依次换）
  rpm_limit: number           // 每分钟请求上限，0=不限
  concurrency_limit: number   // 并发上限，0=不限
  enabled: number
  created_at: string
  rpm_used?: number
  inflight?: number
}
interface Message { role: 'user' | 'assistant'; content: string }
type TabId = 'dashboard' | 'accounts' | 'playground' | 'api-keys' | 'logs' | 'register'
type AppTabId = TabId
type Lang = 'en' | 'zh'
type ToastType = 'SUCCESS' | 'ERROR' | 'INFO'
interface ToastItem { id: number; type: ToastType; title: string; message: string }

interface RegTask {
  stage: string
  logs: string[]
  result: { email: string; password: string; name: string; device: { token: string; refresh_token: string; user_id: string; expires_at: string } } | null
  error: string | null
  started_at: number
}
interface RegStatus {
  running: boolean
  stop_requested: boolean
  parents: number
  started_at: number | null
  verification: string | null
  stats: { success: number; failed: number; total: number }
  active: Record<string, RegTask>
  recent: Record<string, RegTask>
}

const NAV_ITEMS: { id: AppTabId; icon: string; label: string }[] = [
  { id: 'dashboard', icon: 'dashboard', label: 'Dashboard' },
  { id: 'accounts', icon: 'account_balance_wallet', label: 'Account Pool' },
  { id: 'playground', icon: 'smart_toy', label: 'AI Playground' },
  { id: 'api-keys', icon: 'vpn_key', label: 'API Key Management' },
  { id: 'register', icon: 'person_add', label: 'Auto Registrar' },
  { id: 'logs', icon: 'list_alt', label: 'Logs' },
]

const UI_TEXT = {
  en: {
    nav: {
      dashboard: 'Dashboard', accounts: 'Account Pool', playground: 'AI Playground', apiKeys: 'API Key Management', logs: 'Logs', register: 'Auto Registrar',
    },
    breadcrumb: {
      dashboard: 'Control Panel / Overview', accounts: 'Console / Management', playground: 'Playground / Experiment', apiKeys: 'Administration / Security', logs: 'System / Observability', docs: 'Developer Platform / Wiki', register: 'Automation / Registrar',
    },
    title: {
      dashboard: 'System Overview', accounts: 'Account Pool', playground: 'AI Playground', apiKeys: 'API Management', logs: 'Service Logs', docs: 'Documentation', register: 'Auto Registrar',
    },
    common: { docs: 'Docs', support: 'Support', healthy: 'Healthy', offline: 'Offline', signOut: 'Sign Out', refresh: 'Refresh', add: 'Add', delete: 'Delete', copy: 'Copy' },
    dashboard: {
      serviceStatus: 'Service Status', allGatewaysActive: 'All gateways active', noActiveSession: 'No active session', accountPool: 'Account Pool', activeSessions: 'Active Qoder accounts', apiAuth: 'API Auth', openAccess: 'Open access', activeUser: 'Active User', systemBriefing: 'System Briefing', readyBrief: 'Gateway is running. {count} account(s) are available for routing.', notReadyBrief: 'No active session is available. Import an account or add a PAT first.', recentNotifications: 'Recent Notifications', authImportError: 'Auth Import Error', sessionActive: 'Session Active', credentialConfig: 'Credential Configuration', credentialDesc: 'Add a Qoder PAT or import the current local Qoder auth session.', patPlaceholder: 'Enter Qoder PAT...', addPat: 'Add PAT', saving: 'Saving...', autoImport: 'Auto Import',
    },
    accounts: { desc: 'Manage Qoder accounts used by the gateway for request routing and failover.', refreshStatus: 'Refresh Status', importAccounts: 'Import Accounts', search: 'Search accounts...', empty: 'No accounts imported. Click Import Accounts or add a PAT from Dashboard.', showing: 'Showing {count} account(s)' },
    playground: { modelConfig: 'Model Configuration', streamResponse: 'Stream Response', systemPrompt: 'System Prompt', systemPromptPlaceholder: "Define the AI's persona...", ask: 'Ask anything...', send: 'Send', waiting: 'Waiting for response...' },
    api: { generate: 'Generate New Key', desc: 'Manage authentication keys and gateway access permissions for client requests.', gatewayAuth: 'Gateway Authentication', gatewayAuthDesc: 'Toggle API key validation for incoming /v1 requests.', systemStatus: 'System Status', activeKeys: 'Active Keys', configured: 'configured', activeAccessKeys: 'Active Access Keys', keyPlaceholder: 'Enter or paste a key...', noKeys: 'No API keys configured. Generate one above.', namePlaceholder: 'Name (optional)...', strategyFill: 'Strategy 1 · Fill — same Key + model always uses one account', strategyRoundRobin: 'Strategy 2 · Round-robin — rotate account every request', strategyFillShort: 'Fill', strategyRoundRobinShort: 'Round-robin', rpmPlaceholder: 'RPM cap', concPlaceholder: 'Concurrency cap', limitHint: 'Limits: 0 = unlimited. Over-limit requests receive HTTP 429. Saved values apply immediately.', refresh: 'Refresh', generateShort: 'Random', labelRpm: 'RPM', labelConc: 'Conc', unlimited: '∞', colName: 'Name', colKey: 'API Key', colStrategy: 'Routing', colUsage: 'Limits / Live', colStatus: 'Status', colActions: 'Actions', bestPractices: 'Security Best Practices', bestPracticesDesc: 'Do not expose API keys in client-side code. Rotate keys when they appear in logs, screenshots, or shared scripts.', securityPolicy: 'Security Policy' },
    logs: { account: 'Account', status: 'Status', range: 'Range', allAccounts: 'All Accounts', allStatuses: 'All Statuses', last24h: 'Last 24h', lastHour: 'Last hour', last7d: 'Last 7 days', noLogs: 'No logs available', noMatch: 'No logs match current filters', timestamp: 'Timestamp', level: 'Level', message: 'Message' },
    register: {
      desc: 'Register multiple Qoder accounts in parallel, pull device credentials and auto-save them into the pool. Browsers stay hidden in the background; each task pops to top once for human verification, then hides again — finish one, next takes its turn.',
      start: 'Start Registration',
      starting: 'Starting...',
      running: 'Tasks running',
      idle: 'Idle',
      stageLabel: 'Stage',
      statusLabel: 'Status',
      logs: 'Live Logs',
      result: 'Registration Result (auto-imported)',
      noResult: 'No task has run yet',
      countLabel: 'Parent Threads',
      staggerHint: 'Each parent loops forever: 3 child tasks per batch, next batch starts automatically until you click stop',
      stop: 'Stop Registration',
      stopping: 'Stopping (after current batch)...',
      stopHint: 'Stops after the current batch finishes and reports this run\'s stats',
      verifyHint: 'Complete the human verification in the topmost browser window (slide the slider); next task takes over automatically',
      waiting: 'Waiting for human verification',
      task: 'Task',
      statsLabel: 'This Run Stats',
      success: 'Success',
      failed: 'Failed',
      total: 'Total',
      activeTasks: 'Running',
      recentTasks: 'Recent Done',
      stage: {
        idle: 'Idle', registering: 'Registering', waiting_slider: 'Waiting for human verification (topmost)', waiting_otp: 'Waiting for email code', device_auth: 'Device authorization', saving: 'Saving to DB', success: 'Success', failed: 'Failed',
      },
    },
  },
  zh: {
    nav: {
      dashboard: '控制台', accounts: '账号池', playground: '调试对话', apiKeys: 'API Key 管理', logs: '服务日志', register: '自动注册机',
    },
    breadcrumb: {
      dashboard: '控制台 / 概览', accounts: '控制台 / 账号管理', playground: '调试 / 对话测试', apiKeys: '管理 / 安全', logs: '系统 / 日志', docs: '开发者平台 / 文档', register: '自动化 / 注册机',
    },
    title: {
      dashboard: '系统概览', accounts: '账号池', playground: '调试对话', apiKeys: 'API 管理', logs: '服务日志', docs: '文档', register: '自动注册机',
    },
    common: { docs: '文档', support: '支持', healthy: '正常', offline: '未就绪', signOut: '退出', refresh: '刷新', add: '添加', delete: '删除', copy: '复制' },
    dashboard: {
      serviceStatus: '服务状态', allGatewaysActive: '网关可用', noActiveSession: '没有可用账号', accountPool: '账号池', activeSessions: '可参与路由的 Qoder 账号', apiAuth: 'API 鉴权', openAccess: '未开启鉴权', activeUser: '当前账号', systemBriefing: '运行状态', readyBrief: '网关正在运行，当前有 {count} 个账号可用于请求路由。', notReadyBrief: '当前没有可用会话，请先导入账号或添加 PAT。', recentNotifications: '最近状态', authImportError: '本地登录导入失败', sessionActive: '账号已连接', credentialConfig: '凭据配置', credentialDesc: '添加 Qoder PAT，或导入本机已有的 Qoder 登录会话。', patPlaceholder: '输入 Qoder PAT...', addPat: '添加 PAT', saving: '保存中...', autoImport: '自动导入',
    },
    accounts: { desc: '管理网关用于请求路由和失败切换的 Qoder 账号。', refreshStatus: '刷新状态', importAccounts: '导入账号', search: '搜索账号...', empty: '还没有导入账号。点击导入账号，或在控制台添加 PAT。', showing: '共 {count} 个账号' },
    playground: { modelConfig: '模型配置', streamResponse: '流式响应', systemPrompt: '系统提示词', systemPromptPlaceholder: '定义模型的角色或行为...', ask: '输入要发送的内容...', send: '发送', waiting: '正在等待响应...' },
    api: { generate: '生成新 Key', desc: '管理客户端请求网关时使用的 API Key 和访问权限。', gatewayAuth: '网关 API 鉴权', gatewayAuthDesc: '控制 /v1 请求是否必须携带 API Key。', systemStatus: '系统状态', activeKeys: '可用 Key', configured: '已配置', activeAccessKeys: '已启用的 API Key', keyPlaceholder: '输入或粘贴 API Key...', noKeys: '还没有配置 API Key。请先生成并添加。', namePlaceholder: '名称（可留空）...', strategyFill: '策略1 · 填充：同一 Key + 模型固定使用同一账号', strategyRoundRobin: '策略2 · 轮询：每次请求依次换下一个账号', strategyFillShort: '填充', strategyRoundRobinShort: '轮询', rpmPlaceholder: 'RPM 上限', concPlaceholder: '并发上限', limitHint: '上限填 0 表示不限；超出限制的请求返回 429，保存后立即生效。', refresh: '刷新', generateShort: '随机生成', labelRpm: 'RPM', labelConc: '并发', unlimited: '∞', colName: '名称', colKey: 'API Key', colStrategy: '路由策略', colUsage: '上限 / 实时', colStatus: '状态', colActions: '操作', bestPractices: '安全建议', bestPracticesDesc: '不要把 API Key 写在前端代码里。如果 Key 出现在日志、截图或共享脚本中，请及时删除并重新生成。', securityPolicy: '安全策略' },
    logs: { account: '账号', status: '级别', range: '时间范围', allAccounts: '全部账号', allStatuses: '全部级别', last24h: '最近 24 小时', lastHour: '最近 1 小时', last7d: '最近 7 天', noLogs: '暂无日志', noMatch: '没有匹配当前筛选条件的日志', timestamp: '时间', level: '级别', message: '内容' },
    register: {
      desc: '并行注册多个 Qoder 账号并拉取 Device 凭据，成功后自动入库。浏览器平时隐藏后台，人机验证时置顶显示，划完一个自动轮到下一个。',
      start: '开始注册',
      starting: '启动中...',
      running: '任务运行中',
      idle: '空闲',
      stageLabel: '阶段',
      statusLabel: '状态',
      logs: '实时日志',
      result: '注册结果（已自动入库）',
      noResult: '尚未运行注册任务',
      countLabel: '母线程数',
      staggerHint: '每个母线程无限循环：每批 3 个子任务并发，注册完一批自动开下一批，直到点击停止',
      stop: '停止注册',
      stopping: '停止中（当前批完成后停）...',
      stopHint: '当前批次完成后停止，统计本次注册数',
      verifyHint: '请在置顶的浏览器窗口中完成人机验证（滑动滑块），划完自动轮到下一个',
      waiting: '等待人工验证',
      task: '任务',
      statsLabel: '本次注册统计',
      success: '成功',
      failed: '失败',
      total: '总计',
      activeTasks: '运行中任务',
      recentTasks: '最近完成',
      stage: {
        idle: '空闲', registering: '正在注册', waiting_slider: '等待人机验证（已置顶）', waiting_otp: '等待邮箱验证码', device_auth: 'Device 授权中', saving: '入库中', success: '注册成功', failed: '失败',
      },
    },
  },
} as const

const TOAST_STYLES: Record<ToastType, { bg: string; border: string; icon: string; iconFill: string }> = {
  SUCCESS: { bg: 'bg-white', border: 'border-l-[3px] border-l-toast-success', icon: 'check_circle', iconFill: 'text-toast-success' },
  ERROR: { bg: 'bg-white', border: 'border-l-[3px] border-l-toast-error', icon: 'error', iconFill: 'text-toast-error' },
  INFO: { bg: 'bg-white', border: 'border-l-[3px] border-l-toast-info', icon: 'info', iconFill: 'text-toast-info' },
}

// ─── Toast Context ───

const ToastCtx = createContext<{ push: (t: ToastType, title: string, message: string) => void }>({ push: () => {} })

// ─── Custom UI Components ───

function CustomCheckbox({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="flex items-center gap-3 text-sm font-bold text-ink cursor-pointer group select-none"
    >
      <span className={`w-5 h-5 rounded-md border-2 flex items-center justify-center transition-all duration-200 ${
        checked ? 'bg-ink border-ink' : 'bg-white border-hairline-strong group-hover:border-ink/40'
      }`}>
        {checked && <span className="material-symbols-outlined text-white" style={{ fontSize: '14px', fontVariationSettings: "'FILL' 1" }}>check</span>}
      </span>
      {label}
    </button>
  )
}

function CustomSelect({ value, onChange, options, placeholder }: { value: string; onChange: (v: string) => void; options: { value: string; label: string }[]; placeholder?: string }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const selected = options.find(o => o.value === value)

  useEffect(() => {
    const handler = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  return (
    <div ref={ref} className={`relative ${open ? 'z-[5000]' : 'z-10'}`}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full h-11 bg-white border border-hairline-strong rounded-lg px-4 text-sm text-ink font-medium flex items-center justify-between focus:ring-2 focus:ring-ink outline-none cursor-pointer hover:border-ink/30 transition-colors"
      >
        <span className={selected ? 'text-ink' : 'text-body/50'}>{selected?.label || placeholder || 'Select...'}</span>
        <span className={`material-symbols-outlined text-body text-[18px] transition-transform duration-200 ${open ? 'rotate-180' : ''}`}>expand_more</span>
      </button>
      {open && (
        <div className="custom-select-dropdown absolute top-full left-0 right-0 mt-1 bg-white border border-hairline rounded-lg shadow-xl z-[6000] overflow-hidden">
          {options.map(opt => (
            <button
              key={opt.value}
              type="button"
              onClick={() => { onChange(opt.value); setOpen(false) }}
              className={`w-full px-4 py-2.5 text-sm text-left font-medium transition-colors ${
                opt.value === value ? 'bg-canvas-soft text-ink font-bold' : 'text-body hover:bg-canvas-soft hover:text-ink'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function CustomInput({ value, onChange, placeholder, type = 'text', className = '', mono = false }: {
  value: string; onChange: (v: string) => void; placeholder?: string; type?: string; className?: string; mono?: boolean
}) {
  return (
    <input
      type={type}
      value={value}
      onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
      className={`w-full bg-white border border-hairline-strong text-ink text-sm px-4 py-3 rounded-lg outline-none focus:border-ink focus:ring-2 focus:ring-ink/10 transition-all placeholder:text-body/40 ${mono ? 'font-mono' : 'font-medium'} ${className}`}
    />
  )
}

function CustomTextarea({ value, onChange, placeholder, className = '', rows }: {
  value: string; onChange: (v: string) => void; placeholder?: string; className?: string; rows?: number
}) {
  return (
    <textarea
      value={value}
      onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
      rows={rows}
      className={`custom-textarea w-full bg-white border border-hairline-strong text-ink text-sm px-4 py-3 rounded-xl outline-none focus:border-ink focus:ring-2 focus:ring-ink/10 transition-all placeholder:text-body/40 resize-none ${className}`}
    />
  )
}

// ─── Toast Container ───

function ToastContainer({ toasts, dismiss }: { toasts: ToastItem[]; dismiss: (id: number) => void }) {
  const itemRefs = useRef<Map<number, HTMLDivElement>>(new Map())

  useEffect(() => {
    toasts.forEach(t => {
      const el = itemRefs.current.get(t.id)
      if (!el || el.dataset.animated === '1') return
      el.dataset.animated = '1'
      gsap.fromTo(el,
        { opacity: 0, x: 60, scale: 0.92 },
        { opacity: 1, x: 0, scale: 1, duration: 0.4, ease: 'back.out(1.2)' }
      )
    })
  }, [toasts])

  const handleDismiss = (id: number) => {
    const el = itemRefs.current.get(id)
    if (el) {
      gsap.to(el, {
        opacity: 0, x: 60, scale: 0.92, duration: 0.25, ease: 'power2.in',
        onComplete: () => dismiss(id)
      })
    } else {
      dismiss(id)
    }
  }

  return (
    <div className="fixed bottom-6 right-6 z-[100] flex flex-col-reverse gap-3 pointer-events-none" style={{ maxWidth: '380px' }}>
      {toasts.map(t => {
        const s = TOAST_STYLES[t.type]
        return (
          <div
            key={t.id}
            ref={el => { if (el) itemRefs.current.set(t.id, el) }}
            className={`pointer-events-auto ${s.bg} ${s.border} border border-hairline rounded-xl shadow-xl p-4 flex items-start gap-3 min-w-[320px]`}
          >
            <span className={`material-symbols-outlined ${s.iconFill} mt-0.5 shrink-0`} style={{ fontVariationSettings: "'FILL' 1", fontSize: '20px' }}>{s.icon}</span>
            <div className="flex-1 min-w-0">
              <div className="text-xs font-bold text-ink uppercase tracking-wider">{t.title}</div>
              <div className="text-[12px] text-body mt-0.5 leading-relaxed break-words">{t.message}</div>
            </div>
            <button onClick={() => handleDismiss(t.id)} className="text-body/40 hover:text-ink transition-colors shrink-0 mt-0.5">
              <span className="material-symbols-outlined" style={{ fontSize: '16px' }}>close</span>
            </button>
          </div>
        )
      })}
    </div>
  )
}

// ─── Main App ───

// Qoder 模型目录（与后端 bridge.QODER_MODELS 一致，参照 keirouter）
const QODER_MODEL_OPTIONS: { value: string; label: string }[] = [
  { value: 'qfmodel', label: 'Qoder（IDE 默认）' },
  { value: 'auto', label: 'Auto（自动）' },
  { value: 'ultimate', label: 'Ultimate（旗舰）' },
  { value: 'performance', label: 'Performance（性能）' },
  { value: 'efficient', label: 'Efficient（高效）' },
  { value: 'lite', label: 'Lite（轻量）' },
  { value: 'qmodel', label: 'Q Model' },
  { value: 'qmodel_latest', label: 'Q Model (Latest)' },
  { value: 'dmodel', label: 'D Model' },
  { value: 'dfmodel', label: 'DF Model' },
  { value: 'gm51model', label: 'GM 5.1 Model' },
  { value: 'kmodel', label: 'K Model' },
  { value: 'mmodel', label: 'M Model' },
]

export default function App() {
  const [lang, setLang] = useState<Lang>(() => {
    const stored = localStorage.getItem('qodergate_lang')
    if (stored === 'en' || stored === 'zh') return stored
    return navigator.language.toLowerCase().startsWith('zh') ? 'zh' : 'en'
  })
  const [token, setToken] = useState<string | null>(localStorage.getItem('gateway_token'))
  const [authError, setAuthError] = useState<string | null>(null)
  const [inputToken, setInputToken] = useState('')
  const [verifying, setVerifying] = useState(false)
  const [loginSuccess, setLoginSuccess] = useState(false)

  const [activeTab, setActiveTab] = useState<AppTabId>('dashboard')
  const [status, setStatus] = useState<UIStatus>({ ready: false, mode: 'none', username: null, uid: null, user_type: null, error: null, accounts_count: 0 })
  const [accountsConfig, setAccountsConfig] = useState<AccountsConfig>({ accounts: [], active_uid: null })
  const [apiConfig, setApiConfig] = useState<APIConfig>({ auth_required: false, allowed_keys: [] })
  const [logs, setLogs] = useState<string[]>([])
  const [loading, setLoading] = useState(true)

  const [chatMessages, setChatMessages] = useState<Message[]>([
    { role: 'assistant', content: 'Hello! I am the QoderGate AI assistant. Ask me anything — I support Markdown and LaTeX math.' }
  ])
  const [chatInput, setChatInput] = useState('')
  const [model, setModel] = useState('lite')
  const [stream, setStream] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [showThinking, setShowThinking] = useState(true)

  const [newKey, setNewKey] = useState('')
  const [copiedKey, setCopiedKey] = useState<string | null>(null)
  const [apiKeys, setApiKeys] = useState<ApiKeyEntry[]>([])
  const [keyName, setKeyName] = useState('')
  const [keyStrategy, setKeyStrategy] = useState(1)
  const [keyRpm, setKeyRpm] = useState('')
  const [keyConc, setKeyConc] = useState('')
  const [savingKey, setSavingKey] = useState(false)
  const [patToken, setPatToken] = useState('')
  const [submittingPat, setSubmittingPat] = useState(false)
  const [searchAccounts, setSearchAccounts] = useState('')
  const [isExpanded, setIsExpanded] = useState(false)

  const [showBatchImport, setShowBatchImport] = useState(false)
  const [batchJson, setBatchJson] = useState('')
  const [refreshingTokens, setRefreshingTokens] = useState(false)
  const [quotaList, setQuotaList] = useState<{ uid: string; name: string; quota: { userQuota: { total: number; used: number; remaining: number; percentage: number } } }[] | null>(null)

  const [logFilterAccount, setLogFilterAccount] = useState('all')
  const [logFilterStatus, setLogFilterStatus] = useState('all')
  const [logFilterRange, setLogFilterRange] = useState('24h')

  const [regStatus, setRegStatus] = useState<RegStatus | null>(null)
  const [regStarting, setRegStarting] = useState(false)
  const [regStopping, setRegStopping] = useState(false)
  const [regCount, setRegCount] = useState(2)
  const [regTarget, setRegTarget] = useState(0)
  const [regInterval, setRegInterval] = useState(20)
  const [proxyEdit, setProxyEdit] = useState<{ uid: string; name: string; enabled: boolean; url: string; username: string; password: string; passwordSet: boolean } | null>(null)
  const [proxySaving, setProxySaving] = useState(false)

  const switchLang = (next: Lang) => {
    setLang(next)
    localStorage.setItem('qodergate_lang', next)
  }
  const t = UI_TEXT[lang]
  const msg = {
    imported: (name: string) => lang === 'zh' ? `已导入账号：${name}` : `Imported account: ${name}`,
    importFailed: lang === 'zh' ? '导入失败' : 'Import Failed',
    patAdded: (name: string) => lang === 'zh' ? `账号“${name}”已加入账号池` : `Account "${name}" added to pool`,
    patFailed: lang === 'zh' ? 'PAT 添加失败' : 'PAT Failed',
    activated: (uid: string) => lang === 'zh' ? `已切换到账号 ${uid.substring(0, 12)}...` : `Switched active account to ${uid.substring(0, 12)}...`,
    activationFailed: lang === 'zh' ? '激活失败' : 'Activation Failed',
    updated: (enabled: boolean) => lang === 'zh' ? `账号已${enabled ? '启用' : '禁用'}` : `Account ${enabled ? 'enabled' : 'disabled'}`,
    toggleFailed: lang === 'zh' ? '更新失败' : 'Toggle Failed',
    deleted: (uid: string) => lang === 'zh' ? `已删除账号 ${uid.substring(0, 12)}...` : `Removed account ${uid.substring(0, 12)}... from pool`,
    deleteFailed: lang === 'zh' ? '删除失败' : 'Delete Failed',
    configFailed: lang === 'zh' ? '配置保存失败' : 'Config Save Failed',
    authToggled: (enabled: boolean) => lang === 'zh' ? `API Key 鉴权已${enabled ? '开启' : '关闭'}` : `API key validation ${enabled ? 'enabled' : 'disabled'}`,
    keyGenerated: lang === 'zh' ? '已生成新的 API Key，点击添加后生效。' : 'A new API key has been generated. Click Add to activate it.',
    duplicateKey: lang === 'zh' ? '这个 API Key 已存在' : 'This API key already exists in the list',
    keyAdded: lang === 'zh' ? 'API Key 已添加' : 'New API key has been added to the gateway',
    keyRemoved: lang === 'zh' ? 'API Key 已删除' : 'API key has been removed from the gateway',
    copied: lang === 'zh' ? '已复制到剪贴板' : 'Copied to clipboard',
    refreshed: lang === 'zh' ? '状态已刷新' : 'Status Refreshed',
    logsRefreshed: lang === 'zh' ? '日志已刷新' : 'Logs Refreshed',
    aiFailed: lang === 'zh' ? 'AI 请求失败' : 'AI Request Failed',
    responseDone: lang === 'zh' ? '响应已完成' : 'Response Complete',
    connectionError: lang === 'zh' ? '连接失败' : 'Connection Error',
  }
  const navLabels: Record<AppTabId, string> = {
    dashboard: t.nav.dashboard,
    accounts: t.nav.accounts,
    playground: t.nav.playground,
    'api-keys': t.nav.apiKeys,
    logs: t.nav.logs,
    register: t.nav.register,
  }
  const pageMeta: Record<AppTabId, { bc: string; title: string }> = {
    dashboard: { bc: t.breadcrumb.dashboard, title: t.title.dashboard },
    accounts: { bc: t.breadcrumb.accounts, title: t.title.accounts },
    playground: { bc: t.breadcrumb.playground, title: t.title.playground },
    'api-keys': { bc: t.breadcrumb.apiKeys, title: t.title.apiKeys },
    logs: { bc: t.breadcrumb.logs, title: t.title.logs },
    register: { bc: t.breadcrumb.register, title: t.title.register },
  }

  const loginCardRef = useRef<HTMLDivElement>(null)
  const sidebarRef = useRef<HTMLElement>(null)
  const contentBodyRef = useRef<HTMLDivElement>(null)
  const logEndRef = useRef<HTMLDivElement>(null)
  const chatEndRef = useRef<HTMLDivElement>(null)
  const statCardsRef = useRef<HTMLDivElement>(null)
  const notifListRef = useRef<HTMLUListElement>(null)
  const terminalRef = useRef<HTMLDivElement>(null)
  const orbRefs = useRef<(HTMLDivElement | null)[]>([])

  // Toast state
  const [toasts, setToasts] = useState<ToastItem[]>([])
  const toastIdRef = useRef(0)
  const pushToast = useCallback((type: ToastType, title: string, message: string) => {
    const id = ++toastIdRef.current
    setToasts(prev => [...prev, { id, type, title, message }])
    setTimeout(() => {
      setToasts(prev => {
        const el = document.querySelector(`[data-toast-id="${id}"]`)
        if (el) {
          gsap.to(el, { opacity: 0, x: 60, scale: 0.92, duration: 0.25, ease: 'power2.in' })
          setTimeout(() => setToasts(p => p.filter(t => t.id !== id)), 260)
        } else {
          return prev.filter(t => t.id !== id)
        }
        return prev
      })
    }, 4500)
  }, [])
  const dismissToast = useCallback((id: number) => setToasts(prev => prev.filter(t => t.id !== id)), [])

  const authedFetch = useCallback(async (url: string, options: RequestInit = {}) => {
    const headers = { ...(options.headers || {}), 'X-Gateway-Token': token || '' }
    const resp = await fetch(url, { ...options, headers })
    if (resp.status === 401) { localStorage.removeItem('gateway_token'); setToken(null); throw new Error('Unauthorized') }
    return resp
  }, [token])

  const fetchStatus = useCallback(async () => {
    try { const resp = await authedFetch('/ui/status'); const data = await resp.json(); setStatus(data) } catch { /* */ } finally { setLoading(false) }
  }, [authedFetch])
  const fetchAccounts = useCallback(async () => {
    try { const resp = await authedFetch('/ui/accounts'); const data = await resp.json(); setAccountsConfig(data) } catch { /* */ }
  }, [authedFetch])
  const fetchApiConfig = useCallback(async () => {
    try { const resp = await authedFetch('/ui/config'); const data = await resp.json(); setApiConfig(data) } catch { /* */ }
  }, [authedFetch])
  const fetchApiKeys = useCallback(async () => {
    try { const resp = await authedFetch('/ui/keys'); const data = await resp.json(); setApiKeys(data.keys || []) } catch { /* */ }
  }, [authedFetch])
  const doBatchImport = useCallback(async () => {
    let records: unknown
    try { records = JSON.parse(batchJson) } catch { pushToast('ERROR', lang === 'zh' ? 'JSON 解析失败' : 'Invalid JSON', ''); return }
    const arr = Array.isArray(records) ? records : (records as { accounts?: unknown[] }).accounts || []
    if (arr.length === 0) { pushToast('ERROR', lang === 'zh' ? '数组为空' : 'Empty array', ''); return }
    try {
      const resp = await authedFetch('/ui/accounts/batch-import', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ accounts: arr }),
      })
      const data = await resp.json()
      if (data.status === 'ok') {
        pushToast('SUCCESS', lang === 'zh' ? `导入 ${data.imported} 个账号` : `Imported ${data.imported}`, lang === 'zh' ? `跳过 ${data.skipped}` : `skipped ${data.skipped}`)
        setBatchJson(''); setShowBatchImport(false); fetchAccounts()
      } else { pushToast('ERROR', lang === 'zh' ? '导入失败' : 'Import failed', data.detail || '') }
    } catch { pushToast('ERROR', lang === 'zh' ? '导入失败' : 'Import failed', '') }
  }, [authedFetch, batchJson, lang, fetchAccounts, pushToast])

  const doExportAccounts = useCallback(async () => {
    try {
      const resp = await authedFetch('/ui/accounts/export?download=0')
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const text = await resp.text()
      const arr = JSON.parse(text) as unknown[]
      const stamp = new Date().toISOString().replace(/[-:]/g, '').slice(0, 15).replace('T', '-')
      const url = URL.createObjectURL(new Blob([text], { type: 'application/json' }))
      const a = document.createElement('a')
      a.href = url
      a.download = `qoder-accounts-${stamp}.json`
      document.body.appendChild(a); a.click(); a.remove()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
      pushToast('SUCCESS', lang === 'zh' ? `已导出 ${arr.length} 个账号` : `Exported ${arr.length} accounts`, lang === 'zh' ? '含邮箱/密码/token，请妥善保管' : 'Includes email/password/token')
    } catch (e) {
      pushToast('ERROR', lang === 'zh' ? '导出失败' : 'Export failed', String(e))
    }
  }, [authedFetch, lang, pushToast])

  const doRefreshTokens = useCallback(async () => {
    setRefreshingTokens(true)
    try {
      const resp = await authedFetch('/ui/accounts/refresh-tokens', { method: 'POST' })
      const data = await resp.json()
      if (data.status === 'ok') {
        pushToast('SUCCESS', lang === 'zh' ? `刷新完成 ${data.ok}/${data.total}` : `Refreshed ${data.ok}/${data.total}`, lang === 'zh' ? `失败 ${data.failed}` : `failed ${data.failed}`)
      } else { pushToast('ERROR', lang === 'zh' ? '刷新失败' : 'Refresh failed', data.error || '') }
    } catch { pushToast('ERROR', lang === 'zh' ? '刷新失败' : 'Refresh failed', '') } finally { setRefreshingTokens(false) }
  }, [authedFetch, lang, pushToast])

  const loadQuota = useCallback(async () => {
    try {
      const resp = await authedFetch('/ui/accounts/quota')
      const data = await resp.json()
      setQuotaList(data.quotas || [])
    } catch { pushToast('ERROR', lang === 'zh' ? '限额查询失败' : 'Quota query failed', '') }
  }, [authedFetch, lang, pushToast])

  const fetchLogs = useCallback(async () => {
    try { const resp = await authedFetch('/ui/logs'); const data = await resp.json(); setLogs(data) } catch { /* */ }
  }, [authedFetch])
  const fetchRegStatus = useCallback(async () => {
    try { const resp = await authedFetch('/ui/registrar/status'); const data = await resp.json(); setRegStatus(data) } catch { /* */ }
  }, [authedFetch])
  const startRegister = useCallback(async () => {
    if (regStatus?.running) return
    setRegStarting(true)
    try {
      const resp = await authedFetch('/ui/registrar/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ parents: regCount, target_success: regTarget, batch_interval: regInterval }),
      })
      const data = await resp.json()
      if (data.ok) {
        const targetMsg = data.target_success
          ? (lang === 'zh' ? `，目标成功 ${data.target_success} 个后自动停` : `, auto-stop after ${data.target_success} successes`)
          : (lang === 'zh' ? '，不限总数' : ', unlimited')
        pushToast('INFO', lang === 'zh' ? '注册已开始' : 'Registration started', lang === 'zh' ? `${data.parents} 个母线程 × 3 子任务，批间隔 ${data.batch_interval}s${targetMsg}` : `${data.parents} parents x 3 workers, batch interval ${data.batch_interval}s${targetMsg}`)
        fetchRegStatus()
      } else {
        pushToast('ERROR', lang === 'zh' ? '启动失败' : 'Start failed', data.error || '')
      }
    } catch { pushToast('ERROR', lang === 'zh' ? '启动失败' : 'Start failed', '') } finally { setRegStarting(false) }
  }, [authedFetch, fetchRegStatus, pushToast, regStatus?.running, lang, regCount, regTarget, regInterval])

  const stopRegister = useCallback(async () => {
    if (!regStatus?.running || regStopping) return
    setRegStopping(true)
    try {
      const resp = await authedFetch('/ui/registrar/stop', { method: 'POST' })
      const data = await resp.json()
      if (data.ok) {
        pushToast('INFO', lang === 'zh' ? '停止请求已发送' : 'Stop requested', lang === 'zh' ? '当前批次完成后停止' : 'Stops after the current batch')
      } else {
        pushToast('ERROR', lang === 'zh' ? '取消失败' : 'Stop failed', data.error || '')
      }
    } catch { pushToast('ERROR', lang === 'zh' ? '取消失败' : 'Stop failed', '') } finally { setRegStopping(false) }
  }, [authedFetch, pushToast, regStatus?.running, regStopping, lang])

  useEffect(() => {
    if (!token) return
      fetchStatus(); fetchAccounts(); fetchApiConfig(); fetchApiKeys(); fetchLogs(); fetchRegStatus()
    const si = setInterval(fetchStatus, 6000)
     const li = setInterval(() => { if (activeTab === 'logs') fetchLogs() }, 3000)
     const ki = setInterval(() => { if (activeTab === 'api-keys') fetchApiKeys() }, 5000)
     const ri = setInterval(() => { if (activeTab === 'register' && regStatus?.running) fetchRegStatus() }, 2000)
     return () => { clearInterval(si); clearInterval(li); clearInterval(ki); clearInterval(ri) }
   }, [token, activeTab, fetchStatus, fetchAccounts, fetchApiConfig, fetchApiKeys, fetchLogs, fetchRegStatus, regStatus?.running])

  useEffect(() => { if (activeTab === 'logs') logEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [logs, activeTab])
  useEffect(() => { if (activeTab === 'playground') chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [chatMessages, activeTab])

  // GSAP animations
  useEffect(() => { if (!token && loginCardRef.current) gsap.fromTo(loginCardRef.current, { scale: 0.92, opacity: 0, y: 30 }, { scale: 1, opacity: 1, y: 0, duration: 0.7, ease: 'back.out(1.4)' }) }, [token])
  useEffect(() => { if (token && sidebarRef.current) gsap.fromTo(sidebarRef.current, { x: -60, opacity: 0 }, { x: 0, opacity: 1, duration: 0.5, ease: 'power3.out' }) }, [token])
  useEffect(() => { if (token && contentBodyRef.current) gsap.fromTo(contentBodyRef.current, { opacity: 0, y: 20 }, { opacity: 1, y: 0, duration: 0.4, ease: 'power2.out' }) }, [activeTab, token])
  useEffect(() => {
    if (token && activeTab === 'dashboard' && statCardsRef.current) {
      const cards = statCardsRef.current.querySelectorAll('.stat-card')
      gsap.fromTo(cards, { opacity: 0, y: 30, scale: 0.95 }, { opacity: 1, y: 0, scale: 1, duration: 0.5, stagger: 0.1, ease: 'power2.out' })
    }
  }, [activeTab, token, status])
  useEffect(() => {
    if (token && activeTab === 'dashboard' && notifListRef.current) {
      const items = notifListRef.current.querySelectorAll('li')
      gsap.fromTo(items, { opacity: 0, x: -20 }, { opacity: 1, x: 0, duration: 0.4, stagger: 0.12, ease: 'power2.out' })
    }
  }, [activeTab, token])
  useEffect(() => {
    if (token && activeTab === 'dashboard' && terminalRef.current) {
      const lines = terminalRef.current.querySelectorAll('.term-line')
      gsap.fromTo(lines, { opacity: 0, x: -10 }, { opacity: 1, x: 0, duration: 0.3, stagger: 0.15, ease: 'power1.out' })
    }
  }, [activeTab, token])
  useEffect(() => {
    orbRefs.current.forEach((orb, i) => {
      if (!orb) return
      gsap.to(orb, { x: `+=${10 + i * 5}`, y: `-=${8 + i * 3}`, duration: 6 + i * 2, repeat: -1, yoyo: true, ease: 'sine.inOut' })
    })
  }, [token])

  // ─── Handlers ───

  const handleVerifyToken = async (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = inputToken.trim()
    if (!trimmed) return
    setVerifying(true); setAuthError(null)
    try {
      const resp = await fetch('/ui/verify', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token: trimmed }) })
      if (resp.ok) {
        setLoginSuccess(true)
        if (loginCardRef.current) {
          gsap.to(loginCardRef.current, { scale: 1.02, duration: 0.3, ease: 'power2.out', onComplete: () => { localStorage.setItem('gateway_token', trimmed); setToken(trimmed); setInputToken('') } })
        }
      } else {
        if (loginCardRef.current) gsap.to(loginCardRef.current, { x: 10, duration: 0.04, repeat: 7, yoyo: true, onComplete: () => gsap.set(loginCardRef.current!, { x: 0 }) })
        setAuthError('Invalid gateway access token')
      }
    } catch (err: any) { setAuthError(`Connection failed: ${err.message}`) } finally { setVerifying(false) }
  }

  const handleLogout = () => { localStorage.removeItem('gateway_token'); setToken(null); setLoginSuccess(false) }

  const handleImportAuth = async () => {
    setLoading(true)
    try {
      const resp = await authedFetch('/ui/accounts/import', { method: 'POST' })
      if (!resp.ok) { const err = await resp.json(); throw new Error(err.detail || 'Import failed') }
      const data = await resp.json()
      pushToast('SUCCESS', lang === 'zh' ? '账号已导入' : 'Account Imported', msg.imported(data.account?.name || (lang === 'zh' ? '本地会话' : 'local session')))
      fetchAccounts(); fetchStatus(); fetchLogs()
    } catch (err: any) {
      pushToast('ERROR', msg.importFailed, err.message)
    } finally { setLoading(false) }
  }

  const handleSavePat = async () => {
    if (!patToken.trim()) return
    setSubmittingPat(true)
    try {
      const resp = await authedFetch('/ui/session', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pat: patToken }) })
      if (!resp.ok) { const err = await resp.json(); throw new Error(err.detail || 'PAT save failed') }
      const data = await resp.json()
      pushToast('SUCCESS', lang === 'zh' ? 'PAT 已添加' : 'PAT Added', msg.patAdded(data.name || 'PAT Account'))
      setPatToken(''); fetchAccounts(); fetchStatus(); fetchLogs()
    } catch (err: any) {
      pushToast('ERROR', msg.patFailed, err.message)
    } finally { setSubmittingPat(false) }
  }

  const handleSelectAccount = async (uid: string) => {
    try {
      const resp = await authedFetch('/ui/accounts/select', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ uid }) })
      if (!resp.ok) throw new Error('Switch failed')
      pushToast('INFO', lang === 'zh' ? '账号已激活' : 'Account Activated', msg.activated(uid))
      fetchAccounts(); fetchStatus(); fetchLogs()
    } catch (err: any) { pushToast('ERROR', msg.activationFailed, err.message) }
  }

  const handleToggleAccount = async (uid: string, enabled: boolean) => {
    try {
      const resp = await authedFetch('/ui/accounts/toggle', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ uid, enabled }) })
      if (!resp.ok) throw new Error('Toggle failed')
      pushToast('INFO', lang === 'zh' ? '账号已更新' : 'Account Updated', msg.updated(enabled))
      fetchAccounts(); fetchStatus()
    } catch (err: any) { pushToast('ERROR', msg.toggleFailed, err.message) }
  }

  const handleDeleteAccount = async (uid: string) => {
    if (!confirm('Delete this account from the database?')) return
    try {
      const resp = await authedFetch(`/ui/accounts/${uid}`, { method: 'DELETE' })
      if (!resp.ok) throw new Error('Delete failed')
      pushToast('SUCCESS', lang === 'zh' ? '账号已删除' : 'Account Deleted', msg.deleted(uid))
      fetchAccounts(); fetchStatus(); fetchLogs()
    } catch (err: any) { pushToast('ERROR', msg.deleteFailed, err.message) }
  }

  const openProxyEditor = (acc: Account) => {
    setProxyEdit({
      uid: acc.uid, name: acc.name,
      enabled: !!acc.proxy_enabled,
      url: acc.proxy_url || '',
      username: acc.proxy_username || '',
      password: '', passwordSet: !!acc.proxy_password_set,
    })
  }

  const handleSaveProxy = async () => {
    if (!proxyEdit) return
    setProxySaving(true)
    try {
      const body: Record<string, unknown> = {
        uid: proxyEdit.uid,
        proxy_enabled: proxyEdit.enabled,
        proxy_url: proxyEdit.url.trim(),
        proxy_username: proxyEdit.username.trim(),
      }
      // 密码留空 = 保留原密码；只有真输入了才提交
      if (proxyEdit.password !== '') body.proxy_password = proxyEdit.password
      const resp = await authedFetch('/ui/accounts/proxy', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await resp.json()
      if (!resp.ok || !data.ok) throw new Error(data.detail || 'Save failed')
      pushToast('SUCCESS', lang === 'zh' ? '代理设置已保存' : 'Proxy settings saved',
        lang === 'zh' ? `${proxyEdit.name}${proxyEdit.enabled ? ' → ' + (proxyEdit.url || '直连') : ' → 未启用代理'}` : `${proxyEdit.name}`)
      setProxyEdit(null)
      fetchAccounts()
    } catch (err: any) {
      pushToast('ERROR', lang === 'zh' ? '保存失败' : 'Save failed', err.message)
    } finally { setProxySaving(false) }
  }

  // 只提交 auth_required：allowed_keys 由专用接口维护，
  // 避免旧的 string[] 语义把「已停用 Key」的名称/策略/限额连带清掉
  const handleSaveApiConfig = async (newConfig: APIConfig) => {
    try {
      await authedFetch('/ui/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ auth_required: newConfig.auth_required }) })
      setApiConfig(newConfig)
    } catch { pushToast('ERROR', msg.configFailed, lang === 'zh' ? '无法更新 API 配置' : 'Could not update API configuration') }
  }

  const handleToggleAuth = () => {
    const updated = { ...apiConfig, auth_required: !apiConfig.auth_required }
    handleSaveApiConfig(updated)
    pushToast('INFO', lang === 'zh' ? '鉴权状态已更新' : 'Auth Toggled', msg.authToggled(!apiConfig.auth_required))
  }

  const handleGenerateKey = () => {
    const random = 'qg_live_' + Array.from(crypto.getRandomValues(new Uint8Array(16))).map(b => b.toString(16).padStart(2, '0')).join('')
    setNewKey(random)
    pushToast('INFO', lang === 'zh' ? 'Key 已生成' : 'Key Generated', msg.keyGenerated)
  }

  /** 新增或更新一条 API Key（未传字段后端会保留旧值） */
  const handleSaveKey = async (patch: Partial<ApiKeyEntry> & { api_key: string }): Promise<boolean> => {
    setSavingKey(true)
    try {
      const resp = await authedFetch('/ui/keys', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch) })
      if (!resp.ok) {
        const detail = await resp.json().catch(() => ({} as { detail?: string }))
        throw new Error(detail.detail || `HTTP ${resp.status}`)
      }
      await fetchApiKeys()
      return true
    } catch (err) { pushToast('ERROR', lang === 'zh' ? 'API Key 保存失败' : 'Failed to save API Key', (err as Error).message); return false }
    finally { setSavingKey(false) }
  }

  const handleAddKey = async () => {
    const trimmed = newKey.trim()
    if (!trimmed) return
    if (apiKeys.some(k => k.api_key === trimmed)) { pushToast('ERROR', lang === 'zh' ? 'Key 已存在' : 'Duplicate Key', msg.duplicateKey); return }
    const ok = await handleSaveKey({
      api_key: trimmed,
      name: keyName.trim(),
      strategy: keyStrategy,
      rpm_limit: Math.max(0, Number(keyRpm) || 0),
      concurrency_limit: Math.max(0, Number(keyConc) || 0),
      enabled: 1,
    })
    if (ok) {
      pushToast('SUCCESS', lang === 'zh' ? 'Key 已添加' : 'Key Added', msg.keyAdded)
      setNewKey(''); setKeyName(''); setKeyRpm(''); setKeyConc(''); setKeyStrategy(1)
    }
  }

  const handleDeleteKey = async (key: string) => {
    if (!confirm(lang === 'zh' ? `确认删除该 API Key？\n${key}` : `Delete this API Key?\n${key}`)) return
    try {
      const resp = await authedFetch(`/ui/keys/${encodeURIComponent(key)}`, { method: 'DELETE' })
      if (!resp.ok && resp.status !== 404) throw new Error(`HTTP ${resp.status}`)
      await fetchApiKeys()
      pushToast('SUCCESS', lang === 'zh' ? 'Key 已删除' : 'Key Removed', msg.keyRemoved)
    } catch (err) { pushToast('ERROR', msg.deleteFailed, (err as Error).message) }
  }

  const handleToggleKeyEnabled = async (entry: ApiKeyEntry) => {
    await handleSaveKey({ api_key: entry.api_key, enabled: entry.enabled ? 0 : 1 })
  }

  /** Key 打码显示（明文可点复制按钮获取） */
  const maskKey = (key: string) => (key.length <= 14 ? key : `${key.slice(0, 8)}…${key.slice(-4)}`)

  const handleCopyKey = (key: string) => {
    navigator.clipboard.writeText(key)
    setCopiedKey(key)
    pushToast('INFO', lang === 'zh' ? '已复制' : 'Copied', msg.copied)
    setTimeout(() => setCopiedKey(null), 2000)
  }

  const handleRefreshStatus = () => {
    fetchAccounts(); fetchStatus(); fetchLogs()
    pushToast('INFO', msg.refreshed, lang === 'zh' ? '账号池和系统状态已更新' : 'Account pool and system status updated')
  }

  const handleSendChat = async (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = chatInput.trim()
    if (!trimmed || generating) return
    setChatMessages(prev => [...prev, { role: 'user', content: trimmed }])
    setChatInput(''); setGenerating(true)
    setChatMessages(prev => [...prev, { role: 'assistant', content: '' }])

    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    if (apiConfig.auth_required && apiConfig.allowed_keys.length > 0) headers['Authorization'] = `Bearer ${apiConfig.allowed_keys[0]}`

    try {
      const response = await fetch('/v1/chat/completions', { method: 'POST', headers, body: JSON.stringify({ model, messages: [{ role: 'user', content: trimmed }], stream }) })
      if (!response.ok) {
        const errData = await response.json()
        const errMsg = errData.detail || errData.error?.message || response.statusText
        setChatMessages(prev => { const u = [...prev]; u[u.length - 1] = { role: 'assistant', content: `Request failed: ${errMsg}` }; return u })
        pushToast('ERROR', msg.aiFailed, errMsg)
        setGenerating(false); return
      }
      if (stream) {
        const reader = response.body?.getReader()
        if (!reader) throw new Error('No stream reader')
        const decoder = new TextDecoder('utf-8')
        let buffer = ''; let currentResponse = ''
        while (true) {
          const { value, done } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n'); buffer = lines.pop() || ''
          for (const line of lines) {
            const tl = line.trim()
            if (!tl.startsWith('data:')) continue
            const rawData = tl.slice(5).trim()
            if (rawData === '[DONE]') continue
            try { const parsed = JSON.parse(rawData); const chunk = parsed.choices?.[0]?.delta?.content || ''; currentResponse += chunk; setChatMessages(prev => { const u = [...prev]; u[u.length - 1] = { role: 'assistant', content: currentResponse }; return u }) } catch { /* */ }
          }
        }
        pushToast('SUCCESS', msg.responseDone, lang === 'zh' ? '流式响应已结束' : 'AI response stream finished successfully')
      } else {
        const data = await response.json()
        const ans = data.choices?.[0]?.message?.content || ''
        setChatMessages(prev => { const u = [...prev]; u[u.length - 1] = { role: 'assistant', content: ans }; return u })
        pushToast('SUCCESS', msg.responseDone, lang === 'zh' ? '已收到 AI 响应' : 'AI response received successfully')
      }
    } catch (err: any) {
      setChatMessages(prev => { const u = [...prev]; u[u.length - 1] = { role: 'assistant', content: `Connection error: ${err.message}` }; return u })
      pushToast('ERROR', msg.connectionError, err.message)
    } finally { setGenerating(false) }
  }

  const renderMessageContent = (text: string) => {
    const thinkingRegex = /<thinking>([\s\S]*?)(?:<\/thinking>|$)/
    const match = text.match(thinkingRegex)
    if (match) {
      const thinking = match[1]; const response = text.replace(thinkingRegex, '').trim()
      return (
        <div className="space-y-3">
          <div className="bg-canvas-soft border border-hairline rounded-xl overflow-hidden">
            <button onClick={() => setIsExpanded(!isExpanded)} className="w-full flex items-center gap-2 px-4 py-2.5 text-xs font-bold text-body hover:text-ink transition-colors">
              <span className="material-symbols-outlined text-base">psychology</span>Thinking Process
              <span className={`material-symbols-outlined transition-transform ${isExpanded ? 'rotate-180' : ''}`}>expand_more</span>
            </button>
            {isExpanded && <div className="px-4 py-3 text-xs text-body italic leading-relaxed border-t border-hairline opacity-70 whitespace-pre-wrap">{thinking}</div>}
          </div>
          {response && <div className="prose prose-stone max-w-none text-sm leading-relaxed"><ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>{response}</ReactMarkdown></div>}
        </div>
      )
    }
    return <div className="prose prose-stone max-w-none text-sm leading-relaxed"><ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>{text}</ReactMarkdown></div>
  }

  const getLogLevel = (log: string) => (log.match(/\[(INFO|ERROR|WARNING)\]/)?.[1] || 'INFO').toLowerCase()
  const getLogMinutes = (log: string) => {
    const match = log.match(/^\[(\d{2}):(\d{2}):(\d{2})\]/)
    if (!match) return null
    return Number(match[1]) * 60 + Number(match[2])
  }
  const getLogAccount = (log: string) => {
    const routed = log.match(/Request routing via account:\s*(.+?)\s*\(([^)]+)\)/)
    if (routed) return routed[2]
    const failed = log.match(/Request failed on account\s+([^:]+):/)
    if (failed) return failed[1]
    return null
  }
  const accountLogOptions = [
    { value: 'all', label: 'All Accounts' },
    ...Array.from(new Set([
      ...accountsConfig.accounts.map(acc => acc.uid),
      ...logs.map(getLogAccount).filter((uid): uid is string => Boolean(uid))
    ])).map(uid => ({ value: uid, label: accountsConfig.accounts.find(acc => acc.uid === uid)?.name || uid }))
  ]
  const filteredLogs = logs.filter(log => {
    if (logFilterStatus !== 'all' && getLogLevel(log) !== logFilterStatus) return false
    if (logFilterAccount !== 'all' && getLogAccount(log) !== logFilterAccount) return false
    if (logFilterRange === '1h') {
      const minutes = getLogMinutes(log)
      if (minutes === null) return false
      const now = new Date()
      const nowMinutes = now.getHours() * 60 + now.getMinutes()
      const diff = (nowMinutes - minutes + 1440) % 1440
      return diff <= 60
    }
    return true
  })
  // ─── LOGIN PAGE ───
  if (!token) {
    return (
      <div className="bg-surface text-ink min-h-screen flex items-center justify-center p-4 overflow-hidden relative">
        <div ref={el => { orbRefs.current[0] = el }} className="atmospheric-orb absolute top-1/4 left-1/3 w-[400px] h-[400px] bg-lavender rounded-full"></div>
        <div ref={el => { orbRefs.current[1] = el }} className="atmospheric-orb absolute bottom-1/4 right-1/3 w-[500px] h-[500px] bg-sky rounded-full" style={{ animationDelay: '-4s' }}></div>
        <main ref={loginCardRef} className="relative w-full max-w-[440px] z-10">
          <div className="surface-card glass-card rounded-xl p-8 border border-hairline shadow-sm">
            <div className="flex flex-col items-center mb-8">
              <div className="w-10 h-10 bg-ink rounded-lg flex items-center justify-center mb-4">
                <span className="material-symbols-outlined text-white" style={{ fontVariationSettings: "'FILL' 1" }}>gate</span>
              </div>
              <h1 className="font-display-lg text-ink tracking-tight">QoderGate</h1>
              <p className="text-[12px] font-semibold text-on-surface-variant mt-2 uppercase tracking-widest">{lang === 'zh' ? '管理控制台' : 'Management Console'}</p>
            </div>
            <form className="space-y-6" onSubmit={handleVerifyToken}>
              <div className="space-y-2">
                <label className="font-bold text-ink text-[16px]">{lang === 'zh' ? '网关访问密钥' : 'Gateway Access Token'}</label>
                <CustomInput type="password" value={inputToken} onChange={setInputToken} placeholder={lang === 'zh' ? '输入你的安全密钥...' : 'Enter your security token...'} />
              </div>
              {authError && (
                <div className="flex items-center gap-2 p-3.5 bg-red-50 border border-red-200 text-red-700 rounded-lg text-xs font-semibold">
                  <span className="material-symbols-outlined text-base">warning</span>{authError}
                </div>
              )}
              <button className={`w-full font-bold py-4 rounded-full transition-all flex items-center justify-center group ${loginSuccess ? 'bg-mint text-ink' : 'bg-ink text-white hover:bg-primary'}`} type="submit" disabled={verifying}>
                {verifying ? (
                  <><svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg><span>Authenticating...</span></>
                ) : loginSuccess ? (
                  <><span className="material-symbols-outlined">check_circle</span><span className="ml-2">{lang === 'zh' ? '访问已授权' : 'Access Granted'}</span></>
                ) : (
                  <><span className="text-[15px]">{lang === 'zh' ? '验证密钥' : 'Verify Token'}</span><span className="material-symbols-outlined ml-2 transition-transform group-hover:translate-x-1">arrow_forward</span></>
                )}
              </button>
            </form>
            <button onClick={() => switchLang(lang === 'zh' ? 'en' : 'zh')} className="mt-4 w-full text-xs font-bold text-body hover:text-ink transition-colors">
              {lang === 'zh' ? 'Switch to English' : '切换到中文'}
            </button>
            <div className="mt-8 pt-6 border-t border-hairline flex flex-col items-center gap-4">
              <div className="flex items-center gap-2 text-on-surface-variant"><span className="material-symbols-outlined text-[18px]">verified_user</span><p className="text-[13px]">End-to-end encrypted session</p></div>
              <p className="text-[12px] text-on-surface-variant/70 text-center leading-relaxed">Access is restricted to authorized personnel. All connection attempts are logged and monitored.</p>
            </div>
          </div>
          <div className="mt-4 flex justify-between px-4 opacity-40">
            <span className="text-[10px] tracking-widest text-ink uppercase">v2.4.0 stable</span>
            <span className="text-[10px] tracking-widest text-ink uppercase">Status: Operational</span>
          </div>
        </main>
      </div>
    )
  }

  // ─── MAIN LAYOUT ───
  const { bc, title } = pageMeta[activeTab]

  return (
    <div className="bg-surface min-h-screen relative">
      <div ref={el => { orbRefs.current[2] = el }} className="orb bg-mint w-[500px] h-[500px] -top-24 -right-24"></div>
      <div ref={el => { orbRefs.current[3] = el }} className="orb bg-peach w-[400px] h-[400px] bottom-0 left-[20%]"></div>

      <aside ref={sidebarRef} className="fixed left-0 top-0 h-screen w-[280px] bg-surface border-r border-hairline flex flex-col p-6 z-50">
        <div className="flex items-center gap-3 mb-8">
          <div className="w-10 h-10 bg-ink rounded-lg flex items-center justify-center"><span className="material-symbols-outlined text-white" style={{ fontVariationSettings: "'FILL' 1" }}>gate</span></div>
          <div><h1 className="font-display-sm text-ink leading-none">QoderGate</h1><p className="text-[10px] uppercase tracking-widest text-body opacity-60">{lang === 'zh' ? '管理控制台' : 'Management Console'}</p></div>
        </div>
        <nav className="flex-1 space-y-1">
          {NAV_ITEMS.map((item) => (
            <button key={item.id} onClick={() => setActiveTab(item.id)} className={`flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors font-medium w-full text-left ${activeTab === item.id ? 'bg-canvas-soft text-ink font-bold' : 'text-body hover:bg-canvas-soft'}`}>
              <span className="material-symbols-outlined" style={{ fontVariationSettings: activeTab === item.id ? "'FILL' 1" : "" }}>{item.icon}</span>{navLabels[item.id]}
            </button>
          ))}
        </nav>
        <div className="pt-8 border-t border-hairline">
          <div className="flex items-center justify-between px-3 py-2.5">
            <div className="flex items-center gap-2">
              <span className={`w-2.5 h-2.5 rounded-full ${status.ready ? 'bg-mint animate-pulse' : 'bg-red-400'}`}></span>
              <span className="text-xs font-semibold text-body">{status.ready ? t.common.healthy : t.common.offline}</span>
            </div>
            <button onClick={handleLogout} className="text-xs font-bold text-body hover:text-red-600 transition-colors">{t.common.signOut}</button>
          </div>
        </div>
      </aside>

      <main className="ml-[280px] min-h-screen flex flex-col relative z-10">
        <header className="flex justify-between items-center h-24 px-8 w-full border-b border-hairline bg-transparent sticky top-0 z-40 backdrop-blur-sm">
          <div>
            <span className="text-[12px] font-semibold text-body uppercase opacity-60 tracking-[0.96px]">{bc}</span>
            <h2 className="font-display-lg text-ink">{title}</h2>
          </div>
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-8 text-body text-[16px]">
              <a href="/documents" className="hover:text-ink transition-colors cursor-pointer">{t.common.docs}</a>
              <button onClick={() => switchLang(lang === 'zh' ? 'en' : 'zh')} className="hover:text-ink transition-colors cursor-pointer">{lang === 'zh' ? 'English' : '中文'}</button>
              <a className="hover:text-ink transition-colors cursor-pointer">{t.common.support}</a>
            </div>
            <div className="flex items-center gap-4">
              <button className="p-2 text-body hover:text-ink transition-colors"><span className="material-symbols-outlined">notifications</span></button>
              <div className="w-10 h-10 rounded-full bg-hairline flex items-center justify-center border border-hairline-strong text-xs font-bold text-ink">{status.username ? status.username[0].toUpperCase() : 'Q'}</div>
            </div>
          </div>
        </header>

        <div ref={contentBodyRef} className="flex-1 p-8 w-full">
          {/* ─── DASHBOARD ─── */}
          {activeTab === 'dashboard' && (
            <div className="space-y-8">
              <section ref={statCardsRef} className="grid grid-cols-1 md:grid-cols-4 gap-6">
                {[
                  { label: t.dashboard.serviceStatus, value: status.ready ? t.common.healthy : t.common.offline, detail: status.ready ? t.dashboard.allGatewaysActive : t.dashboard.noActiveSession, dot: status.ready ? 'bg-mint' : 'bg-red-400' },
                  { label: t.dashboard.accountPool, value: String(status.accounts_count || 0), detail: t.dashboard.activeSessions },
                  { label: t.dashboard.apiAuth, value: apiConfig.auth_required ? (lang === 'zh' ? '已开启' : 'Enabled') : (lang === 'zh' ? '未开启' : 'Disabled'), detail: apiConfig.auth_required ? `${apiConfig.allowed_keys.length} keys active` : t.dashboard.openAccess },
                  { label: t.dashboard.activeUser, value: status.username || (lang === 'zh' ? '无' : 'None'), detail: status.user_type || 'N/A' }
                ].map((stat, i) => (
                  <div key={i} className="stat-card bg-surface-card border border-hairline p-6 rounded-xl hover:shadow-[0_4px_16px_rgba(0,0,0,0.04)] transition-all cursor-default">
                    <div className="text-[12px] font-semibold text-body mb-2 uppercase tracking-widest">{stat.label}</div>
                    <div className="flex items-center gap-2"><span className="font-display-sm text-ink">{stat.value}</span>{stat.dot && <div className={`h-2 w-2 rounded-full ${stat.dot}`}></div>}</div>
                    <div className="text-[12px] text-body mt-2">{stat.detail}</div>
                  </div>
                ))}
              </section>

              <section className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-stretch">
                <div className="lg:col-span-2 glass-card p-8 rounded-2xl flex flex-col">
                  <div className="text-[12px] font-semibold text-body mb-2 uppercase tracking-widest">{t.dashboard.systemBriefing}</div>
                  <div className="font-display-md text-ink mb-4 max-w-lg">{status.ready ? t.dashboard.readyBrief.replace('{count}', String(status.accounts_count)) : t.dashboard.notReadyBrief}</div>
                  <div className="mt-auto bg-ink/5 p-4 rounded-lg border border-hairline-strong" ref={terminalRef}>
                    <code className="text-sm font-mono text-ink">
                      <span className="text-primary font-bold">system@qodergate:~$</span> status --check --all<br />
                      <span className="term-line opacity-70">Checking nodes... [{status.ready ? 'OK' : 'FAIL'}]<br /></span>
                      <span className="term-line opacity-70">Validating certificates... [OK]<br /></span>
                      <span className="term-line opacity-70">Routing traffic to nearest node...</span><span className="cursor-blink">_</span>
                    </code>
                  </div>
                </div>
                <div className="bg-surface-card border border-hairline p-8 rounded-2xl">
                  <div className="text-[12px] font-semibold text-body mb-6 uppercase tracking-widest">{t.dashboard.recentNotifications}</div>
                  <ul ref={notifListRef} className="space-y-4">
                    {status.error ? (
                      <li className="flex items-start gap-4"><span className="material-symbols-outlined text-peach">warning</span><div><div className="font-bold text-[16px]">{t.dashboard.authImportError}</div><div className="text-[12px] text-body break-all">{status.error}</div></div></li>
                    ) : (
                      <>
                        <li className="flex items-start gap-4"><span className="material-symbols-outlined text-sky">info</span><div><div className="font-bold text-[16px]">{t.dashboard.apiAuth}</div><div className="text-[12px] text-body">{apiConfig.auth_required ? (lang === 'zh' ? '外部请求需要 API Key' : 'External requests require API keys') : t.dashboard.openAccess}</div></div></li>
                        <li className="flex items-start gap-4"><span className="material-symbols-outlined text-mint">check_circle</span><div><div className="font-bold text-[16px]">{t.dashboard.sessionActive}</div><div className="text-[12px] text-body">{status.username || (lang === 'zh' ? '暂无账号' : 'No account')}</div></div></li>
                      </>
                    )}
                  </ul>
                </div>
              </section>

              <section className="bg-surface-card border border-hairline p-8 rounded-2xl">
                <div className="text-[12px] font-semibold text-body mb-2 uppercase tracking-widest">{t.dashboard.credentialConfig}</div>
                <p className="text-body text-[16px] mb-6">{t.dashboard.credentialDesc}</p>
                <div className="flex flex-col sm:flex-row gap-4 max-w-2xl">
                  <div className="flex-grow">
                    <CustomInput type="password" value={patToken} onChange={setPatToken} placeholder={t.dashboard.patPlaceholder} />
                  </div>
                  <div className="flex gap-2">
                    <button onClick={handleSavePat} disabled={submittingPat} className="bg-ink text-white font-bold px-5 py-3 rounded-lg text-sm transition-all hover:bg-primary disabled:opacity-50">
                      {submittingPat ? t.dashboard.saving : t.dashboard.addPat}
                    </button>
                    <button onClick={handleImportAuth} className="flex items-center gap-2 px-4 py-3 text-ink hover:bg-canvas-soft border border-hairline font-semibold rounded-lg text-sm transition-all">
                      <span className="material-symbols-outlined text-[18px]">refresh</span>{t.dashboard.autoImport}
                    </button>
                  </div>
                </div>
              </section>
            </div>
          )}

          {/* ─── ACCOUNT POOL ─── */}
          {activeTab === 'accounts' && (
            <div className="space-y-8">
              <section className="flex justify-between items-end flex-wrap gap-4">
                <div className="max-w-xl"><p className="text-body text-[16px]">{t.accounts.desc}</p></div>
                <div className="flex gap-4 flex-wrap">
                  <button onClick={doExportAccounts} className="flex items-center gap-2 px-4 py-2.5 rounded-lg transition-all font-bold text-sm border text-body hover:text-ink border-hairline">
                    <span className="material-symbols-outlined text-[18px]">file_download</span>{lang === 'zh' ? '导出账号' : 'Export'}
                  </button>
                  <button onClick={() => { setShowBatchImport(v => !v); setQuotaList(null) }} className={`flex items-center gap-2 px-4 py-2.5 rounded-lg transition-all font-bold text-sm border ${showBatchImport ? 'bg-ink text-white border-ink' : 'text-body hover:text-ink border-hairline'}`}>
                    <span className="material-symbols-outlined text-[18px]">file_upload</span>{lang === 'zh' ? '批量导入' : 'Batch Import'}
                  </button>
                  <button onClick={doRefreshTokens} disabled={refreshingTokens} className="flex items-center gap-2 px-4 py-2.5 text-body hover:text-ink transition-colors font-bold text-sm disabled:opacity-40">
                    <span className="material-symbols-outlined text-[18px]">autorenew</span>{refreshingTokens ? (lang === 'zh' ? '刷新中...' : 'Refreshing...') : (lang === 'zh' ? '刷新 Token' : 'Refresh Tokens')}
                  </button>
                  <button onClick={() => { loadQuota(); setShowBatchImport(false) }} className={`flex items-center gap-2 px-4 py-2.5 rounded-lg transition-all font-bold text-sm border ${quotaList ? 'bg-ink text-white border-ink' : 'text-body hover:text-ink border-hairline'}`}>
                    <span className="material-symbols-outlined text-[18px]">data_usage</span>{lang === 'zh' ? '查看限额' : 'Quota'}
                  </button>
                  <button onClick={handleRefreshStatus} className="flex items-center gap-2 px-4 py-2.5 text-body hover:text-ink transition-colors font-bold text-sm">
                    <span className="material-symbols-outlined text-[18px]">refresh</span>{t.accounts.refreshStatus}
                  </button>
                  <button onClick={handleImportAuth} className="flex items-center gap-2 px-6 py-2.5 bg-ink text-white rounded-lg hover:bg-neutral-800 transition-all font-bold text-sm shadow-md">
                    <span className="material-symbols-outlined text-[18px]">add</span>{t.accounts.importAccounts}
                  </button>
                </div>
              </section>

              {showBatchImport && (
                <section className="bg-surface-card border border-hairline rounded-2xl p-6">
                  <label className="text-[12px] font-semibold text-body mb-3 block uppercase tracking-widest">{lang === 'zh' ? '粘贴注册机导出的 JSON（accounts.json）' : 'Paste registrar-exported JSON (accounts.json)'}</label>
                  <textarea
                    value={batchJson}
                    onChange={e => setBatchJson(e.target.value)}
                    rows={6}
                    placeholder='[{ "user_id": "019f...", "name": "...", "email": "...", "token": "dt-...", "refresh_token": "drt-...", "expires_at": "..." }]'
                    className="w-full p-4 rounded-xl border border-hairline bg-white/60 font-mono text-[13px] text-ink outline-none focus:border-ink/30 transition-colors"
                  />
                  <div className="mt-3 flex gap-3">
                    <button onClick={doBatchImport} className="bg-ink text-white font-bold px-6 py-2.5 rounded-lg text-sm transition-all hover:bg-neutral-800">{lang === 'zh' ? '导入' : 'Import'}</button>
                    <button onClick={() => { setBatchJson(''); setShowBatchImport(false) }} className="px-4 py-2.5 text-body border border-hairline rounded-lg text-sm font-bold hover:text-ink">{lang === 'zh' ? '取消' : 'Cancel'}</button>
                  </div>
                </section>
              )}

              {proxyEdit && (
                <section className="bg-surface-card border border-hairline rounded-2xl p-6">
                  <div className="flex items-center gap-2 mb-4">
                    <span className="material-symbols-outlined text-[18px] text-body">vpn_lock</span>
                    <span className="text-sm font-semibold text-ink">
                      {lang === 'zh' ? '账号代理设置' : 'Account Proxy'} — <span className="font-mono">{proxyEdit.name}</span>
                    </span>
                  </div>
                  <div className="space-y-4">
                    <label className="flex items-center gap-3 cursor-pointer select-none">
                      <button
                        onClick={() => setProxyEdit({ ...proxyEdit, enabled: !proxyEdit.enabled })}
                        className={`w-11 h-6 rounded-full p-0.5 transition-colors relative ${proxyEdit.enabled ? 'bg-ink' : 'bg-hairline-strong'}`}
                      >
                        <div className={`w-5 h-5 bg-white rounded-full transition-transform duration-200 ${proxyEdit.enabled ? 'translate-x-5' : 'translate-x-0'}`}></div>
                      </button>
                      <span className="text-sm font-semibold text-ink">{lang === 'zh' ? '启用代理' : 'Enable proxy'}</span>
                      <span className="text-[11px] text-body">{lang === 'zh' ? '关闭时回退 .env 全局代理或直连' : 'Falls back to .env global proxy or direct'}</span>
                    </label>
                    <div>
                      <label className="text-[12px] font-semibold text-body mb-2 block uppercase tracking-widest">{lang === 'zh' ? '代理地址' : 'Proxy URL'}</label>
                      <CustomInput value={proxyEdit.url} onChange={v => setProxyEdit({ ...proxyEdit, url: v })} placeholder="http://127.0.0.1:7890 或 socks5://127.0.0.1:7891" className="!py-3 !rounded-xl !bg-white/60" />
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div>
                        <label className="text-[12px] font-semibold text-body mb-2 block uppercase tracking-widest">{lang === 'zh' ? '代理账号（可空）' : 'Proxy user (optional)'}</label>
                        <CustomInput value={proxyEdit.username} onChange={v => setProxyEdit({ ...proxyEdit, username: v })} placeholder="user" className="!py-3 !rounded-xl !bg-white/60" />
                      </div>
                      <div>
                        <label className="text-[12px] font-semibold text-body mb-2 block uppercase tracking-widest">
                          {lang === 'zh' ? '代理密码（可空）' : 'Proxy password (optional)'}
                          {proxyEdit.passwordSet && <span className="ml-2 text-mint">{lang === 'zh' ? '已设置' : 'set'}</span>}
                        </label>
                        <CustomInput value={proxyEdit.password} onChange={v => setProxyEdit({ ...proxyEdit, password: v })} placeholder={proxyEdit.passwordSet ? (lang === 'zh' ? '留空 = 保持不变' : 'empty = keep') : 'password'} className="!py-3 !rounded-xl !bg-white/60" />
                      </div>
                    </div>
                    <div className="flex gap-3 pt-1">
                      <button onClick={handleSaveProxy} disabled={proxySaving} className="bg-ink text-white font-bold px-6 py-2.5 rounded-lg text-sm transition-all hover:bg-neutral-800 disabled:opacity-50">
                        {proxySaving ? (lang === 'zh' ? '保存中...' : 'Saving...') : (lang === 'zh' ? '保存' : 'Save')}
                      </button>
                      <button onClick={() => setProxyEdit(null)} className="px-4 py-2.5 text-body border border-hairline rounded-lg text-sm font-bold hover:text-ink">{lang === 'zh' ? '取消' : 'Cancel'}</button>
                    </div>
                  </div>
                </section>
              )}

              {quotaList && (
                <section className="bg-surface-card border border-hairline rounded-2xl overflow-hidden">
                  <div className="px-6 py-4 border-b border-hairline flex items-center gap-2">
                    <span className="material-symbols-outlined text-[18px] text-body">data_usage</span>
                    <span className="text-sm font-semibold text-ink">{lang === 'zh' ? '账号限额（credits）' : 'Account Quota (credits)'}</span>
                    <button onClick={loadQuota} className="ml-auto text-[12px] text-body hover:text-ink flex items-center gap-1"><span className="material-symbols-outlined text-[14px]">refresh</span>{lang === 'zh' ? '刷新' : 'Refresh'}</button>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-left">
                      <thead className="bg-canvas-soft border-b border-hairline">
                        <tr>{['Account', 'Total', 'Used', 'Remaining', 'Usage %'].map((h, i) => (
                          <th key={i} className="px-6 py-3 text-[10px] font-semibold text-body uppercase tracking-wider">{h}</th>
                        ))}</tr>
                      </thead>
                      <tbody className="divide-y divide-hairline">
                        {quotaList.map((q, i) => {
                          const uq = q.quota?.userQuota || {}
                          return (
                            <tr key={i} className="hover:bg-canvas-soft transition-colors">
                              <td className="px-6 py-4 font-semibold text-ink">{q.name || q.uid.slice(0, 12)}</td>
                              <td className="px-6 py-4 font-mono text-xs text-body">{uq.total ?? '--'}</td>
                              <td className="px-6 py-4 font-mono text-xs text-body">{uq.used ?? '--'}</td>
                              <td className={`px-6 py-4 font-mono text-xs ${uq.percentage > 0.8 ? 'text-red-600 font-bold' : 'text-body'}`}>{uq.remaining ?? '--'}</td>
                              <td className="px-6 py-4">
                                <div className="w-24 h-1.5 bg-hairline-strong rounded-full overflow-hidden">
                                  <div className={`h-full ${(uq.percentage || 0) > 0.8 ? 'bg-red-500' : 'bg-mint'}`} style={{ width: `${Math.min(100, (uq.percentage || 0) * 100)}%` }} />
                                </div>
                              </td>
                            </tr>
                          )
                        })}
                        {quotaList.length === 0 && <tr><td colSpan={5} className="py-6 text-center text-xs text-body">{lang === 'zh' ? '暂无账号' : 'No accounts'}</td></tr>}
                      </tbody>
                    </table>
                  </div>
                </section>
              )}

              <section className="flex items-center gap-6">
                <div className="relative flex-grow max-w-md group">
                  <span className="material-symbols-outlined absolute left-4 top-1/2 -translate-y-1/2 text-body opacity-50 group-focus-within:opacity-100 transition-opacity">search</span>
                  <CustomInput value={searchAccounts} onChange={setSearchAccounts} placeholder={t.accounts.search} className="!pl-12 !py-3 !rounded-xl !bg-white/50" />
                </div>
              </section>

              <section className="glass-card rounded-2xl overflow-hidden shadow-sm">
                <div className="overflow-x-auto">
                  <table className="w-full text-left">
                    <thead className="bg-canvas-soft border-b border-hairline">
                      <tr>{['Account', 'UID', 'Plan / Quota', 'Status', 'Reset', 'Enabled', 'Proxy', 'Actions'].map((h, i) => (
                        <th key={i} className={`px-6 py-4 text-[10px] font-semibold text-body uppercase tracking-wider ${i === 5 ? 'text-center' : ''}`}>{h}</th>
                      ))}</tr>
                    </thead>
                    <tbody className="divide-y divide-hairline">
                      {accountsConfig.accounts.length === 0 ? (
                        <tr><td colSpan={8} className="py-8 text-center text-xs text-body font-medium">{t.accounts.empty}</td></tr>
                      ) : accountsConfig.accounts
                        .filter(acc => !searchAccounts || acc.name.toLowerCase().includes(searchAccounts.toLowerCase()) || acc.uid.includes(searchAccounts))
                        .map((acc) => {
                          const isActive = accountsConfig.active_uid === acc.uid
                          return (
                            <tr key={acc.uid} className={`hover:bg-canvas-soft transition-colors group ${isActive ? 'bg-mint/5' : ''}`}>
                              <td className="px-6 py-5 font-bold text-ink"><div className="flex items-center gap-2">{acc.name}{isActive && <span className="text-[9px] bg-mint/20 text-ink px-1.5 py-0.5 rounded font-extrabold uppercase">Active</span>}</div></td>
                              <td className="px-6 py-5 font-mono text-xs text-body select-all">{acc.uid}</td>
                              <td className="px-6 py-5"><div className="flex flex-col"><span className="text-xs font-semibold text-ink">{acc.user_tag || acc.plan || 'Trial'}</span><span className="text-[10px] text-body font-mono">Quota: {acc.quota}</span></div></td>
                              <td className="px-6 py-5">
                                {acc.is_quota_exceeded ? <span className="px-3 py-1 text-[10px] font-bold rounded-full uppercase tracking-wider bg-red-100 text-red-700">Exceeded</span>
                                : acc.last_status === 'ok' ? <span className="px-3 py-1 text-[10px] font-bold rounded-full uppercase tracking-wider bg-mint/20 text-ink">Enabled</span>
                                : <span className="px-3 py-1 text-[10px] font-bold rounded-full uppercase tracking-wider bg-red-100 text-red-700" title={acc.last_error || ''}>Error</span>}
                              </td>
                              <td className="px-6 py-5 text-xs font-mono text-body">{acc.next_reset_at ? new Date(acc.next_reset_at).toLocaleDateString() : '--'}</td>
                              <td className="px-6 py-5 text-center">
                                <button onClick={() => handleToggleAccount(acc.uid, !acc.enabled)} className={`w-11 h-6 rounded-full p-0.5 transition-colors relative ${acc.enabled ? 'bg-ink' : 'bg-hairline-strong'}`}>
                                  <div className={`w-5 h-5 bg-white rounded-full transition-transform duration-200 ${acc.enabled ? 'translate-x-5' : 'translate-x-0'}`}></div>
                                </button>
                              </td>
                               <td className="px-6 py-5">
                                 {acc.proxy_enabled ? (
                                   <span className="px-2 py-1 text-[10px] font-bold rounded-full bg-mint/20 text-ink font-mono" title={acc.proxy_url || ''}>{acc.proxy_url || (lang === 'zh' ? '已启用' : 'ON')}</span>
                                 ) : (
                                   <span className="text-[10px] text-body font-mono">--</span>
                                 )}
                               </td>
                               <td className="px-6 py-5 text-right">
                                 <div className="flex items-center justify-end gap-4 opacity-0 group-hover:opacity-100 transition-opacity">
                                   <button onClick={() => openProxyEditor(acc)} className="text-body hover:text-ink" title={lang === 'zh' ? '代理设置' : 'Proxy settings'}><span className="material-symbols-outlined">vpn_lock</span></button>
                                   <button onClick={() => handleSelectAccount(acc.uid)} disabled={isActive || !acc.enabled} className="text-body hover:text-ink disabled:opacity-30" title="Activate"><span className="material-symbols-outlined">play_circle</span></button>
                                   <button onClick={() => handleDeleteAccount(acc.uid)} className="text-body hover:text-red-600" title="Delete"><span className="material-symbols-outlined">delete</span></button>
                                 </div>
                               </td>
                            </tr>
                          )
                        })}
                    </tbody>
                  </table>
                </div>
                <div className="px-6 py-5 flex items-center justify-between border-t border-hairline bg-canvas-soft/20">
                  <p className="text-[11px] text-body uppercase tracking-wider">{t.accounts.showing.replace('{count}', String(accountsConfig.accounts.length))}</p>
                </div>
              </section>
            </div>
          )}

          {/* ─── AI PLAYGROUND ─── */}
          {activeTab === 'playground' && (
            <div className="flex gap-8 h-[calc(100vh-14rem)]">
              <section className="w-[320px] flex flex-col gap-6 overflow-y-auto pr-4">
                <div className="space-y-3">
                  <label className="font-bold text-ink">{t.playground.modelConfig}</label>
                  <CustomSelect value={model} onChange={setModel} options={QODER_MODEL_OPTIONS} placeholder="e.g. lite" />
                </div>
                <div className="space-y-3">
                  <CustomCheckbox checked={stream} onChange={setStream} label={t.playground.streamResponse} />
                </div>
                <div className="space-y-3 flex-1 flex flex-col">
                  <label className="font-bold text-ink">{t.playground.systemPrompt}</label>
                  <CustomTextarea value="" onChange={() => {}} placeholder={t.playground.systemPromptPlaceholder} className="flex-1 !min-h-[150px]" />
                </div>
              </section>

              <section className="flex-1 flex flex-col glass-card rounded-2xl overflow-hidden shadow-sm relative">
                <div className="flex-1 overflow-y-auto p-8 space-y-8">
                  {chatMessages.map((msg, idx) => (
                    <div key={idx} className={`flex gap-4 ${msg.role === 'user' ? 'max-w-[80%] ml-auto flex-row-reverse' : ''}`}>
                      <div className={`w-8 h-8 rounded flex-shrink-0 flex items-center justify-center text-[10px] font-bold ${msg.role === 'user' ? 'bg-ink text-white' : 'bg-mint text-ink'}`}>
                        {msg.role === 'user' ? 'U' : <span className="material-symbols-outlined text-sm" style={{ fontVariationSettings: "'FILL' 1" }}>bolt</span>}
                      </div>
                      <div className={`flex-1 ${msg.role === 'user' ? '' : 'space-y-4'}`}>
                        {msg.role === 'user' ? (
                          <div className="bg-canvas-soft border border-hairline p-4 rounded-xl rounded-tl-none"><p className="text-ink whitespace-pre-wrap">{msg.content}</p></div>
                        ) : msg.content === '' ? (
                          <div className="flex items-center gap-2 text-body py-1 text-xs font-semibold animate-pulse">
                            <svg className="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                            {t.playground.waiting}
                          </div>
                        ) : renderMessageContent(msg.content)}
                      </div>
                    </div>
                  ))}
                  <div ref={chatEndRef} />
                </div>
                <form onSubmit={handleSendChat} className="p-8 border-t border-hairline bg-white/50">
                  <div className="flex items-center gap-3">
                    <CustomTextarea value={chatInput} onChange={setChatInput} placeholder={t.playground.ask} className="flex-1" />
                    <button type="submit" disabled={generating || !chatInput.trim()} className="h-11 px-4 bg-ink text-white rounded-xl flex items-center gap-2 hover:bg-neutral-800 transition-all active:scale-95 shadow-md disabled:opacity-50 shrink-0">
                      <span className="font-bold text-sm">{t.playground.send}</span><span className="material-symbols-outlined text-sm">send</span>
                    </button>
                  </div>
                </form>
              </section>
            </div>
          )}

          {/* ─── API KEYS ─── */}
          {activeTab === 'api-keys' && (
            <div className="space-y-8">
              <div className="flex justify-between items-end">
                <p className="text-body font-medium max-w-xl">{t.api.desc}</p>
                <button onClick={handleGenerateKey} className="bg-ink text-white px-6 py-3 rounded-xl flex items-center gap-2 hover:bg-neutral-800 transition-all font-bold shadow-md">
                  <span className="material-symbols-outlined text-[20px]">add</span>{t.api.generate}
                </button>
              </div>

              <div className="space-y-6">
                <div className="grid grid-cols-12 gap-6">
                  <div className="col-span-12 lg:col-span-6 glass-card p-8 rounded-2xl flex flex-col justify-between min-h-[220px]">
                    <div><h3 className="font-bold text-ink text-lg mb-2">{t.api.gatewayAuth}</h3><p className="text-body text-sm">{t.api.gatewayAuthDesc}</p></div>
                    <div className="flex items-center justify-between pt-6 border-t border-hairline mt-auto">
                      <span className="text-[10px] font-bold text-body uppercase tracking-widest">{t.api.systemStatus}</span>
                      <button className={`w-11 h-6 rounded-full p-0.5 transition-colors relative ${apiConfig.auth_required ? 'bg-ink' : 'bg-hairline-strong'}`} onClick={handleToggleAuth}>
                        <div className={`w-5 h-5 bg-white rounded-full transition-transform duration-200 ${apiConfig.auth_required ? 'translate-x-5' : 'translate-x-0'}`}></div>
                      </button>
                    </div>
                  </div>
                  <div className="col-span-6 lg:col-span-3 glass-card p-4 rounded-xl">
                    <span className="text-[10px] font-bold text-body uppercase tracking-widest">{t.api.activeKeys}</span>
                    <div className="mt-2 flex items-baseline gap-2"><span className="font-display-sm text-ink">{apiKeys.filter(k => k.enabled).length}</span><span className="text-[10px] text-body font-bold">/ {apiKeys.length} {t.api.configured}</span></div>
                  </div>
                  <div className="col-span-6 lg:col-span-3 glass-card p-4 rounded-xl">
                    <span className="text-[10px] font-bold text-body uppercase tracking-widest">{t.api.colUsage}</span>
                    <div className="mt-2 flex items-baseline gap-2"><span className="font-display-sm text-ink">{apiKeys.reduce((s, k) => s + (k.inflight || 0), 0)}</span><span className="text-[10px] text-body font-bold">{t.api.labelConc}</span></div>
                  </div>
                </div>
                <div className="glass-card rounded-2xl overflow-hidden flex flex-col shadow-sm">
                  <div className="p-6 border-b border-hairline space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="font-bold">{t.api.activeAccessKeys}</span>
                      <button onClick={fetchApiKeys} className="text-[10px] font-bold text-body uppercase tracking-widest hover:text-ink">{t.api.refresh}</button>
                    </div>
                    <div className="grid grid-cols-12 gap-2">
                      <CustomInput value={keyName} onChange={setKeyName} placeholder={t.api.namePlaceholder} className="col-span-12 md:col-span-4 !py-2 !bg-canvas-soft !border-hairline" />
                      <CustomInput value={newKey} onChange={setNewKey} placeholder={t.api.keyPlaceholder} className="col-span-12 md:col-span-8 !py-2 !bg-canvas-soft !border-hairline" mono />
                      <select value={keyStrategy} onChange={e => setKeyStrategy(Number(e.target.value))} className="col-span-12 md:col-span-4 rounded-lg border border-hairline bg-canvas-soft px-3 py-2 text-xs font-medium text-ink cursor-pointer">
                        <option value={1}>{t.api.strategyFill}</option>
                        <option value={2}>{t.api.strategyRoundRobin}</option>
                      </select>
                      <CustomInput value={keyRpm} onChange={setKeyRpm} placeholder={t.api.rpmPlaceholder} className="col-span-6 md:col-span-2 !py-2 !bg-canvas-soft !border-hairline" mono />
                      <CustomInput value={keyConc} onChange={setKeyConc} placeholder={t.api.concPlaceholder} className="col-span-6 md:col-span-2 !py-2 !bg-canvas-soft !border-hairline" mono />
                      <div className="col-span-12 md:col-span-4 flex gap-2">
                        <button onClick={handleGenerateKey} className="flex-1 border border-hairline rounded-lg px-3 py-2 text-xs font-bold text-body hover:text-ink transition-all whitespace-nowrap">{t.api.generateShort}</button>
                        <button onClick={handleAddKey} disabled={!newKey.trim() || savingKey} className="flex-1 bg-ink text-white px-4 py-2 rounded-lg font-bold text-sm hover:bg-neutral-800 transition-all disabled:opacity-50">{t.common.add}</button>
                      </div>
                    </div>
                    <p className="text-[10px] text-body font-medium leading-relaxed">{t.api.limitHint}</p>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[700px] text-left">
                      <thead className="bg-canvas-soft/50 border-b border-hairline"><tr>{[t.api.colName, t.api.colKey, t.api.colStrategy, t.api.colUsage, t.api.colStatus, t.api.colActions].map(h => (<th key={h} className="px-4 py-4 text-[10px] font-semibold text-body uppercase tracking-widest whitespace-nowrap">{h}</th>))}</tr></thead>
                      <tbody className="divide-y divide-hairline">
                        {apiKeys.length === 0 ? (
                          <tr><td colSpan={6} className="py-6 text-center text-xs text-body font-medium">{t.api.noKeys}</td></tr>
                        ) : apiKeys.map((entry) => (
                          <tr key={entry.api_key} className={`hover:bg-canvas-soft/30 transition-colors ${entry.enabled ? '' : 'opacity-45'}`}>
                            <td className="px-4 py-4 text-xs font-bold text-ink whitespace-nowrap">{entry.name || <span className="text-body font-normal">—</span>}</td>
                            <td className="px-4 py-4 font-mono text-[11px] tracking-wider text-body opacity-80 select-all whitespace-nowrap" title={entry.api_key}>{maskKey(entry.api_key)}</td>
                            <td className="px-4 py-4">
                              <select value={entry.strategy} onChange={e => { void handleSaveKey({ api_key: entry.api_key, strategy: Number(e.target.value) }) }} className="rounded-lg border border-hairline bg-transparent px-2 py-1 text-[11px] font-bold text-ink cursor-pointer">
                                <option value={1}>{t.api.strategyFillShort}</option>
                                <option value={2}>{t.api.strategyRoundRobinShort}</option>
                              </select>
                            </td>
                            <td className="px-4 py-4">
                              <div className="flex flex-col gap-1 text-[10px] font-mono text-body whitespace-nowrap">
                                <div className="flex items-center gap-1.5">
                                  <span className="w-9 opacity-70">{t.api.labelRpm}</span>
                                  <input type="number" min={0} defaultValue={entry.rpm_limit} onBlur={e => { const v = Math.max(0, Number(e.target.value) || 0); if (v !== entry.rpm_limit) void handleSaveKey({ api_key: entry.api_key, rpm_limit: v }) }} className="w-14 rounded border border-hairline bg-canvas-soft px-1 py-0.5 text-[10px] text-ink" />
                                  <span className="opacity-60">{entry.rpm_used ?? 0} / {entry.rpm_limit || t.api.unlimited}</span>
                                </div>
                                <div className="flex items-center gap-1.5">
                                  <span className="w-9 opacity-70">{t.api.labelConc}</span>
                                  <input type="number" min={0} defaultValue={entry.concurrency_limit} onBlur={e => { const v = Math.max(0, Number(e.target.value) || 0); if (v !== entry.concurrency_limit) void handleSaveKey({ api_key: entry.api_key, concurrency_limit: v }) }} className="w-14 rounded border border-hairline bg-canvas-soft px-1 py-0.5 text-[10px] text-ink" />
                                  <span className="opacity-60">{entry.inflight ?? 0} / {entry.concurrency_limit || t.api.unlimited}</span>
                                </div>
                              </div>
                            </td>
                            <td className="px-4 py-4">
                              <button onClick={() => handleToggleKeyEnabled(entry)} className={`w-9 h-5 rounded-full p-0.5 transition-colors relative ${entry.enabled ? 'bg-ink' : 'bg-hairline-strong'}`}>
                                <div className={`w-4 h-4 bg-white rounded-full transition-transform duration-200 ${entry.enabled ? 'translate-x-4' : 'translate-x-0'}`}></div>
                              </button>
                            </td>
                            <td className="px-4 py-4 text-right">
                              <div className="flex justify-end gap-2">
                                <button onClick={() => handleCopyKey(entry.api_key)} className="p-1.5 text-body hover:text-ink" title="Copy"><span className="material-symbols-outlined text-[18px]">{copiedKey === entry.api_key ? 'check_circle' : 'content_copy'}</span></button>
                                <button onClick={() => handleDeleteKey(entry.api_key)} className="p-1.5 text-red-400 hover:text-red-600" title="Delete"><span className="material-symbols-outlined text-[18px]">block</span></button>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>

              <section className="bg-ink text-white p-8 rounded-2xl flex items-center justify-between relative overflow-hidden shadow-xl">
                <div className="relative z-10 max-w-xl">
                  <h2 className="font-display-sm mb-4">{t.api.bestPractices}</h2>
                  <p className="text-white/70 font-medium leading-relaxed text-sm">{t.api.bestPracticesDesc}</p>
                  <button className="mt-8 border border-white/20 px-6 py-2.5 rounded-xl hover:bg-white/10 transition-all font-bold text-xs uppercase tracking-wider">{t.api.securityPolicy}</button>
                </div>
                <div className="hidden lg:block opacity-20"><span className="material-symbols-outlined" style={{ fontSize: '120px', fontVariationSettings: "'FILL' 1" }}>shield</span></div>
              </section>
            </div>
          )}

          {/* ─── LOGS ─── */}
          {activeTab === 'logs' && (
            <div className="space-y-8">
              <div className="relative z-[4000] grid grid-cols-1 md:grid-cols-4 gap-4 p-6 bg-white/60 backdrop-blur-md border border-hairline rounded-2xl">
                <div className="space-y-2">
                  <label className="text-[11px] font-semibold text-body uppercase opacity-60 tracking-wider">{t.logs.account}</label>
                  <CustomSelect value={logFilterAccount} onChange={setLogFilterAccount} options={accountLogOptions.map((option, index) => index === 0 ? { ...option, label: t.logs.allAccounts } : option)} placeholder={t.logs.allAccounts} />
                </div>
                <div className="space-y-2">
                  <label className="text-[11px] font-semibold text-body uppercase opacity-60 tracking-wider">{t.logs.status}</label>
                  <CustomSelect value={logFilterStatus} onChange={setLogFilterStatus} options={[{ value: 'all', label: t.logs.allStatuses }, { value: 'info', label: 'Info' }, { value: 'error', label: 'Error' }, { value: 'warning', label: 'Warning' }]} placeholder={t.logs.allStatuses} />
                </div>
                <div className="space-y-2">
                  <label className="text-[11px] font-semibold text-body uppercase opacity-60 tracking-wider">{t.logs.range}</label>
                  <CustomSelect value={logFilterRange} onChange={setLogFilterRange} options={[{ value: '24h', label: t.logs.last24h }, { value: '1h', label: t.logs.lastHour }, { value: '7d', label: t.logs.last7d }]} placeholder={t.logs.last24h} />
                </div>
                <div className="flex items-end">
                  <button onClick={() => { fetchLogs(); pushToast('INFO', 'Logs Refreshed', 'Log entries updated') }} className="w-full h-11 bg-ink text-white rounded-xl flex items-center justify-center gap-2 hover:bg-neutral-800 transition-all shadow-sm">
                    <span className="material-symbols-outlined text-sm">filter_list</span><span className="font-bold text-sm">{t.common.refresh}</span>
                  </button>
                </div>
              </div>

              <div className="relative z-0 bg-white/80 backdrop-blur-xl border border-hairline rounded-2xl overflow-hidden">
                <table className="w-full text-left">
                  <thead><tr className="bg-canvas-soft border-b border-hairline">{[t.logs.timestamp, t.logs.level, t.logs.message].map(h => (<th key={h} className="px-6 py-4 text-[10px] font-semibold text-body uppercase tracking-widest">{h}</th>))}</tr></thead>
                  <tbody className="divide-y divide-hairline">
                    {logs.length === 0 ? (
                      <tr><td colSpan={3} className="py-8 text-center text-xs text-body font-medium">{t.logs.noLogs}</td></tr>
                    ) : filteredLogs.length === 0 ? (
                      <tr><td colSpan={3} className="py-8 text-center text-xs text-body font-medium">{t.logs.noMatch}</td></tr>
                    ) : filteredLogs.map((log, i) => {
                      const isError = log.includes('[ERROR]') || log.includes('[WARNING]')
                      return (
                        <tr key={i} className={`hover:bg-black/5 transition-colors ${isError ? 'bg-red-50' : ''}`}>
                          <td className="px-6 py-4 font-mono text-[13px] text-body whitespace-nowrap">{log.substring(0, 10)}</td>
                          <td className="px-6 py-4">
                            <span className={`px-2 py-1 rounded text-[11px] font-bold uppercase ${log.includes('[ERROR]') ? 'bg-red-50 text-red-700' : log.includes('[WARNING]') ? 'bg-peach/20 text-ink' : 'bg-mint/20 text-ink'}`}>
                              {log.match(/\[(INFO|ERROR|WARNING)\]/)?.[1] || 'INFO'}
                            </span>
                          </td>
                          <td className="px-6 py-4 font-mono text-[13px] text-ink opacity-80 break-all">{log.replace(/^\[[\d:]+\]\s*\[\w+\]\s*/, '')}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
                <div ref={logEndRef} />
              </div>
            </div>
          )}

          {/* ─── AUTO REGISTRAR ─── */}
          {activeTab === 'register' && (
            <div className="space-y-6">
              <div className="relative z-[4000] flex flex-col md:flex-row md:items-center justify-between gap-4 p-6 bg-white/60 backdrop-blur-md border border-hairline rounded-2xl">
                <div>
                  <h2 className="text-lg font-semibold text-ink">{t.title.register}</h2>
                  <p className="text-sm text-body mt-1 max-w-2xl">{t.register.desc}</p>
                  <p className="text-xs text-body opacity-70 mt-1">{t.register.staggerHint}</p>
                </div>
                <div className="flex items-center gap-3 flex-wrap">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-ink">{t.register.countLabel}</span>
                    <div className="flex bg-white border border-hairline rounded-xl p-1 gap-1">
                      {[1, 2, 3, 4].map(n => (
                        <button
                          key={n}
                          onClick={() => setRegCount(n)}
                          disabled={regStatus?.running}
                          className={`w-9 h-9 rounded-lg text-sm font-bold transition-all ${regCount === n ? 'bg-ink text-white' : 'text-body hover:bg-black/5'}`}
                        >{n}</button>
                      ))}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-ink">{lang === 'zh' ? '目标成功数' : 'Target'}</span>
                    <input
                      type="number"
                      min={0}
                      value={regTarget}
                      onChange={e => setRegTarget(Math.max(0, parseInt(e.target.value) || 0))}
                      disabled={regStatus?.running}
                      title={lang === 'zh' ? '0 = 不限，达到后当前批次结束自动停' : '0 = unlimited; auto-stops at batch boundary when reached'}
                      className="w-20 h-11 px-3 bg-white border border-hairline rounded-xl text-sm font-bold text-ink outline-none focus:border-ink disabled:opacity-50"
                    />
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-ink">{lang === 'zh' ? '批间隔(s)' : 'Interval(s)'}</span>
                    <input
                      type="number"
                      min={0}
                      max={3600}
                      value={regInterval}
                      onChange={e => setRegInterval(Math.min(3600, Math.max(0, parseInt(e.target.value) || 0)))}
                      disabled={regStatus?.running}
                      title={lang === 'zh' ? '同一母线程两批之间的等待秒数' : 'Seconds between batches of the same parent thread'}
                      className="w-20 h-11 px-3 bg-white border border-hairline rounded-xl text-sm font-bold text-ink outline-none focus:border-ink disabled:opacity-50"
                    />
                  </div>
                  {regStatus?.running ? (
                    <button
                      onClick={stopRegister}
                      disabled={regStopping || regStatus?.stop_requested}
                      className={`h-11 px-6 rounded-xl flex items-center justify-center gap-2 transition-all shadow-sm font-bold text-sm ${regStopping || regStatus?.stop_requested ? 'bg-neutral-300 text-neutral-500 cursor-not-allowed' : 'bg-red-600 text-white hover:bg-red-700'}`}
                    >
                      <span className="material-symbols-outlined text-sm">stop_circle</span>
                      <span>{regStopping ? t.register.stopping : regStatus?.stop_requested ? t.register.stopping : t.register.stop}</span>
                    </button>
                  ) : (
                    <button
                      onClick={startRegister}
                      disabled={regStarting}
                      className={`h-11 px-6 rounded-xl flex items-center justify-center gap-2 transition-all shadow-sm font-bold text-sm ${regStarting ? 'bg-neutral-300 text-neutral-500 cursor-not-allowed' : 'bg-ink text-white hover:bg-neutral-800'}`}
                    >
                      <span className="material-symbols-outlined text-sm">person_add</span>
                      <span>{regStarting ? t.register.starting : t.register.start}</span>
                    </button>
                  )}
                </div>
              </div>

              {regStatus?.verification && regStatus?.running && (
                <div className="p-4 bg-amber-50 border border-amber-200 rounded-2xl text-sm text-amber-800 flex items-center gap-2 animate-pulse">
                  <span className="material-symbols-outlined text-base">touch_app</span>
                  <span>{t.register.verifyHint}（{t.register.task} {regStatus.verification}）</span>
                </div>
              )}

              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <div className="p-6 bg-white/60 backdrop-blur-md border border-hairline rounded-2xl">
                  <label className="text-[11px] font-semibold text-body uppercase opacity-60 tracking-wider">{t.register.statsLabel}</label>
                  <div className="mt-2 text-3xl font-bold text-ink">{regStatus?.stats?.total ?? 0}</div>
                </div>
                <div className="p-6 bg-white/60 backdrop-blur-md border border-hairline rounded-2xl">
                  <label className="text-[11px] font-semibold text-emerald-600 uppercase opacity-80 tracking-wider">{t.register.success}</label>
                  <div className="mt-2 text-3xl font-bold text-emerald-600">{regStatus?.stats?.success ?? 0}</div>
                </div>
                <div className="p-6 bg-white/60 backdrop-blur-md border border-hairline rounded-2xl">
                  <label className="text-[11px] font-semibold text-red-600 uppercase opacity-80 tracking-wider">{t.register.failed}</label>
                  <div className="mt-2 text-3xl font-bold text-red-600">{regStatus?.stats?.failed ?? 0}</div>
                </div>
                <div className="p-6 bg-white/60 backdrop-blur-md border border-hairline rounded-2xl">
                  <label className="text-[11px] font-semibold text-body uppercase opacity-60 tracking-wider">{lang === 'zh' ? '启动时间' : 'Started At'}</label>
                  <div className="mt-2 font-mono text-sm text-ink">{regStatus?.started_at ? new Date(regStatus.started_at * 1000).toLocaleTimeString() : '—'}</div>
                </div>
              </div>

              {(() => {
                const allTasks = { ...(regStatus?.active || {}), ...(regStatus?.recent || {}) }
                const entries = Object.entries(allTasks)
                if (entries.length === 0) {
                  return <div className="p-10 text-center text-sm text-body bg-white/60 backdrop-blur-md border border-hairline rounded-2xl">{t.register.noResult}</div>
                }
                return entries.map(([tid, task]) => {
                  const stageText = (t.register.stage as Record<string, string>)[task.stage] || task.stage
                  const isVerify = regStatus?.verification === tid
                  const isActive = !!regStatus?.active?.[tid]
                  return (
                    <div key={tid} className={`relative z-0 bg-white/80 backdrop-blur-xl border rounded-2xl overflow-hidden ${isVerify ? 'border-amber-400 ring-2 ring-amber-200' : 'border-hairline'}`}>
                      <div className="px-6 py-4 border-b border-hairline flex items-center justify-between flex-wrap gap-2">
                        <div className="flex items-center gap-3">
                          <span className="text-sm font-semibold text-ink">{t.register.task} {tid}</span>
                          <span className={`px-2 py-1 rounded text-[11px] font-bold uppercase ${task.stage === 'success' ? 'bg-emerald-100 text-emerald-700' : task.stage === 'failed' ? 'bg-red-50 text-red-700' : task.stage === 'waiting_slider' ? 'bg-amber-100 text-amber-700' : 'bg-neutral-100 text-neutral-600'}`}>{stageText}</span>
                        </div>
                        <div className="flex items-center gap-2 text-xs text-body font-mono">
                          <span className={`h-2.5 w-2.5 rounded-full inline-block ${isActive ? (task.stage === 'success' ? 'bg-emerald-500' : task.stage === 'failed' ? 'bg-red-500' : 'bg-amber-400 animate-pulse') : 'bg-neutral-300'}`} />
                          <span>{task.started_at ? new Date(task.started_at * 1000).toLocaleTimeString() : ''}</span>
                        </div>
                      </div>
                      <div className="p-6 h-48 overflow-y-auto font-mono text-[13px] leading-relaxed text-ink opacity-80 space-y-1">
                        {task.logs.slice().reverse().map((line, i) => (
                          <div key={i} className={`break-all ${/FAILED|ERROR/i.test(line) ? 'text-red-600' : ''}`}>{line}</div>
                        ))}
                      </div>
                      {task.result && (
                        <div className="px-6 pb-6 pt-4 grid grid-cols-1 md:grid-cols-2 gap-4 text-sm border-t border-hairline">
                          {[
                            { label: lang === 'zh' ? '邮箱' : 'Email', value: task.result.email },
                            { label: lang === 'zh' ? '密码' : 'Password', value: task.result.password },
                            { label: lang === 'zh' ? '姓名' : 'Name', value: task.result.name },
                            { label: 'Token (dt-)', value: task.result.device.token },
                            { label: 'Refresh (drt-)', value: task.result.device.refresh_token },
                            { label: 'UID', value: task.result.device.user_id },
                          ].map((f, i) => (
                            <div key={i}>
                              <div className="text-[11px] font-semibold text-body uppercase opacity-60 tracking-wider">{f.label}</div>
                              <div className="mt-1 font-mono text-ink break-all">{f.value}</div>
                            </div>
                          ))}
                        </div>
                      )}
                      {task.error && (
                        <div className="px-6 pb-6 text-sm text-red-700">{task.error}</div>
                      )}
                    </div>
                  )
                })
              })()}
            </div>
          )}
        </div>
      </main>

      <ToastContainer toasts={toasts} dismiss={dismissToast} />
    </div>
  )
}
