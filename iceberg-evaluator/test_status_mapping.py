#!/usr/bin/env python3
"""测试冰山上状态映射逻辑"""

STATUS_MAPPING = {
    "met": "evidenced",
    "matched": "evidenced",
    "satisfied": "evidenced",
    "fulfilled": "evidenced",
    "partial": "partially_evidenced",
    "partially_matched": "partially_evidenced",
    "partially_met": "partially_evidenced",
    "not_met": "not_evidenced",
    "not_evidenced": "not_evidenced",
    "missing": "not_evidenced",
    "not_configured": "not_configured",
}

def test_mapping():
    test_cases = [
        ("met", "evidenced"),
        ("matched", "evidenced"),
        ("satisfied", "evidenced"),
        ("fulfilled", "evidenced"),
        ("partial", "partially_evidenced"),
        ("partially_matched", "partially_evidenced"),
        ("partially_met", "partially_evidenced"),
        ("not_met", "not_evidenced"),
        ("not_evidenced", "not_evidenced"),
        ("missing", "not_evidenced"),
        ("not_configured", "not_configured"),
        ("unknown_value", "not_evidenced"),  # 未知值默认映射为 not_evidenced
    ]
    
    print("测试冰山上状态映射逻辑：\n")
    all_passed = True
    
    for raw, expected in test_cases:
        result = STATUS_MAPPING.get(raw, "not_evidenced")
        status = "[OK]" if result == expected else "[FAIL]"
        if result != expected:
            all_passed = False
        print(f"{status} {raw:20s} -> {result:20s} (期望：{expected})")
    
    print(f"\n{'所有测试通过！' if all_passed else '有测试失败！'}")
    return all_passed

if __name__ == "__main__":
    test_mapping()
