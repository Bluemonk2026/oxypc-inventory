"""Final QC decision form (templates/cosmetic/final_qc.html) — Bucket Name
(both Pass and Fail), plus Failure Reason and Final Notes on Fail, are
required — but validated by hand rather than the native HTML `required`
attribute, since that shows the browser's own validation bubble/tooltip.
An empty field instead gets Bootstrap's red .is-invalid border and keyboard
focus, and submission is blocked until it's filled in — no popup, no
thrown error. Backend (routers/cosmetic.py advance_stage) is unchanged and
still accepts blank values if posted directly (e.g. by a script) — this is
a client-side UX gate only.
"""
import pathlib

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)


def _read():
    return (pathlib.Path(ROOT) / "templates" / "cosmetic" / "final_qc.html").read_text(encoding="utf-8")


def test_none_of_the_three_fields_use_the_native_required_attribute():
    # The native `required` attribute triggers the browser's own popup/
    # tooltip on an invalid submit — exactly what this validation must not
    # show. Bucket Name, Failure Reason, and Final Notes must rely solely on
    # the hand-rolled validate() function instead.
    src = _read()
    assert 'name="bucket_name" class="form-control form-control-sm"' in src
    assert 'name="failure_reason" class="form-select form-select-sm"' in src
    assert 'name="notes" class="form-control form-control-sm" placeholder="Remarks"' in src


def test_validate_function_checks_bucket_name_always_and_reason_notes_on_fail():
    src = _read()
    assert "var REQUIRED_ALWAYS = ['bucket_name'];" in src
    assert "var REQUIRED_ON_FAIL = ['failure_reason', 'notes'];" in src


def test_invalid_field_gets_bootstrap_red_border_class_not_a_thrown_error():
    src = _read()
    assert "classList.toggle('is-invalid', empty)" in src
    assert "firstInvalid.focus()" in src
    # No alert()/throw for this validation path specifically.
    block = src[src.index("function validate(form)"):][:600]
    assert "alert(" not in block
    assert "throw " not in block


def test_submit_is_blocked_when_validation_fails():
    src = _read()
    assert "form.addEventListener('submit', function (e) {" in src
    assert "if (!validate(form)) e.preventDefault();" in src


def test_form_marks_novalidate_so_browser_never_shows_its_own_bubble():
    src = _read()
    assert "form.setAttribute('novalidate', 'novalidate');" in src


def test_fixing_a_field_clears_its_invalid_state():
    src = _read()
    assert "function clearInvalid(field)" in src
    assert "field.classList.remove('is-invalid');" in src
    assert "field.addEventListener('input', function () { clearInvalid(field); });" in src
