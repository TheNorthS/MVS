import { test, expect } from "@playwright/test";
import fs from "node:fs";
test("治理页加载审批、历史、OAuth和模型路由", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("管理员令牌").fill(token);
  await page.getByRole("button", { name: "进入控制台" }).click();
  await page.getByRole("button", { name: "治理与运维", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "治理与运维", exact: true, level: 1 }),
  ).toBeVisible();
  for (const name of [
    "配置回滚",
    "角色规则",
    "MCP安装",
    "OAuth",
    "多模型路由",
  ]) {
    await page.getByRole("button", { name, exact: true }).click();
    await expect(page.getByRole("alert")).toHaveCount(0);
  }
  await page.screenshot({
    path: "../docs/assets/console/console-governance.png",
    fullPage: true,
  });
});
const token = fs
  .readFileSync(
    process.env.MVS_UI_TEST_HOME
      ? `${process.env.MVS_UI_TEST_HOME}/admin-token`
      : "../.tools/console-ui/admin-token",
    "utf8",
  )
  .trim();
test("真实后台：登录、服务发现、工具调用、授权和自适应布局", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.getByLabel("管理员令牌").fill(token);
  await page.getByRole("button", { name: "进入控制台" }).click();
  await expect(
    page.getByRole("heading", { name: "所有工具，一处掌控。" }),
  ).toBeVisible();
  await page.screenshot({
    path: "../docs/assets/console/console-overview.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "服务与工具", exact: true }).click();
  await page.getByRole("button", { name: "连接与工具" }).first().click();
  await expect(
    page.getByRole("heading", { name: "demo · 工具发现" }),
  ).toBeVisible();
  await expect(page.getByLabel("授权 add")).toBeChecked();
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "添加服务", exact: true }).click();
  await page.getByLabel("服务 ID").fill("extra");
  await page.getByLabel("启动程序").fill("python");
  await page
    .getByLabel("启动参数 · 每行一个")
    .fill("-m\nmvs.infrastructure.mcp.demo_server");
  await page.getByLabel("允许调用的工具 · 逗号分隔").fill("add");
  await page.getByRole("button", { name: "保存并应用" }).click();
  await expect(
    page.getByRole("heading", { name: "extra", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "调用工作台", exact: true }).click();
  await page
    .getByLabel("虚拟命令", { exact: true })
    .fill("/mcp/extra/tools/add --a 2 --b 3");
  await page.getByRole("button", { name: "执行命令", exact: true }).click();
  await expect(page.locator("pre.result")).toContainText('"result": 5');
  await page.getByRole("button", { name: "用户与授权", exact: true }).click();
  await page.getByRole("button", { name: "添加用户" }).click();
  await page.getByLabel("用户ID", { exact: true }).fill("testuser");
  await page.getByLabel("显示名称").fill("测试用户");
  await page.getByLabel("extra", { exact: true }).check();
  await page.getByRole("button", { name: "保存用户" }).click();
  await expect(
    page.getByRole("heading", { name: "请保存新的访问令牌" }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByText("测试用户", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "调用记录", exact: true }).click();
  await expect(page.getByText("配置已应用").first()).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "概览", exact: true }).click();
  await page.screenshot({
    path: "../docs/assets/console/console-mobile.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  expect(errors).toEqual([]);
});

test("原生命令表单与管理员令牌轮换", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("管理员令牌").fill(token);
  await page.getByRole("button", { name: "进入控制台" }).click();
  await page.getByRole("button", { name: "服务与工具", exact: true }).click();
  await page.getByRole("button", { name: "添加服务", exact: true }).click();
  await page.getByRole("button", { name: "原生命令", exact: true }).click();
  await page.getByLabel("服务 ID").fill("nativehost");
  await page.getByLabel("允许调用的工具 · 逗号分隔").fill("hostname");
  await page.getByRole("button", { name: "保存并应用" }).click();
  await expect(
    page.getByRole("heading", { name: "nativehost", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "调用工作台", exact: true }).click();
  await page
    .getByLabel("虚拟命令", { exact: true })
    .fill("/os/nativehost/tools/hostname");
  await page.getByRole("button", { name: "执行命令", exact: true }).click();
  await expect(page.locator("pre.result").first()).toContainText(
    '"exit_code": 0',
  );
  await page.getByRole("button", { name: "用户与授权", exact: true }).click();
  await page
    .getByRole("row")
    .filter({ hasText: "管理员" })
    .filter({ hasText: "admin" })
    .first()
    .getByRole("button", { name: "轮换令牌" })
    .click();
  await page.getByRole("button", { name: "确认执行" }).click();
  await expect(
    page.getByRole("heading", { name: "请保存新的访问令牌" }),
  ).toBeVisible();
  const newToken = (
    await page.getByRole("dialog").locator("pre").innerText()
  ).trim();
  expect(newToken).not.toEqual(token);
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await page.screenshot({
    path: "../docs/assets/console/console-users.png",
    fullPage: true,
  });
});
