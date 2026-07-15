import { defineConfig, devices } from '@playwright/test'

// 端到端回归：真实浏览器 + 真实 uvicorn 后端 + Vite 开发服务器（含 /api → 8000 代理）。
// 后端只有单元测试和基准兜底，前端此前只有「构建通过」——3D 渲染、顺序回放、2D 俯视、
// CSV 导出、诊断分层都没有任何自动化验证。这套用例补的就是这个缺口。
//
// 后端解释器：必须和跑单元测试的那个环境一致，否则 e2e 会在一个没人维护的环境上跑。
// PATH 上的 `python` 未必就是项目环境（本机 PATH 上是独立的 D:\Python313，而项目用的是
// conda 的 packaging 环境），所以用 PACKAGING_PYTHON 显式指定。见 CLAUDE.md 的运行命令。
const PYTHON = process.env.PACKAGING_PYTHON || 'python'

// 本机把 HTTP_PROXY 指向本地代理软件（如 Bright Data / Clash，端口 24000）。Playwright 用 Node
// 侧的请求做两件事：webServer 启动前探测 URL 是否「已占用」、启动后轮询 URL 是否「就绪」。这两个
// 请求都会走代理，而代理对 127.0.0.1:8000/5173 一律回错误响应（403 之类）——于是探测阶段把这个
// 响应当成「端口已被占用」直接报错，就绪阶段又永远等不到 2xx 而 60s 超时。e2e 全是本地回环，
// 根本不需要代理，直接在本进程内清掉，子进程（uvicorn / vite）也一并干净。
for (const key of ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy']) {
  delete process.env[key]
}
process.env.NO_PROXY = '*'
process.env.no_proxy = '*'

export default defineConfig({
  testDir: './e2e',
  // 求解 1140 件要几秒，默认 30s 断言超时不够。
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: 'http://127.0.0.1:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        // 3D 场景要真实 WebGL；无头 Chromium 默认用 SwiftShader 软件渲染，够用。
        launchOptions: { args: ['--enable-unsafe-swiftshader'] },
      },
    },
  ],
  // reuseExistingServer 一律关掉：开着的话 Playwright 会把后端/前端进程留在后台供下次复用，
  // 结果是测试跑完 8000 端口还被占着，之后手动起后端会撞 WinError 10013（Windows 对这种
  // 部分重叠的绑定冲突报的是权限错误，不是「地址已占用」，排查起来很误导）。
  // 代价是每次 e2e 都重启一次服务，多几秒；换来的是跑完不留残留进程。
  webServer: [
    {
      command: `${PYTHON} -m uvicorn app.main:app --port 8000`,
      cwd: '../backend',
      url: 'http://127.0.0.1:8000/health',
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      // 必须显式 --host 127.0.0.1：vite 默认绑 `localhost`，而 Node 17+ 把 localhost 解析到 IPv6
      // 的 ::1，vite 就只在 ::1 监听。可后端 uvicorn 和这里的 url 都是 IPv4 的 127.0.0.1，
      // Playwright 探 127.0.0.1:5173 探不到 → 就绪超时。把 vite 也钉到 127.0.0.1，全栈统一到 IPv4。
      command: 'npm run dev -- --host 127.0.0.1',
      url: 'http://127.0.0.1:5173',
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
})
