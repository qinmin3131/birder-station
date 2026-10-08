from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

BRANDED_FILES = (
    "README.md",
    "CLAUDE.md",
    "docs/NAS_SETUP_zh.md",
    "scripts/config_wizard.py",
    "scripts/lib/config.sh",
    "scripts/lib/tui.sh",
    "scripts/tui_main.py",
    "src/web/templates/admin.html",
    "src/web/templates/admin_index.html",
    "src/web/templates/gallery.html",
    "src/web/templates/guide.html",
    "src/web/templates/import.html",
    "src/web/templates/index.html",
    "src/web/templates/log.html",
    "src/web/templates/navbar.html",
    "src/web/templates/select.html",
    "src/web/templates/settings.html",
)


def test_user_facing_product_name_is_wingtrace():
    combined_text = "\n".join(
        (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        for relative_path in BRANDED_FILES
    )

    user_facing_text = combined_text.replace("WingScribePipeline", "")

    assert "羽迹" in user_facing_text
    assert "WingTrace" in user_facing_text
    assert "飞羽志" not in user_facing_text
    assert "WingScribe" not in user_facing_text
