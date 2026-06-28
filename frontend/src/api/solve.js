// 调用后端 POST /solve。开发期经 Vite 代理到 http://127.0.0.1:8000（见 vite.config.js）。
export async function solve(payload) {
  const res = await fetch('/api/solve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`求解失败 (${res.status}): ${text}`)
  }
  return res.json()
}
