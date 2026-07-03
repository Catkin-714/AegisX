# AegisX

基于 MCU 协议族的多方安全 Transformer 推理系统。

## 系统概述

AegisX 实现了三条可比较的 BERT 推理路径，展示从明文到密文推理的隐私保护效果：

| 路径 | 隐私保护 | 说明 |
|------|---------|------|
| **Plaintext** | 无 | 标准 HuggingFace/PyTorch 明文基准 |
| **CrypTen** | 两方 MPC | 两个 rank 通过 Gloo/TCP 通信 |
| **MCU** | 三方 MPC | `p0/p1/hp` 通过 TCP 完成端到端密文推理 |

### 当前状态

- **Goal 1**：算子级优化完成。BERT-like batch `1,2,4` 下主要算子均达到当前 CPU Docker 接受阈值
- **Goal 2**：完整 BERT Docker 数值推理完成，并已和 CrypTen Docker 对比
- **Goal 3**：Dashboard 已支持选择进程启动或 Docker 启动，并可在同一输入上比较 plaintext、CrypTen、MCU

### 技术栈

- **后端**：Python 3.11 + FastAPI + PyTorch 2.5.1 (CUDA 12.1) + CrypTen
- **前端**：单文件 HTML + CSS + JavaScript
- **协议引擎**：Rust (mcu_rust) + Python 绑定
- **容器化**：Docker + docker-compose
- **模型**：BERT-Base/Large (HuggingFace transformers)

## 目录结构

```text
AegisX/
├── dashboard/                  # FastAPI 后端和单页前端
│   ├── backend/
│   │   ├── main.py            # FastAPI 服务入口
│   │   ├── bert_orchestrator.py # BERT 三路径编排
│   │   ├── infer_engine.py    # 推理引擎（规则+MCU线性）
│   │   └── rust_verify.py     # Rust 协议验证
│   └── frontend/
│       └── index.html         # 单文件前端界面
├── docker/                     # Dockerfile 与 docker-compose
│   ├── docker-compose.mpc.yml # MPC 服务编排
│   ├── Dockerfile.crypten     # CrypTen 镜像
│   └── Dockerfile.mcu         # MCU 镜像
├── experiments/                # 实验脚本与数据
│   ├── docker_real_comm/      # 算子级 Docker 对比实验
│   ├── docker_bert_full/      # 完整 BERT Docker 推理
│   └── *.py                   # 各类实验脚本
├── mcu_rust/                   # Rust 协议引擎
│   ├── src/                   # Rust 源码
│   └── target/release/        # 编译产物
├── mcu_core/                   # Python MCU 协议实现
│   ├── protocols/             # 核心协议（multiply/exp/softmax/gelu）
│   ├── comm.py                # 三方通信层
│   └── prg_sync.py            # PRG 同步
├── transformer/                # BERT 推理层
│   ├── mcu_linear.py          # 密文线性层
│   ├── mcu_bert_crypten.py    # CrypTen BERT
│   └── plaintext_bert.py      # 明文 BERT
├── results/                    # 实验结果数据
├── scripts/                    # 辅助脚本
└── start_dashboard.bat        # 一键启动脚本
```

## 快速开始

### 前置要求

| 组件 | 版本 | 说明 |
|------|------|------|
| Windows | 10/11 | 主要开发环境 |
| Python | 3.11+ | 宿主机 Python |
| Rust | 1.70+ (MSVC) | 编译 mcu_rust |
| Docker | Desktop | 可选，用于容器化部署 |
| Visual Studio 2022 | C++ 桌面开发 | Rust 编译依赖 |

### 1. 克隆并进入项目

```bash
git clone https://github.com/napnah/AegisX.git AegisX
cd AegisX
```

### 2. 创建 Python 虚拟环境

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 3. 编译 Rust 协议引擎

```powershell
cd mcu_rust
cargo build --release
cd ..
```

编译成功后，二进制位于 `mcu_rust\target\release\mcu_hp.exe`。

### 4. 准备模型文件

```powershell
python scripts/download_models.py
```

或手动将模型放在项目根目录：
```text
bert-base-uncased/
checkpoints/bert-sst2/
```

### 5. 启动 Dashboard

```powershell
start_dashboard.bat
```

浏览器打开 `dashboard/frontend/index.html`，在舆情情感分析场景中：

- 选择 BERT 模式：plaintext、CrypTen 或 MCU-Rust
- 选择启动方式：进程启动、Docker 启动或 Docker 服务
- 点击 `加密推理` 运行单一路径
- 点击 `比较三路` 在同一输入上比较三条路径

## Docker 部署

### 构建镜像

```powershell
# 构建 CrypTen 镜像
docker compose -f docker/docker-compose.mpc.yml build crypten-r0

# 构建 MCU 镜像
docker compose -f docker/docker-compose.mpc.yml build mcu-hp
```

### 启动服务

```powershell
# 启动 CrypTen 服务
python experiments/docker_bert_full/warm_docker_service.py start-crypten-service

# 启动 MCU 服务
python experiments/docker_bert_full/warm_docker_service.py start-mcu-service

# 查看状态
python experiments/docker_bert_full/warm_docker_service.py status
```

### 运行推理

```powershell
# CrypTen 推理
python experiments/docker_bert_full/warm_docker_service.py infer-crypten-service --text "This movie is wonderful."

# MCU 推理
python experiments/docker_bert_full/warm_docker_service.py infer-mcu-service --text "This movie is wonderful."
```

## 实验数据

### 算子级 Docker 对比

数据来源：`experiments/20260624_154028_docker_real_comm/summary.csv`

实验范围：真实 Docker 通信；MCU 为 `p0/p1/hp` TCP；CrypTen 为两 rank Gloo/TCP

| 算子 | Batch 1 | Batch 2 | Batch 4 | 状态 |
|---|---:|---:|---:|---|
| `elemul` | 7.39x | 8.85x | 8.01x | accepted |
| `matmul` | 7.76x | 7.07x | 7.57x | accepted |
| `exp` | 10.13x | 19.28x | 34.00x | accepted |
| `sigmoid` | 2.79x | 4.49x | 9.13x | accepted |
| `gelu` | 2.58x | 4.90x | 9.24x | accepted |
| `softmax` | 0.73x | 1.33x | 2.68x | accepted |

> 注：ratio < 1.0x 表示 MCU 更快

### BERT 推理对比

数据来源：`experiments/20260703_084824_bert_process_compare/summary.csv`（进程模式，10 个样本）

| 路径 | 样本数 | 平均延迟 | 准确率 | top-1 匹配 | Mean JS |
|------|--------|----------|--------|------------|---------|
| Plaintext | 10 | 0.164s | 60% | 1.00 | 0 |
| CrypTen | 10 | 11.765s | 60% | 1.00 | 0.000251 |

> 注：模型未微调（`bert-base-uncased` 原始权重），准确率较低属预期。核心结论是 CrypTen 与 Plaintext 预测 100% 一致，JS 散度极小（0.000251），验证密文推理正确性。

### GLUE 基线

数据来源：`results/baseline_results.csv`

| 模型 | 任务 | 分数 |
|------|------|------|
| BERT-Large | CoLA | 60.7 |
| BERT-Base | CoLA | 53.9 |
| BERT-Base | RTE | 66.8 |
| BERT-Base | MRPC | 87.4 |
| BERT-Base | STS-B | 88.9 |
| BERT-Base | QNLI | 91.4 |

### 2Quad 精度归零

数据来源：`results/2quad_collapse.txt`

```
BERT-Large CoLA original_softmax: 59.92
BERT-Large CoLA 2quad: 0.0
```

SecFormer 的 2Quad 近似导致精度完全归零，证明 MCU 精确 Softmax 的必要性。

### CrypTen 延迟基线

数据来源：`results/crypten_latency.txt`

```
Q投影 (768x768): plain=2.914ms, cipher=566.5ms (194x)
FFN第一层 (768x3072): plain=1.437ms, cipher=3211.1ms (2235x)
FFN第二层 (3072x768): plain=2.476ms, cipher=4465.9ms (1846x)
```

## 命令行使用

### 进程模式

```powershell
venv\Scripts\python.exe -c "
import sys; sys.path[:0] = ['dashboard/backend', '.']
from bert_orchestrator import compare
out = compare('This movie is wonderful.', launch='process', max_seq_len=16)
print(out['success'], out['success_count'], out['total_count'])
"
```

### Docker 模式

```powershell
venv\Scripts\python.exe -c "
import sys; sys.path[:0] = ['dashboard/backend', '.']
from bert_orchestrator import compare
out = compare('This movie is wonderful.', launch='docker', max_seq_len=16)
print(out['success'], out['success_count'], out['total_count'])
"
```

### 算子级 benchmark

```powershell
venv\Scripts\python.exe experiments/docker_real_comm/run_docker_comparison.py --preset bert --repeat 3 --batches 1,2,4 --skip-build
```

## 安全边界

### 已实现

- MCU `p0/p1/hp` 真实 TCP 通信
- CrypTen 两 rank 真实 Docker 通信
- 张量级 matmul 和批量非线性算子
- 使用真实 checkpoint 权重和真实输入 embedding 的完整 BERT 数值 Docker 流程

### 尚未达到最终安全版本

- MCU 完整 BERT 仍使用 HP-clear 数值桥接（rescale/fixed-real conversion/LayerNorm/tanh/reveal）
- 后续应替换为 wrap-correct secure truncation/rescale、安全 fixed/real conversion、安全 LayerNorm

## 常见问题

**Docker daemon 不可用**
```powershell
docker info
```
运行 Docker 路径前，请先启动 Docker Desktop。

**缺少模型文件**
```powershell
python scripts/download_models.py
```

**清理残留容器**
```powershell
docker compose -f docker/docker-compose.mpc.yml down --remove-orphans
```

**端口 9000 被占用**
```powershell
netstat -ano | findstr 9000
taskkill /F /PID <PID>
```

**Python 控制台中文乱码**
```powershell
$env:PYTHONIOENCODING = "utf-8"
```
