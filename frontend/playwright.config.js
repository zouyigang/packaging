import { defineConfig, devices } from '@playwright/test'

// 端到端回归：真实浏览器 + 真实 uvicorn 后端 + Vite 开发服务器（含 /api → 8000 代理）。
// 后端只有单元测试和基准兜底，前端此前只有「构建通过」——3D 渲染、顺序回放、2D 俯视、
// CSV 导出、诊断分层都没有任何自动化验证。这套用例补的就是这个缺口。
//
// 后端解释器可用 PACKAGING_PYTHON 覆盖（如 conda 环境的 python.exe）。
const PYTHON = process.env.PACKAGING_PYTHON || 'python'

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
  webServer: [
    {
      command: `${PYTHON} -m uvicorn app.main:app --port 8000`,
      cwd: '../backend',
      url: 'http://127.0.0.1:8000/health',
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: 'npm run dev',
      url: 'http://127.0.0.1:5173',
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
})
