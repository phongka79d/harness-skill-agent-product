# Đánh giá bộ Phongka Agentic Engineering Skills v3.4.0

Ngày đánh giá: 2026-08-07  
Phạm vi: toàn bộ thư mục skills/ trong workspace này.

## Kết luận ngắn

Bộ skill có nền tảng tốt và có kỷ luật workflow rõ: một Primary Agent duy nhất, role read-only/source-editing tách biệt, route trung tâm, review trước verify, hash workspace và approval gate. Điểm tổng thể: **7,4/10**.

Kết luận vận hành: **đủ tốt để dùng như policy package cho một host đáng tin cậy; chưa đủ kín để xem là runtime tự-enforce khi caller/host không đáng tin hoặc state bị hỏng**.

Năm vấn đề cần ưu tiên là: decision tự ký hash vẫn được nhận, state optional tạo runtime actions mâu thuẫn, recovery bỏ sót state invariant, task ID khác hoa/thường làm hỏng index trên Windows, và acceptance ID toàn khoảng trắng vẫn được chấp nhận.

## Phạm vi và phương pháp

Đã kiểm kê và đọc các thành phần dưới skills/:

| Hạng mục | Số lượng |
|---|---:|
| Skill directory | 13 |
| SKILL.md | 13 |
| Tổng file | 154 |
| Markdown | 69 |
| Python | 32 |
| JSON | 40 |
| YAML | 13 |
| Tổng dung lượng | 364.258 bytes |
| Tổng số dòng | 10.012 |

Phạm vi đọc gồm README, architecture, changelog, migration, mọi SKILL.md, prompt, reference, config, profile, schema, example và script. Không có .git ở root hoặc các thư mục con; vì vậy không thể dùng git status/diff. Việc kiểm tra thay đổi được thực hiện bằng snapshot filesystem.

Delegation: không có sub-agent API được cung cấp trong workspace; Primary Agent thực hiện việc đọc, mô phỏng và đánh giá trực tiếp, không giả định đã spawn model.

## Kết quả validation hiện tại

Tất cả lệnh validation được README công bố đều chạy thành công:

| Lệnh | Kết quả |
|---|---|
| load_config.py --check | CONFIG_VALID |
| validate_skill_layout.py | VALID, 13 skills, 9 model agents |
| run_exams.py | PASSED, 13 cases, 294 matrix cases |
| run_workflow_smoke.py | PASSED, 14 route cases, 3 runtime cases |
| run_contract_tests.py | PASSED, 13 adversarial cases |
| validate_markdown_links.py | MARKDOWN_LINKS_VALID |
| validate_examples.py | VALID, 11 examples |
| python -m compileall -q skills | exit code 0 |

Các kết quả trên chứng minh package hợp lệ theo các contract đã được viết. Chúng không chứng minh mọi policy boundary đều được enforce ở runtime.

## Chấm điểm

| Tiêu chí | Điểm | Nhận xét |
|---|---:|---|
| Kiến trúc và phân vai | 8,5 | Primary Agent, role boundaries, fresh context và writer sequencing rõ |
| Routing và thứ tự gate | 8,0 | Route matrix tốt, debug-before-edit và review-before-verify được kiểm tra |
| State và evidence integrity | 7,0 | Workspace hash, revision và claim mapping mạnh; còn lỗi trust/recovery/index |
| Safety và security | 6,5 | Path containment và approval tốt; context/secrets/package boundary còn host-only |
| Test và observability | 7,0 | Có validator, smoke và adversarial tests; thiếu các case đã tái hiện |
| Documentation và portability | 7,5 | Tài liệu có cấu trúc và migration tốt; một số claim coverage lệch implementation |
| **Tổng thể** | **7,4** | Tốt cho host tin cậy, chưa phải closed-loop enforcement |

## Điểm mạnh đáng giữ

1. **Một orchestrator và role boundary rõ.** agentic-engineering-core giữ quyền phân loại intent, lập scope, approval, scheduling, tích hợp và final reporting. Các role explorer, planner, reviewer, verifier và recovery đều read-only theo contract.
2. **Routing tập trung và có thứ tự gate.** agentic-config.json là source of truth; resolver bảo vệ source-editing route, debug trước edit, verify sau edit, controlled review và delivery ordering.
3. **Evidence stateful có tính liên kết tốt.** work_revision, workflow_decision_hash, snapshot file/size/SHA-256, completion claim và completion gate tạo một chuỗi kiểm chứng mạnh; delivery còn recheck claim hash.
4. **Path và task-scope safety tốt.** Traversal, absolute path, .phongka, .agent, duplicate normalized workspace path và shared-file dependency đều đã có kiểm tra.
5. **Không giả vờ thực hiện side effect.** Delivery finalizer chỉ ghi decision; merge, push, deploy và cleanup vẫn thuộc host được cấp quyền. Recovery cũng có nguyên tắc không blind retry.

## Findings ưu tiên cao

### F-01 — Runtime tin decision tự ký hash, không xác thực nguồn policy

**Mức độ: P1 / High.**

init_runtime.py:28 chỉ validate decision theo schema, kiểm tra decision_hash bằng cách hash lại chính payload, rồi lưu các field policy vào state. Nó không load central config, không re-resolve request và không xác nhận profile/risk/evidence/stage của decision khớp policy hiện hành.

Probe đã tái hiện: một decision hợp lệ cho security_sensitive yêu cầu user approval; sau khi đổi approval.required thành false, đổi kind/key, rồi tính lại hash, init_runtime.py vẫn trả exit code 0 và tạo runtime.

**Tác động:** caller có quyền ghi decision file có thể downgrade approval hoặc evidence gate mà vẫn tạo state hợp lệ về mặt schema. Hash ở đây chỉ là content-integrity binding, không phải authenticity.

**Sửa đề xuất:** chỉ nhận decision do resolver tạo hoặc thêm bước re-resolve/semantic validation với config hiện tại; lưu thêm config/profile hash. Tách legacy initialization thành compatibility mode có cảnh báo và không cho bypass approval-gated route. Thêm contract test cho decision downgrade.

### F-02 — state_mode: optional mâu thuẫn với runtime_actions

**Mức độ: P1 / High.**

Với personal + feature + standard, resolver trả:

```text
state_mode: optional
optional_skills: [agentic-state-tools]
runtime_actions.before: [init_runtime, open_task]
runtime_actions.after: [record_verification_evidence, mark_task_completed,
                        verify_completion_claim, validate_state]
stages: route, plan, implement, verify, report
```

Nguồn là resolve_workflow.py:454-468 và _runtime_actions tại :275. Decision vừa nói state là optional, vừa phát ra hành động bắt buộc cần state, trong khi stages không có state_init/state_finalize.

**Tác động:** host có thể tạo state ngoài ý muốn, hoặc làm theo required_skills và bỏ qua runtime actions; hai cách đều không có contract rõ ràng.

**Sửa đề xuất:** resolve thành hai mode rõ ràng (off hoặc required), hoặc thêm state_execution: use|skip do host chọn và phát runtime actions tương ứng. Bổ sung exam cho mọi route có standard_state: optional.

### F-03 — Recovery có thể báo CLEAN khi runtime invariant bị hỏng

**Mức độ: P1 / High.**

inspect_recovery.py:27-53 chỉ kiểm tra schema, task-index và đọc task được active_task_id trỏ tới. Nó không kiểm tra quan hệ state.status ↔ active_task_id ↔ trạng thái task như validate_state.py.

Probe đã tái hiện: state có task COMPLETED, active_task_id: TASK-1, nhưng status: IDLE; recovery trả status: CLEAN, next_action: NO_ACTION thay vì yêu cầu reconcile.

**Tác động:** recovery có thể bỏ qua runtime corruption và cho workflow tiếp tục với state không nhất quán.

**Sửa đề xuất:** dùng một hàm invariant chung cho validate_state.py, inspect_recovery.py, dashboard và delivery; mọi mismatch phải thành RECOVERY_REQUIRED, không phải CLEAN.

### F-04 — Task ID không chống collision hoa/thường trên Windows

**Mức độ: P1 / High trong môi trường Windows.**

runtime_utils.py:70-80 cho phép cả Task và task, rồi map trực tiếp sang <task_id>.json. update_task_state.py:93-104 cũng không xác nhận previous.task_id khớp với ID đang cập nhật.

Probe trên filesystem Windows đã tạo thành công hai entry index Task và task nhưng chỉ có một file Task.json; lệnh update trả exit code 0, còn validate_state.py chỉ phát hiện lỗi ở bước sau (missing task files: task).

**Tác động:** dữ liệu task có thể bị ghi đè và command báo thành công trước khi corruption được phát hiện.

**Sửa đề xuất:** canonicalize task ID bằng casefold() hoặc cấm ID collision theo filesystem; kiểm tra previous.task_id == task_id; post-write validate index và rollback nếu state/index không nhất quán.

### F-05 — Acceptance/check ID toàn khoảng trắng vẫn được chấp nhận

**Mức độ: P2 / Medium.**

Schema chỉ yêu cầu minLength: 1. Code tại record_verification_evidence.py:68-71 và verify_completion_claim.py:35-50 strip ID nhưng chỉ kiểm tra uniqueness, không kiểm tra chuỗi sau strip có rỗng.

Probe đã ghi verification check với name: " ", claim với id: " ", và verify_completion_claim.py trả accepted: true.

**Tác động:** stable acceptance mapping có thể chứa ID vô nghĩa, làm giảm khả năng truy vết và tạo completion gate giả hình thức.

**Sửa đề xuất:** reject ID sau khi trim nếu rỗng; canonicalize ID trước schema validation; thêm test duplicate/blank/whitespace-only.

## Gaps cấp hệ thống

### G-01 — Context budget, dispatch budget và repair stop chưa được machine-enforce

agentic-config.json khai báo max_parallel_read_only, context_budget.max_bytes và allow_unbounded_scan tại :236, :258-259. Decision chỉ mang max_context_files; policy enforcement ghi rõ context byte limit, role invocation, repair-cycle stopping và redaction là host-enforced.

Điều này là boundary thiết kế hợp lệ nếu host đáng tin, nhưng có nghĩa package không tự chứng minh rằng host đã đọc dưới byte budget, không vượt dispatch ceiling, không vượt repair rounds và không gửi secret vào prompt. synthesized_fallback: true cũng chỉ là cờ policy, chưa phải giao thức fallback có log/owner/exit condition.

**Khuyến nghị:** đưa byte budget và scan policy vào decision; thêm dispatch/repair ledger hoặc wrapper API; ghi rõ fallback khi model fail lặp lại: retry giới hạn, Primary takeover, hoặc BLOCKED kèm evidence.

### G-02 — Security flags không tạo ra redaction thực tế

Config đặt redact_environment_values, redact_tokens, forbid_secret_persistence là true, nhưng artifact writers nhận và ghi summary, notes, findings, evidence và approval reference mà không có sanitizer. policy-enforcement.md:29-38 xác nhận đây là host boundary.

**Khuyến nghị:** thêm pre-persist secret scanner/redactor tối thiểu cho artifact nhạy cảm, hoặc đổi tên policy thành host_must_enforce và bắt host cung cấp evidence đã redacted trước khi persist.

### G-03 — Packaging chưa kiểm tra symlink và chưa chạy preflight

package_skill.py:26-49 dùng root.rglob("*") và path.is_file() nhưng không loại symlink. archive.write() có thể follow symlink tới file ngoài package. Script cũng package trực tiếp mà không gọi layout, link, example, compile hay config validator.

**Khuyến nghị:** reject symlink/reparse point và kiểm tra path.resolve() luôn nằm trong root; chạy package preflight trước khi tạo archive; tạo test symlink trên nền tảng hỗ trợ symlink.

### G-04 — Test coverage và changelog không khớp

CHANGELOG.md:14 nêu “10,094-request route matrix”, nhưng runner hiện chỉ tạo 7 profiles × 14 routes × 3 preferences = 294 matrix cases; run_exams.py:76-125 không có nguồn dữ liệu 10.094 request. Các probes F-01 đến F-05 cũng đều nằm ngoài 13 contract tests hiện tại.

**Khuyến nghị:** hoặc khôi phục matrix 10.094 thật sự, hoặc sửa changelog; bổ sung contract tests cho decision authenticity, optional state, recovery invariant, case collision và blank IDs.

### G-05 — Schema validator là subset và không cảnh báo keyword bị bỏ qua

schema_validation.py chỉ triển khai một subset nhỏ của JSON Schema. Hiện các schema đang dùng chủ yếu nằm trong subset đó, nên validation hiện tại pass là hợp lệ; nhưng nếu contributor thêm oneOf, allOf, format, const hoặc keyword tương đương, validator sẽ bỏ qua mà không báo.

**Khuyến nghị:** thêm check từ chối keyword ngoài subset hoặc dùng thư viện JSON Schema chuẩn trong CI; ít nhất phải có test bảo vệ phạm vi schema được hỗ trợ.

## Lỗi/gaps workflow cần lưu ý

| Flow | Trạng thái | Vấn đề |
|---|---|---|
| Focused source edit | Tốt | implement → verify, nhưng evidence chủ yếu do host giữ, không có state gate |
| Standard source edit | Cần sửa | state_mode optional nhưng runtime actions giống stateful bắt buộc |
| Controlled source edit | Tốt | Plan review, task review, verify và state finalize đúng thứ tự |
| Debug | Tốt | Debug trước implement; không lặp Explorer thừa |
| Read-only research | Chấp nhận được | Không có verification artifact ở focused; completion traceability phụ thuộc host |
| Plan/brainstorm/review | Chấp nhận được | Không có completion gate machine-level; cần host giữ decision handoff |
| Recovery | Cần sửa | Không gọi invariant validation đầy đủ, có thể bỏ sót corruption |
| Standalone delivery | Tốt | Rebind idle, không mở task mới; evidence được recheck |
| External delivery | Boundary rõ | Finalizer chỉ record; host phải reconcile side effect thật |

## Thứ tự sửa đề xuất

1. Sửa F-01 đến F-04: decision authenticity, state mode, recovery invariant và task ID collision.
2. Sửa F-05 và bổ sung validation cho mọi identifier sau normalization.
3. Đưa context/dispatch/repair limits và fallback protocol thành contract có dữ liệu/evidence rõ trong decision hoặc host adapter.
4. Harden packaging và secret persistence boundary.
5. Bổ sung các adversarial tests còn thiếu, rồi cập nhật changelog/coverage claim.

## Verdict cuối

Đây là một package workflow có chất lượng khá cao ở phần kiến trúc và evidence model. Các lỗi tìm được không phủ nhận nền tảng đó, nhưng chúng cho thấy một nguyên tắc quan trọng: **schema-valid và hash-valid chưa đồng nghĩa policy-valid, recovery-safe hoặc portable-safe**.

Sau khi xử lý F-01 đến F-04 và biến các host-enforced boundary thành contract có evidence, bộ này có thể nâng lên khoảng 8,5/10 và đáng tin hơn cho controlled/production workflow.

