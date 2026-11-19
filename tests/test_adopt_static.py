"""RFC-20261119-03 Phase 3：Adopt 只读静态抽取 + stale 门 + PRD 确认闸。"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
ADOPT = PKG_ROOT / "scripts" / "adopt_static.py"
VALIDATE = PKG_ROOT / "validators" / "validate_adopt_facts.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _fixture(root: Path) -> None:
    _write(root, "src/main/java/demo/OrderController.java", """\
package demo;

import org.springframework.web.bind.annotation.*;
import org.springframework.http.ResponseEntity;
import java.util.List;

@RestController
public class OrderController {
    @PostMapping("/api/orders/{id}/cancel")
    public ResponseEntity<OrderView> cancel(@PathVariable("id") Long id,
                                            @RequestBody CancelRequest req) {
        return null;
    }

    @GetMapping("/api/orders")
    public List<OrderView> list(@RequestParam("status") String status) {
        return null;
    }
}
""")
    _write(root, "src/main/java/demo/CancelRequest.java", """\
package demo;
public class CancelRequest {
    private String reason;
    private boolean force;
}
""")
    _write(root, "src/main/java/demo/Order.java", """\
package demo;
import jakarta.persistence.*;
@Entity
@Table(name = "orders")
public class Order {
    @Id
    @GeneratedValue
    private Long id;
    @Column(nullable = false)
    private String status;
    @Enumerated(EnumType.STRING)
    private OrderStatus state;
}
""")
    _write(root, "src/main/java/demo/OrderStatus.java", """\
package demo;
public enum OrderStatus { NEW, PAID, CANCELLED }
""")
    _write(root, "src/test/java/demo/OrderServiceTest.java", """\
package demo;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;
import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.mock;

class OrderServiceTest {
    @Test
    @DisplayName("负金额下单应被拒绝")
    void shouldRejectNegativeAmount() {
        var result = new OrderResult("INVALID_AMOUNT");
        assertThat(result.getCode()).isEqualTo("INVALID_AMOUNT");
    }

    @Test
    void shouldCallRepository() {
        var repo = mock(OrderRepository.class);
        assertEquals(1, repo.count());
    }
}
""")


def test_adopt_static_extracts_java_facts_and_ac_drafts() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _fixture(root)
        p = subprocess.run(
            [sys.executable, str(ADOPT), "--root", td, "--out", ".adapter-out/adopt", "--json"],
            capture_output=True, text=True, timeout=60)
        assert p.returncode == 0, p.stderr
        facts = json.loads((root / ".adapter-out/adopt/facts.json").read_text(encoding="utf-8"))
        assert facts["schema_version"] == 1
        assert facts["source_fingerprints"], facts
        assert facts["git_commit"] == "" or len(facts["git_commit"]) == 40

        cancel = [e for e in facts["endpoints"]
                  if e["payload"]["handler"] == "cancel"][0]
        assert cancel["payload"]["http"] == "POST"
        assert cancel["payload"]["path"] == "/api/orders/{id}/cancel"
        assert cancel["payload"]["request"]["path"] == ["id"]
        assert cancel["payload"]["request"]["body"] == "CancelRequest"
        assert {f["name"] for f in cancel["payload"]["request"]["body_fields"]} == {
            "reason", "force"}
        assert cancel["payload"]["response"] == "OrderView"
        assert cancel["source"]["file"].endswith("OrderController.java")
        assert cancel["source"]["line"] > 0

        orders = [e for e in facts["entities"] if e["table"] == "orders"]
        assert orders, facts["entities"]
        state = [e for e in orders if e["field"] == "state"][0]
        assert state["enum"] == "OrderStatus"
        assert state["line"] > 0
        assert any(x["field"] == "status" and x["constraints"] == "非空"
                   for x in orders)
        assert any(set(v["value"] for v in e["values"]) >= {"NEW", "PAID", "CANCELLED"}
                   for e in facts["enums"])

        assert len(facts["ac_drafts"]) == 2
        by_test = {d["source"]["test"]: d for d in facts["ac_drafts"]}
        assert by_test["shouldRejectNegativeAmount"]["confidence"] == "high"
        assert by_test["shouldRejectNegativeAmount"]["display_name"] == "负金额下单应被拒绝"
        assert by_test["shouldCallRepository"]["confidence"] == "low"
        assert all(d["confirmed"] is False for d in facts["ac_drafts"])
        assert (root / ".adapter-out/adopt/ac-draft.md").is_file()


def test_adopt_facts_stale_validator() -> None:
    v = _load(VALIDATE, "validate_adopt_facts_test")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _fixture(root)
        subprocess.run([sys.executable, str(ADOPT), "--root", td, "--out", ".adapter-out/adopt"],
                       check=True, capture_output=True, text=True, timeout=60)
        res = v.validate_adopt_facts(root)
        assert res.ok, res.checks
        # 源变 ⇒ stale FAIL，且不得携带自动重录命令
        (root / "src/main/java/demo/OrderController.java").write_text(
            "package demo;\n// changed\n", encoding="utf-8")
        res2 = v.validate_adopt_facts(root)
        assert not res2.ok, res2.checks
        detail = " ".join(c.get("detail", "") for c in res2.checks)
        assert "源指纹不一致" in detail
        assert "--write" not in detail and "--record" not in detail


def test_adopt_verify_command_reports_stale() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _fixture(root)
        subprocess.run([sys.executable, str(ADOPT), "--root", td, "--out", ".adapter-out/adopt"],
                       check=True, capture_output=True, text=True, timeout=60)
        ok = subprocess.run([sys.executable, str(ADOPT), "--root", td, "--verify"],
                            capture_output=True, text=True, timeout=60)
        assert ok.returncode == 0, ok.stdout + ok.stderr
        (root / "src/test/java/demo/OrderServiceTest.java").write_text(
            "class X {}\n", encoding="utf-8")
        bad = subprocess.run([sys.executable, str(ADOPT), "--root", td, "--verify"],
                             capture_output=True, text=True, timeout=60)
        assert bad.returncode == 1, bad.stdout + bad.stderr


def test_same_line_annotation_forms_supported() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write(root, "src/main/java/demo/C.java", """\
package demo;
@RestController public class C { @GetMapping("/x") public String x() { return "ok"; } }
""")
        p = subprocess.run(
            [sys.executable, str(ADOPT), "--root", td, "--out", ".adapter-out/adopt", "--json"],
            capture_output=True, text=True, timeout=60)
        assert p.returncode == 0, p.stderr
        facts = json.loads((root / ".adapter-out/adopt/facts.json").read_text(encoding="utf-8"))
        assert len(facts["endpoints"]) == 1, facts
        ep = facts["endpoints"][0]["payload"]
        assert ep["http"] == "GET" and ep["path"] == "/x" and ep["handler"] == "x"


def test_orchestrator_has_no_framework_literals() -> None:
    """框架知识只能落在 adapters/；scripts/adopt_static.py 只做编排。"""
    text = ADOPT.read_text(encoding="utf-8").lower()
    for token in ("spring", "junit", "assertj", "jakarta.persistence",
                  "@entity", "restcontroller", "src/main/java", "src/test/java"):
        assert token not in text, f"adopt_static.py 含框架字面量：{token}"


def test_prd_rejects_unconfirmed_adopt_draft() -> None:
    v = _load(PKG_ROOT / "validators" / "validate_prd.py", "validate_prd_adopt_test")
    assert v.adopt_draft_findings("## 五 AC\n| AC-1 | x |", "a.md") == []
    assert v.adopt_draft_findings(
        "source: adopt-draft\nconfirmed: false", "a.md")
    assert v.adopt_draft_findings("source: adopt-draft", "a.md")
    assert v.adopt_draft_findings(
        "source: adopt-draft\nconfirmed: true", "a.md") == []
