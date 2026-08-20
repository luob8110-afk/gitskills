#!/usr/bin/env python3
"""HR 本地体验页：上传三份材料，校验或生成一份 HTML 报告。"""
from __future__ import annotations

import os
import tempfile
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable

from flask import Flask, Response, jsonify, render_template, request

import iceberg_evaluator as evaluator


SKILL_ROOT = Path(__file__).resolve().parents[1]
WEB_ASSETS = SKILL_ROOT / "assets" / "hr_app"
SAMPLE_PATHS = {
    "resume": SKILL_ROOT / "templates" / "candidate_resume.example.txt",
    "interview": SKILL_ROOT / "templates" / "interview_qa.example.json",
    "benchmark": SKILL_ROOT / "templates" / "benchmark_profile.example.json",
}
REPORT_TTL_SECONDS = 60 * 60
REPORT_LIMIT = 20


class ReportStore:
    def __init__(self) -> None:
        self._items: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def put(self, report_html: str, filename: str) -> str:
        token = uuid.uuid4().hex
        now = time.time()
        with self._lock:
            self._purge(now)
            self._items[token] = {"html": report_html, "filename": filename, "created_at": now}
            while len(self._items) > REPORT_LIMIT:
                self._items.popitem(last=False)
        return token

    def get(self, token: str) -> dict[str, Any] | None:
        now = time.time()
        with self._lock:
            self._purge(now)
            item = self._items.get(token)
            return dict(item) if item else None

    def _purge(self, now: float) -> None:
        expired = [key for key, item in self._items.items() if now - item["created_at"] > REPORT_TTL_SECONDS]
        for key in expired:
            self._items.pop(key, None)


def _save_uploads(target_dir: Path) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    specs = {
        "resume": ("resume_file", ".txt"),
        "interview": ("interview_file", ".json"),
        "benchmark": ("benchmark_file", ".json"),
    }
    for key, (field, suffix) in specs.items():
        upload = request.files.get(field)
        if upload is None or not upload.filename:
            raise ValueError("请同时上传简历 TXT、面试问答 JSON 和成功画像 JSON。")
        if Path(upload.filename).suffix.lower() != suffix:
            raise ValueError(f"{field} 文件类型必须为 {suffix}。")
        path = target_dir / f"{key}{suffix}"
        upload.save(path)
        paths[key] = path
    return paths


def _load_inputs(paths: dict[str, Path]) -> tuple[str, dict[str, Any], dict[str, Any]]:
    resume = evaluator.load_text(str(paths["resume"]), "简历文件")
    interview = evaluator.load_json(str(paths["interview"]), "interview")
    benchmark = evaluator.load_json(str(paths["benchmark"]), "benchmark")
    evaluator.validate_interview(interview)
    evaluator.validate_benchmark(benchmark)
    return resume, interview, benchmark


def create_app(
    evaluate_fn: Callable[[str, dict[str, Any], dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None,
) -> Flask:
    app = Flask(__name__, template_folder=str(WEB_ASSETS))
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
    reports = ReportStore()

    @app.get("/")
    def index() -> str:
        return render_template("index.html")

    @app.post("/api/process")
    def process() -> tuple[Response, int] | Response:
        action = request.form.get("action", "validate")
        if action not in {"validate", "evaluate"}:
            return jsonify({"ok": False, "error": "未知操作。"}), 400
        try:
            with tempfile.TemporaryDirectory(prefix="iceberg-hr-") as tmp:
                if request.form.get("use_sample") == "true":
                    paths = SAMPLE_PATHS
                else:
                    paths = _save_uploads(Path(tmp))
                resume, interview, benchmark = _load_inputs(paths)

                if action == "validate":
                    report_html = evaluator.generate_validation_html(interview, benchmark)
                    filename = "iceberg-input-validation.html"
                    message = "输入与画像治理门槛校验通过，未调用模型。"
                else:
                    config = evaluator.resolve_model_config(
                        request.form.get("model") or None,
                        request.form.get("base_url") or None,
                        request.form.get("output_mode") or None,
                    )
                    llm = evaluate_fn(resume, interview, benchmark, config) if evaluate_fn else evaluator.call_llm(
                        resume, interview, benchmark, config
                    )
                    result = evaluator.post_process(llm, interview, benchmark, resume=resume, model=config["model"])
                    violations = evaluator.check_decision_boundary(result)
                    if violations:
                        raise ValueError("检测到越界结论，已中止报告生成：" + "；".join(violations))
                    report_html = evaluator.generate_html(result)
                    filename = f"{result['candidate_id']}-iceberg-report.html"
                    message = "报告已生成；请结合证据、置信度和限制进行人工复核。"

            token = reports.put(report_html, filename)
            return jsonify({
                "ok": True,
                "message": message,
                "preview_url": f"/report/{token}",
                "download_url": f"/download/{token}",
            })
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.get("/report/<token>")
    def preview(token: str) -> Response:
        item = reports.get(token)
        if item is None:
            return Response("报告不存在或已过期。", status=404, content_type="text/plain; charset=utf-8")
        return Response(item["html"], content_type="text/html; charset=utf-8")

    @app.get("/download/<token>")
    def download(token: str) -> Response:
        item = reports.get(token)
        if item is None:
            return Response("报告不存在或已过期。", status=404, content_type="text/plain; charset=utf-8")
        response = Response(item["html"], content_type="text/html; charset=utf-8")
        response.headers["Content-Disposition"] = f'attachment; filename="{item["filename"]}"'
        return response

    return app


def main() -> None:
    port = int(os.getenv("ICEBERG_HR_PORT", "8765"))
    create_app().run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
