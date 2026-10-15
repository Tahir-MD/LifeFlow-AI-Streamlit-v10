"""A small set of sample accounts and requests so a fresh deployment does not look empty. Only runs on an empty database."""
from datetime import datetime, timedelta

DEMO_PASSWORD = "Demo@1234"

HOSPITALS = [
    ("City Care Hospital", "hospital@demo.lifeflow", "DEMO-LIC-1001", "+92 3001234567", "Shikarpur Road", "Sukkur", 27.7052, 68.8574),
    ("Civil Hospital Larkana", "larkana@demo.lifeflow", "DEMO-LIC-1002", "+92 3007654321", "Station Road", "Larkana", 27.5590, 68.2123),
]
DONORS = [
    ("Ayesha Khan", "donor@demo.lifeflow", "O-", "female", 27, 58.0, 27.7100, 68.8500, 120, 4),
    ("Bilal Ahmed", "bilal@demo.lifeflow", "A+", "male", 31, 72.0, 27.6950, 68.8650, 400, 7),
    ("Sana Memon", "sana@demo.lifeflow", "B+", "female", 24, 55.0, 27.7200, 68.8400, None, 0),
    ("Imran Shaikh", "imran@demo.lifeflow", "O+", "male", 35, 80.0, 27.7000, 68.8800, 95, 3),
    ("Farah Soomro", "farah@demo.lifeflow", "AB+", "female", 29, 61.0, 27.7300, 68.8300, 200, 2),
    ("Kamran Ali", "kamran@demo.lifeflow", "A-", "male", 40, 77.0, 27.6900, 68.8700, 300, 5),
    ("Nida Baloch", "nida@demo.lifeflow", "O-", "female", 22, 52.0, 27.7150, 68.8600, None, 0),
    ("Zeeshan Rind", "zeeshan@demo.lifeflow", "B-", "male", 33, 70.0, 27.7050, 68.8450, 150, 1),
]


def seed_demo() -> None:
    from app.database import SessionLocal
    from app.models.camp import DonationCamp
    from app.models.donor import Donor
    from app.models.donation import Donation
    from app.models.hospital import Hospital
    from app.models.inventory import BloodInventory
    from app.models.receiver import Receiver
    from app.models.request import BloodRequest
    from app.models.request_event import RequestEvent
    from app.services.referral_service import new_referral_code
    from app.utils.security import hash_password

    db = SessionLocal()
    try:
        if db.query(Hospital).count() or db.query(Donor).count():
            return
        hashed = hash_password(DEMO_PASSWORD)
        now = datetime.utcnow()

        hospitals = []
        for name, email, licence, phone, area, city, lat, lng in HOSPITALS:
            h = Hospital(name=name, email=email, hashed_password=hashed, license_number=licence, phone_number=phone,
                         latitude=lat, longitude=lng, area=area, city=city, country="Pakistan",
                         is_verified=True, verified_at=now, phone_verified=True)
            db.add(h)
            hospitals.append(h)
        db.flush()
        for h in hospitals:
            for i, bt in enumerate(["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]):
                units = [6, 1, 8, 0, 3, 0, 9, 2][i] if h is hospitals[0] else [2, 0, 3, 1, 0, 0, 4, 0][i]
                db.add(BloodInventory(hospital_id=h.id, blood_type=bt, units_available=units, low_stock_threshold=3))

        donors = []
        for name, email, bt, gender, age, weight, lat, lng, days_ago, n_don in DONORS:
            d = Donor(full_name=name, email=email, hashed_password=hashed, blood_type=bt, phone_number="+92 3011111111",
                      latitude=lat, longitude=lng, area="Sukkur", city="Sukkur", country="Pakistan", age=age, gender=gender,
                      weight_kg=weight, last_donation_date=(now - timedelta(days=days_ago)) if days_ago else None,
                      points=n_don * 10, phone_verified=True, eligibility_checked_at=now, referral_code=new_referral_code(db))
            db.add(d)
            donors.append((d, n_don))
            db.flush()

        receiver = Receiver(full_name="Hamza Qureshi", email="patient@demo.lifeflow", hashed_password=hashed,
                            phone_number="+92 3022222222", cnic_number="4540112345671", address="Barrage Colony, Sukkur",
                            patient_name="Abdul Qureshi", latitude=27.7080, longitude=68.8520, area="Barrage Colony",
                            city="Sukkur", country="Pakistan", phone_verified=True)
        db.add(receiver)
        db.flush()

        r1 = BloodRequest(requester_type="receiver", requester_id=receiver.id, blood_type_needed="O-", units_needed=2,
                          patient_name="Abdul Qureshi", patient_age=58, patient_gender="Male", medical_reason="Heart surgery",
                          urgency_type="emergency", latitude=27.7080, longitude=68.8520, status="open", review_status="ok")
        r2 = BloodRequest(requester_type="hospital", requester_id=hospitals[0].id, blood_type_needed="B+", units_needed=3,
                          patient_name="Mariam Bibi", patient_age=31, patient_gender="Female", medical_reason="Thalassemia transfusion",
                          urgency_type="days", urgency_value=3, latitude=27.7052, longitude=68.8574, status="open", review_status="ok")
        db.add_all([r1, r2])
        db.flush()
        for r in (r1, r2):
            db.add(RequestEvent(request_id=r.id, kind="created", message="Request created."))
            db.add(RequestEvent(request_id=r.id, kind="donors_alerted", message="Matching donors nearby were alerted."))

        for donor, n in donors:
            for k in range(n):
                db.add(Donation(donor_id=donor.id, request_id=r1.id, units_donated=1, donated_at=now - timedelta(days=60 * (k + 1))))

        db.add(DonationCamp(hospital_id=hospitals[0].id, title="World Blood Donor Day camp",
                            description="Free screening and refreshments for every donor.", location_label="City Care Hospital lawn, Sukkur",
                            latitude=27.7052, longitude=68.8574, camp_date=now + timedelta(days=9)))
        from app.models.staff import Staff
        db.add(Staff(hospital_id=hospitals[0].id, full_name="Demo Manager", email="staff@demo.lifeflow", hashed_password=hashed,
                     shift="Shift 1", role="manager"))
        db.commit()
    finally:
        db.close()
