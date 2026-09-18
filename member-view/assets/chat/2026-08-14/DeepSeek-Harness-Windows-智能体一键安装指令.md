# DeepSeek Harness｜Windows 智能体一键安装指令

> 把本文件完整交给 Codex、WorkBuddy、Coze Bot 或其他智能体，然后发送：`严格按照文件帮我在 Windows 上安装 DeepSeek Harness。`

## 给执行智能体的任务

在用户的 Windows 电脑上尝试安装并启动 DeepSeek Harness，完成基础配置引导和结果验收。

从本段开始，所有指令均写给执行智能体。

## 重要说明

DeepSeek Harness 官方当前提供的是 Node.js/npm 启动方式，但没有在公开安装说明中明确列出 Windows 支持状态。

因此，本文件要求在 Windows 真机上逐项验证。只有安装、版本检查、本地网页和真实任务全部通过，才能汇报“安装成功”。如果出现平台不兼容，必须如实报告具体错误，不得伪造成功，也不得用危险方法强行绕过。

## 强制规则

1. 所有命令默认在 Windows PowerShell 中执行，不使用 macOS、Linux、WSL 或 Git Bash 命令代替。
2. 先判断你是否拥有这台 Windows 电脑的本地 PowerShell 和浏览器操作权限。
3. 有本地权限：直接执行命令，并逐步读取结果。
4. 没有本地权限：不要声称“已安装”；把命令一次只发一组，等待用户返回真实输出后再继续。
5. 禁止索取、读取、复制、记录或回显用户的 DeepSeek API Key。
6. API Key 必须由用户本人在 DeepSeek Harness 本地设置页中填写。
7. 不要为了安装而关闭杀毒软件、防火墙或 Windows 安全中心。
8. 不要全局降低 PowerShell 执行策略。遇到 `.ps1` 被限制时，优先使用对应的 `.cmd` 命令。
9. 禁止操作用户桌面、文档库、代码库或其他无关目录。
10. 第一次运行必须使用独立空工作区。
11. 每一步都要验收。命令没有报错，不等于安装成功。
12. 遇到需要用户登录、输入密钥、确认系统安装或授权的步骤时暂停，告诉用户在哪里操作，并等待用户回复“填好了”或“完成了”。

## 第 1 步：确认 Windows 和 PowerShell

执行：

```powershell
$env:OS
$PSVersionTable.PSVersion.ToString()
$env:PROCESSOR_ARCHITECTURE
```

验收标准：

- `$env:OS` 返回 `Windows_NT`。
- PowerShell 能正常返回版本号。
- 记录架构，例如 `AMD64`、`ARM64` 或 `x86`。

如果不是 Windows，停止执行并说明：本文件只负责 Windows 安装。

如果当前终端不是 PowerShell，请先打开 PowerShell，再继续执行。

## 第 2 步：检查 Node.js 和 npm

执行：

```powershell
Get-Command node -ErrorAction SilentlyContinue
node --version
Get-Command npm.cmd -ErrorAction SilentlyContinue
npm.cmd --version
```

判断：

- 四条检查都有正常结果：继续下一步。
- `node` 或 `npm.cmd` 不存在：安装 Node.js LTS。

优先检查 Windows Package Manager：

```powershell
Get-Command winget -ErrorAction SilentlyContinue
```

如果存在 `winget`，执行：

```powershell
winget install --id OpenJS.NodeJS.LTS --exact --source winget
```

系统弹出安装或权限确认时，让用户本人确认。安装完成后关闭当前 PowerShell，重新打开一个 PowerShell 窗口，再执行：

```powershell
node --version
npm.cmd --version
```

如果没有 `winget`，打开 Node.js 官方页面，让用户下载安装 LTS 版本：

```powershell
Start-Process "https://nodejs.org/"
```

安装完成并重新打开 PowerShell 后，必须重新检查 Node.js 和 npm 的真实版本。

## 第 3 步：安装 DeepSeek Harness

执行：

```powershell
npm.cmd install -g @deepseek-ai/dsh
```

安装结束后立即验收：

```powershell
Get-Command dsh.cmd -ErrorAction SilentlyContinue
dsh.cmd --version
```

验收标准：

- `Get-Command dsh.cmd` 返回真实命令路径。
- `dsh.cmd --version` 返回版本号。

如果安装完成但找不到 `dsh.cmd`，执行：

```powershell
$NpmPrefix = (npm.cmd config get prefix).Trim()
$NpmPrefix
Test-Path (Join-Path $NpmPrefix "dsh.cmd")
$env:Path -split ";"
```

如果 `dsh.cmd` 确实位于 `$NpmPrefix`，但 `$NpmPrefix` 不在用户 `PATH` 中，执行以下用户级修复。禁止修改系统级 `PATH`：

```powershell
$NpmPrefix = (npm.cmd config get prefix).Trim()
$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
$UserPathParts = @($UserPath -split ";" | Where-Object { $_ })
if ($UserPathParts -notcontains $NpmPrefix) {
    $NewUserPath = (($UserPathParts + $NpmPrefix) | Select-Object -Unique) -join ";"
    [Environment]::SetEnvironmentVariable("Path", $NewUserPath, "User")
}
$env:Path = "$NpmPrefix;$env:Path"
Get-Command dsh.cmd -ErrorAction SilentlyContinue
dsh.cmd --version
```

如果 PowerShell 提示 `npm.ps1` 或 `dsh.ps1` 因执行策略无法加载，不要修改执行策略，继续使用 `npm.cmd` 和 `dsh.cmd`。

如果 npm 报出平台不支持、原生模块无法安装或类似兼容性错误：

1. 保存完整错误信息。
2. 不要关闭安全软件，不要下载来源不明的二进制文件。
3. 停止安装，并在最终回执中写明“当前版本未通过 Windows 兼容性验证”。

只有命令路径和版本号都出现，才可以进入下一步。

## 第 4 步：创建独立工作区

执行：

```powershell
$DshWorkspace = Join-Path $env:USERPROFILE "Documents\DeepSeek-Harness-Workspace"
New-Item -ItemType Directory -Path $DshWorkspace -Force | Out-Null
$DshWorkspace
```

不要把整个桌面、下载目录、文档目录或已有项目根目录设为第一次运行的工作区。

## 第 5 步：启动本地网页

先检查服务是否已经运行：

```powershell
try {
    $Response = Invoke-WebRequest -Uri "http://127.0.0.1:3080/" -UseBasicParsing -TimeoutSec 5
    "Harness 已在运行，HTTP 状态：$($Response.StatusCode)"
} catch {
    "Harness 尚未运行"
}
```

如果尚未运行，优先在当前 PowerShell 中执行：

```powershell
dsh.cmd web
```

这个命令需要保持运行。不要因为终端暂时没有新输出就结束进程。

如果当前智能体无法维持长时间运行的命令，就启动一个独立 PowerShell 窗口：

```powershell
Start-Process powershell.exe -ArgumentList "-NoExit", "-Command", "dsh.cmd web"
```

然后打开本地页面：

```powershell
Start-Process "http://127.0.0.1:3080"
```

等待服务启动后验收：

```powershell
$Response = Invoke-WebRequest -Uri "http://127.0.0.1:3080/" -UseBasicParsing -TimeoutSec 10
$Response.StatusCode
```

验收标准：

- 返回正常 HTTP 状态。
- 浏览器能打开 `http://127.0.0.1:3080`。
- 能看到 DeepSeek Harness 页面。

## 第 6 步：让用户亲自填写 API Key

告诉用户：

1. 没有 DeepSeek API Key 时，打开 `https://platform.deepseek.com/` 创建。
2. 回到 Harness，进入“设置 → 模型 → DeepSeek”。
3. 由用户本人在页面中填写 API Key 并保存。
4. 填写后只回复智能体：`填好了`。

执行智能体不得要求用户把 API Key 发到聊天中，不得截图密钥，不得从页面、剪贴板、配置文件或日志中提取密钥。

用户回复“填好了”以后，只检查 DeepSeek 模型是否显示“已配置”或绿色状态，不检查密钥内容。

## 第 7 步：创建首次会话

在 Harness 新会话中设置：

- 工作区：使用第 4 步实际打印出来的完整 Windows 路径，不要把 `%USERPROFILE%` 当成文字填写
- 运行模式：标准模式
- 访问权限：`Workspace Write`
- 模型：当前可用的 DeepSeek 模型
- 推理等级：先使用默认值；用户需要复杂任务时再提高

如果智能体无法操作本地浏览器，就逐项告诉用户点击，不要编造已选择状态。

## 第 8 步：完成真实任务验收

不要发送“请只回复连接成功”一类无意义测试。

请用户提供一个范围清晰、可以在独立工作区完成的小任务，例如：整理一份资料、生成一个简单项目、处理一份允许访问的文件。

验收至少检查：

1. Harness 是否实际创建或修改了目标文件。
2. 需要执行的 PowerShell 或其他命令是否真的运行。
3. 检查或测试是否通过。
4. Harness 是否重新读取最终结果并给出交付说明。

如果用户暂时没有任务，只完成安装与配置，不要虚构任务结果；在回执里写明“真实任务验收待用户提供任务”。

## 常见问题处理

### `node` 或 `npm.cmd` 找不到

关闭 PowerShell，重新打开后再检查。仍然找不到时执行：

```powershell
Get-ChildItem "C:\Program Files\nodejs" -ErrorAction SilentlyContinue
[Environment]::GetEnvironmentVariable("Path", "User")
[Environment]::GetEnvironmentVariable("Path", "Machine")
```

确认 Node.js 是否真实安装。不要反复安装多个版本。

### `dsh.cmd` 找不到

执行：

```powershell
$NpmPrefix = (npm.cmd config get prefix).Trim()
$NpmPrefix
Get-ChildItem $NpmPrefix -Filter "dsh*" -ErrorAction SilentlyContinue
```

如果文件存在，按第 3 步把该用户目录加入用户 `PATH`；如果文件不存在，回读 npm 安装错误，不要声称安装完成。

### `127.0.0.1:3080` 打不开

确认运行 `dsh.cmd web` 的 PowerShell 窗口仍然开启，然后执行：

```powershell
Get-NetTCPConnection -LocalPort 3080 -State Listen -ErrorAction SilentlyContinue
Test-NetConnection -ComputerName 127.0.0.1 -Port 3080
```

根据真实错误继续处理，不要立即重装。

### 端口 3080 已被占用

执行：

```powershell
$Connection = Get-NetTCPConnection -LocalPort 3080 -State Listen -ErrorAction SilentlyContinue
$Connection
if ($Connection) {
    Get-Process -Id $Connection.OwningProcess -ErrorAction SilentlyContinue
}
```

如果占用者就是 DeepSeek Harness，直接打开页面。不能确认进程身份时，不得强制结束进程。

### Windows 防火墙弹出提示

Harness 默认使用本机地址 `127.0.0.1`。不要主动创建公网入站规则，也不要关闭防火墙。需要确认时，让用户阅读弹窗并自行决定；本教程不要求把服务开放到局域网或互联网。

### 模型显示未配置或请求失败

让用户在 Harness 设置页重新检查 API Key、账户余额和网络状态。仍然禁止用户把 Key 发给智能体。

### 停止 Harness

回到运行 `dsh.cmd web` 的 PowerShell 窗口，按：

```text
Ctrl + C
```

不要通过进程 ID 强制停止无法确认身份的进程。

## 最终回执格式

完成后只汇报真实结果：

```text
DeepSeek Harness Windows 安装结果
- 系统：Windows 版本 / 处理器架构
- PowerShell：版本号
- Node.js：版本号
- npm：版本号
- dsh 路径：真实路径
- dsh 版本：版本号
- 本地地址：http://127.0.0.1:3080
- 独立工作区：真实路径
- DeepSeek 模型：已配置 / 待用户配置（禁止显示 Key）
- 服务状态：正在运行 / 已停止
- Windows 兼容性验证：已通过 / 未通过及具体错误
- 真实任务验收：已通过 / 待用户提供任务 / 未通过及具体原因
```

任何一项没有实际检查，就写“未验证”，不得猜测或伪造成功。

## 官方入口

- DeepSeek Harness：https://github.com/deepseek-ai/deepseek-harness
- DeepSeek 开放平台：https://platform.deepseek.com/
- DeepSeek API 文档：https://api-docs.deepseek.com/
- Node.js：https://nodejs.org/

> 本文件针对原生 Windows PowerShell，不针对 WSL。DeepSeek Harness 当前处于 Developer Preview，官方目前没有在公开安装说明中明确承诺 Windows 支持。执行时如发现版本或平台差异，应优先核对官方仓库，并如实反馈兼容性结果。
