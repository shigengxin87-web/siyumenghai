# DeepSeek Harness｜Mac 智能体一键安装指令

> 把本文件完整交给 Codex、WorkBuddy、Coze Bot 或其他智能体，然后发送：`严格按照文件帮我安装 DeepSeek Harness。`

## 给执行智能体的任务

在用户的 Mac 上安装并启动 DeepSeek Harness，完成基础配置引导和结果验收。

从本段开始，所有指令均写给执行智能体。

## 强制规则

1. 先判断你是否拥有这台 Mac 的本地终端和浏览器操作权限。
2. 有本地权限：直接执行命令，并逐步读取结果。
3. 没有本地权限：不要声称“已安装”；把命令一次只发一组，等待用户返回真实输出后再继续。
4. 禁止索取、读取、复制、记录或回显用户的 DeepSeek API Key。
5. API Key 必须由用户本人在 DeepSeek Harness 本地设置页中填写。
6. 禁止使用 `sudo npm install`。
7. 禁止操作用户桌面、文稿库、代码库或其他无关目录。
8. 第一次运行必须使用独立空工作区。
9. 每一步都要验收。命令没有报错，不等于安装成功。
10. 遇到需要用户登录、输入密钥或确认权限的步骤时暂停，明确告诉用户在哪里操作，然后等待用户回复“填好了”或“完成了”。

## 第 1 步：确认系统

执行：

```bash
uname -s
uname -m
```

验收标准：

- `uname -s` 必须返回 `Darwin`。
- 记录芯片架构是 `arm64` 还是 `x86_64`。
- 如果不是 macOS，停止执行并说明：本文件只负责 Mac 安装，不能照搬到其他系统。

## 第 2 步：检查 Node.js 和 npm

执行：

```bash
command -v node
node --version
command -v npm
npm --version
```

判断：

- 四条命令都有正常输出：继续下一步。
- `node` 或 `npm` 不存在：安装 Node.js LTS。

如果本机已有 Homebrew，执行：

```bash
brew install node
```

如果没有 Homebrew，不要擅自安装 Homebrew。打开以下页面，让用户安装 Node.js LTS：

```text
https://nodejs.org/
```

安装后重新执行本步骤的四条检查命令。拿到真实版本号后才能继续。

## 第 3 步：安装 DeepSeek Harness

先执行全局安装：

```bash
npm install -g @deepseek-ai/dsh
```

安装完成后立即验收：

```bash
command -v dsh
dsh --version
```

验收标准：

- `command -v dsh` 返回真实可执行文件路径。
- `dsh --version` 返回版本号。

如果出现 npm 权限错误，不要使用 `sudo`。改用用户目录安装：

```bash
DSH_NPM_PREFIX="$HOME/.npm-global"
mkdir -p "$DSH_NPM_PREFIX"
npm config set prefix "$DSH_NPM_PREFIX"
export PATH="$DSH_NPM_PREFIX/bin:$PATH"
npm install -g @deepseek-ai/dsh
command -v dsh
dsh --version
```

如果这样可以运行，但新终端里找不到 `dsh`，先判断用户当前 Shell：

```bash
printf '%s\n' "$SHELL"
```

macOS 默认 zsh 时，把下面这一行加入 `~/.zprofile`；写入前先检查，禁止重复追加：

```bash
grep -qxF 'export PATH="$HOME/.npm-global/bin:$PATH"' "$HOME/.zprofile" 2>/dev/null || printf '%s\n' 'export PATH="$HOME/.npm-global/bin:$PATH"' >> "$HOME/.zprofile"
export PATH="$HOME/.npm-global/bin:$PATH"
```

再次执行：

```bash
command -v dsh
dsh --version
```

只有路径和版本号都出现，才可以判定安装完成。

## 第 4 步：创建独立工作区

执行：

```bash
DSH_WORKSPACE="$HOME/Documents/DeepSeek-Harness-Workspace"
mkdir -p "$DSH_WORKSPACE"
printf '%s\n' "$DSH_WORKSPACE"
```

不要把整个桌面、下载目录、文稿目录或现有项目根目录设为第一次运行的工作区。

## 第 5 步：启动本地网页

先检查服务是否已经运行：

```bash
curl -fsS http://127.0.0.1:3080/ >/dev/null 2>&1 && echo "Harness 已在运行" || echo "Harness 尚未运行"
```

如果尚未运行，执行：

```bash
dsh web
```

这个命令需要保持运行。不要因为终端暂时没有新输出就结束进程。

看到下面的本地地址后，打开它：

```text
http://127.0.0.1:3080
```

macOS 可执行：

```bash
open http://127.0.0.1:3080
```

如果当前智能体的命令执行器不能保持长时间进程，就让用户在一个独立终端窗口中运行 `dsh web`，并提醒该窗口保持开启。

验收标准：

```bash
curl -I http://127.0.0.1:3080/
```

返回 HTTP 响应，并且浏览器能打开 Harness 页面。

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

- 工作区：`$HOME/Documents/DeepSeek-Harness-Workspace`
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
2. 需要执行的命令是否真的运行。
3. 检查或测试是否通过。
4. Harness 是否重新读取最终结果并给出交付说明。

如果用户暂时没有任务，只完成安装与配置，不要虚构任务结果；在回执里写明“真实任务验收待用户提供任务”。

## 常见问题处理

### `dsh: command not found`

执行：

```bash
npm config get prefix
printf '%s/bin\n' "$(npm config get prefix)"
printf '%s\n' "$PATH"
```

把 npm 全局可执行目录加入当前 Shell 的 `PATH`，然后重新执行 `command -v dsh` 和 `dsh --version`。

### `127.0.0.1:3080` 打不开

确认 `dsh web` 进程仍在运行，然后执行：

```bash
curl -v http://127.0.0.1:3080/
lsof -nP -iTCP:3080 -sTCP:LISTEN
```

根据真实错误继续处理，不要反复重装。

### 端口 3080 已被其他程序占用

先用下面的命令确认占用者：

```bash
lsof -nP -iTCP:3080 -sTCP:LISTEN
```

如果占用者就是 DeepSeek Harness，直接打开页面。不能确认进程身份时，不得强制结束。

### 模型显示未配置或请求失败

让用户在 Harness 设置页重新检查 API Key、账户余额和网络状态。仍然禁止用户把 Key 发给智能体。

### 停止 Harness

回到运行 `dsh web` 的终端，按：

```text
Control + C
```

## 最终回执格式

完成后只汇报真实结果：

```text
DeepSeek Harness 安装结果
- 系统：macOS / 芯片架构
- Node.js：版本号
- npm：版本号
- dsh 路径：真实路径
- dsh 版本：版本号
- 本地地址：http://127.0.0.1:3080
- 独立工作区：真实路径
- DeepSeek 模型：已配置 / 待用户配置（禁止显示 Key）
- 服务状态：正在运行 / 已停止
- 真实任务验收：已通过 / 待用户提供任务 / 未通过及具体原因
```

任何一项没有实际检查，就写“未验证”，不得猜测或伪造成功。

## 官方入口

- DeepSeek Harness：https://github.com/deepseek-ai/deepseek-harness
- DeepSeek 开放平台：https://platform.deepseek.com/
- DeepSeek API 文档：https://api-docs.deepseek.com/
- Node.js：https://nodejs.org/

> 本文件针对 macOS。DeepSeek Harness 当前处于 Developer Preview，后续命令和界面可能变化；执行时如发现版本差异，应优先核对官方仓库，不得盲目套用旧步骤。
