# 💭 碎碎念 · 云部署包（全中文版）

把碎碎念放到**云服务器**上，24小时在线，朋友在哪都能打开！

---

## 📁 包里都有什么

```
cloud_deploy/
├── server.py          # 后端程序（已经加好了可见性功能）
├── index.html         # 网页界面（已经加好了公开/私密切换）
├── requirements.txt   # 依赖清单（告诉服务器要装什么）
├── Procfile           # 启动配置（告诉服务器怎么运行）
├── Dockerfile         # 容器配置（另一种启动方式）
└── README.md          # 这份说明书
```

---

## 🚀 方法一：用 Railway 部署（推荐，需要有 GitHub 账号）

> 如果你有 GitHub 账号，这个方法最方便！

**第一步：注册 Railway 账号**
1. 打开 https://railway.com
2. 点右上角「Login」→ 选择「GitHub」
3. 用你的 GitHub 账号登录（免费）
4. 授权后自动创建好账号

**第二步：把代码上传到 GitHub**
1. 打开 https://github.com 登录你的账号
2. 点右上角「+」→「New repository」
3. 仓库名字随便写，比如 `suisui`
4. 选「Public」（公开）或「Private」（私密）都可以
5. 点「Create repository」
6. 把 zip 包里的文件解压出来，全部上传到 GitHub 这个仓库里
7. 上传方法：点仓库里的「Add file」→「Upload files」→把文件拖进去→点「Commit changes」

**第三步：在 Railway 上部署**
1. 打开 Railway 网站（https://railway.com）
2. 点「New Project」→「Deploy from GitHub repo」
3. 选择你刚才上传的那个仓库（比如 `suisui`）
4. Railway 会自动检测到 Dockerfile，开始构建和部署
5. 等一两分钟，出现绿色「Deployed」就成功了！
6. Railway 会给你一个地址，像这样：`https://xxxx.railway.app`
7. **大功告成！** 把这个地址发给朋友，谁都能打开碎碎念了！

> ⚠️ 注意：Railway 免费版每月能用 500 小时（大概21天），重启后数据会丢失
> 如果想要数据不丢，可以花 5 美元/月升级，就有永久保存了

---

## 🚀 方法二：用 PythonAnywhere 部署（最简单！不需要 GitHub 账号）

> 这个方法**最简单**，直接在网页上操作，点点点就好了！

**第一步：注册账号**
1. 打开 https://www.pythonanywhere.com
2. 点「Pricing & Signup」→ 选「Create a Beginners account」（免费）
3. 输入你想用的用户名、邮箱、密码，注册

**第二步：上传文件**
1. 登录后进到控制台（Dashboard）
2. 点上面的「Files」标签
3. 在文件列表里，点「Upload a file」
4. 把 zip 包里的 **所有文件** 一个一个上传上去
   - server.py
   - index.html
   - requirements.txt
   - Procfile
   - Dockerfile（这个可以不上传）

**第三步：创建 Web 应用**
1. 点上面的「Web」标签
2. 点「Add a new web app」
3. 点「Manual configuration」（手动配置）
4. Python 版本选「3.12」
5. 点「Next」创建完成

**第四步：安装依赖**
1. 还是在「Web」页面
2. 往下找到「Virtualenv」部分
3. 点「Start a console in this virtualenv」
4. 在弹出的终端里输入：`pip install -r requirements.txt`
5. 等它安装完成，关掉终端

**第五步：配置启动文件**
1. 还是在「Web」页面
2. 找到「Code」部分
3. 点「WSGI configuration file」旁边的链接
4. 把里面的内容**全部删掉**，换成下面的代码：

```python
import sys
path = '/home/你的用户名/cloud_deploy'
if path not in sys.path:
    sys.path.append(path)
from server import app as application
```

> ⚠️ 记得把「你的用户名」改成你注册时设置的用户名！

5. 点「Save」保存

**第六步：启动！**
1. 回到「Web」页面顶部
2. 点绿色的「Reload」按钮
3. 等几秒钟，页面刷新后显示「Reloaded successfully」
4. 你的碎碎念地址就是：`https://你的用户名.pythonanywhere.com`
5. **大功告成！** 发给朋友就能用了！

> ✅ PythonAnywhere 免费版文件永久保存，数据不会丢！
> 唯一的缺点是免费版每天只能有 100 个人访问，对朋友来说完全够用～

---

## 🔐 可见性功能说明

发帖的时候，心情标签旁边有个按钮：
- 🌍 **公开** → 所有人都能看到你发的
- 🔒 **私密** → 只有你自己能看到（别人刷新也看不到）

点一下就能切换啦～

---

## 💜 有问题随时问我！

选一个方法试试，如果卡在哪一步了，截图发给我，我一步步教你！
