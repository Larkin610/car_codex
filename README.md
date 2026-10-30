# 东风汽车简讯 Codex 独立项目

工作目录：`D:\Projects\car_codex`。日常将《汽车早餐》《国际快讯》放入 `PDFday`，在Codex打开本目录后输入：**按规则生产YYYY-MM-DD东风日报，先读早餐，自主联网补齐48槽位与3—5条数据。**

业务规则见 `rules/业务规则.md`，执行步骤与命令见 `rules/工作手册.md`，字段见 `rules/矩阵字段.md`。本项目通过当前Codex对话做采编和语义审核，无需额外OpenAI API密钥。独立`.venv`负责PDF/OCR和本地机械检查；不调用WorkBuddy脚本。

目录：PDFday（日常输入）；input（来源快照、PDF逐页/网页证据）；history（迁移后的本地滚动历史、比较及新增表）；candidates（未刊备用）；matrix（统一事实底稿）；output（送审与人工终审后的正式双版本）；logs（检索和检查）；scripts（工具）；.agents/skills（可复用采编入口）；.codex（项目实时搜索配置）。

安装/恢复：用Python3.12创建`.venv`，执行`.venv\Scripts\python.exe -m pip install -r requirements.txt`。确切安装版本保存在`requirements.lock.txt`；恢复生产环境优先按lock重建。当前安装已在此目录进行，运行命令用 `powershell -File scripts/brief.ps1 --help`。

本项目完整交付要求48固定槽位全合格、数据3—5条、政策最多12条。结构通过不能替代事实语义验证。正式发布需要用户实际人工终审授权；工具不代替签核。不写远程历史、不发送邮件、不设置自动运行。2026年11月起日常只读本地滚动30日历史；Google快照只用于一次迁移、恢复或人工审计，不能声称完整历史去重。

网页采集支持 HTTP 优先及 Crawl4AI 浏览器补抓，批量入口为 `fetch-batch`。选型、安装和使用见 [采集工具选型与使用](docs/采集工具选型与使用.md)。采集环境与核心环境独立，抓取成功不代表事实已核实。

This product includes software developed by UncleCode (https://x.com/unclecode) as part of the Crawl4AI project (https://github.com/unclecode/crawl4ai).
