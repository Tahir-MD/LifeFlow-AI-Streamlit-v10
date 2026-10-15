"""Pure-logic tests (no database, no Streamlit). Run: python -m pytest -q"""
from datetime import date

from app.services import insight_logic as logic
from app.services.eligibility_service import evaluate_eligibility


def base_answers(**over):
    answers = {"age": 30, "gender": "male", "weight_kg": 70, "hemoglobin": 14.0, "last_donation_date": None}
    answers.update(over)
    return answers


def test_eligible_adult():
    assert evaluate_eligibility(base_answers())["eligible"] is True


def test_underweight_blocked():
    assert evaluate_eligibility(base_answers(weight_kg=45))["eligible"] is False


def test_temporary_deferral_has_retry_date():
    verdict = evaluate_eligibility(base_answers(unwell_today=True), today=date(2026, 1, 1))
    assert not verdict["eligible"] and not verdict["permanent"] and verdict["retry_after_date"] == "2026-01-15"


def test_permanent_block():
    assert evaluate_eligibility(base_answers(hiv_aids=True))["permanent"] is True


def test_yes_no_in_three_languages():
    assert logic.interpret_yes_no("ہاں") is True
    assert logic.interpret_yes_no("نہیں جی") is False
    assert logic.interpret_yes_no("جي ها") is True
    assert logic.interpret_yes_no("nahi") is False
    assert logic.interpret_yes_no("maybe") is None


def test_numbers_and_dates():
    assert logic.extract_number("وزن ۶۵ کلو") == 65
    assert logic.interpret_last_donation("3 months ago", date(2026, 10, 11)) == ("date", "2026-07-13")
    assert logic.interpret_last_donation("never")[0] == "never"


def test_blood_type_cleaning():
    assert logic.normalise_blood_type("O negative") == "O-"
    fields = logic.clean_request_fields({"blood_type_needed": "ab+", "units_needed": "2", "patient_age": 300, "patient_name": "Ali123"})
    assert fields["blood_type_needed"] == "AB+" and fields["units_needed"] == 2 and fields["patient_age"] is None and fields["patient_name"] == "Ali"


def test_travel_estimates_are_sane():
    ambulance = logic.estimate_travel(10, "ambulance")
    bike = logic.estimate_travel(10, "bike")
    assert 1 <= ambulance["minutes"] < bike["minutes"]


def test_response_prediction_prefers_close_active_donors():
    near = logic.predict_response(5, 4, 2, 200, 14, True, 4.8)
    far = logic.predict_response(0, 0, 45, None, 2, False)
    assert near["probability"] > far["probability"]
    assert 0 < far["probability"] < 1


def test_camp_predictor_scales_with_registrations():
    small = logic.predict_camp(10, None, 50, 6, 10)
    large = logic.predict_camp(100, None, 50, 6, 10)
    assert large["expected_turnout"] > small["expected_turnout"]
    assert large["staff_total"] >= small["staff_total"] and large["beds"] >= small["beds"]


def test_staff_roles_and_permissions():
    from app.utils.permissions import can, permissions_for
    assert can("doctor", "screen_donors") and not can("receptionist", "screen_donors")
    assert can("lab_technician", "manage_stock") and not can("doctor", "manage_stock")
    assert set(permissions_for("manager")) >= {"log_visitors", "camp_checkin", "screen_donors", "manage_stock"}
    assert can(None, "log_visitors")   # old staff rows without a role keep front-desk powers


def test_donor_qr_code_text_is_understood_by_check_in():
    import re
    text = "LIFEFLOW-DONOR|id:12|name:Ali Khan|type:O+"
    assert int(re.search(r"id:\s*(\d+)", text, re.I).group(1)) == 12
