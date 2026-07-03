# AegisX 环境构建指南

> 从零搭建到跑通全部演示，约 15-20 分钟。

---

## 一、前置要求

| 组件 | 版本要求 | 检查命令 |
|---|---|---|
| Windows | 10/11 | — |
| Python | 3.11+ | `python --version` |
| Rust | 1.70+ (MSVC) | `rustc --version` |
| Visual Studio 2022 | 含 C++ 桌面开发 | 安装时勾选"使用 C++ 的桌面开发" |
| Docker Desktop | 最新版 | `docker --version`（可选，用于容器化部署） |

### 安装 Rust（如未安装）

```powershell
# 下载 rustup-init.exe 从 https://rustup.rs
# 安装时选择 "Visual Studio 2022" 工具链
rustup default stable-msvc
```

### 安装 Docker Desktop（可选）

1. 下载 Docker Desktop for Windows
2. 启用 WSL2 后端
3. 配置镜像源加速（国内环境）

---

## 二、构建步骤

### 1. 克隆项目

```powershell
git clone https://github.com/napnah/AegisX.git AegisX
cd AegisX
```

### 2. 创建 Python 虚拟环境

```powershell
python -m venv venv
venv\Scripts\activate
```

### 3. 安装 Python 依赖

```powershell
pip install -r requirements.txt
```

核心依赖：
- `torch==2.5.1`（CUDA 12.1）
- `transformers==4.46.0`
- `crypten`（MPC 框架）
- `fastapi` + `uvicorn`（Web 服务）
- `pycryptodome`（加密原语）

### 4. 编译 Rust 协议引擎

```powershell
cd mcu_rust
cargo build --release
cd ..
```

编译成功后，二进制位于 `mcu_rust\target\release\mcu_hp.exe`。

**验证编译**：
```powershell
mcu_rust\target\release\mcu_hp.exe --help
```

### 5. 准备模型文件

```powershell
python scripts/download_models.py
```

或手动将模型放在项目根目录：
```text
bert-base-uncased/
checkpoints/bert-sst2/
```

### 6. 验证安装

```powershell
# 全量验证（约 5 秒）
venv\Scripts\python.exe verify_all.py
```

预期输出：`5/5 ALL PASSED`

---

## 三、Docker 配置（可选）

### 启动 Docker Desktop

确保 Docker Desktop 正在运行：
```powershell
docker info
```

### 构建镜像

```powershell
# 构建 CrypTen 镜像
docker compose -f docker/docker-compose.mpc.yml build crypten-r0

# 构建 MCU 镜像
docker compose -f docker/docker-compose.mpc.yml build mcu-hp
```

### 配置镜像源（国内环境）

编辑 Docker Desktop 设置 → Docker Engine，添加：
```json
{
  "registry-mirrors": [
    "https://docker.1ms.run",
    "https://docker.xuanyuan.me"
  ]
}
```

---

## 四、快速演示

### 方式一：一键启动 Dashboard

```powershell
start_dashboard.bat
```

浏览器打开 `dashboard/frontend/index.html`，在舆情情感分析场景中：
- 选择 BERT 模式：plaintext、CrypTen 或 MCU-Rust
- 选择启动方式：进程启动、Docker 启动或 Docker 服务
- 点击 `加密推理` 运行单一路径
- 点击 `比较三路` 在同一输入上比较三条路径

### 方式二：命令行演示

| 命令 | 用途 | 耗时 |
|---|---|---|
| `venv\Scripts\python.exe demo_all.py` | 全协议精度演示 | ~3s |
| `demo_party.bat` | 三方联调（三个窗口） | — |
| `venv\Scripts\python.exe bert_mpc_demo.py` | Tiny BERT MPC 推理 | ~1s |

### 方式三：Docker 服务

```powershell
# 启动 CrypTen 服务
python experiments/docker_bert_full/warm_docker_service.py start-crypten-service

# 启动 MCU 服务
python experiments/docker_bert_full/warm_docker_service.py start-mcu-service

# 查看状态
python experiments/docker_bert_full/warm_docker_service.py status

# 运行推理
python experiments/docker_bert_full/warm_docker_service.py infer-crypten-service --text "This movie is wonderful."
python experiments/docker_bert_full/warm_docker_service.py infer-mcu-service --text "This movie is wonderful."
```

---

## 五、运行实验

### 算子级 Docker 对比

```powershell
venv\Scripts\python.exe experiments/docker_real_comm/run_docker_comparison.py --preset bert --repeat 3 --batches 1,2,4 --skip-build
```

### BERT 三路径对比

```powershell
venv\Scripts\python.exe -c "
import sys; sys.path[:0] = ['dashboard/backend', '.']
from bert_orchestrator import compare
out = compare('This movie is wonderful.', launch='docker', max_seq_len=16)
print(out['success'], out['success_count'], out['total_count'])
"
```

### GLUE 基线实验

```powershell
venv\Scripts\python.exe experiments/run_glue_baseline.py
```

### 2Quad 精度归零验证

```powershell
venv\Scripts\python.exe experiments/verify_2quad_collapse.py
```

---

## 六、常见问题

**Q：`cargo build` 报错 "linker not found"？**
安装 Visual Studio 2022 时确保勾选了"使用 C++ 的桌面开发"工作负载。

**Q：`pycryptodome` 安装失败？**
需要 Visual C++ 编译工具。或者用 `pip install pycryptodome --only-binary :all:` 安装预编译版。

**Q：端口 9000 被占用？**
```powershell
netstat -ano | findstr 9000
taskkill /F /PID <PID>
```

**Q：Python 控制台中文乱码？**
```powershell
$env:PYTHONIOENCODING = "utf-8"
```

**Q：Docker 镜像下载慢？**
配置镜像源加速，或使用代理。

**Q：`mcu_rust` Python 绑定缺失？**
当前 `mcu_rust` 未编译 Python 绑定，`import mcu_rust` 成功但 `prg_next_batch` 属性缺失。这是已知限制，不影响 Dashboard 演示。

**Q：Docker bind mount 失败？**
Windows 上 Docker Desktop 偶尔无法绑定非系统盘，使用 tempdir 作为 fallback。

---

## 七、项目结构

```text
AegisX/
├── dashboard/                  # FastAPI 后端和单页前端
├── docker/                     # Dockerfile 与 docker-compose
├── experiments/                # 实验脚本与数据
├── mcu_rust/                   # Rust 协议引擎
├── mcu_core/                   # Python MCU 协议实现
├── transformer/                # BERT 推理层
├── results/                    # 实验结果数据
├── scripts/                    # 辅助脚本
├── start_dashboard.bat         # 一键启动脚本
└── verify_all.py               # 全量验证脚本
```
