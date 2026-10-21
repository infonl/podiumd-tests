"""Open Formulieren's own checks of its form definitions and logic (the bin/report_*.py scripts of its image).

Returns {script: [ok, output]}; ok is the script's main() result, True when it found nothing. Params: none.
"""

REPORTS = (
    "report_component_problems",
    "report_invalid_form_logic",
    "report_conditional_eq_properties",
    "report_file_component_inconsistent_catalogues",
    "report_logic_with_deprecated_clear_on_hide_behavior",
)
# report_component_problems' main() needs its command line options.
OPTIONS = {"report_component_problems": {"component_types": (), "check_html_usage": False}}


def run(params):
    import contextlib
    import importlib
    import io
    import sys

    del params
    sys.path.insert(0, "/app/bin")
    results = {}
    for name in REPORTS:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            ok = importlib.import_module(name).main(skip_setup=True, **OPTIONS.get(name, {}))
        results[name] = [bool(ok), output.getvalue()[-2000:]]
    return results
