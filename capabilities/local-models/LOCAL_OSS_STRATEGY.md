# Architectural Strategy: Local OSS Model Integration

This document outlines the strategy, model recommendations, workload allocation, and technical implementation plan for integrating local Open-Source Software (OSS) LLMs into the `hermes-coder` (Coding Coordinator) workflow on Apple Silicon (M-series) Macs to minimize API costs and maximize execution speed.

---

## 1. Local Model Selection (M-Series Optimized)

On Apple Silicon Macs, the unified memory architecture allows the GPU to access system RAM at extreme bandwidth (up to 800 GB/s on Max/Ultra chips). This makes running large open-source models locally highly performant.

For our programming-heavy workloads, we prioritize the following state-of-the-art models available in the Ollama registry:

### A. Google's Flagship Frontier-Level Engine: Gemma 4 & Gemma 4 Coder

Google's brand new **Gemma 4** represents a massive leap, delivering frontier-class reasoning, native tool calling, structured thinking, and multimodal (vision) support directly on consumer hardware.

- **Gemma 4 (26B / 31B):**
  - *Performance:* Google's premier open weights model designed for agentic workflows, deep logical reasoning, coding, and multi-turn discussions. The **26B** and **31B** dense variants are state-of-the-art for local development.
  - *Sizing:* Ideal for Macs with **32GB or 48GB** of unified memory.
- **Gemma 4 e2b / e4b (Lightweight / Edge):**
  - *Performance:* Breakthrough ultra-compact models. They execute at extreme speeds on normal devices and are perfect for fast, nightly triage loops, simple syntax linting, or formatting.
- **Community Coder Variants (e.g., `gemma4-e4b-claude-coder`):**
  - *Performance:* Highly optimized community models designed to serve as drop-in local coding agents specifically tailored for tools like **Claude Code**, supporting a 64K context window and native, lightning-fast local tool-calling.

### B. Alibaba's Agentic Champion: Qwen3-Coder & Qwen3-Coder-Next

Alibaba’s Qwen series remains a key heavyweight, with the third generation heavily focused on agentic executions.

- **Qwen3-Coder-Next:**
  - *Performance:* Specifically optimized for **agentic coding workflows** and local multi-agent coordination. It features advanced tooling compliance, robust state-tracking, and zero-shot planning capabilities.
- **Qwen3-Coder (30B / 480B):**
  - *Performance:* Features exceptional long-context windows and deep logical reasoning. The **30B** variant is a massive sweet spot, matching GPT-4o and Claude 3.5 Sonnet on programming benchmarks.
  - *Sizing:* The 30B model runs beautifully on **36GB or 48GB unified memory Mac** configurations under 4-bit or 5-bit quantization (`Q4_K_M` / `Q5_K_M`).

### C. The Deep-Reasoning Engine: DeepCoder (14B)

- *Performance:* An open-source 14B model that specializes in deep, multi-turn reasoning and operates at the **O3-mini level**. Perfect for highly complex bug-fixing and multi-file code integration challenges.
- *Sizing:* Easily fits on any Mac with **24GB or higher** of unified memory.

---

## 2. Workload Allocation (Cloud vs. Local)

To achieve maximum "Cognitive-to-Cost Efficiency", we establish a strict division of labor between high-cost Cloud APIs and free Local OSS models:

```
                   ┌──────────────────────────────────────┐
                   │        Incoming Task / Event         │
                   └──────────────────┬───────────────────┘
                                      │
                                      ▼
                   ┌──────────────────────────────────────┐
                   │          Complexity Triage           │
                   └──────────────────┬───────────────────┘
                                      │
            ┌─────────────────────────┴─────────────────────────┐
            ▼                                                   ▼
┌──────────────────────────────────────┐            ┌──────────────────────────────────────┐
│        High-Reasoning Workloads      │            │        Repetitive / Scoped Tasks     │
│             (Cloud APIs)             │            │             (Local OSS)              │
├──────────────────────────────────────┤            ├──────────────────────────────────────┤
│ - Backlog Triage & Research          │            │ - Code Implementation (S/M Tasks)    │
│   (Needs Gemini's 2M context)        │            │   (Qwen-2.5-Coder-32B)               │
│                                      │            │                                      │
│ - Security & Quality PR Reviews      │            │ - Unit Test Generation               │
│   (Requires maximum logical depth)   │            │   (Repetitive, high-token boilerplate)│
│                                      │            │                                      │
│ - Epic & Task Decomposition          │            │ - Static Code Analysis & Linting     │
│   (High-level systemic planning)     │            │   (Rule-based automated fixes)       │
└──────────────────────────────────────┘            └──────────────────────────────────────┘
```

---

## 3. Technical Implementation Framework

To integrate local execution seamlessly into our existing active backlog, we leverage **Ollama** as our background model gateway.

### A. Why Ollama is the Best Choice

- **Headless Background Execution:** Ollama runs as a lightweight macOS system service (`brew install ollama`), making it perfect for automated nightly cron jobs.
- **Unified OpenAI-Compatible API:** Ollama automatically exposes an OpenAI-compatible endpoint at `http://localhost:11434/v1`. This allows us to hook it directly into any tool that supports custom base URLs.
- **Metal Acceleration:** Automatically utilizes Apple's native GPU acceleration (Metal) on M-series chips out of the box with zero compilation necessary.

### B. Integrating with the Backlog Automations

#### 1. Dynamic Engine Dispatches (OpenCode & Claude Code)

Our **`DYNAMIC_TOOLING.md`** architecture can dynamically override the model flag at execution time based on task sizing:

- **With OpenCode:** Natively supports custom OpenAI-compatible endpoints. The coordinator triggers:

  ```bash
  opencode run '<prompt>' --dir <workdir> -m openai/qwen2.5-coder:32b --api-base http://localhost:11434/v1
  ```

- **With Claude Code:** While Claude Code is optimized for Anthropic's cloud, we can configure its backend via `~/.claude/settings.json` to route to a local Ollama endpoint when executing **S-sized** tasks, then swap it back for **L-sized** tasks.

#### 2. Local-First Nightly Triage & Auditing

Instead of calling expensive cloud APIs to run our nightly triage and security code audits:

- The **Security Auditor** and **Triage Engine** scripts can execute local API requests directly against Ollama using the standard Python `ollama` library:

  ```python
  import ollama

  response = ollama.chat(
      model="qwen2.5-coder:7b",
      messages=[{"role": "user", "content": "Analyze this diff for safety concerns..."}]
  )
  ```

- This keeps our nightly processing completely **free, private, and offline**.

---

## 4. Other Recommendations & Tooling Options

While **OpenCode + Ollama** is our highly recommended stack, there are a couple of additional options worth noting for future expansion:

1. **Llama.cpp (The Power-User Alternative):**
   - If you want absolute maximum control over quantization schemes (`GGUF`), context-length scaling, and raw speed, running `llama-cpp-python` as a direct library dependency is an option. However, it requires manual compilation with Metal support, making **Ollama** far superior for a friction-free setup.
2. **OrbStack (Docker & Virtualization Upgrade):**
   - On an M-series Mac, swap Docker Desktop for **OrbStack**. It is a drop-in replacement that uses native macOS kernel virtualization to run Docker containers at double the speed with near-zero CPU/RAM idle drain.
