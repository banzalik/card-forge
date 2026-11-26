"""Unit tests for the CardForge skill scripts (stdlib unittest)."""
import io
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "card-forge"
sys.path.insert(0, str(SKILL / "scripts"))

import build_pkpass  # noqa: E402
import gwallet_link  # noqa: E402
import render  # noqa: E402
from cardforge_common import CardError, load_records, normalize, validate  # noqa: E402
from impose import CR80_H, CR80_W, compute_imposition  # noqa: E402

SAMPLES = sorted((SKILL / "assets" / "samples").glob("*.json"))


def quiet(fn, *a, **kw):
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return fn(*a, **kw)


class ImpositionTests(unittest.TestCase):
    def test_grid_is_centered(self):
        for paper in ("letter", "a4"):
            for n in (1, 2, 4, 8, 10):
                imp = compute_imposition(paper, n, "long-edge")
                pw, ph = imp["paper"]["width_mm"], imp["paper"]["height_mm"]
                xs = [s["front"]["x_mm"] for s in imp["slots"]]
                ys = [s["front"]["y_mm"] for s in imp["slots"]]
                self.assertEqual(len(imp["slots"]), n)
                self.assertAlmostEqual(min(xs), pw - (max(xs) + CR80_W), places=2)
                self.assertAlmostEqual(min(ys), ph - (max(ys) + CR80_H), places=2)

    def test_long_edge_mirrors_columns(self):
        imp = compute_imposition("letter", 8, "long-edge")
        pw = imp["paper"]["width_mm"]
        for s in imp["slots"]:
            # Flipping across the vertical axis: back x = paper width - (front x + card width).
            self.assertAlmostEqual(s["back"]["x_mm"], pw - s["front"]["x_mm"] - CR80_W, places=2)
            self.assertEqual(s["back"]["y_mm"], s["front"]["y_mm"])

    def test_short_edge_mirrors_rows(self):
        imp = compute_imposition("a4", 8, "short-edge")
        ph = imp["paper"]["height_mm"]
        for s in imp["slots"]:
            self.assertAlmostEqual(s["back"]["y_mm"], ph - s["front"]["y_mm"] - CR80_H, places=2)
            self.assertEqual(s["back"]["x_mm"], s["front"]["x_mm"])

    def test_offsets_only_move_backs(self):
        a = compute_imposition("letter", 4, "long-edge")
        b = compute_imposition("letter", 4, "long-edge", 1.5, -0.75)
        for sa, sb in zip(a["slots"], b["slots"]):
            self.assertEqual(sa["front"], sb["front"])
            self.assertAlmostEqual(sb["back"]["x_mm"] - sa["back"]["x_mm"], 1.5, places=3)
            self.assertAlmostEqual(sb["back"]["y_mm"] - sa["back"]["y_mm"], -0.75, places=3)

    def test_ten_up_letter_warns_and_clips_bleed(self):
        imp = compute_imposition("letter", 10, "long-edge")
        self.assertTrue(any("gutter" in w for w in imp["warnings"]))
        self.assertTrue(any("margin" in w for w in imp["warnings"]))
        self.assertEqual(imp["card"]["effectiveBleed_mm"]["inner"]["y"], 1.0)
        self.assertEqual(imp["card"]["effectiveBleed_mm"]["outer"]["y"], 0.75)

    def test_eight_up_letter_is_clean(self):
        self.assertEqual(compute_imposition("letter", 8, "long-edge")["warnings"], [])

    def test_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            compute_imposition("legal", 8, "long-edge")
        with self.assertRaises(ValueError):
            compute_imposition("letter", 6, "long-edge")
        with self.assertRaises(ValueError):
            compute_imposition("letter", 8, "sideways")


class DataTests(unittest.TestCase):
    def test_samples_validate(self):
        self.assertGreaterEqual(len(SAMPLES), 4)
        for f in SAMPLES:
            self.assertEqual(validate(json.loads(f.read_text())), [], f.name)

    def test_invalid_payload_reports_problems(self):
        bad = {"template": "nope", "front": {"issuerName": "x"}, "back": {}, "branding": {"primaryColor": "red"}}
        errs = validate(bad)
        self.assertTrue(any("template" in e for e in errs))
        self.assertTrue(any("holderName" in e for e in errs))
        self.assertTrue(any("primaryColor" in e for e in errs))
        with self.assertRaises(CardError):
            normalize(bad)

    def test_csv_dotted_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp, "c.csv")
            p.write_text(
                "template,front.issuerName,front.holderName,front.idNumber,front.fields.0.label,front.fields.0.value,"
                "back.showMagStripe,back.barcode.format,back.barcode.value\n"
                'generic-id,ACME,"Doe, Jane",A1,Dept,Ops,true,QR,A1\n'
                "generic-id,ACME,Bob,A2,,,false,CODE128,A2\n",
                encoding="utf-8",
            )
            recs = load_records(p)
        self.assertEqual(len(recs), 2)
        self.assertEqual(recs[0]["front"]["holderName"], "Doe, Jane")
        self.assertEqual(recs[0]["front"]["fields"], [{"label": "Dept", "value": "Ops"}])
        self.assertIs(recs[0]["back"]["showMagStripe"], True)
        self.assertNotIn("fields", recs[1]["front"])
        for r in recs:
            self.assertEqual(validate(r), [])


class RenderTests(unittest.TestCase):
    def test_batch_pages_and_escaping(self):
        card = json.loads((SKILL / "assets/samples/generic-id.json").read_text())
        card["front"]["holderName"] = "<script>alert(1)</script>"
        cards = [normalize(card)] * 9
        imp = compute_imposition("letter", 8, "long-edge")
        html = render.build_sheets(cards, imp, "batch", True, False)
        self.assertEqual(html.count('class="sheet front"'), 2)
        self.assertEqual(html.count('class="sheet back"'), 2)
        self.assertNotIn("<script>alert", html)
        self.assertIn("&lt;script&gt;", html)

    def test_cli_writes_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc = quiet(render.main, [str(SAMPLES[0]), "--mode", "copies", "--html-only", "--out", tmp, "--name", "x"])
            self.assertEqual(rc, 0)
            html = Path(tmp, "x.html").read_text()
            self.assertIn("@page { size: 215.9mm 279.4mm", html)
            self.assertEqual(html.count('class="bleedbox"'), 16)

    def test_calibration(self):
        html = render.build_calibration(compute_imposition("a4", 4, "short-edge"))
        self.assertEqual(html.count('class="cal-cross"'), 8)  # 4 crosshairs per page


class WalletTests(unittest.TestCase):
    def setUp(self):
        self.card = normalize(json.loads((SKILL / "assets/samples/auto-insurance.json").read_text()))

    def test_pass_json_mapping(self):
        p = build_pkpass.build_pass_json(self.card, "pass.x", "TEAM")
        g = p["generic"]
        self.assertEqual(g["primaryFields"][0]["value"], "Jordan A. Rivera")
        self.assertLessEqual(len(g["auxiliaryFields"]), 4)
        self.assertEqual(p["barcodes"][0]["format"], "PKBarcodeFormatPDF417")
        self.assertEqual(p["backgroundColor"], "rgb(15, 23, 42)")
        self.assertTrue(any(f["key"] == "legal" for f in g["backFields"]))

    def test_aux_overflow_goes_to_back(self):
        self.card["front"]["fields"] = [{"key": f"k{i}", "label": f"L{i}", "value": str(i)} for i in range(6)]
        g = build_pkpass.build_pass_json(self.card, "pass.x", "TEAM")["generic"]
        self.assertEqual(len(g["auxiliaryFields"]), 4)
        self.assertEqual(sum(f["key"].startswith("more_") for f in g["backFields"]), 2)

    def test_unsigned_bundle_manifest(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            path = build_pkpass.build_pkpass(self.card, Path(tmp))
            self.assertTrue(path.name.endswith(".pkpass.zip"))
            with zipfile.ZipFile(path) as z:
                manifest = json.loads(z.read("manifest.json"))
                for name, digest in manifest.items():
                    self.assertEqual(hashlib.sha1(z.read(name)).hexdigest(), digest)
                self.assertIn("icon.png", manifest)
                self.assertNotIn("signature", z.namelist())

    def test_google_object(self):
        claims = gwallet_link.build_claims([self.card], "1234", "sa@x", [])
        obj = claims["payload"]["genericObjects"][0]
        self.assertEqual(claims["typ"], "savetowallet")
        self.assertEqual(obj["id"], "1234.EMA-4471-2290-03")
        self.assertEqual(obj["barcode"]["type"], "PDF_417")
        self.assertEqual(claims["payload"]["genericClasses"][0]["id"], obj["classId"])

    def test_rs256_signature_verifies(self):
        import base64
        with tempfile.TemporaryDirectory() as tmp:
            key, pub = Path(tmp, "k.pem"), Path(tmp, "p.pem")
            subprocess.run(["openssl", "genrsa", "-out", key, "2048"], check=True, capture_output=True)
            subprocess.run(["openssl", "rsa", "-in", key, "-pubout", "-out", pub], check=True, capture_output=True)
            jwt = gwallet_link.sign_rs256({"a": 1}, str(key))
            h, b, s = jwt.split(".")
            sig = Path(tmp, "sig")
            sig.write_bytes(base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)))
            proc = subprocess.run(["openssl", "dgst", "-sha256", "-verify", pub, "-signature", sig],
                                  input=f"{h}.{b}".encode(), capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
