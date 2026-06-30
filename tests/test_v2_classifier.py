from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from classifier import classify  # noqa: E402

CASES = [
    ("แก้พอร์ตในเว็บอ่านนิยาย", {"software_it"}),
    ("เปลี่ยน model ใน config finance", {"software_it"}),
    ("debug api ของระบบ healthcare", {"software_it"}),
    ("fix error ใน legal document parser", {"software_it"}),
    ("รัน server สำหรับเว็บข่าว", {"software_it"}),
    ("เขียน script ดึงข้อมูล finance", {"software_it"}),
    ("เขียนนิยาย fantasy", {"writing_language"}),
    ("แต่งบทความเกี่ยวกับ finance", {"writing_language"}),
    ("draft contract สำหรับ startup", {"legal_government"}),
    ("เขียน report ผลประกอบการ", {"business_finance"}),
    ("คำนวณ ROI ของ project", {"math", "business_finance"}),
    ("อธิบาย black hole", {"science"}),
    ("วิเคราะห์ contract clause นี้", {"legal_government"}),
    ("อธิบายอาการ side effect ของยานี้", {"medicine_healthcare"}),
    ("commit และ push ได้เลย", {"none"}),
    ("โอเคครับ", {"none"}),
    ("ขอบคุณ", {"none"}),
]


def main() -> None:
    failures = []
    for text, expected in CASES:
        result = classify([text])
        ok = result.topic in expected
        print(
            f"{'PASS' if ok else 'FAIL'} | {text!r} -> {result.topic} "
            f"conf={result.confidence:.2f} action={result.action_detected}:{result.action_score:.2f} "
            f"subject={result.subject_detected} reason={result.final_route_reason}"
        )
        if not ok:
            failures.append((text, expected, result))
    if failures:
        raise SystemExit(f"{len(failures)} failures")


def test_v2_classifier_cases() -> None:
    main()


if __name__ == "__main__":
    main()
