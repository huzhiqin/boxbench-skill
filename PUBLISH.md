# BoxBench Skill 发布仓库

## 发布步骤

1. **GitHub 建仓**：新建公开仓库 `boxbench-skill`（MIT），不要初始化 README
2. **替换 huzhiqin**：全局搜索 `huzhiqin` 替换为你的 GitHub 用户名（install.sh、README.md、生成的 boxbench-update 中共 3 处）
3. **推送**：
```bash
cd /Users/mac/Desktop/MT-AIBox/BoxHarness/boxbench-skill
git init && git add -A && git commit -m "v1.2: 初始发布"
git remote add origin git@github.com:<huzhiqin>/boxbench-skill.git
git push -u origin main
git tag v1.2 && git push origin v1.2
```
4. **Gitee 镜像**：gitee.com 新建同名仓库 → 导入 GitHub 仓库（Gitee 支持一键导入，之后可设为定时同步或手动同步）
5. **验证**：
```bash
curl -fsSL --connect-timeout 5 https://raw.githubusercontent.com/<huzhiqin>/boxbench-skill/main/install.sh | head -5
curl -fsSL --connect-timeout 5 https://gitee.com/<huzhiqin>/boxbench-skill/raw/main/install.sh | head -5
```
6. **发新版**：改 skill/SKILL.md 的 `version:` + 更新 CHANGELOG.md + 打 tag push

## 注意

- skill/ 目录内容 = 本地 ~/.workbuddy/skills/box-bench/（措辞已清洗：去审查→去对齐微调）
- install.sh 有三处机制：本地文件优先 → GitHub → Gitee，curl|bash 时 5s 连接超时自动切换
- 升级命令 boxbench-update 由安装时写入用户 skills 目录
