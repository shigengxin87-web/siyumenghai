# 如何在Obdisian侧边栏接入AI模型直接对话

### 接入Deepseek，使用Copilot插件

这种方法比较简单实用，需要注册Deepseek官方的API。

**第1步**：点击左下角的设置按钮

**第2步**：第一次安装插件，需要先关闭"安全模式"

**第3步**：关闭"安全模式"后，就会出现"社区插件市场"，然后点击"浏览"按钮

**第4步**：在插件市场搜索"Copilot"，然后安装Copilot插件

**第5步**：安装好后，在"设置"中进入Copilot插件的设置页面，然后点击"Model"-"添加Model"

![这张图片是Obdisian的插件市场页面，页面顶部搜索框内输入了“copl”，显示“仅显示已安装”的开关为关闭状态，当前显示34个插件。页面中，被红色框标注突出的“Copilot”插件是核心展示内容，该插件作者为Logan Yan，下载量达149.3K，更新于1个月前，说明文字为“You AI Copilot: Chat With Your Second Brain, Learn Faster, Work Smarter”，对应文档中接入Copilot插件的操作步骤，是搜索该插件时出现的结果界面。](https://feishu.cn/file/LaafbIMgUo9m5ZxFBOzcwpJwnYd)

![图片展示的是Obdisian中Copilot插件的设置页面。页面左侧有多个选项，当前选中“第三方插件”。右侧是Copilot Settings v3.3.3设置界面，有Basic、Model、QA等标签，当前选中Model标签。在Model标签下，有多个Chat Models列表，如copilot-plus-flash、google/gemini-2.5-flash等，右侧有Enable、CORS、Actions等设置项。页面右上角有“Add Model”按钮，用于添加模型。该图片与文档中介绍在Obdisian侧边栏接入AI模型直接对话的步骤相关，是第5步安装好Copilot插件后，在“设置”中进入Copilot插件设置页面，点击“Model” - “添加Model”这一步骤的展示。](https://feishu.cn/file/A4lRbhJ66oPZeTxmwPKcJJb6nsM)

![这张图片展示的是在Obdisian中添加自定义聊天模型的设置界面，对应接入Copilot插件步骤里添加模型的环节，是设置流程中的关键操作界面。界面里有两个被红色方框标注的核心输入项，分别是必填的“Model Name”输入栏，提示可输入模型名称如gpt-4，以及“API Key”输入栏，提示可填入OpenRouter的API密钥。该界面还包含可选项“Display Name”“Provider”“Base URL”等内容，底部设有“Test”和“Add Model”按钮，用于测试添加的模型信息并完成添加操作。](https://feishu.cn/file/Q6dYbSRpEoKhVhx2HFMcdGvfnog)

**第6步**：接下来，去申请API。由于这个插件支持的国内大模型只有Deepseek，这里以申请DeepSeek的官方API为例。先打开DeepSeek开放平台的网页端：https://platform.deepseek.com，然后用微信扫码登录即可。

**第7步**：点击"充值"，然后点击"去认证"，输入相关信息后即可完成认证。

**第8步**：按需求充值即可

**第9步**：然后点击"API Keys"去创建API

**第10步**：输入便于你分辨这个API是用于何处的名称，然后点击"创建"

**第11步**：创建好API后，注意保存好这个Key。这个Key只会出现一次，如果忘记了，只能重新再生产一个。

**第12步**：最后回到Obsidian，去添加模型的API key。**（要注意，你所使用的API必须保证有余额，否则会添加失败）**

**第13步**：模型添加完成之后，在左侧工具栏点击Copilot按钮打开插件。第一次使用前，务必先选前面添加好的模型。选择模型后就可以开始使用了。

![图片展示的是在Obsidian左侧工具栏中添加模型的界面。界面中列出了多个模型，如grok-4.3、x - ai/grok - 4.3等，每个模型右侧有勾选框，其中“deepseek - chat”模型的勾选框被勾选。下方有“Conversation turns in context”设置区域，可调整上下文对话轮数，默认为15轮，即30条消息。该图片与上下文关系紧密，是第13步“添加模型的API key后，在左侧工具栏点击Copilot按钮打开插件，选择添加好的模型”操作后的呈现，用于指导用户选择添加的模型。](https://feishu.cn/file/QxSgbk2Pxo2cXFxI59gcen29n5e)

![图片展示了在Obsidian中使用Deepseek插件的界面。左侧为侧边栏，有“Open Copilot Chat”选项。右侧是笔记内容区域，显示了“01 - 私域增长飞轮：修改稿”等信息。右下角是聊天窗口，有“@Add context”提示，下方是“deepseek - chat”输入框。该图片与上下文紧密相关，直观呈现了在Obsidian中添加模型API key后，使用Copilot插件进行对话的界面情况，辅助说明了第13步操作的实现效果。](https://feishu.cn/file/T8gobRCZ7osMs1xoZ0Zc7X07ngc)

---

### 接入Codex或Claude code，使用Claudian插件

这种方法需要电脑本地已经安装好Codex或者 Claude Code，才可以使用

**第1步**：点击左下角的设置按钮

**第2步**：第一次安装插件，需要先关闭"安全模式"

**第3步**：关闭"安全模式"后，就会出现"社区插件市场"，然后点击"浏览"按钮

**第4步**：打开插件市场后，在搜索栏搜索"claudian"

**第5步**：点击"claudian"，进入介绍界面，然后点击"安装"，进行插件安装。

**第6步**：安装好后，"安装"按钮会变为"选项"，点击"选项"

![图片展示了在Obdisian中安装Claudian插件后的“选项”界面。左侧为已安装插件列表，Claudian处于安装状态。右侧是Claudian插件介绍页面，显示版本、作者、GitHub仓库地址等信息，下方有“选项”按钮，其被红色框突出显示。该图片与文档中“第6步：安装好后，‘安装’按钮会变为‘选项’，点击‘选项’”的内容对应，直观呈现了点击“选项”按钮的操作位置。](https://feishu.cn/file/TOalb9gNqotUcnxC77xcxyYSnbb)

![图片展示了Obdisian插件市场中Claudian插件的“选项”界面。左侧有多个选项卡，当前选中“Claude”选项卡。右侧“Setup”部分，有“Enable Codex provider”开关，已开启；“Codex CLI path”显示为“/Applications/Codex_app/Conte”。下方“Safety”部分有“Safe mode”选项。最下方“Models”部分列出“Custom models”和“Reasoning summary”等设置项。该图片与文档中接入Codex或Claude code，使用Claudian插件的第6步操作相关，展示了插件安装好后的设置界面。](https://feishu.cn/file/LGElbn8hko1DSyxxRYXcgVbmnjh)
![图片展示的是在Obdisian侧边栏接入AI模型时，使用Claudian插件后，输入“我的codex cli路径是什么”后得到的回复。回复显示“你的Codex命令行工具路径是：/Applications/...codex”，其中部分路径被模糊处理。该图片与文档中接入Codex或Claude code，使用Claudian插件的步骤说明相关，是插件安装好后，通过输入指令获取Codex命令行工具路径的示例。](https://feishu.cn/file/OuZDbWQz1okWmQxZwsEcUBWvn8c)
选【codex】，如果用Claude code就选claude。
打开【开关】。
去Codex对话框里输入：【我Codex cli path是什么】，把回复的内容复制粘贴到【Codex cli path】
然后右上角x关闭即可。
![图片展示的是Obdisian侧边栏接入AI模型时Codex设置界面。界面中有General、Claude、Codex、OpenCode、Pi五个选项卡，当前选中Codex。在Setup部分，Enable Codex provider开关处于开启状态，Codex CLI path输入框内显示路径为/Applications/Codex.app/Content。此图与文档中接入Codex或Claude code，使用Claudian插件的第6步操作相关，用于说明在侧边栏设置中配置Codex相关参数的步骤。](https://feishu.cn/file/CM2BbGNEooHx2jx4zaccaFJCn9c)

![图片展示了在Obdisian侧边栏接入AI模型直接对话的界面。左侧为侧边栏，有多个文件夹和标签。右侧是新标签页，显示“新标签页”字样及创建新文件、打开文件等选项。右侧还显示“Happy Sunday”及“Claudian”字样。右侧下方弹出一个对话框，列出多个AI模型，其中“GPT-5.5”模型被红色框突出显示。该图片与文档中接入Claudian插件、选择GPT5.5模型等操作步骤相关，直观呈现了操作后的界面情况。](https://feishu.cn/file/VV63brVI2oPznPx9aoZceBH5nLf)

**第7步**：点击侧边栏claudian按钮，右边出现对话框，选用GPT5.5模型。

![图片展示了Obdisian侧边栏界面。左侧是侧边栏，有多个图标和文件夹，其中“Open Claudian”图标被红色框突出显示。右侧是内容区域，显示“新标签页”。该图片对应文档中“第7步”操作说明，即点击侧边栏claudian按钮，右边出现对话框，选用GPT5.5模型，此图直观呈现了侧边栏中claudian按钮的位置，帮助用户找到操作入口。](https://feishu.cn/file/NiHSbQ7Oyoc57bx7ySYcLsWgnPe)

![图片展示了在Obdisian侧边栏接入AI模型直接对话时，选择Claudian插件后，点击侧边栏claudian按钮，右边出现的对话框界面。对话框中显示“Happy Sunday”，下方有模型选择区域，其中GPT-5.5模型被红色框突出显示，其下方还标注了“Effort: Medium”。该图片与文档中接入Claudian插件后选择GPT-5.5模型的步骤说明相契合，直观呈现了操作后的界面情况。](https://feishu.cn/file/Zts7b0O8toneBxxcylGcnwDsnph)
