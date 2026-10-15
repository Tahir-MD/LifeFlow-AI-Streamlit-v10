"""The weekly report screen (admin: whole platform, hospital: its own numbers)."""
import streamlit as st

from app.models.weekly_report import WeeklyReport
from app.services import v6_service as svc
from app.services.export_service import build_pdf, build_xlsx
from ui import theme
from ui.i18n import lang, t
from ui.widgets import listen_button


def weekly_report_view(db, scope: str, hospital_id=None, key: str = "wr") -> None:
    rows = (db.query(WeeklyReport).filter(WeeklyReport.scope == scope, WeeklyReport.hospital_id == hospital_id)
            .order_by(WeeklyReport.created_at.desc()).limit(12).all())
    st.caption(t("A new report is written automatically every week. It uses real numbers from the app, then explains them in plain words."))
    if st.button(t("Make this week's report now"), key=key + "_make", type="primary"):
        with st.spinner(t("Please wait...")):
            svc.generate_weekly_report(db, scope, hospital_id)
        st.rerun()
    if not rows:
        theme.empty(t("No report yet. Press the button to make the first one."), "📈")
        return
    report = svc.report_to_dict(rows[0])
    s = report["stats"]
    source = t("written by AI from the numbers") if report["narrative_source"] == "ai" else t("written from the numbers")
    st.caption(f"{s['period_start']} → {s['period_end']} · {source}")
    st.markdown(f'<div class="lf-card">{theme.esc(report["narrative"]).replace(chr(10), "<br>")}</div>', unsafe_allow_html=True)
    theme.stat_cards([
        ("🩸", s["requests"], f"{t('requests')} ({t('last week')}: {s['requests_previous_period']})"),
        ("✅", s["fulfilled"], t("fully covered")),
        ("📦", f"{s['units_fulfilled']}/{s['units_requested']}", t("bags supplied / needed")),
        ("💉", s["donations"], t("donations")),
    ])
    if s["low_stock"]:
        st.warning(f"{t('Low stock')}: " + ", ".join(f"{x['blood_type']} ({x['units']})" for x in s["low_stock"]))
    if s["expiring_soon"]:
        st.warning(f"{t('Expiring within a week')}: " + ", ".join(f"{x['blood_type']} ×{x['units']}" for x in s["expiring_soon"]))
    title = f"LifeFlow weekly report {s['period_start']} to {s['period_end']}"
    sheets = svc.report_sheets(report)
    c1, c2, c3 = st.columns([1, 1, 2])
    c1.download_button("📊 " + t("Download Excel"), build_xlsx(title, sheets), file_name=f"lifeflow_weekly_{report['id']}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=key + "_xlsx")
    c2.download_button("📄 " + t("Download PDF"), build_pdf(title, sheets), file_name=f"lifeflow_weekly_{report['id']}.pdf",
                       mime="application/pdf", key=key + "_pdf")
    with c3:
        listen_button(report["narrative"], lang() if lang() in ("ur", "sd", "en") else "en")
    if len(rows) > 1:
        with st.expander(t("Earlier reports")):
            for older in rows[1:]:
                o = svc.report_to_dict(older)
                st.markdown(f"**{o['stats']['period_start']} → {o['stats']['period_end']}** · {o['stats']['requests']} {t('requests')}")
                st.caption(o["narrative"])
