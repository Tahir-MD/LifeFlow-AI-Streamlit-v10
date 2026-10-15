"""Pages for every signed-in person (notifications, security) and public pages (forgot password, certificate check)."""
import os

import streamlit as st

from app.models.notification import Notification
from app.routes.certificate_routes import my_certificates, verify_certificate
from app.routes.donor_routes import NotificationPrefs, set_my_notification_channels
from app.routes.password_routes import ForgotIn, ResetIn
from app.routes.password_routes import forgot_password as api_forgot
from app.routes.password_routes import reset_password as api_reset
from app.services.delivery_service import delivery_status, is_email_configured
from app.utils.security import hash_password, verify_password
from app.utils.totp import generate_secret, get_otpauth_uri, verify_totp
from app.utils.validators import validate_password_strength
from ui import accounts, qr, theme
from ui.db import friendly_error, session
from ui.i18n import t


# ------------------------------------------------------------------ forgot password (public)
def forgot_password() -> None:
    theme.page_header(t("Forgot your password?"), t("We email you a 6-digit code to choose a new one."), "🔑")
    if not is_email_configured():
        st.warning(t("Email sending is not set up on this server, so codes cannot be delivered. Please ask the administrator to reset your password."))
    labels = {k: t(v) for k, v in accounts.ROLE_LABELS.items()}
    c1, c2 = st.columns(2)
    role_name = c1.selectbox(t("I am a"), list(labels), format_func=lambda r: labels[r], key="fp_role")
    email = c2.text_input(t("Email"), key="fp_email")
    if st.button(t("Send code"), key="fp_send", disabled=not email.strip()):
        try:
            with session() as db:
                reply = api_forgot(ForgotIn(role=role_name, email=email.strip()), db)
            st.session_state["fp_sent"] = True
            st.success(t(reply["message"]))
            if reply.get("dev_code"):
                st.info(f"{t('Test mode code')}: **{reply['dev_code']}**")
        except Exception as error:  # noqa: BLE001
            st.error(friendly_error(error))
    if st.session_state.get("fp_sent"):
        st.markdown("#### " + t("Choose a new password"))
        code = st.text_input(t("6-digit code"), key="fp_code", max_chars=6)
        c3, c4 = st.columns(2)
        new = c3.text_input(t("New password"), type="password", key="fp_new", help=t("At least 8 characters with upper case, lower case, a number and a special character."))
        again = c4.text_input(t("Confirm password"), type="password", key="fp_new2")
        if st.button(t("Change password"), type="primary", key="fp_go"):
            if new != again:
                st.error(t("The two passwords do not match."))
            else:
                try:
                    with session() as db:
                        done = api_reset(ResetIn(role=role_name, email=email.strip(), code=code.strip(), new_password=new), db)
                    st.success("✅ " + t(done["message"]))
                    st.session_state.pop("fp_sent", None)
                except Exception as error:  # noqa: BLE001
                    st.error(friendly_error(error))
    theme.footer()


# ------------------------------------------------------------------ certificate check (public)
def verify_certificate_page() -> None:
    theme.page_header(t("Verify a certificate"), t("Type the code printed on a donor certificate to check that it is real."), "✅")
    code = st.text_input(t("Certificate code"), value=st.query_params.get("code", ""), placeholder="LF-000012-AB12CD34", key="vc_code")
    if code.strip():
        with session() as db:
            result = verify_certificate(code.strip(), db)
        if result.get("valid"):
            st.success("✅ " + t("This certificate is genuine."))
            st.markdown(f"**{theme.esc(result['donor'])}** · {theme.blood_badge(result['blood_type'])} · {result['units']} {t('bags')} · {result['date']}<br>"
                        f"{t('Given to')}: {theme.esc(result['given_to'])}", unsafe_allow_html=True)
        else:
            st.error(t("This code is not valid. The certificate may be fake."))
    theme.footer()


# ------------------------------------------------------------------ certificates and donor card (donor)
def verify_link(code: str) -> str:
    base = os.environ.get("LIFEFLOW_PUBLIC_URL", "").rstrip("/")
    return f"{base}/verify-certificate?code={code}" if base else code


def certificate_pdf(donor_name: str, cert, total_units: int) -> bytes:
    import io

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    width, height = landscape(A4)
    pdf = canvas.Canvas(buffer, pagesize=(width, height))
    pdf.setStrokeColor(colors.HexColor("#B3202F"))
    pdf.setLineWidth(6)
    pdf.rect(24, 24, width - 48, height - 48)
    pdf.setLineWidth(1)
    pdf.rect(36, 36, width - 72, height - 72)
    pdf.setFillColor(colors.HexColor("#B3202F"))
    pdf.setFont("Helvetica-Bold", 34)
    pdf.drawCentredString(width / 2, height - 110, "Certificate of Blood Donation")
    pdf.setFillColor(colors.HexColor("#444444"))
    pdf.setFont("Helvetica", 15)
    pdf.drawCentredString(width / 2, height - 165, "This certificate is proudly presented to")
    pdf.setFillColor(colors.HexColor("#7A1F2B"))
    pdf.setFont("Helvetica-Bold", 32)
    pdf.drawCentredString(width / 2, height - 220, donor_name)
    pdf.setFillColor(colors.HexColor("#444444"))
    pdf.setFont("Helvetica", 15)
    pdf.drawCentredString(width / 2, height - 262,
                          f"for donating {cert.units_donated} bag(s) of blood (group {cert.blood_type}) on {cert.donated_at:%d %B %Y}")
    pdf.drawCentredString(width / 2, height - 288, f"to {cert.given_to}.")
    pdf.setFont("Helvetica-Oblique", 13)
    pdf.drawCentredString(width / 2, height - 330, "Every bag can help up to three people. Thank you for saving lives.")
    pdf.setFont("Helvetica", 11)
    pdf.drawString(60, 70, f"Certificate code: {cert.code}")
    pdf.drawString(60, 54, "Check it at the LifeFlow 'Verify a certificate' page.")
    image = qr.png_bytes(verify_link(cert.code), scale=6)
    if image:
        pdf.drawImage(ImageReader(io.BytesIO(image)), width - 170, 52, 100, 100)
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawRightString(width - 70, 40, "LifeFlow Blood Network")
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def certificates() -> None:
    theme.page_header(t("Certificates & donor card"), t("Your proof of giving, and your QR card for donation camps."), "🏅")
    with session() as db:
        donor = accounts.load(db)
        data = my_certificates(db, donor)
        tab_cards, tab_card = st.tabs([t("Certificates"), t("My donor card")])
        with tab_cards:
            theme.stat_cards([("💉", data.total_donations, t("donations")), ("🩸", data.total_units, t("bags donated")),
                              ("❤️", data.lives_impacted, t("lives you may have helped")), ("🏅", data.badge_tier, t("Badge"))])
            if not data.certificates:
                theme.empty(t("Your certificates will appear after your first donation."), "🏅")
            for cert in data.certificates:
                with st.container(border=True):
                    c1, c2 = st.columns([3, 1])
                    c1.markdown(f'<div class="lf-title">{cert.units_donated} {t("bags")} · {cert.donated_at:%d %b %Y}</div>'
                                f'<div class="lf-sub">{t("Given to")}: {theme.esc(cert.given_to)} · {t("Code")}: <b>{cert.code}</b></div>', unsafe_allow_html=True)
                    try:
                        c2.download_button("⬇️ PDF", certificate_pdf(data.donor_name, cert, data.total_units), file_name=f"certificate_{cert.code}.pdf",
                                           mime="application/pdf", key=f"cert_{cert.donation_id}")
                    except Exception:  # noqa: BLE001
                        c2.caption(t("PDF needs reportlab"))
        with tab_card:
            text = qr.donor_card_text(donor)
            image = qr.png_bytes(text)
            c1, c2 = st.columns([1, 2])
            if image:
                c1.image(image, width=220)
                c1.download_button("⬇️ PNG", image, file_name="lifeflow_donor_card.png", mime="image/png", key="card_png")
            else:
                c1.info(t("The QR picture needs the segno package. You can still give the staff your donor number."))
            c2.markdown(f"### {theme.esc(donor.full_name)}")
            c2.markdown(f"{theme.blood_badge(donor.blood_type)} &nbsp; {t('Donor number')}: **LF-{donor.id}**", unsafe_allow_html=True)
            c2.caption(t("Show this card at a donation camp. The staff scan it to check you in."))
    theme.footer()


# ------------------------------------------------------------------ notifications (donor, patient, hospital)
def notifications() -> None:
    theme.page_header(t("Notifications"), t("Alerts about your requests, donations and camps."), "🔔")
    auth = accounts.current()
    with session() as db:
        rows = (db.query(Notification).filter(Notification.user_type == auth["role"], Notification.user_id == auth["id"])
                .order_by(Notification.created_at.desc()).limit(100).all())
        unread = [n for n in rows if not n.is_read]
        if unread and st.button(t("Mark all as read"), key="notif_all"):
            for n in unread:
                n.is_read = True
            db.commit()
            st.rerun()
        if not rows:
            theme.empty(t("No notifications yet."), "🔔")
        for n in rows:
            mark = "🔵 " if not n.is_read else ""
            st.markdown(f'<div class="lf-card"><div class="lf-title">{mark}{theme.esc(n.title)}</div><div>{theme.esc(n.message)}</div>'
                        f'<div class="lf-sub">{n.created_at:%d %b %Y, %H:%M}</div></div>', unsafe_allow_html=True)
        if auth["role"] == "donor":
            donor = accounts.load(db)
            st.subheader(t("How should urgent alerts reach you?"))
            st.caption(t("The app always keeps your notifications. You can also get SMS or WhatsApp messages."))
            status = delivery_status()
            c1, c2 = st.columns(2)
            sms = c1.toggle("SMS", value=bool(donor.notify_sms), key="nt_sms", disabled=not status["sms_configured"])
            wa = c2.toggle("WhatsApp", value=bool(donor.notify_whatsapp), key="nt_wa", disabled=not status["whatsapp_configured"])
            if not (status["sms_configured"] or status["whatsapp_configured"]):
                st.caption(t("SMS and WhatsApp are not set up on this server yet."))
            if st.button(t("Save"), key="nt_save"):
                set_my_notification_channels(NotificationPrefs(notify_sms=sms, notify_whatsapp=wa), db, donor)
                st.success("✅ " + t("Saved."))
    st.caption(t("Browser push notifications need a service worker, which Streamlit cannot register. Use the web edition for push alerts."))
    theme.footer()


# ------------------------------------------------------------------ security (everyone signed in)
def security() -> None:
    theme.page_header(t("Account & security"), t("Change your password and protect your account."), "🔒")
    auth = accounts.current()
    with session() as db:
        me = accounts.load(db)
        st.markdown("#### " + t("Change password"))
        with st.form("pw_change"):
            old = st.text_input(t("Current password"), type="password")
            c1, c2 = st.columns(2)
            new = c1.text_input(t("New password"), type="password")
            again = c2.text_input(t("Confirm password"), type="password")
            go = st.form_submit_button(t("Change password"), type="primary")
        if go:
            try:
                if not verify_password(old, me.hashed_password):
                    raise ValueError("Current password is incorrect.")
                if new != again:
                    raise ValueError("The two passwords do not match.")
                me.hashed_password = hash_password(validate_password_strength(new))
                if hasattr(me, "must_change_password"):
                    me.must_change_password = False
                db.commit()
                st.success("✅ " + t("Your password has been changed."))
            except Exception as error:  # noqa: BLE001
                st.error(friendly_error(error))
        if auth["role"] in ("hospital", "admin"):
            st.markdown("#### " + t("Two-step verification"))
            if me.two_factor_enabled:
                st.success("🟢 " + t("Two-step verification is on."))
                pw = st.text_input(t("Password"), type="password", key="tf_off_pw")
                if st.button(t("Turn off"), key="tf_off"):
                    if verify_password(pw, me.hashed_password):
                        me.two_factor_enabled, me.totp_secret = False, None
                        db.commit()
                        st.rerun()
                    else:
                        st.error(t("Incorrect password"))
            else:
                st.caption(t("Use an authenticator app (Google Authenticator, Authy). You then type a 6-digit code every time you log in."))
                if st.button(t("Set up"), key="tf_setup"):
                    me.totp_secret = generate_secret()
                    db.commit()
                if me.totp_secret:
                    uri = get_otpauth_uri(me.totp_secret, getattr(me, "email", "lifeflow"))
                    image = qr.png_bytes(uri, scale=6)
                    c1, c2 = st.columns([1, 2])
                    if image:
                        c1.image(image, width=200)
                    c2.markdown(f"{t('Secret key')}: `{me.totp_secret}`")
                    code = c2.text_input(t("6-digit code"), key="tf_code", max_chars=6)
                    if c2.button(t("Turn on"), type="primary", key="tf_on"):
                        if verify_totp(me.totp_secret, code.strip()):
                            me.two_factor_enabled = True
                            db.commit()
                            st.rerun()
                        else:
                            st.error(t("Incorrect code -- check your authenticator app and try again"))
        if auth["role"] == "admin":
            st.markdown("#### " + t("Change admin email"))
            from app.routes.admin_routes import change_admin_credentials
            from app.schemas.admin_schema import AdminChangeCredentials
            with st.form("admin_cred"):
                cur = st.text_input(t("Current password"), type="password", key="ac_cur")
                new_mail = st.text_input(t("New email"), value=me.email, key="ac_mail")
                new_name = st.text_input(t("Name"), value=me.full_name, key="ac_name")
                new_pw = st.text_input(t("New password"), type="password", key="ac_pw")
                saved = st.form_submit_button(t("Save"), type="primary")
            if saved:
                try:
                    change_admin_credentials(AdminChangeCredentials(current_password=cur, new_email=new_mail, new_full_name=new_name, new_password=new_pw), db, me)
                    st.success("✅ " + t("Saved. Use the new details next time you log in."))
                except Exception as error:  # noqa: BLE001
                    st.error(friendly_error(error))
    theme.footer()
