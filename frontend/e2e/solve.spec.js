import { expect, test } from '@playwright/test'

// 真实浏览器 + 真实后端的端到端回归。此前前端唯一的验证是「构建通过」——
// 3D 渲染、2D 俯视、顺序回放、筛选、CSV 导出、诊断分层全都没有自动化守护。

/** 点「求解装箱」并等到结果面板出数。 */
async function solve(page) {
  await page.getByRole('button', { name: /求解装箱/ }).click()
  await expect(page.locator('.metric-strip')).toBeVisible({ timeout: 60_000 })
  await expect(page.locator('.playback-count')).toBeVisible()
}

/** 当前容器的放置件数（回放栏的「游标 / 总数」里的总数）。 */
async function placementTotal(page) {
  const text = await page.locator('.playback-count').innerText()
  return Number(text.split('/')[1].trim())
}

/** AntD Segmented 的 radio input 是视觉隐藏的（opacity:0），点不动，只能点它的 label。 */
async function switchTo2D(page) {
  await page.locator('.app-topbar .ant-segmented-item', { hasText: '2D 俯视' }).click()
  await expect(page.getByTestId('topview')).toBeVisible()
}

const resetButton = (page) => page.locator('.playback-row button').first()
const playButton = (page) => page.getByRole('button', { name: /回放|暂停/ })

test.beforeEach(async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '3D 装箱' })).toBeVisible()
})

test('求解后 3D 场景渲染出画面，指标条给出方案数据', async ({ page }) => {
  await expect(page.getByText('点击求解装箱后查看方案')).toBeVisible()

  await solve(page)

  // WebGL canvas 真的挂上且有尺寸（无头下走 SwiftShader 软件渲染，也算渲染）。
  const canvas = page.locator('.app-viewport canvas')
  await expect(canvas).toBeVisible()
  const box = await canvas.boundingBox()
  expect(box.width).toBeGreaterThan(100)
  expect(box.height).toBeGreaterThan(100)

  expect(await placementTotal(page)).toBeGreaterThan(0)
  await expect(page.locator('.metric-strip')).toContainText('体积利用率')
})

test('2D 俯视画出全部货品，且与当前容器件数一致', async ({ page }) => {
  await solve(page)
  const total = await placementTotal(page)
  expect(total).toBeGreaterThan(0)

  await switchTo2D(page)

  await expect(page.getByTestId('topview')).toBeVisible()
  await expect(page.getByTestId('topview-box')).toHaveCount(total)
})

test('顺序回放：重置清空、播放逐件加回', async ({ page }) => {
  await solve(page)
  const total = await placementTotal(page)
  await switchTo2D(page)
  await expect(page.getByTestId('topview-box')).toHaveCount(total)

  await resetButton(page).click()
  await expect(page.locator('.playback-count')).toHaveText(`0 / ${total}`)
  await expect(page.getByTestId('topview-box')).toHaveCount(0)

  // 播放：画面必须真的逐件长回来，而不是一步到位。
  await playButton(page).click()
  await expect(page.getByTestId('topview-box')).not.toHaveCount(0)
  await expect(page.getByTestId('topview-box')).toHaveCount(total, { timeout: 60_000 })
})

test('导出 CSV：文件名、表头与行数与方案一致', async ({ page }) => {
  await solve(page)

  // 逐个容器累加放置数，作为 CSV 行数的期望值。
  const segments = page.locator('.metric-strip .ant-segmented-item')
  const containerCount = await segments.count()
  let totalPlacements = 0
  for (let i = 0; i < containerCount; i += 1) {
    await segments.nth(i).click()
    totalPlacements += await placementTotal(page)
  }
  expect(totalPlacements).toBeGreaterThan(0)

  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: '导出 CSV' }).click(),
  ])

  expect(download.suggestedFilename()).toMatch(/^packing-report-\d+\.csv$/)
  const stream = await download.createReadStream()
  const chunks = []
  for await (const chunk of stream) chunks.push(chunk)
  const csv = Buffer.concat(chunks).toString('utf8')

  // 结构：方案摘要 → 空行 → 「装载明细」→ 表头 → 一行一个放置 →（可选）余货段。
  const lines = csv.split(/\r?\n/)
  const detailIndex = lines.findIndex((line) => line.startsWith('装载明细'))
  expect(detailIndex).toBeGreaterThan(0)                    // 摘要段在前
  expect(lines[detailIndex + 1]).toContain('装箱顺序seq')    // 表头

  const body = lines.slice(detailIndex + 2)
  const endIndex = body.findIndex((line) => line.trim() === '' || line.startsWith('余货'))
  const placementRows = (endIndex === -1 ? body : body.slice(0, endIndex)).filter(Boolean)
  expect(placementRows.length).toBe(totalPlacements)        // 一行一个放置
})

test('筛选货品后，2D 俯视只画出被选中的那种货', async ({ page }) => {
  await solve(page)
  await switchTo2D(page)
  const total = await page.getByTestId('topview-box').count()
  expect(total).toBeGreaterThan(0)

  const itemFilter = page.locator('.view-filter-control', { hasText: '货品筛选' }).locator('.ant-select')
  await itemFilter.click()
  // 下拉第一项是「全部货品」，取第二项＝某个具体货品。
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option').nth(1).click()

  const filtered = page.getByTestId('topview-box')
  await expect(filtered).not.toHaveCount(total)   // 确实筛掉了一部分
  expect(await filtered.count()).toBeGreaterThan(0)
})

test('工业校验：诊断按错误/风险/提示分层展示，每条都能定位', async ({ page }) => {
  await page.locator('.solve-actions .ant-select').first().click()
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option', { hasText: '工业校验' }).click()

  await solve(page)

  const panel = page.locator('.diagnostics-panel')
  await expect(panel).toBeVisible()
  await expect(panel.locator('.diagnostics-summary')).not.toBeEmpty()

  // 至少分出一层，且每层都带「该拿它怎么办」的说明。
  const layers = panel.locator('.diagnostics-layer')
  expect(await layers.count()).toBeGreaterThan(0)
  await expect(layers.first().locator('.diagnostics-layer-hint')).not.toBeEmpty()

  // 与设备/货品/站点相关的诊断必须给出定位，否则用户不知道去改哪儿。
  // （策略别名弃用这类全局提示没有定位对象，不强求。）
  const located = panel.locator('.diagnostics-item .diagnostics-location')
  expect(await located.count()).toBeGreaterThan(0)

  const locations = await located.allInnerTexts()
  expect(locations.every((text) => /容器 #|设备 |货品 |站点 /.test(text))).toBe(true)
})
