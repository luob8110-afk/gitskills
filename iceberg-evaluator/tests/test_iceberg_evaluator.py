#!/usr/bin/env python3
"""iceberg-evaluator 离线自动化测试（unittest，不访问网络、不调用真实模型）。

运行：
    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import iceberg_evaluator as ice  # noqa: E402


RESUME = "候选人具有三年运营经验，主导跨部门协作，将报表错误率降低30%，并持续追踪问题直至闭环。"
ANSWER_Q1 = "在一次资源受限的项目中，我主动承担了协调工作，并持续追踪问题直到闭环。"
ANSWER_Q2 = "在另一个跨团队项目中，我主导了流程优化，将交付周期缩短了20%。"
QA = [{"question_id": "Q1", "question": "请描述一次协作经历。", "answer": ANSWER_Q1}]
QA2 = [
    {"question_id": "Q1", "question": "请描述一次协作经历。", "answer": ANSWER_Q1},
    {"question_id": "Q2", "question": "请描述一次流程优化经历。", "answer": ANSWER_Q2},
]


def make_benchmark(status: str = "confirmed") -> dict:
    return {
        "model_version": "MGT-ICEBERG-TEST",
        "benchmark_status": status,
        "scope": "测试适用范围",
        "success_definition": {"observation_months": 18, "sample_note": "测试样本"},
        "success_sample_basis": "12 名测试样本",
        "above_water_indicators": [
            {"indicator": "岗位相关经历", "priority": "must", "observable_evidence": ["简历事实"], "note": ""},
            {"indicator": "协作推进经历", "priority": "preferred", "observable_evidence": ["简历事实"], "note": ""},
        ],
        "dimensions": {
            "motivation": {"definition": "d", "behavioral_anchors": ["主动承担具有挑战的工作"], "benchmark_score": 80},
            "trait": {"definition": "d", "behavioral_anchors": ["在变化中保持任务拆解"], "benchmark_score": 78},
            "self_concept": {"definition": "d", "behavioral_anchors": ["能基于反馈反思并改进"], "benchmark_score": 75},
            "values": {"definition": "d", "behavioral_anchors": ["在速度与质量冲突时透明呈报"], "benchmark_score": 82},
        },
        "weights": {"motivation": 0.3, "trait": 0.25, "self_concept": 0.2, "values": 0.25},
    }


def make_interview(candidate_name: str = "CAND-01", position: str = "运营管培生", qa=None) -> dict:
    return {"candidate_name": candidate_name, "position": position, "interview_qa": qa if qa is not None else []}


def ev(source: str, excerpt: str, claim: str = "c", strength: str = "strong", polarity: str = "supportive") -> dict:
    return {"source": source, "excerpt": excerpt, "claim": claim, "strength": strength, "polarity": polarity}


def make_dim(score=80, evidence=None, counter_evidence=None, coverage=70, validation_questions=None) -> dict:
    return {
        "score": score,
        "signals": ["s"],
        "evidence": evidence if evidence is not None else [],
        "counter_evidence": counter_evidence if counter_evidence is not None else [],
        "evidence_coverage": coverage,
        "confidence": "medium",
        "benchmark_gap": "差距说明",
        "validation_questions": validation_questions if validation_questions is not None else ["请描述一次相关工作经历。"],
    }


def make_full_llm_output() -> dict:
    return {
        "above_water_summary": [
            {"indicator": "岗位相关经历", "priority": "must", "status": "evidenced",
             "evidence": [ev("简历", "三年运营经验")], "caveat": ""},
            {"indicator": "协作推进经历", "priority": "preferred", "status": "evidenced",
             "evidence": [ev("简历", "主导跨部门协作")], "caveat": ""},
        ],
        "iceberg_scores": {
            "motivation": make_dim(82, [ev("简历", "主导跨部门协作")]),
            "trait": make_dim(80, [ev("简历", "降低30%")]),
            "self_concept": make_dim(78, [ev("简历", "三年运营经验")]),
            "values": make_dim(84, [ev("简历", "持续追踪问题直至闭环")]),
        },
        "key_strengths": ["协作推进能力强"],
        "risk_flags": ["关键证据不足"],
        "llm_report": "匹配点较多，建议补证。",
        "analysis_limitations": ["样本有限"],
    }


# =========================== 原有 P0 测试 =========================== #
class TestInputContract(unittest.TestCase):
    def test_valid_complete_input(self):
        ice.validate_interview(make_interview(qa=QA))
        ice.validate_benchmark(make_benchmark())

    def test_empty_qa_legal_downgrade(self):
        ice.validate_interview(make_interview(qa=[]))

    def test_empty_candidate_name_or_position(self):
        with self.assertRaises(ValueError):
            ice.validate_interview(make_interview(candidate_name="  "))
        with self.assertRaises(ValueError):
            ice.validate_interview(make_interview(position=""))

    def test_empty_question_id(self):
        bad = make_interview(qa=[{"question_id": "", "question": "问", "answer": "答"}])
        with self.assertRaises(ValueError):
            ice.validate_interview(bad)

    def test_duplicate_question_id(self):
        bad = make_interview(qa=[
            {"question_id": "Q1", "question": "问1", "answer": "答1"},
            {"question_id": "Q1", "question": "问2", "answer": "答2"},
        ])
        with self.assertRaises(ValueError):
            ice.validate_interview(bad)

    def test_benchmark_missing_above_water(self):
        b = make_benchmark()
        del b["above_water_indicators"]
        with self.assertRaises(ValueError):
            ice.validate_benchmark(b)

    def test_benchmark_duplicate_indicator(self):
        b = make_benchmark()
        b["above_water_indicators"].append(dict(b["above_water_indicators"][0]))
        with self.assertRaises(ValueError):
            ice.validate_benchmark(b)

    def test_benchmark_bad_weights(self):
        for bad in (-0.1, float("nan"), float("inf")):
            b = make_benchmark()
            b["weights"]["motivation"] = bad
            with self.assertRaises(ValueError):
                ice.validate_benchmark(b)
        b = make_benchmark()
        b["weights"] = {"motivation": 0, "trait": 0, "self_concept": 0, "values": 0}
        with self.assertRaises(ValueError):
            ice.validate_benchmark(b)


class TestEvidenceGrounding(unittest.TestCase):
    def _index(self):
        return ice.build_source_index(RESUME, make_interview(qa=QA))

    def test_evidence_source_not_exist(self):
        issues = []
        valid = ice.validate_evidence_grounding([ev("不存在的来源", "三年运营经验")], self._index(), "supportive", "motivation", issues)
        self.assertEqual(valid, [])
        self.assertTrue(any("来源不存在" in i["reason"] for i in issues))

    def test_evidence_excerpt_not_in_source(self):
        issues = []
        valid = ice.validate_evidence_grounding([ev("简历", "这段文字不在简历里")], self._index(), "supportive", "motivation", issues)
        self.assertEqual(valid, [])
        self.assertTrue(any("真实子串" in i["reason"] for i in issues))

    def test_supportive_evidence_wrong_polarity(self):
        issues = []
        valid = ice.validate_evidence_grounding([ev("简历", "三年运营经验", polarity="counter")], self._index(), "supportive", "motivation", issues)
        self.assertEqual(valid, [])
        self.assertTrue(any("polarity" in i["reason"] for i in issues))

    def test_counter_evidence_wrong_polarity(self):
        issues = []
        valid = ice.validate_evidence_grounding([ev("简历", "三年运营经验", polarity="supportive")], self._index(), "counter", "motivation", issues)
        self.assertEqual(valid, [])
        self.assertTrue(any("polarity" in i["reason"] for i in issues))


class TestPerDimensionDegradation(unittest.TestCase):
    def test_no_valid_evidence_coverage_zero_low(self):
        benchmark = make_benchmark()
        issues = []
        src_index = ice.build_source_index(RESUME, make_interview(qa=[]))
        detail, _ = ice.post_process_dimension("motivation", make_dim(80, [ev("不存在", "x")]), src_index, issues, benchmark, make_interview(qa=[]))
        self.assertEqual(detail["evidence_coverage"], 0)
        self.assertEqual(detail["confidence"], "low")
        self.assertTrue(issues)

    def test_long_answer_not_unlock_all_dims(self):
        llm = make_full_llm_output()
        result = ice.post_process(llm, make_interview(qa=QA), make_benchmark(), resume=RESUME, model="test")
        for dim in ice.DIMENSIONS:
            self.assertEqual(result["iceberg_scores"][dim]["evidence_stage"], "resume_hypothesis", dim)
            self.assertEqual(result["iceberg_scores"][dim]["confidence"], "low", dim)

    def test_one_dim_interview_only_that_dim(self):
        llm = make_full_llm_output()
        llm["iceberg_scores"]["motivation"]["evidence"] = [ev("Q1", "主动承担了协调工作")]
        result = ice.post_process(llm, make_interview(qa=QA), make_benchmark(), resume=RESUME, model="test")
        self.assertEqual(result["iceberg_scores"]["motivation"]["evidence_stage"], "interview_supported")
        for dim in ("trait", "self_concept", "values"):
            self.assertEqual(result["iceberg_scores"][dim]["evidence_stage"], "resume_hypothesis", dim)
            self.assertEqual(result["iceberg_scores"][dim]["confidence"], "low", dim)


class TestAboveWaterAlignment(unittest.TestCase):
    def test_missing_indicator_filled(self):
        llm = make_full_llm_output()
        llm["above_water_summary"] = [llm["above_water_summary"][0]]
        result = ice.post_process(llm, make_interview(qa=[]), make_benchmark(), resume=RESUME, model="test")
        indicators = {item["indicator"]: item for item in result["above_water_summary"]}
        self.assertIn("协作推进经历", indicators)
        self.assertEqual(indicators["协作推进经历"]["status"], "not_evidenced")

    def test_fabricated_indicator_rejected(self):
        llm = make_full_llm_output()
        llm["above_water_summary"].append({"indicator": "杜撰指标", "priority": "must", "status": "evidenced",
                                           "evidence": [ev("简历", "三年运营经验")], "caveat": ""})
        result = ice.post_process(llm, make_interview(qa=[]), make_benchmark(), resume=RESUME, model="test")
        indicators = {item["indicator"] for item in result["above_water_summary"]}
        self.assertNotIn("杜撰指标", indicators)
        self.assertTrue(any("杜撰" in i["reason"] for i in result["evidence_validation_issues"]))


class TestHtmlRendering(unittest.TestCase):
    def test_html_shows_above_water_evidence(self):
        result = ice.post_process(make_full_llm_output(), make_interview(qa=[]), make_benchmark(), resume=RESUME, model="test")
        html_out = ice.generate_html(result)
        self.assertIn("三年运营经验", html_out)
        self.assertIn("主导跨部门协作", html_out)

    def test_draft_shows_exploratory(self):
        result = ice.post_process(make_full_llm_output(), make_interview(qa=QA), make_benchmark(status="draft"), resume=RESUME, model="test")
        html_out = ice.generate_html(result)
        self.assertIn("探索性综合分", html_out)
        self.assertIn("探索性画像相似度", html_out)

    def test_resume_only_shows_exploratory(self):
        result = ice.post_process(make_full_llm_output(), make_interview(qa=[]), make_benchmark(), resume=RESUME, model="test")
        html_out = ice.generate_html(result)
        self.assertIn("探索性综合分", html_out)

    def test_html_escaping(self):
        llm = make_full_llm_output()
        llm["llm_report"] = "<script>alert(1)</script> 结论"
        result = ice.post_process(llm, make_interview(qa=[]), make_benchmark(), resume=RESUME, model="test")
        html_out = ice.generate_html(result)
        self.assertNotIn("<script>", html_out)
        self.assertIn("&lt;script&gt;", html_out)


class TestOutputSafety(unittest.TestCase):
    def test_decision_boundary_blocked(self):
        llm = make_full_llm_output()
        llm["llm_report"] = "该候选人表现优秀，建议录用。"
        result = ice.post_process(llm, make_interview(qa=QA), make_benchmark(), resume=RESUME, model="test")
        violations = ice.check_decision_boundary(result)
        self.assertTrue(any("建议录用" in v for v in violations))

    def test_disclaimer_not_flagged(self):
        result = ice.post_process(make_full_llm_output(), make_interview(qa=QA), make_benchmark(), resume=RESUME, model="test")
        self.assertIn("不构成自动录用或淘汰决定", result["decision_boundary"])
        self.assertEqual(ice.check_decision_boundary(result), [])


class TestNoApiNoNetwork(unittest.TestCase):
    def test_dry_run_no_api_key(self):
        old_openai = os.environ.pop("OPENAI_API_KEY", None)
        old_dash = os.environ.pop("DASHSCOPE_API_KEY", None)
        try:
            cfg = ice.resolve_model_config()
            self.assertEqual(cfg["api_key"], "")
            with tempfile.TemporaryDirectory() as tmp:
                resume_path = os.path.join(tmp, "resume.txt")
                with open(resume_path, "w", encoding="utf-8") as fh:
                    fh.write(RESUME)
                interview_path = os.path.join(tmp, "interview.json")
                with open(interview_path, "w", encoding="utf-8") as fh:
                    json.dump(make_interview(), fh, ensure_ascii=False)
                benchmark_path = os.path.join(tmp, "benchmark.json")
                with open(benchmark_path, "w", encoding="utf-8") as fh:
                    json.dump(make_benchmark(), fh, ensure_ascii=False)
                html_path = os.path.join(tmp, "out.html")
                args = argparse.Namespace(resume=resume_path, interview=interview_path, benchmark=benchmark_path,
                                          html=html_path, model=None, base_url=None, output_mode=None, dry_run=True)
                self.assertEqual(ice.evaluate_mode(args), 0)
                self.assertTrue(os.path.exists(html_path))
        finally:
            if old_openai is not None:
                os.environ["OPENAI_API_KEY"] = old_openai
            if old_dash is not None:
                os.environ["DASHSCOPE_API_KEY"] = old_dash

    def test_no_network(self):
        result = ice.post_process(make_full_llm_output(), make_interview(qa=QA), make_benchmark(), resume=RESUME, model="test")
        html_out = ice.generate_html(result)
        self.assertTrue(html_out)
        self.assertNotIn("openai", sys.modules)


# =========================== 新增：置信度与基准解耦 =========================== #
class TestConfidenceDecoupling(unittest.TestCase):
    def test_score_above_benchmark_but_resume_only_low(self):
        llm = make_full_llm_output()
        llm["iceberg_scores"]["motivation"] = make_dim(90, [ev("简历", "主导跨部门协作")])  # 90 > 基准80
        result = ice.post_process(llm, make_interview(qa=[]), make_benchmark(), resume=RESUME, model="test")
        self.assertEqual(result["iceberg_scores"]["motivation"]["confidence"], "low")

    def test_score_below_benchmark_but_interview_medium(self):
        llm = make_full_llm_output()
        llm["iceberg_scores"]["motivation"] = make_dim(50, [ev("Q1", "主动承担了协调工作")], coverage=70)  # 50 < 基准80
        result = ice.post_process(llm, make_interview(qa=QA), make_benchmark(), resume=RESUME, model="test")
        self.assertEqual(result["iceberg_scores"]["motivation"]["confidence"], "medium")

    def test_benchmark_score_change_no_confidence_change(self):
        b1 = make_benchmark()
        b2 = make_benchmark()
        b2["dimensions"]["motivation"]["benchmark_score"] = 95
        llm = make_full_llm_output()
        llm["iceberg_scores"]["motivation"] = make_dim(80, [ev("简历", "主导跨部门协作")])
        r1 = ice.post_process(llm, make_interview(qa=[]), b1, resume=RESUME, model="test")
        r2 = ice.post_process(llm, make_interview(qa=[]), b2, resume=RESUME, model="test")
        self.assertEqual(r1["iceberg_scores"]["motivation"]["confidence"], r2["iceberg_scores"]["motivation"]["confidence"])

    def test_overall_score_change_no_confidence_change(self):
        llm1 = make_full_llm_output()
        llm2 = make_full_llm_output()
        # 改变其它维度分数以改变 overall，但 motivation 证据不变
        for dim in ("trait", "self_concept", "values"):
            llm2["iceberg_scores"][dim]["score"] = 10
        r1 = ice.post_process(llm1, make_interview(qa=[]), make_benchmark(), resume=RESUME, model="test")
        r2 = ice.post_process(llm2, make_interview(qa=[]), make_benchmark(), resume=RESUME, model="test")
        self.assertNotEqual(r1["overall_score"], r2["overall_score"])
        self.assertEqual(r1["iceberg_scores"]["motivation"]["confidence"], r2["iceberg_scores"]["motivation"]["confidence"])

    def test_similarity_change_no_confidence_change(self):
        llm1 = make_full_llm_output()
        llm2 = make_full_llm_output()
        for dim in ("trait", "self_concept", "values"):
            llm2["iceberg_scores"][dim]["score"] = 10
        r1 = ice.post_process(llm1, make_interview(qa=[]), make_benchmark(), resume=RESUME, model="test")
        r2 = ice.post_process(llm2, make_interview(qa=[]), make_benchmark(), resume=RESUME, model="test")
        self.assertNotEqual(r1["similarity_to_benchmark"], r2["similarity_to_benchmark"])
        self.assertEqual(r1["iceberg_scores"]["motivation"]["confidence"], r2["iceberg_scores"]["motivation"]["confidence"])


class TestConfidenceRules(unittest.TestCase):
    def test_medium_confidence_rule(self):
        llm = make_full_llm_output()
        llm["iceberg_scores"]["motivation"] = make_dim(70, [ev("Q1", "主动承担了协调工作", strength="medium")], coverage=65)
        result = ice.post_process(llm, make_interview(qa=QA), make_benchmark(), resume=RESUME, model="test")
        self.assertEqual(result["iceberg_scores"]["motivation"]["confidence"], "medium")

    def test_high_confidence_rule(self):
        llm = make_full_llm_output()
        llm["iceberg_scores"]["motivation"] = make_dim(80, [
            ev("Q1", "主动承担了协调工作", strength="strong"),
            ev("Q2", "主导了流程优化", strength="medium"),
        ], coverage=85)
        result = ice.post_process(llm, make_interview(qa=QA2), make_benchmark(), resume=RESUME, model="test")
        self.assertEqual(result["iceberg_scores"]["motivation"]["confidence"], "high")

    def test_strong_counter_blocks_high(self):
        llm = make_full_llm_output()
        llm["iceberg_scores"]["motivation"] = make_dim(80, [
            ev("Q1", "主动承担了协调工作", strength="strong"),
            ev("Q2", "主导了流程优化", strength="medium"),
        ], coverage=85, counter_evidence=[ev("简历", "主导跨部门协作", strength="strong", polarity="counter")])
        result = ice.post_process(llm, make_interview(qa=QA2), make_benchmark(), resume=RESUME, model="test")
        self.assertEqual(result["iceberg_scores"]["motivation"]["confidence"], "low")


class TestBenchmarkComparison(unittest.TestCase):
    def test_low_no_level(self):
        # 等级现在始终显示（3 档：优秀/中等/较差），旧的 4 档措辞已移除
        llm = make_full_llm_output()
        result = ice.post_process(llm, make_interview(qa=[]), make_benchmark(), resume=RESUME, model="test")
        html_out = ice.generate_html(result)
        for word in ("良好", "一般", "较弱"):
            self.assertNotIn(word, html_out)
        self.assertIn("等级：", html_out)

    def test_low_no_benchmark_comparison_words(self):
        llm = make_full_llm_output()
        result = ice.post_process(llm, make_interview(qa=[]), make_benchmark(), resume=RESUME, model="test")
        html_out = ice.generate_html(result)
        self.assertIn("当前四维证据均不充分，暂不进行高于或低于画像基准的判断", html_out)
        for word in ("高于基准", "低于基准", "符合基准"):
            self.assertNotIn(word, html_out)

    def test_draft_no_deterministic_match(self):
        llm = make_full_llm_output()
        llm["iceberg_scores"]["motivation"] = make_dim(70, [ev("Q1", "主动承担了协调工作", strength="medium")], coverage=65)
        result = ice.post_process(llm, make_interview(qa=QA), make_benchmark(status="draft"), resume=RESUME, model="test")
        html_out = ice.generate_html(result)
        self.assertNotIn("已达到成功画像", html_out)
        self.assertNotIn("优于成功画像", html_out)
        self.assertIn("仅供探索性参考", html_out)


class TestFollowupStructure(unittest.TestCase):
    def test_q1_resolved_to_full_question(self):
        detail = make_dim(80, [ev("简历", "主导跨部门协作")], validation_questions=["Q1"])
        fus = ice.normalize_validation_questions(detail["validation_questions"], make_interview(qa=QA), make_benchmark(), "motivation")
        self.assertEqual(fus[0]["question"], "请描述一次协作经历。")
        self.assertEqual(fus[0]["source_question_id"], "Q1")
        self.assertFalse(fus[0]["generated_by_rule"])

    def test_q_missing_generates_fallback(self):
        detail = make_dim(80, [ev("简历", "主导跨部门协作")], validation_questions=["Q99"])
        fus = ice.normalize_validation_questions(detail["validation_questions"], make_interview(qa=QA), make_benchmark(), "motivation")
        self.assertTrue(fus[0]["generated_by_rule"])
        self.assertNotEqual(fus[0]["question"], "Q99")

    def test_empty_followup_generates_fallback(self):
        detail = make_dim(80, [ev("简历", "主导跨部门协作")], validation_questions=[])
        fus = ice.normalize_validation_questions(detail["validation_questions"], make_interview(qa=[]), make_benchmark(), "motivation")
        self.assertTrue(fus[0]["generated_by_rule"])
        self.assertIn("主动承担具有挑战的工作", fus[0]["question"])

    def test_each_low_dim_has_followup(self):
        llm = make_full_llm_output()
        result = ice.post_process(llm, make_interview(qa=[]), make_benchmark(), resume=RESUME, model="test")
        for dim in ice.DIMENSIONS:
            fus = result["iceberg_scores"][dim]["validation_questions"]
            self.assertGreaterEqual(len(fus), 1, dim)
            self.assertFalse(any(re.fullmatch(r"Q\d+", f["question"]) for f in fus), dim)

    def test_html_shows_full_question(self):
        llm = make_full_llm_output()
        result = ice.post_process(llm, make_interview(qa=[]), make_benchmark(), resume=RESUME, model="test")
        html_out = ice.generate_html(result)
        self.assertIn("请描述一次相关工作经历", html_out)
        self.assertNotIn(">Q1<", html_out)
        self.assertNotIn(">Q2<", html_out)

    def test_html_shows_purpose(self):
        llm = make_full_llm_output()
        result = ice.post_process(llm, make_interview(qa=[]), make_benchmark(), resume=RESUME, model="test")
        html_out = ice.generate_html(result)
        self.assertIn("验证目的", html_out)

    def test_html_shows_expected_evidence(self):
        llm = make_full_llm_output()
        result = ice.post_process(llm, make_interview(qa=[]), make_benchmark(), resume=RESUME, model="test")
        html_out = ice.generate_html(result)
        self.assertIn("期望证据", html_out)


class TestOverallStage(unittest.TestCase):
    def test_all_resume_stage(self):
        llm = make_full_llm_output()
        result = ice.post_process(llm, make_interview(qa=QA2), make_benchmark(), resume=RESUME, model="test")
        self.assertEqual(result["evaluation_stage"], ice.STAGE_NO_INTERVIEW)

    def test_partial_stage(self):
        llm = make_full_llm_output()
        llm["iceberg_scores"]["motivation"]["evidence"] = [ev("Q1", "主动承担了协调工作")]
        result = ice.post_process(llm, make_interview(qa=QA), make_benchmark(), resume=RESUME, model="test")
        self.assertEqual(result["evaluation_stage"], ice.STAGE_PARTIAL)
        self.assertIn("动机", result["interview_supported_dimensions"])

    def test_all_interview_stage(self):
        llm = make_full_llm_output()
        for dim in ice.DIMENSIONS:
            llm["iceberg_scores"][dim]["evidence"] = [ev("Q1", "主动承担了协调工作")]
        result = ice.post_process(llm, make_interview(qa=QA), make_benchmark(), resume=RESUME, model="test")
        self.assertEqual(result["evaluation_stage"], ice.STAGE_FULL)

    def test_builtin_placeholder_sample_stage(self):
        # 内置样例 Q1/Q2 为占位回答，四维均 resume_hypothesis，总体应为「简历前置识别（结构化问答待补充）」
        placeholder_qa = [
            {"question_id": "Q1", "question": "请描述一次协作经历。", "answer": "填写候选人的完整回答，保留情境、任务、个人行动、结果和反思。"},
            {"question_id": "Q2", "question": "请描述一次流程优化经历。", "answer": "填写候选人的完整回答。"},
        ]
        llm = make_full_llm_output()
        result = ice.post_process(llm, make_interview(qa=placeholder_qa), make_benchmark(), resume=RESUME, model="test")
        self.assertEqual(result["evaluation_stage"], ice.STAGE_NO_INTERVIEW)


class TestLevel(unittest.TestCase):
    def test_level_boundaries(self):
        self.assertEqual(ice.level(59), "较差")
        self.assertEqual(ice.level(60), "中等")
        self.assertEqual(ice.level(79), "中等")
        self.assertEqual(ice.level(80), "优秀")
        self.assertEqual(ice.level(100), "优秀")
        self.assertEqual(ice.level(0), "较差")

    def test_four_dimensions_show_level(self):
        llm = make_full_llm_output()
        result = ice.post_process(llm, make_interview(qa=[]), make_benchmark(), resume=RESUME, model="test")
        html_out = ice.generate_html(result)
        for dim in ice.DIMENSIONS:
            self.assertIn(result["iceberg_scores"][dim]["level"], ("优秀", "中等", "较差"))


class TestAnonymization(unittest.TestCase):
    def test_real_name_not_in_html(self):
        llm = make_full_llm_output()
        result = ice.post_process(llm, make_interview(candidate_name="张三", qa=[]), make_benchmark(), resume=RESUME, model="test")
        html_out = ice.generate_html(result)
        self.assertNotIn("张三", html_out)
        self.assertIn("候选人编号：", html_out)

    def test_generate_anonymous_id_when_no_candidate_id(self):
        llm = make_full_llm_output()
        result = ice.post_process(llm, make_interview(candidate_name="张三", qa=[]), make_benchmark(), resume=RESUME, model="test")
        self.assertTrue(result["candidate_id"].startswith("CAND-"))

    def test_candidate_id_used(self):
        llm = make_full_llm_output()
        interview = make_interview(candidate_name="张三", qa=[])
        interview["candidate_id"] = "MY-ID-001"
        result = ice.post_process(llm, interview, make_benchmark(), resume=RESUME, model="test")
        html_out = ice.generate_html(result)
        self.assertIn("MY-ID-001", html_out)
        self.assertNotIn("张三", html_out)


class TestEvidenceDirection(unittest.TestCase):
    def test_direction_and_id_assignment(self):
        llm = make_full_llm_output()
        llm["iceberg_scores"]["motivation"]["evidence"] = [ev("简历", "主导跨部门协作")]
        llm["iceberg_scores"]["motivation"]["counter_evidence"] = [ev("Q1", "主动承担了协调工作", polarity="counter")]
        result = ice.post_process(llm, make_interview(qa=QA), make_benchmark(), resume=RESUME, model="test")
        m = result["iceberg_scores"]["motivation"]
        self.assertEqual(m["evidence"][0]["direction"], "positive")
        self.assertTrue(m["evidence"][0]["evidence_id"].startswith("CV-E"))
        self.assertEqual(m["evidence"][0]["source_label"], "简历")
        self.assertEqual(m["counter_evidence"][0]["direction"], "negative")
        self.assertTrue(m["counter_evidence"][0]["evidence_id"].startswith("INT-E"))
        self.assertEqual(m["counter_evidence"][0]["source_label"], "面试")

    def test_cv_int_numbering(self):
        llm = make_full_llm_output()
        llm["iceberg_scores"]["motivation"]["evidence"] = [ev("简历", "主导跨部门协作"), ev("Q1", "主动承担了协调工作")]
        result = ice.post_process(llm, make_interview(qa=QA), make_benchmark(), resume=RESUME, model="test")
        ids = [e["evidence_id"] for e in result["iceberg_scores"]["motivation"]["evidence"]]
        self.assertTrue(any(i.startswith("CV-E") for i in ids))
        self.assertTrue(any(i.startswith("INT-E") for i in ids))

    def test_no_counter_shows_placeholder(self):
        llm = make_full_llm_output()
        result = ice.post_process(llm, make_interview(qa=[]), make_benchmark(), resume=RESUME, model="test")
        html_out = ice.generate_html(result)
        self.assertIn("暂无有效证据", html_out)
        self.assertIn("当前材料未发现可成立的反向证据", html_out)

    def test_counter_shown_in_html(self):
        llm = make_full_llm_output()
        llm["iceberg_scores"]["values"]["counter_evidence"] = [ev("简历", "持续追踪问题直至闭环", polarity="counter")]
        result = ice.post_process(llm, make_interview(qa=[]), make_benchmark(), resume=RESUME, model="test")
        html_out = ice.generate_html(result)
        self.assertIn("持续追踪问题直至闭环", html_out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
