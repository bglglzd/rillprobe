import json
from importlib.resources import files
from pathlib import Path


def render_html(report):
    template = files("rillprobe").joinpath("assets/report.html").read_text(encoding="utf-8")
    logo = files("rillprobe").joinpath("assets/mark.svg").read_text(encoding="utf-8")
    # Escaping '<' prevents a fixture from terminating the application/json script.
    data = json.dumps(report, ensure_ascii=True, allow_nan=False).replace("<", "\\u003c").replace(
        ">", "\\u003e").replace("&", "\\u0026")
    return template.replace("__LOGO__", logo).replace("__REPORT_DATA__", data)


def write_report(report, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=True, allow_nan=False) + "\n",
                                         encoding="utf-8")
    (output / "report.html").write_text(render_html(report), encoding="utf-8")
