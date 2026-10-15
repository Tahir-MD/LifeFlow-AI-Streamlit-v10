"""The health questionnaire: question lists, the conversational flow, and the verdict (same rules as the web app)."""
from typing import Dict, List

from app.services.eligibility_service import FEMALE_ONLY, YES_MEANS_NO, evaluate_eligibility

GROUPS = [
    ("Right now", [
        ("unwell_today", "Are you unwell today (fever, cold, cough, sore throat)?"),
        ("antibiotics_recent", "Did you take antibiotics or have an infection in the last 2 weeks?"),
        ("dental_week", "Did you have a tooth taken out or dental work in the last week?"),
        ("alcohol_24h", "Did you drink alcohol in the last 24 hours?"),
        ("vaccine_4w", "Did you have a vaccination in the last 4 weeks?"),
    ]),
    ("Last few months", [
        ("malaria_3m", "Did you have malaria in the last 3 months?"),
        ("tattoo_6m", "Did you get a tattoo, piercing or acupuncture in the last 6 months?"),
        ("surgery_6m", "Did you have major surgery in the last 6 months?"),
        ("transfusion_12m", "Did you receive blood from someone else in the last 12 months?"),
        ("exposure_12m", "Did a needle prick you, or did you live with someone who has hepatitis or HIV, in the last 12 months?"),
    ]),
    ("Long-term health", [
        ("hiv_aids", "Do you have HIV / AIDS?"),
        ("hepatitis", "Do you have hepatitis B or C?"),
        ("heart_disease", "Do you have heart disease?"),
        ("cancer", "Have you ever had cancer?"),
        ("bleeding_disorder", "Do you have a bleeding disorder or thalassemia major?"),
        ("seizures", "Do you have seizures or epilepsy?"),
        ("insulin_diabetes", "Do you have diabetes and use insulin?"),
        ("kidney_liver", "Do you have long-term kidney or liver disease?"),
        ("uncontrolled_bp", "Do you have high blood pressure that is not controlled?"),
        ("blood_thinners", "Do you take blood thinners (for example warfarin)?"),
        ("injected_drugs", "Have you ever used injected drugs that were not prescribed by a doctor?"),
    ]),
]
FEMALE_GROUP = ("For women", [
    ("pregnant", "Are you pregnant?"),
    ("childbirth_6m", "Did you give birth, or are you breastfeeding, in the last 6 months?"),
])

ALL_KEYS = [key for key, _m, _d in YES_MEANS_NO + FEMALE_ONLY]

BASE_STEPS = [
    ("age", "age", "How old are you?"),
    ("gender", "gender", "Are you male or female?"),
    ("weight_kg", "weight", "How much do you weigh, in kg?"),
    ("hemoglobin", "hemoglobin", "Do you know your haemoglobin (g/dL) from a blood test? Say no if you do not know."),
    ("last_donation_date", "last_donation", "When did you last give blood? For example “3 months ago”, or say “never”."),
]

# The same questions in Urdu and Sindhi for the chat (spoken aloud for people who cannot read well).
CHAT_TEXT = {
    "ur": {
        "hello": "السلام علیکم! میں چند آسان سوال پوچھوں گا تاکہ دیکھ سکوں کہ آپ خون دے سکتے ہیں یا نہیں۔",
        "age": "آپ کی عمر کتنی ہے؟", "gender": "آپ مرد ہیں یا خاتون؟", "weight": "آپ کا وزن کتنے کلو ہے؟",
        "hemoglobin": "کیا آپ کو خون کے ٹیسٹ سے اپنا ہیموگلوبن معلوم ہے؟ اگر معلوم نہیں تو “نہیں” کہیں۔",
        "last_donation": "آپ نے آخری بار خون کب دیا؟ مثلاً “3 مہینے پہلے”، یا “کبھی نہیں” کہیں۔",
        "retry": "معذرت، میں سمجھ نہیں سکا۔ براہ کرم دوبارہ بتائیں۔",
        "yes_no_hint": "ہاں یا نہیں میں جواب دیں۔",
    },
    "sd": {
        "hello": "السلام عليڪم! مان ڪجهه آسان سوال پڇندس ته ڏسان ته توهان رت ڏئي سگهو ٿا يا نه.",
        "age": "توهان جي عمر ڪيتري آهي؟", "gender": "توهان مرد آهيو يا عورت؟", "weight": "توهان جو وزن ڪيترا ڪلو آهي؟",
        "hemoglobin": "ڇا توهان کي رت جي ٽيسٽ مان پنهنجو هيموگلوبن خبر آهي؟ جي خبر نه آهي ته “نه” چئو.",
        "last_donation": "توهان آخري ڀيرو رت ڪڏهن ڏنو؟ مثال طور “3 مهينا اڳ”، يا “ڪڏهن به نه” چئو.",
        "retry": "معاف ڪجو، مان سمجهي نه سگهيس. مهرباني ڪري ٻيهر ٻڌايو.",
        "yes_no_hint": "ها يا نه ۾ جواب ڏيو.",
    },
}

def empty_answers() -> Dict:
    answers = {"age": None, "gender": "", "weight_kg": None, "hemoglobin": None, "last_donation_date": None}
    answers.update({key: False for key in ALL_KEYS})
    return answers


def groups_for(gender: str) -> List:
    return GROUPS + ([FEMALE_GROUP] if (gender or "").lower() == "female" else [])


def chat_steps(gender: str) -> List[tuple]:
    steps = list(BASE_STEPS)
    for _title, items in groups_for(gender):
        steps.extend((key, "yes_no", question) for key, question in items)
    return steps


def verdict(answers: Dict) -> Dict:
    return evaluate_eligibility(answers)


def interpret(step_type: str, text: str, question: str = "") -> Dict:
    """Understands a typed or spoken answer (rules first, AI only if the rules are unsure)."""
    from app.routes.ai_v6_routes import HealthAnswerIn, health_chat_interpret
    return health_chat_interpret(HealthAnswerIn(step=step_type, text=text, question=question or None))

