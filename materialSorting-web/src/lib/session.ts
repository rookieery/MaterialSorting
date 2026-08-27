// session.ts —— 浏览器会话标识 get-or-create（US-005 多会话前端接入）。
//
// 约定：
//   - localStorage 键 ``ms_sid`` 持有 uuid4 hex（32 个小写 hex 字符，与后端
//     sessions.SID_RE「字母数字 1-128」字符集兼容且形状固定可校验）；
//   - 刷新页面 / 重开 Tab 不变（localStorage 同源持久）；换浏览器 / 隐身窗口
//     = 新 sid = 新会话（多设备模拟的天然边界）；
//   - 存量值损坏（非 32-hex）→ 静默重生成（防御性，正常不会发生）；
//   - localStorage 不可用（隐私模式极端等）→ 内存 sid 降级（刷新即换，仅影响
//     会话粘性不影响功能）。
//
// 消费方：lib/api.ts（X-Session-Id Header 注入）、lib/ws.ts（?sid= query）、
// App 挂载探测（probeSession）。模块级缓存避免每次请求都读 localStorage。

/** localStorage 键名（PRD US-005 指定）。 */
const SID_KEY = 'ms_sid';

/** 合法形状：32 位小写 hex（uuid4 去连字符）。 */
const SID_RE = /^[0-9a-f]{32}$/;

/** 模块级缓存（get-or-create 后进程内恒定；刷新页面经 localStorage 恢复同值）。 */
let cached: string | null = null;

/**
 * uuid4 hex（32 字符，无连字符）：crypto.getRandomValues 优先（浏览器 / Node
 * webcrypto 都有），缺失时 Math.random 兜底（sid 仅是会话标签，非密钥）。
 * 按 RFC 4122 定 version=4 / variant=10 位（与 crypto.randomUUID() 去连字符同形）。
 */
function uuid4Hex(): string {
  const bytes = new Uint8Array(16);
  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
    crypto.getRandomValues(bytes);
  } else {
    for (let i = 0; i < 16; i++) bytes[i] = Math.floor(Math.random() * 256);
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // variant 10xx
  let out = '';
  for (const b of bytes) out += b.toString(16).padStart(2, '0');
  return out;
}

/**
 * 会话标识 get-or-create：localStorage 有合法值 → 返回；否则生成 + 落盘。
 * 返回值形状恒为 32 位小写 hex（后端 SID_RE 兼容）。
 */
export function getSessionId(): string {
  if (cached && SID_RE.test(cached)) return cached;
  let sid: string | null = null;
  try {
    sid = localStorage.getItem(SID_KEY);
  } catch {
    sid = null; // localStorage 不可用 —— 走内存降级
  }
  if (!sid || !SID_RE.test(sid)) {
    sid = uuid4Hex();
    try {
      localStorage.setItem(SID_KEY, sid);
    } catch {
      // 落盘失败（隐私模式等）—— 内存 sid 照常工作，仅刷新后换新
    }
  }
  cached = sid;
  return sid;
}

/**
 * 丢弃当前 sid（US-005）：仅在后端宣判 ``session_expired`` 时调用 —— 后端墓碑
 * （US-001）保证过期 sid 1h 内不可重建，若刷新后仍带旧 sid，探测将持续 401 弹窗
 * 死循环；清掉 ms_sid 后刷新即铸造全新 sid 获得干净会话（「刷新重来」唯一通路）。
 * ``session_limit`` **不**清（sid 仍有效，稍后重试原会话可续）。
 */
export function clearPersistedSessionId(): void {
  cached = null;
  try {
    localStorage.removeItem(SID_KEY);
  } catch {
    // localStorage 不可用 —— 内存缓存已清，下一次 getSessionId 自然换新
  }
}

/** 测试隔离：仅清模块级缓存（不动 localStorage —— 「预置值 + 重载」场景可先写库
 *  再调本函数模拟页面刷新；测试通用清理直接 localStorage.clear()）。 */
export function resetSessionIdForTest(): void {
  cached = null;
}
