# ⚡ Hermes ARC — Adaptive Routing Core

> **Reference implementation สำหรับ intent-aware runtime model routing บน Hermes Agent**
> ARC ตรวจว่าผู้ใช้กำลังจะทำอะไรเป็นหลัก แล้วใช้หัวข้อเป็นตัวช่วยตัดสินใจเมื่อจำเป็น

<p align="center">
  <strong>Intent-aware routing</strong> · <strong>Runtime model switching</strong> · <strong>Final-model signatures</strong> · <strong>Hermes plugin</strong>
</p>

<p align="center">
  <strong>ไทย</strong> · <a href="README.md">English</a>
</p>

---

## สรุปเร็ว

ARC คือ Hermes Agent plugin ที่ route แต่ละ turn ไปยัง specialist model ที่ผู้ใช้ config ไว้เมื่อคุ้มกว่า และปล่อยแชตทั่วไปให้อยู่กับ main model ตามเดิม

- **ปัญหา:** default model ตัวเดียวไม่ใช่ตัวเลือกที่ถูกสุดหรือเก่งสุดสำหรับทุกงาน
- **แนวทาง:** ตรวจ action/intent ก่อน แล้วใช้ subject/topic เป็นตัวช่วยตัดสินใจ
- **สถานะตอนนี้:** ใช้งานได้จริงแบบ plugin; `patch_run_agent.py` เป็น compatibility bridge ชั่วคราว
- **ทาง upstream:** หลัง NousResearch/hermes-agent#23898 merge แล้ว ARC จะถอด patch และใช้ native plugin runtime override ได้
- **ทิศทางถัดไป:** smart routing ที่ดู complexity, cost/latency, hardware awareness และ external router integration

---

## ทำไม ARC ถึงมีอยู่

Hermes ใช้ main model ตัวเดียวตอบทุกงานได้ แต่ในโลกจริงมันไม่ใช่ทางเลือกที่ดีที่สุดเสมอไป:

- คำถาม coding อาจเหมาะกับโมเดลที่แข็งด้าน coding มากกว่า
- คำถาม finance อาจเหมาะกับโมเดลด้าน business/finance มากกว่า
- งาน creative/media อาจไม่จำเป็นต้องใช้ reasoning model แพง ๆ
- แชตทั่วไปควรอยู่กับ main model โดยไม่สลับมั่ว

**Hermes ARC ทำให้ model routing เป็น plugin-level capability:**

```text
User message
  → detect action/intent first
  → use topic as tiebreaker when needed
  → choose configured model/persona
  → call Hermes with a runtime override
  → append a small routing signature
```

ARC ตั้งใจให้เล็ก ใช้งานจริง และเป็นฐานสำหรับ smart routing ในอนาคต ไม่ได้พยายามเป็น router อัจฉริยะครบทุกอย่างตั้งแต่แรก

---

## ทำอะไรได้

- **ตรวจ intent/action ก่อนหัวข้อ** ด้วย keyword, semantic หรือ hybrid routing
- **ใช้หัวข้อเป็น tiebreaker** เมื่อ action อย่างเดียวไม่พอ
- **สลับ model/provider แบบ runtime** ตาม `topic_detect.topics`
- **ใส่ persona เฉพาะหัวข้อ** จาก `AGENTS.md`
- **รองรับ fallback เฉพาะ topic แบบ optional** (`primary → topic fallback(s) → main/global fallback`)
- **รองรับ `/sd <message>`** (และคำเต็ม `/skipdetect`) เพื่อ bypass ARC classification และใช้ main model เฉพาะ turn นั้น
- **fallback ปลอดภัย** กลับ main Hermes model ถ้าหัวข้อไม่ชัดพอ
- **แสดง signature** เพื่อให้เห็นว่า turn นั้น route ไปไหน

ตัวอย่าง signature:

```text
- gemma-4-31b [software_it]
- minimax-m2.5 [business_finance]
- glm-4.5-air [entertainment_media]
- gpt-5.5 [general]
- gemini-3-flash [software_it | routed: ring-2.6-1t]
```

ภายใน ARC ยังใช้ `none` เพื่อหมายถึง “ไม่มี specialized topic ที่มั่นใจพอ” แต่ฝั่ง user-facing signature จะแสดงเป็น `[general]` เพราะเข้าใจง่ายกว่า

---

## ตัวอย่าง Routing

ตัวอย่างเหล่านี้อธิบาย behavior ไม่ใช่การ recommend model แบบตายตัว เพราะ model จริงขึ้นกับ mapping ใน `topic_detect.topics` ของผู้ใช้

```text
User: fix this failing API test
ARC:  action=technical → route=software_it
Shown suffix: - gemma-4-31b [software_it]

User: calculate ROI for this project
ARC:  action=analytical + subject=business_finance → route=business_finance
Shown suffix: - minimax-m2.5 [business_finance]

User: write a short fantasy scene
ARC:  action=creative + subject=writing_language → route=writing_language
Shown suffix: - gemma-4-31b [writing_language]

User: thanks
ARC:  no confident specialist route → main model
Shown suffix: - gpt-5.5 [general]

User: debug this server, but the routed model falls back in Hermes
ARC:  route=software_it, final responder differs from requested route model
Shown suffix: - gemini-3-flash [software_it | routed: ring-2.6-1t]

User: /sd fix this failing API test
ARC:  skip classification and routing for this turn → main model
Shown suffix: - gpt-5.5 [skip]
```

Alias ที่รองรับ: `/sd`, `!sd`, `@@sd`, `/skipdetect`, `!skipdetect`, `@@skipdetect`.

---

## ระบบ Fallback Chain

แต่ละ topic สามารถกำหนด `fallbacks` เป็น list ได้ เมื่อ model ที่ route ไปหลัก ล้มเหลว (429, 503, timeout, error) Hermes จะลอง fallback ทีละตัว **ตามลำดับ** ก่อนจะยอมกลับไปใช้ main/global model ของ agent

คู่มือ operational แบบละเอียดอยู่ที่ [`docs/FALLBACK_CHAINS.md`](docs/FALLBACK_CHAINS.md)

โครงสร้าง chain:

```text
primary model  →  topic fallback 1  →  topic fallback 2  →  ...  →  Hermes main/global model
```

**พฤติกรรมสำคัญ:**

- `fallbacks` ไม่บังคับ — topic ไหนไม่ใส่ก็ทำงานแบบเดิม
- แต่ละ fallback entry เป็น provider+model+config เต็มรูปแบบ เหมือน shape ของ topic หลัก
- Hermes จัดการ retry ภายในผ่าน `runtime_override` ไม่ต้องแก้ plugin code เมื่อเพิ่มหรือสลับลำดับ fallback
- Signature ที่ส่งกลับใช้ **model ที่ตอบจริง** จึงเห็นได้ว่า model ไหนจัดการ request นั้น

ตัวอย่าง signature เมื่อ fallback ทำงาน:

```text
gemini-3-flash [software_it | routed: ring-2.6-1t]
```

หมายความว่า ARC route ไป `software_it` แต่ model ที่ตอบจริงหลัง fallback คือ `gemini-3-flash`

ตัวอย่าง config:

```yaml
topic_detect:
  topics:
    software_it:
      provider: openrouter
      model: inclusionai/ring-2.6-1t:free
      fallbacks:
        - provider: openrouter
          model: baidu/cobuddy:free
        - provider: openrouter
          model: deepseek/deepseek-v4-flash:free
```

Fallback chain แนะนำตามหัวข้อ (ปรับตามงบและ latency ที่ต้องการ):

| Topic             | Primary                   | Fallback 1                | Fallback 2             |
|-------------------|---------------------------|---------------------------|------------------------|
| `software_it`     | ring-2.6-1t               | cobuddy:free              | deepseek-v4-flash → owl-alpha |
| `math`            | deepseek-v4-flash         | owl-alpha                 | ring-2.6-1t            |
| `science`         | deepseek-v4-flash         | owl-alpha                 | ring-2.6-1t            |
| `business_finance`| deepseek-v4-flash         | owl-alpha                 | ring-2.6-1t            |
| `legal_government`| owl-alpha                 | deepseek-v4-flash         | main/global            |
| `medicine_healthcare`| deepseek-v4-flash      | owl-alpha                 | ring-2.6-1t            |
| `writing_language`| owl-alpha                | step-3.5-flash            | main/global            |
| `entertainment_media`| step-3.5-flash          | owl-alpha                 | main/global            |

---

## ความสัมพันธ์กับ Hermes Core

ตอนนี้ ARC ทำงานเป็น Hermes plugin และอาจต้องใช้ compatibility patch ใน Hermes version ที่ `pre_llm_call` ยัง apply runtime override ไม่ได้

งาน upstream ที่เกี่ยวข้อง:

- Smart routing discussion: https://github.com/NousResearch/hermes-agent/issues/21827
- Core primitive proposal: https://github.com/NousResearch/hermes-agent/issues/23739
- Native plugin runtime override PR: https://github.com/NousResearch/hermes-agent/pull/23898

จนกว่า Hermes core จะมี native runtime override, ARC ยัง ship `patch_run_agent.py` เป็น compatibility bridge อยู่ หลัง upstream PR #23898 merge และออกมากับ Hermes release แล้ว ARC v2.x จะถอด dependency นี้ออกและใช้ native plugin hook โดยตรง

Architecture เป้าหมาย:

```text
Hermes core pre_llm_call runtime override
  → router plugins/providers
  → topic routing, complexity routing, Manifest-style smart routing
```

---

## ติดตั้งเร็ว

```bash
curl -fsSL https://raw.githubusercontent.com/ShockShoot/hermes-arc/main/install.sh | bash
```

คำสั่งเดียวกันนี้ใช้เป็นคำสั่ง update/repatch หลัง `hermes update` ได้เลย: installer จะโหลด ARC ล่าสุด เติม config และ auto-patch runtime เมื่อเจอ Hermes `run_agent.py` เพียงตัวเดียว ถ้ามีหลาย runtime และ installer ต่ออยู่กับ terminal จะมีเมนูให้เลือกด้วยปุ่มลูกศร ↑/↓ แล้วกด Enter ถ้าเป็น shell แบบ non-interactive ให้ใส่ `--run-agent-path /path/to/run_agent.py` เพื่อเลือกให้ชัดเจน

เช็ค update โดยยังไม่ติดตั้ง:

```bash
curl -fsSL https://raw.githubusercontent.com/ShockShoot/hermes-arc/main/install.sh | bash -s -- --check
```

อัปเดตแบบ explicit:

```bash
curl -fsSL https://raw.githubusercontent.com/ShockShoot/hermes-arc/main/install.sh | bash -s -- --update
```

หลังติดตั้ง ใส่ provider key เช่น OpenRouter:

```bash
echo 'OPENROUTER_API_KEY=<your-key>' >> ~/.hermes/.env
hermes gateway restart
```

---

## Config แนะนำ

เพิ่มหรืออัปเดต section นี้ใน `~/.hermes/config.yaml`:

```yaml
plugins:
  enabled:
    - topic_detect

topic_detect:
  enabled: true
  routing_mode: hybrid
  inertia: 2
  min_confidence: 0.45
  agents_file: ~/.hermes/plugins/topic_detect/AGENTS.md
  semantic:
    enabled: true
    provider: openrouter
    model: baidu/cobuddy:free
    min_confidence: 0.7
    base_url: https://openrouter.ai/api/v1
    api_key: ${OPENROUTER_API_KEY}
  signature:
    enabled: true
  update_check:
    enabled: true
    url: https://raw.githubusercontent.com/ShockShoot/hermes-arc/main/plugin.yaml
    timeout_seconds: 2.5
  topics:
    software_it:
      provider: openrouter
      model: google/gemma-4-31b:free
      base_url: https://openrouter.ai/api/v1
      api_key: ${OPENROUTER_API_KEY}
      fallbacks:
        - provider: openrouter
          model: baidu/cobuddy:free
          base_url: https://openrouter.ai/api/v1
          api_key: ${OPENROUTER_API_KEY}
    math:
      provider: openrouter
      model: google/gemma-4-31b:free
      base_url: https://openrouter.ai/api/v1
      api_key: ${OPENROUTER_API_KEY}
    science:
      provider: openrouter
      model: google/gemma-4-31b:free
      base_url: https://openrouter.ai/api/v1
      api_key: ${OPENROUTER_API_KEY}
    business_finance:
      provider: openrouter
      model: minimax/minimax-m2.5:free
      base_url: https://openrouter.ai/api/v1
      api_key: ${OPENROUTER_API_KEY}
    legal_government:
      provider: openrouter
      model: minimax/minimax-m2.5:free
      base_url: https://openrouter.ai/api/v1
      api_key: ${OPENROUTER_API_KEY}
    medicine_healthcare:
      provider: openrouter
      model: minimax/minimax-m2.5:free
      base_url: https://openrouter.ai/api/v1
      api_key: ${OPENROUTER_API_KEY}
    writing_language:
      provider: openrouter
      model: google/gemma-4-31b:free
      base_url: https://openrouter.ai/api/v1
      api_key: ${OPENROUTER_API_KEY}
    entertainment_media:
      provider: openrouter
      model: z-ai/glm-4.5-air:free
      base_url: https://openrouter.ai/api/v1
      api_key: ${OPENROUTER_API_KEY}
```

นี่เป็นแค่ตัวอย่าง default ที่ใช้งานได้จริง ARC **ไม่ดึงคะแนน Arena และไม่เลือกโมเดลให้อัตโนมัติ** ผู้ใช้ยังเป็นคนกำหนด mapping เอง

แต่ละ topic ใส่ `fallbacks` ได้แบบ optional ถ้า routed model ล่ม Hermes จะลอง fallback เหล่านี้ก่อนค่อยกลับไป global fallback/main runtime:

```yaml
topic_detect:
  topics:
    software_it:
      provider: openrouter
      model: inclusionai/ring-2.6-1t:free
      fallbacks:
        - provider: openrouter
          model: baidu/cobuddy:free
        - provider: openrouter
          model: deepseek/deepseek-v4-flash:free
```

---

## Topics ที่รองรับ

ARC ใช้ primary topic taxonomy ที่ align กับ Arena:

| Topic | ใช้กับอะไร |
|---|---|
| `software_it` | programming, debugging, infra, software/IT systems |
| `math` | calculation, proofs, symbolic reasoning, quantitative problems |
| `science` | science explanation, mechanisms, research-style questions |
| `business_finance` | markets, finance, accounting, business operations, strategy |
| `legal_government` | legal, policy, compliance, public-sector questions |
| `medicine_healthcare` | medical/healthcare information และคำตอบที่ระวัง safety |
| `writing_language` | writing, editing, translation, literature, language nuance |
| `entertainment_media` | movies, games, sports, media analysis, pop culture |

หมวด Arena เช่น Expert, Hard Prompts, Instruction Following, Multi-Turn, Longer Query และ language-specific boards ถือเป็น future metadata/modifier ไม่ใช่ primary route ใน version นี้

---

## Routing Modes

| Mode | พฤติกรรม |
|---|---|
| `keyword` | deterministic keyword matching เร็วที่สุด |
| `semantic` | ใช้ LLM classification |
| `hybrid` | แนะนำ: keyword ก่อน semantic fallback |

ค่าที่ควรรู้:

- `min_confidence`: เพิ่มเพื่อลดการ route พลาด, ลดเพื่อ route ให้ aggressive ขึ้น
- `inertia`: เพิ่มเพื่อลดการสลับหัวข้อถี่ใน multi-turn conversation
- `semantic.min_confidence`: confidence ขั้นต่ำของ semantic classifier

---

## ตรวจสอบ

```bash
hermes plugins list | grep topic_detect
hermes logs | grep topic_detect
```

ตัวอย่าง log:

```text
topic_detect: loaded
topic_detect: switching provider=openrouter model=google/gemma-4-31b:free
topic_detect: signature=- gemma-4-31b [software_it]
```

---

## Development

ไฟล์ runtime plugin ตั้งใจให้ import/run ได้แบบไม่ต้อง package install แต่ test ต้องมี dependency เล็กน้อย:

```bash
python -m pip install -r requirements-test.txt
python -m compileall . -q
python tests/test_v2_classifier.py
python tests/test_signature_finalize.py
python tests/test_fallback_config.py
python tests/test_skipdetect.py
```

ตอนนี้ `requirements-test.txt` มี `PyYAML` เพราะ config loader ของ plugin import `yaml`

---

## Signature ใช้จากตัวไหน

path ปัจจุบันเมื่อ Hermes core ถูก patch ถูกต้องคือ:

```text
runtime_override._arc_signature
  → transform_llm_output(_arc_finalize=...)
  → signature.build_final_signature(...)
```

ดังนั้น signature ที่ user เห็นจะใช้ model ที่ตอบจริงหลัง fallback แล้ว ไม่ใช่แค่ model ที่ ARC route ไปตอนแรก ส่วน `runtime_override.response_suffix` ยังเก็บไว้เป็น compatibility fallback สำหรับ core patch รุ่นเก่า

รายละเอียดอยู่ใน [`docs/SIGNATURE_FLOW.md`](docs/SIGNATURE_FLOW.md)

---

## โครง repo

ไฟล์ runtime plugin ยังตั้งใจวาง flat ที่ root เพราะ installer แบบ one-line download raw files เข้า `~/.hermes/plugins/topic_detect` โดยตรง

- `tests/` — smoke tests ของ classifier และ signature
- `docs/` — design/operation notes
- `.github/workflows/` — CI smoke checks

รายละเอียดอยู่ใน [`docs/REPO_LAYOUT.md`](docs/REPO_LAYOUT.md)

Design notes เพิ่มเติม:

- [`docs/SIGNATURE_FLOW.md`](docs/SIGNATURE_FLOW.md) — flow ของ final-model-aware signatures
- [`docs/FALLBACK_CHAINS.md`](docs/FALLBACK_CHAINS.md) — วิธี config และอ่านผล topic-scoped fallback chains
- [`docs/V2_REWRITE_PLAN.md`](docs/V2_REWRITE_PLAN.md) — แผน rewrite v2 แบบ action-first routing
- [`docs/V3_SMART_ROUTER.md`](docs/V3_SMART_ROUTER.md) — ทิศทาง smart-router ในอนาคต

---

## แก้ปัญหา

| ปัญหา | วิธีแก้ |
|---|---|
| Plugin ไม่โหลด | เช็ค `plugins.enabled` มี `topic_detect` แล้ว restart Hermes |
| หัวข้อไม่สลับ | ลด `min_confidence` หรือใช้ `routing_mode: semantic` |
| สลับบ่อยเกินไป | เพิ่ม `inertia` เป็น `3` หรือ `4` |
| prompt ทั่วไปถูก route ผิด | เพิ่ม `min_confidence`; prompt ไม่ชัดควรเป็น internal `none` / display `[general]` |
| model/provider ไม่สลับ | รัน `python3 ~/.hermes/plugins/topic_detect/patch_run_agent.py --check` แล้ว apply compatibility patch ถ้าจำเป็น |
| persona ไม่ถูกใส่ | เหมือนด้านบน; Hermes core รุ่นเก่าต้องรองรับ runtime system-prompt override |

---

## Roadmap

- **v1:** Topic-aware runtime model routing
- **v2:** Intent/action-first routing พร้อม technical override และ final-model-aware signatures
- **v2.x:** ถอด dependency ของ `patch_run_agent.py` หลัง upstream PR #23898 merge native plugin runtime override support
- **v3:** Smart-router พร้อม complexity scoring, cost/latency policy และ external router integration

---

## Design Principles

- **Configurable, not magical.** ผู้ใช้เลือก model mapping เอง
- **Main model is the safe fallback.** ไม่มั่นใจหัวข้อ → ไม่ override
- **Transparent but quiet.** มี signature เล็ก ๆ ไม่รก chat
- **Plugin first, core-friendly later.** ARC พิสูจน์ behavior วันนี้ และ align กับ Hermes core hook ที่สะอาดกว่าในอนาคต

---

## License

MIT
